#!/usr/bin/env python3
"""Run a read-only local text-generation probe of the pinned Qwen3.5-9B."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sft.artifacts import Invalid, atomic_json, digest, fields, file_hash, identifier, read_json, safe_path
from sft.models import MODEL_ARCHITECTURES, _hash_file, _model_record, _validate


MODEL_ID = "qwen35_9b"
MAX_NEW_TOKENS = 128
SEED = 17
SYSTEM_PROMPT = "You are a concise OCaml coding assistant. Output source code only."
USER_PROMPT = (
    "Write one OCaml function named sum_squares that returns the sum of the squares "
    "of an int list. Use List.fold_left. Output only OCaml source code, with no explanation."
)
EXPECTED_PACKAGES = {"mlx": "0.32.4", "mlx-lm": "0.32.2", "transformers": "5.20.1"}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_relative(value: str, label: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value or
            value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise Invalid(f"unsafe {label}")
    return value


def _config_and_model(config_path: Path):
    raw = read_json(config_path)
    effective = _validate(ROOT, raw)
    if effective["kind"] != "official":
        raise Invalid("runtime probe requires the official pinned model config")
    rows = [model for model in effective["models"] if model["id"] == MODEL_ID]
    if len(rows) != 1:
        raise Invalid(f"model config must contain exactly one {MODEL_ID} entry")
    model = rows[0]
    if (model["repo_id"], model["revision"], model["weight_format"]) != (
            "Qwen/Qwen3.5-9B", "c202236235762e1c871ad0ccb60c8ee5ba337b9a", "safetensors"):
        raise Invalid("Qwen3.5 repository, revision, or weight format differs from the reviewed pin")
    return effective, model


def _verify_optional_manifest(manifest_path: Path | None, effective: dict, selected: dict):
    if manifest_path is None:
        return None
    if not manifest_path.is_file():
        raise Invalid("optional acquisition manifest is missing")
    manifest = read_json(manifest_path)
    fields(manifest, ["schema_version", "id", "kind", "config_hash", "implementation_hash", "models"])
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or
            not isinstance(manifest["id"], str) or manifest["kind"] != "official" or
            manifest["config_hash"] != digest(effective) or not isinstance(manifest["models"], list)):
        raise Invalid("acquisition manifest identity/config differs from the pinned official model config")
    rows = [row for row in manifest["models"] if isinstance(row, dict) and row.get("id") == MODEL_ID]
    if len(rows) != 1 or rows[0] != selected:
        raise Invalid("acquisition manifest selected-model record differs from verified pinned files")
    return {"path": str(manifest_path.relative_to(ROOT)), "sha256": file_hash(manifest_path), "id": manifest["id"]}


def _verify_selected_files(effective: dict, model: dict):
    records = []
    expected = {entry["path"]: entry for entry in model["files"]}
    if len(expected) != len(model["files"]):
        raise Invalid("duplicate selected-model file pin")
    for source_path, pin in sorted(expected.items()):
        source_path = _safe_relative(source_path, "pinned model path")
        if not isinstance(pin.get("sha256"), str) or len(pin["sha256"]) != 64:
            raise Invalid(f"invalid SHA256 pin for {source_path}")
        blob_rel = f"artifacts/models/cache/sha256/{pin['sha256']}"
        blob = safe_path(ROOT, blob_rel)
        if not blob.is_file():
            raise Invalid(f"pinned CAS file missing: {source_path}")
        size = blob.stat().st_size
        if size <= 0 or size > pin["max_bytes"] or _hash_file(blob) != pin["sha256"]:
            raise Invalid(f"pinned CAS file size/hash mismatch: {source_path}")
        records.append({"source_path": source_path, "path": blob_rel.removeprefix("artifacts/models/"),
                        "sha256": pin["sha256"], "bytes": size, "max_bytes": pin["max_bytes"],
                        "role": pin["role"], "absolute_path": blob})
    if set(model["tokenizer_files"]) - set(expected):
        raise Invalid("pinned model config references tokenizer files absent from its file inventory")
    public_records = [{key: value for key, value in record.items() if key != "absolute_path"}
                      for record in records]
    rebuilt = _model_record(ROOT, model, public_records)
    expected_type, expected_architectures = MODEL_ARCHITECTURES[MODEL_ID]
    if (rebuilt["architecture"].get("model_type") != expected_type or
            rebuilt["architecture"].get("architectures") != expected_architectures):
        raise Invalid("selected model architecture differs from Qwen3.5-9B pin")
    return records, rebuilt


def _versions():
    versions = {}
    for package in ("mlx", "mlx-lm", "transformers", "tokenizers", "huggingface-hub"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    for package, expected in EXPECTED_PACKAGES.items():
        if versions[package] != expected:
            raise Invalid(f"runtime package {package} is {versions[package]}, expected pinned {expected}")
    return versions


def _link_snapshot(source_dir: Path, records: list[dict]):
    source_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for record in records:
        relative = _safe_relative(record["source_path"], "source filename")
        target = safe_path(source_dir, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(record["absolute_path"], target)
        if target.stat().st_ino != record["absolute_path"].stat().st_ino:
            raise Invalid(f"source materialization was not a hardlink: {relative}")
        rows.append({"path": relative, "sha256": record["sha256"], "bytes": record["bytes"], "role": record["role"]})
    return rows


def _assert_unchanged(records: list[dict], source_dir: Path):
    for record in records:
        for path in (record["absolute_path"], safe_path(source_dir, record["source_path"])):
            if path.stat().st_size != record["bytes"] or _hash_file(path) != record["sha256"]:
                raise Invalid(f"pinned bytes changed during probe: {record['source_path']}")


def _run_model(source_dir: Path):
    # These flags make accidental Hub access fail instead of silently downloading.
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"})
    import mlx.core as mx
    from mlx_lm import load
    from mlx_lm.generate import stream_generate

    versions = _versions()
    mx.random.seed(SEED)
    model, tokenizer, runtime_config = load(
        str(source_dir),
        tokenizer_config={"trust_remote_code": False, "local_files_only": True},
        trust_remote_code=False,
        return_config=True,
    )
    if not tokenizer.has_chat_template:
        raise Invalid("loaded tokenizer did not expose the pinned native chat template")
    rendered = tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": USER_PROMPT}],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    if not isinstance(rendered, (list, tuple)) or not rendered or any(type(token) is not int for token in rendered):
        raise Invalid("native chat template did not produce a nonempty token ID sequence")

    started = time.perf_counter()
    generated_ids = []
    text_parts = []
    final_response = None
    for response in stream_generate(model, tokenizer, list(rendered), max_tokens=MAX_NEW_TOKENS):
        generated_ids.append(int(response.token))
        text_parts.append(response.text)
        final_response = response
    elapsed = time.perf_counter() - started
    if final_response is None:
        raise Invalid("runtime returned no generation response")

    try:
        metal_available = bool(mx.metal.is_available())
    except Exception:
        metal_available = None
    try:
        device_info = mx.device_info()
    except Exception:
        device_info = None
    return {
        "versions": versions,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "device": {"default": str(mx.default_device()), "metal_available": metal_available,
                   "info": device_info},
        "loaded_config": {"model_type": runtime_config.get("model_type"),
                          "architectures": runtime_config.get("architectures")},
        "prompt": {"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                 {"role": "user", "content": USER_PROMPT}],
                   "chat_template_sha256": file_hash(Path(source_dir, "chat_template.jinja")),
                   "enable_thinking": False, "token_ids": [int(token) for token in rendered]},
        "generation": {"method": "greedy", "temperature": 0.0, "seed": SEED,
                       "max_new_tokens": MAX_NEW_TOKENS, "token_ids": generated_ids,
                       "finish_reason": final_response.finish_reason,
                       "eos_emitted": final_response.finish_reason == "stop",
                       "text": "".join(text_parts), "elapsed_seconds": elapsed,
                       "mlx_peak_memory_bytes": int(mx.get_peak_memory()),
                       "max_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)},
    }


def run(config_path: str, manifest_arg: str | None, run_id: str):
    identifier(run_id)
    config_rel = _safe_relative(config_path, "config path")
    effective, model = _config_and_model(safe_path(ROOT, config_rel))
    records, rebuilt = _verify_selected_files(effective, model)
    acquisition = None
    if manifest_arg is not None:
        manifest_rel = _safe_relative(manifest_arg, "acquisition manifest path")
        acquisition = _verify_optional_manifest(safe_path(ROOT, manifest_rel), effective, rebuilt)

    output = safe_path(ROOT, f"artifacts/models/probes/{run_id}")
    if output.exists():
        raise Invalid(f"probe run directory already exists and is immutable: {output}")
    source_dir = safe_path(output, "source")
    output.mkdir(parents=True, exist_ok=False)
    base = {
        "schema_version": 1,
        "id": run_id,
        "status": "FAILED",
        "scope": ("T12B selected-model row plus runtime probe; full four-model acquisition not asserted"
                  if acquisition else "selected-model pinned-file runtime probe only; full acquisition incomplete"),
        "model_id": MODEL_ID,
        "repo_id": model["repo_id"],
        "revision": model["revision"],
        "config": {"path": config_rel, "sha256": file_hash(safe_path(ROOT, config_rel)),
                   "effective_config_sha256": digest(effective)},
        "acquisition_manifest": acquisition,
        "architecture": rebuilt["architecture"],
        "tensor_inventory": rebuilt["tensor_inventory"],
        "tokenizer": rebuilt["tokenizer"],
        "source_files": [],
        "runtime": None,
        "readiness": {"scope": "runtime_probe_only", "generation_allowed": False,
                      "benchmark": False, "code_executed": False},
        "implementation": {"path": "scripts/probe_qwen35.py", "sha256": file_hash(Path(__file__))},
    }
    result_path = safe_path(output, "manifest.json")
    try:
        base["source_files"] = _link_snapshot(source_dir, records)
        runtime = _run_model(source_dir)
        _assert_unchanged(records, source_dir)
        expected_template = model["chat_template_sha256"]
        if runtime["prompt"]["chat_template_sha256"] != expected_template:
            raise Invalid("native chat template hash differs from the reviewed model pin")
        if runtime["loaded_config"] != {"model_type": rebuilt["architecture"]["model_type"],
                                         "architectures": rebuilt["architecture"]["architectures"]}:
            raise Invalid("loaded MLX-LM architecture differs from pinned config")
        base["runtime"] = runtime
        generated_text = runtime["generation"]["text"]
        base["output_text"] = generated_text
        base["output_text_sha256"] = _sha(generated_text)
        base["output_token_ids"] = runtime["generation"]["token_ids"]
        base["status"] = "PASSED"
        base["implementation"]["sha256"] = file_hash(Path(__file__))
        atomic_json(result_path, base)
        manifest_sha256 = file_hash(result_path)
        print(json.dumps({"status": base["status"], "manifest": str(result_path),
                          "manifest_sha256": manifest_sha256,
                          "generated_tokens": len(runtime["generation"]["token_ids"]),
                          "finish_reason": runtime["generation"]["finish_reason"]}, sort_keys=True))
        return 0
    except Exception as error:
        base["error"] = {"type": type(error).__name__, "message": str(error)}
        base["implementation"]["sha256"] = file_hash(Path(__file__))
        atomic_json(result_path, base)
        manifest_sha256 = file_hash(result_path)
        print(json.dumps({"status": base["status"], "manifest": str(result_path),
                          "manifest_sha256": manifest_sha256,
                          "error": base["error"]}, sort_keys=True), file=sys.stderr)
        return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/models.json", help="root-relative pinned model config")
    parser.add_argument("--manifest", help="optional root-relative combined T12B acquisition manifest")
    parser.add_argument("--run-id", required=True, help="new immutable probe artifact ID")
    args = parser.parse_args()
    try:
        return run(args.config, args.manifest, args.run_id)
    except Exception as error:
        print(json.dumps({"status": "BLOCKED", "error": {"type": type(error).__name__,
                                                              "message": str(error)}}, sort_keys=True),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
