#!/usr/bin/env python3
"""Run a bounded synthetic Qwen3.5 LoRA mechanics probe (not training readiness)."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import resource
import sys
import tempfile
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from sft.artifacts import Invalid, file_hash, identifier, safe_path
from sft.models import MODEL_ARCHITECTURES
from probe_qwen35 import _config_and_model, _verify_selected_files, _safe_relative


MODEL_ID = "qwen35_9b"
REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
SOURCE_DIR = ROOT / "artifacts/models/probes/qwen35-runtime-001/source"
RESULTS = ROOT / "artifacts/models/adapter-probes"
RANK = 8
SCALE = 20.0
DROPOUT = 0.0
LEARNING_RATE = 1.0e-5
STEPS = 2
ATOL = 1.0e-4
RTOL = 1.0e-4
SYNTHETIC_IDS = [1, 42, 314, 2718, 17, 6, 2048, 2]
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
EXPECTED_ADAPTER_SCALARS = 1_900_544
EXPECTED_TARGETS = 24
EXPECTED_PACKAGES = {"mlx": "0.32.4", "mlx-lm": "0.32.2", "transformers": "5.20.1"}
EXPECTED_SOURCE_HASHES = {
    "mlx_lm/models/qwen3_5.py": "851449fd9989d6bf4b3c4fed92ddc3be5f1e781eb2246f89c54d7eff2518d9c6",
    "mlx_lm/models/qwen3_next.py": "67ca08a4d08cb7be124965e95399735e556f1eaeb21a16bc23cb88d1ac035e11",
    "mlx_lm/tuner/utils.py": "f59f3c027176a3975fe60e7fbd9f3f38723c27c3f888cf9e591c103f93f68588",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canon(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _targets() -> list[str]:
    linear = [16, 17, 18, 20, 21, 22, 24, 25, 26, 28, 29, 30]
    full = [19, 23, 27, 31]
    result = [f"language_model.model.layers.{i}.linear_attn.in_proj_qkv" for i in linear]
    for i in full:
        result.extend(f"language_model.model.layers.{i}.self_attn.{proj}" for proj in ("q_proj", "k_proj", "v_proj"))
    return sorted(result)


def _digest_array(array) -> str:
    import mlx.core as mx
    # Reinterpret as bytes before copying; this preserves exact BF16 payloads.
    raw = array.view(mx.uint8).reshape((-1,))
    digest = hashlib.sha256()
    chunk_bytes = 2 * 1024 * 1024
    for start in range(0, int(raw.size), chunk_bytes):
        part = raw[start:start + chunk_bytes]
        mx.eval(part)
        host = np.asarray(part)
        digest.update(memoryview(host).cast("B"))
        del part, host
    return digest.hexdigest()


def _array_row(name: str, value) -> dict:
    return {"name": name, "shape": [int(x) for x in value.shape],
            "dtype": str(value.dtype), "elements": int(value.size),
            "sha256": _digest_array(value)}


def _flat(module) -> dict:
    from mlx.utils import tree_flatten
    return dict(tree_flatten(module.parameters()))


def _snapshot_base(module) -> tuple[dict, str]:
    flat = _flat(module)
    rows = [_array_row(name, value) for name, value in sorted(flat.items())]
    return {row["name"]: row for row in rows}, _sha(_canon(rows))


def _expected_weight_shape(path: str) -> tuple[int, int]:
    if path.endswith(".self_attn.k_proj") or path.endswith(".self_attn.v_proj"):
        return (1024, 4096)
    return (8192, 4096)


def _memory_metrics(mx) -> dict:
    metrics = {}
    for name in ("get_peak_memory", "get_active_memory", "get_cache_memory"):
        try:
            metrics[name.removeprefix("get_")] = int(getattr(mx, name)())
        except Exception:
            metrics[name.removeprefix("get_")] = None
    return metrics


def _versions() -> dict:
    versions = {}
    for package in ("mlx", "mlx-lm", "transformers"):
        versions[package] = importlib.metadata.version(package)
    for package, expected in EXPECTED_PACKAGES.items():
        if versions[package] != expected:
            raise Invalid(f"runtime {package}={versions[package]}, expected pinned {expected}")
    return versions


def _runtime_sources() -> dict:
    import mlx_lm
    package_root = Path(mlx_lm.__file__).resolve().parent
    rows = {}
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        path = package_root / relative.removeprefix("mlx_lm/")
        actual = file_hash(path)
        if actual != expected:
            raise Invalid(f"pinned mlx-lm source hash differs: {relative}")
        rows[relative] = {"sha256": actual, "bytes": path.stat().st_size}
    return rows


def _verify_source(effective: dict, selected: dict) -> list[dict]:
    records, rebuilt = _verify_selected_files(effective, selected)
    if (selected["repo_id"], selected["revision"], selected["weight_format"]) != (
            "Qwen/Qwen3.5-9B", REVISION, "safetensors"):
        raise Invalid("selected model identity differs from the reviewed Qwen3.5 pin")
    expected_type, expected_arch = MODEL_ARCHITECTURES[MODEL_ID]
    if (rebuilt["architecture"].get("model_type") != expected_type or
            rebuilt["architecture"].get("architectures") != expected_arch):
        raise Invalid("selected architecture does not match the reviewed config")
    if not SOURCE_DIR.is_dir() or SOURCE_DIR.is_symlink():
        raise Invalid("previously verified local model source snapshot is missing or unsafe")
    source_rows = []
    for row in records:
        rel = _safe_relative(row["source_path"], "model source path")
        path = SOURCE_DIR / rel
        if path.is_symlink() or not path.is_file():
            raise Invalid(f"source snapshot file missing or symlinked: {rel}")
        if path.stat().st_size != row["bytes"] or file_hash(path) != row["sha256"]:
            raise Invalid(f"source snapshot hash/size differs from pinned CAS: {rel}")
        source_rows.append({"path": rel, "bytes": row["bytes"], "sha256": row["sha256"],
                            "role": row["role"]})
    return source_rows


def _adapter_expected(target_shapes: dict) -> dict[str, tuple[tuple[int, ...], str]]:
    result = {}
    for target, shape in target_shapes.items():
        out_dim, in_dim = shape
        result[f"{target}.lora_a"] = ((in_dim, RANK), "mlx.core.float32")
        result[f"{target}.lora_b"] = ((RANK, out_dim), "mlx.core.float32")
    return result


def _validate_adapter_inventory(weights: dict, expected: dict, label: str) -> dict:
    import mlx.core as mx
    actual_keys = set(weights)
    expected_keys = set(expected)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        raise Invalid(f"{label} adapter inventory mismatch (missing={missing[:3]}, extra={extra[:3]})")
    rows = []
    for name in sorted(expected):
        value = weights[name]
        shape, dtype = expected[name]
        if tuple(int(x) for x in value.shape) != shape or str(value.dtype) != dtype:
            raise Invalid(f"{label} adapter shape/dtype mismatch for {name}: actual={tuple(value.shape)}/{value.dtype}, expected={shape}/{dtype}")
        if not bool(mx.all(mx.isfinite(value)).item()):
            raise Invalid(f"{label} adapter contains nonfinite values for {name}")
        rows.append(_array_row(name, value))
    return {"tensors": rows, "sha256": _sha(_canon(rows)),
            "scalar_count": sum(row["elements"] for row in rows)}


def _adapter_config(targets: list[str]) -> dict:
    return {"fine_tune_type": "lora", "num_layers": 32,
            "lora_parameters": {"rank": RANK, "scale": SCALE, "dropout": DROPOUT,
                                "keys": targets}}


def _finite_and_norm(array) -> tuple[bool, float]:
    import mlx.core as mx
    finite = bool(mx.all(mx.isfinite(array)).item())
    norm = float(mx.sqrt(mx.sum(array.astype(mx.float32) * array.astype(mx.float32))).item())
    return finite, norm


def _train(model, tokens, targets):
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    from mlx.nn import value_and_grad
    from mlx.utils import tree_flatten

    model.train()
    optimizer = optim.Adam(learning_rate=LEARNING_RATE)

    def loss_fn(batch, expected):
        logits = model(batch)
        return mx.mean(nn.losses.cross_entropy(logits[:, :-1, :], expected[:, 1:]))

    loss_and_grad = value_and_grad(model, loss_fn)
    steps = []
    for step in range(1, STEPS + 1):
        loss, gradients = loss_and_grad(tokens, targets)
        mx.eval(loss, gradients)
        loss_value = float(loss.item())
        if not np.isfinite(loss_value):
            raise Invalid(f"synthetic loss is nonfinite at step {step}")
        grad_rows = []
        family_branch_sq = {(family, branch): 0.0
                            for family in ("deltanet", "full_attention") for branch in ("lora_a", "lora_b")}
        family_finite = {family: True for family in ("deltanet", "full_attention")}
        for name, value in sorted(tree_flatten(gradients)):
            finite, norm = _finite_and_norm(value)
            if not finite or not np.isfinite(norm):
                raise Invalid(f"nonfinite adapter gradient at step {step}: {name}")
            family = "deltanet" if ".linear_attn." in name else "full_attention"
            branch = "lora_a" if name.endswith(".lora_a") else "lora_b" if name.endswith(".lora_b") else None
            if branch is None:
                raise Invalid(f"unexpected trainable parameter in adapter gradient: {name}")
            family_branch_sq[(family, branch)] += norm * norm
            family_finite[family] = family_finite[family] and finite
            grad_rows.append({"name": name, "shape": [int(x) for x in value.shape],
                              "norm": norm, "finite": finite})
        group_norms = {f"{family}.{branch}": float(np.sqrt(squared))
                       for (family, branch), squared in family_branch_sq.items()}
        if any(group_norms[f"{family}.lora_b"] <= 0
               for family in ("deltanet", "full_attention")):
            raise Invalid(f"no nonzero LoRA B gradient for both attention families at step {step}: {group_norms}")
        if step >= 2 and any(group_norms[f"{family}.lora_a"] <= 0
                             for family in ("deltanet", "full_attention")):
            raise Invalid(f"second-step LoRA A gradient absent for an attention family: {group_norms}")
        optimizer.update(model, gradients)
        mx.eval(model.trainable_parameters(), optimizer.state)
        steps.append({"step": step, "loss": loss_value, "gradient_tensors": grad_rows,
                      "family_branch_gradient_norms": group_norms, "family_gradients_finite": family_finite,
                      "memory": _memory_metrics(mx)})
    return optimizer, steps


def _save_json(path: Path, value):
    raw = _canon(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".adapter-probe-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temp)
    return _sha(raw)


def _eval_logits(model, tokens):
    import mlx.core as mx
    model.eval()
    logits = model(tokens)
    mx.eval(logits)
    return np.asarray(logits, dtype=np.float32)


def run(run_id: str) -> int:
    identifier(run_id)
    if not RUN_RE.fullmatch(run_id):
        raise Invalid("invalid run ID")
    result_dir = RESULTS / run_id
    result_path = result_dir / "manifest.json"
    if result_dir.exists():
        raise Invalid(f"probe result directory already exists and is immutable: {result_dir}")
    target_paths = _targets()
    target_shapes = {}
    base_before = None
    base_before_sha = None
    step_results = []
    adapter_initial = None
    adapter_final = None
    logits_before_reload = None
    reload_results = None
    status = "FAILED"
    error = None
    model = optimizer = None
    started = time.monotonic()
    report = {
        "schema_version": 1, "id": run_id, "kind": "qwen35_synthetic_lora_mechanics_probe",
        "status": "FAILED", "scope": "synthetic-mechanics-only",
        "claim_limit": "Not approved training data, not fine-tuning, benchmark, evaluation, or training readiness.",
        "model": {"id": MODEL_ID, "repo_id": "Qwen/Qwen3.5-9B", "revision": REVISION,
                  "config_hash": None},
        "source_snapshot": {"path": str(SOURCE_DIR.relative_to(ROOT)), "files": []},
        "runtime": {"packages": {}, "sources": {}, "python": platform.python_version(),
                    "platform": platform.platform()},
        "synthetic_input": {"label": "fixed synthetic token IDs; never approved source data",
                            "token_ids": SYNTHETIC_IDS, "sha256": _sha(_canon(SYNTHETIC_IDS))},
        "targets": target_paths,
        "adapter_config": _adapter_config(target_paths),
        "adapter_parameter_budget": {"rank": RANK, "scale": SCALE, "dropout": DROPOUT,
                                      "expected_scalar_count": EXPECTED_ADAPTER_SCALARS},
        "base_integrity": {}, "training_steps": [], "adapter": {}, "reload": {},
        "stage_progress": [],
        "memory": {},
        "diagnostic_limits": {"gradient_checkpointing": False, "reason": "Eight-token, two-step mechanics diagnostic only; production checkpointing remains unverified."},
        "readiness": {"training_allowed": False, "benchmark": False, "data_approved": False},
        "implementation": {"path": str(Path(__file__).resolve().relative_to(ROOT)),
                           "sha256": file_hash(Path(__file__))},
        "started_unix": time.time(),
    }
    result_dir.mkdir(parents=True, exist_ok=False)
    adapter_dir = result_dir / "adapter"
    adapter_dir.mkdir()
    try:
        config_path = safe_path(ROOT, "config/models.json")
        effective, selected = _config_and_model(config_path)
        report["model"]["config_hash"] = file_hash(config_path)
        source_files = _verify_source(effective, selected)
        report["source_snapshot"]["files"] = source_files
        if len(target_paths) != EXPECTED_TARGETS or len(set(target_paths)) != EXPECTED_TARGETS:
            raise Invalid("reviewed target inventory is not exactly 24 modules")
        report["stage_progress"].append({"stage": "source-verified", "elapsed_seconds": round(time.monotonic()-started, 3)})
        os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"})
        report["runtime"]["packages"] = _versions()
        report["runtime"]["sources"] = _runtime_sources()
        report["implementation"]["verification_helper"] = {
            "path": "scripts/probe_qwen35.py", "sha256": file_hash(ROOT / "scripts/probe_qwen35.py")}
        import mlx.core as mx
        from mlx_lm import load
        from mlx_lm.tuner.utils import linear_to_lora_layers, load_adapters
        from mlx.utils import tree_flatten

        model, tokenizer, loaded_config = load(
            str(SOURCE_DIR), tokenizer_config={"trust_remote_code": False, "local_files_only": True},
            trust_remote_code=False, return_config=True,
        )
        report["memory"]["model_loaded"] = _memory_metrics(mx)
        report["stage_progress"].append({"stage": "model-loaded", "elapsed_seconds": round(time.monotonic()-started, 3)})
        expected_arch = MODEL_ARCHITECTURES[MODEL_ID]
        if (loaded_config.get("model_type"), loaded_config.get("architectures")) != expected_arch:
            raise Invalid("loaded Qwen3.5 config differs from the selected pinned architecture")
        if not tokenizer.has_chat_template:
            raise Invalid("pinned tokenizer chat template unavailable during model load")
        tokenizer_template = SOURCE_DIR / "chat_template.jinja"
        if file_hash(tokenizer_template) != selected["chat_template_sha256"]:
            raise Invalid("source snapshot template hash differs from the reviewed pin")

        mx.random.seed(17)
        mx.eval(model.parameters())
        module_paths = {name: module for name, module in model.named_modules()}
        if not set(target_paths).issubset(module_paths):
            missing = sorted(set(target_paths) - set(module_paths))
            raise Invalid(f"target path missing from instantiated model: {missing[:3]}")
        import mlx.nn as nn
        for path in target_paths:
            module = module_paths[path]
            if not isinstance(module, nn.Linear):
                raise Invalid(f"target is not mlx.nn.Linear: {path} ({type(module).__name__})")
            shape = tuple(int(x) for x in module.weight.shape)
            if shape != _expected_weight_shape(path):
                raise Invalid(f"target weight shape differs from reviewed architecture for {path}: {shape}")
            target_shapes[path] = shape
        report["target_modules"] = [{"path": path, "module_type": type(module_paths[path]).__name__,
                                     "weight_shape": target_shapes[path]}
                                    for path in target_paths]
        if len(target_shapes) != EXPECTED_TARGETS:
            raise Invalid("instantiated target count differs from reviewed count")

        base_before, base_before_sha = _snapshot_base(model)
        model.freeze()
        lora_config = {"rank": RANK, "scale": SCALE, "dropout": DROPOUT, "keys": target_paths}
        linear_to_lora_layers(model, len(model.layers), lora_config)
        expected_adapter = _adapter_expected(target_shapes)
        trainable = dict(tree_flatten(model.trainable_parameters()))
        adapter_initial = _validate_adapter_inventory(trainable, expected_adapter, "initialized")
        if adapter_initial["scalar_count"] != EXPECTED_ADAPTER_SCALARS:
            raise Invalid(f"adapter scalar count {adapter_initial['scalar_count']} differs from reviewed budget")
        report["adapter"]["initialized_inventory"] = adapter_initial
        report["stage_progress"].append({"stage": "adapters-installed", "elapsed_seconds": round(time.monotonic()-started, 3)})

        tokens = mx.array([SYNTHETIC_IDS], dtype=mx.int32)
        optimizer, step_results = _train(model, tokens, tokens)
        report["training_steps"] = step_results
        report["memory"]["after_two_steps"] = _memory_metrics(mx)
        report["stage_progress"].append({"stage": "two-synthetic-steps-complete", "elapsed_seconds": round(time.monotonic()-started, 3)})
        current = dict(tree_flatten(model.trainable_parameters()))
        adapter_final = _validate_adapter_inventory(current, expected_adapter, "trained")
        report["adapter"]["trained_inventory"] = adapter_final
        init_rows = {row["name"]: row for row in adapter_initial["tensors"]}
        final_rows = {row["name"]: row for row in adapter_final["tensors"]}
        changes = {name: init_rows[name]["sha256"] != final_rows[name]["sha256"] for name in expected_adapter}
        if not any(changes.values()):
            raise Invalid("no adapter parameter changed after the two optimizer steps")
        if not any(changes[name] for name in changes if name.endswith(".lora_b")):
            raise Invalid("no LoRA B tensor changed after optimizer steps")
        if not any(changes[name] for name in changes if name.endswith(".lora_a")):
            raise Invalid("no LoRA A tensor changed after two optimizer steps")
        changed_by_family = {
            "deltanet": any(changes[name] for name in changes if ".linear_attn." in name),
            "full_attention": any(changes[name] for name in changes if ".self_attn." in name),
        }
        if not all(changed_by_family.values()):
            raise Invalid(f"adapter update did not touch both attention families: {changed_by_family}")
        changed_by_family_branch = {
            f"{family}.{branch}": any(changes[name] for name in changes
                                       if family_marker in name and name.endswith(f".{branch}"))
            for family, family_marker in (("deltanet", ".linear_attn."),
                                          ("full_attention", ".self_attn."))
            for branch in ("lora_a", "lora_b")
        }
        if not all(changed_by_family_branch.values()):
            raise Invalid(f"two steps did not update both LoRA factors in both attention families: {changed_by_family_branch}")
        report["adapter"]["changed_tensors"] = changes
        report["adapter"]["changed_by_family"] = changed_by_family
        report["adapter"]["changed_by_family_branch"] = changed_by_family_branch

        target_weight_paths = {f"{path}.weight" for path in target_paths}
        all_after_params = _flat(model)
        unexpected_adapter_keys = sorted(name for name in all_after_params
                                         if name.endswith((".lora_a", ".lora_b")) and name not in expected_adapter)
        if unexpected_adapter_keys:
            raise Invalid(f"unexpected LoRA parameter paths after conversion: {unexpected_adapter_keys[:5]}")
        base_after = {}
        for name, value in sorted(all_after_params.items()):
            if name in expected_adapter:
                continue
            canonical_name = name[:-len(".linear.weight")] + ".weight" if name.endswith(".linear.weight") and name[:-len(".linear.weight")] + ".weight" in target_weight_paths else name
            if canonical_name in base_after:
                raise Invalid(f"duplicate base parameter path after LoRA wrapping: {canonical_name}")
            base_after[canonical_name] = _array_row(canonical_name, value)
        del all_after_params
        mismatches = []
        if set(base_after) != set(base_before):
            mismatches.append({"kind": "keyset", "before_only": sorted(set(base_before)-set(base_after))[:10],
                               "after_only": sorted(set(base_after)-set(base_before))[:10]})
        for name in set(base_before) & set(base_after):
            if (base_before[name]["sha256"] != base_after[name]["sha256"] or
                    base_before[name]["shape"] != base_after[name]["shape"] or
                    base_before[name]["dtype"] != base_after[name]["dtype"]):
                mismatches.append({"kind": "tensor", "name": name})
        base_after_rows = [base_after[name] for name in sorted(base_after)]
        base_after_sha = _sha(_canon(base_after_rows))
        report["base_integrity"] = {"before_tensor_count": len(base_before), "after_tensor_count": len(base_after),
                                    "before_inventory_sha256": base_before_sha,
                                    "after_inventory_sha256": base_after_sha,
                                    "changed_base_tensors": mismatches[:20], "bit_identical": not mismatches}
        if mismatches:
            raise Invalid("one or more base tensors changed during adapter-only update")
        report["stage_progress"].append({"stage": "base-tensors-bit-identical", "elapsed_seconds": round(time.monotonic()-started, 3)})

        adapter_file = adapter_dir / "adapters.safetensors"
        mx.save_safetensors(str(adapter_file), current, metadata={"format": "mlx"})
        config_file = adapter_dir / "adapter_config.json"
        config_sha = _save_json(config_file, _adapter_config(target_paths))
        loaded_weights = dict(mx.load(str(adapter_file)))
        disk_inventory = _validate_adapter_inventory(loaded_weights, expected_adapter, "saved")
        if disk_inventory["sha256"] != adapter_final["sha256"]:
            raise Invalid("saved adapter tensor inventory differs from trained parameters")
        report["adapter"].update({"path": str(adapter_file.relative_to(ROOT)),
                                   "sha256": file_hash(adapter_file), "bytes": adapter_file.stat().st_size,
                                   "config_path": str(config_file.relative_to(ROOT)),
                                   "config_sha256": config_sha, "disk_inventory": disk_inventory})
        report["stage_progress"].append({"stage": "adapter-saved", "elapsed_seconds": round(time.monotonic()-started, 3)})
        # Exact inventory validator must reject missing keys before invoking mlx-lm's
        # permissive strict=False loader. This is an adapter-boundary check, not a
        # claim that mlx-lm itself rejects missing tensors.
        missing_key = sorted(expected_adapter)[0]
        negative = dict(loaded_weights)
        negative.pop(missing_key)
        try:
            _validate_adapter_inventory(negative, expected_adapter, "missing-key-control")
        except Invalid as reject:
            report["adapter"]["missing_key_negative"] = {"rejected": True, "missing_key": missing_key,
                                                          "reason": str(reject)}
        else:
            raise Invalid("exact inventory validator accepted an adapter with a missing tensor")

        logits_before_reload = _eval_logits(model, tokens)
        logits_file = result_dir / "updated_logits.npy"
        np.save(logits_file, logits_before_reload, allow_pickle=False)
        report["reload"]["updated_logits"] = {"path": str(logits_file.relative_to(ROOT)),
                                                "sha256": file_hash(logits_file),
                                                "shape": list(logits_before_reload.shape),
                                                "dtype": str(logits_before_reload.dtype)}
        # Drop the trained 9B tree and optimizer state before loading the fresh tree.
        del current, loaded_weights, negative, optimizer, model, tokenizer, module_paths, module, trainable
        del value, name, canonical_name
        model = optimizer = None
        gc.collect()
        try:
            mx.clear_cache()
        except AttributeError:
            pass
        reloaded, reloaded_tokenizer, reload_config = load(
            str(SOURCE_DIR), tokenizer_config={"trust_remote_code": False, "local_files_only": True},
            trust_remote_code=False, return_config=True,
        )
        report["memory"]["fresh_model_loaded"] = _memory_metrics(mx)
        report["stage_progress"].append({"stage": "fresh-model-loaded", "elapsed_seconds": round(time.monotonic()-started, 3)})
        if (reload_config.get("model_type"), reload_config.get("architectures")) != expected_arch:
            raise Invalid("fresh model config differs from selected architecture")
        reloaded.freeze()
        load_adapters(reloaded, str(adapter_dir))
        reloaded.eval()
        reload_params = dict(tree_flatten(reloaded.trainable_parameters()))
        reload_inventory = _validate_adapter_inventory(reload_params, expected_adapter, "reloaded")
        if reload_inventory["sha256"] != adapter_final["sha256"]:
            raise Invalid("reloaded adapter tensors differ from saved adapter values")
        logits_after = _eval_logits(reloaded, tokens)
        if logits_after.shape != logits_before_reload.shape:
            raise Invalid("reloaded logits shape differs from in-memory updated logits")
        max_abs_error = float(np.max(np.abs(logits_after - logits_before_reload)))
        allclose = bool(np.allclose(logits_after, logits_before_reload, atol=ATOL, rtol=RTOL))
        report["reload"].update({"adapter_inventory": reload_inventory,
                                 "logits": {"shape": list(logits_after.shape), "dtype": str(logits_after.dtype),
                                            "sha256": _sha(logits_after.tobytes()),
                                            "max_abs_error": max_abs_error,
                                            "atol": ATOL, "rtol": RTOL, "allclose": allclose}})
        if not allclose:
            raise Invalid(f"reloaded logits differ beyond fixed tolerances (max_abs_error={max_abs_error})")
        report["stage_progress"].append({"stage": "adapter-reload-logits-match", "elapsed_seconds": round(time.monotonic()-started, 3)})
        del reloaded, reloaded_tokenizer
        gc.collect()
        try:
            mx.clear_cache()
        except AttributeError:
            pass
        # Ensure pinned source inputs were not changed while loading/training/reloading.
        for row in source_files:
            path = SOURCE_DIR / row["path"]
            if path.stat().st_size != row["bytes"] or file_hash(path) != row["sha256"]:
                raise Invalid(f"pinned model source file changed during probe: {row['path']}")
        report["runtime"]["max_rss_bytes"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        report["status"] = "PASSED"
        report["readiness"]["mechanics_probe_passed"] = True
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        report["error"] = error
        report["readiness"]["mechanics_probe_passed"] = False
    finally:
        if "mlx.core" in sys.modules:
            import mlx.core as mx
            report["runtime"]["mlx_peak_memory_bytes"] = int(mx.get_peak_memory())
        report["runtime"]["max_rss_bytes"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["finished_unix"] = time.time()
        script_path = Path(__file__).resolve()
        if report["implementation"]["sha256"] != file_hash(script_path):
            report["status"] = "FAILED"
            report.setdefault("error", {"type": "Invalid", "message": "implementation changed during probe"})
        report_sha = _save_json(result_path, report)
        print(json.dumps({"status": report["status"], "report": str(result_path),
                          "report_sha256": report_sha, "error": report.get("error")}, sort_keys=True))
    return 0 if report["status"] == "PASSED" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        return run(args.run_id)
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": {"type": type(exc).__name__,
                                                              "message": str(exc)}}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
