"""Fixture-only public E2Es for the pinned model acquisition stage."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import struct

from tokenizers import AddedToken, Tokenizer, models


MODEL_IDS = {
    "bonito": ("BatsResearch/bonito-v1", "pytorch_bin"),
    "qwen35_9b": ("Qwen/Qwen3.5-9B", "safetensors"),
    "qwen3_8b": ("Qwen/Qwen3-8B", "safetensors"),
    "qwen3_coder_teacher": ("Qwen/Qwen3-Coder-30B-A3B-Instruct", "safetensors"),
}
SPECIAL = {"<unk>": 0, "<s>": 1, "</s>": 2}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _pin(path, role, fixture, *, max_bytes=None):
    raw = Path(fixture).read_bytes()
    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(),
            "max_bytes": max_bytes or max(1024, len(raw) + 32), "role": role,
            "fixture_path": str(Path(fixture).resolve())}


def _safetensors():
    return _safetensors_raw({"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}},
                            b"\x00\x00\x80?")


def _safetensors_raw(header, payload):
    raw_header = json.dumps(header, separators=(",", ":")).encode()
    raw_header += b" " * ((8 - len(raw_header) % 8) % 8)
    return struct.pack("<Q", len(raw_header)) + raw_header + payload


def _fixture(t, label="good"):
    src = t.temporary / f"models-fixture-{label}"
    src.mkdir()
    models_config = []
    vocab = {token: token_id for token, token_id in SPECIAL.items()}
    tokenizer = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tokenizer.add_special_tokens([AddedToken(token, special=True) for token in SPECIAL])
    tokenizer_json = src / "tokenizer.json"
    tokenizer_json.write_text(tokenizer.to_str(), encoding="utf-8")
    template = "{{ messages }}\n"
    for model_id, (repo, weight_format) in MODEL_IDS.items():
        model_dir = src / model_id
        model_type, architectures = {
            "bonito": ("mistral", ["MistralForCausalLM"]),
            "qwen3_8b": ("qwen3", ["Qwen3ForCausalLM"]),
            "qwen35_9b": ("qwen3_5", ["Qwen3_5ForConditionalGeneration"]),
            "qwen3_coder_teacher": ("qwen3_moe", ["Qwen3MoeForCausalLM"]),
        }[model_id]
        config_file = _write(model_dir / "config.json", {"model_type": model_type, "architectures": architectures})
        index_name = "pytorch_model.bin.index.json" if weight_format == "pytorch_bin" else "model.safetensors.index.json"
        shard_name = "pytorch_model-00001-of-00001.bin" if weight_format == "pytorch_bin" else "model-00001-of-00001.safetensors"
        index_file = _write(model_dir / index_name, {"weight_map": {"weight": shard_name}})
        shard_file = model_dir / shard_name
        shard_file.write_bytes(b"opaque fixture weight payload" if weight_format == "pytorch_bin" else _safetensors())
        tokenizer_copy = model_dir / "tokenizer.json"
        tokenizer_copy.write_bytes(tokenizer_json.read_bytes())
        tokenizer_config = _write(model_dir / "tokenizer_config.json", {
            "chat_template": None if model_id == "bonito" else template})
        files = [_pin("config.json", "config", config_file), _pin(index_name, "index", index_file),
                 _pin(shard_name, "weights", shard_file), _pin("tokenizer.json", "tokenizer", tokenizer_copy),
                 _pin("tokenizer_config.json", "tokenizer", tokenizer_config)]
        chat_sha = None if model_id == "bonito" else hashlib.sha256(template.encode()).hexdigest()
        models_config.append({"id": model_id, "repo_id": repo, "revision": hashlib.sha1(model_id.encode()).hexdigest(),
                              "weight_format": weight_format, "config_path": "config.json", "index_path": index_name,
                              "tokenizer_files": ["tokenizer.json", "tokenizer_config.json"],
                              "special_tokens": SPECIAL, "chat_template_sha256": chat_sha, "files": files})
    return {"schema_version": 1, "stage": "models", "kind": "fixture", "models": models_config}


def _invoke(t, config, run_id, *, root=None, expected=0):
    root = root or t.temporary / f"models-project-{run_id}"
    root.mkdir(parents=True, exist_ok=True)
    config_path = t.temporary / f"models-config-{run_id}.json"
    _write(config_path, config)
    return t.cli("prepare", "--config", config_path, "--run-id", run_id, root=root, expected=expected), root


def _model(config, model_id):
    return next(model for model in config["models"] if model["id"] == model_id)


def _pin_for(model, path):
    return next(item for item in model["files"] if item["path"] == path)


def _replace(config, model_id, path, content):
    pin = _pin_for(_model(config, model_id), path)
    source = Path(pin["fixture_path"])
    source.write_bytes(content)
    pin["sha256"] = hashlib.sha256(content).hexdigest()
    pin["max_bytes"] = max(1024, len(content) + 32)
    return source


def test_models(t):
    config = _fixture(t)
    result, root = _invoke(t, config, "models-good")
    manifest_path = root / "artifacts/models/manifests/models-good.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    t.check(result["exit_code"] == 0 and manifest["kind"] == "fixture" and len(manifest["models"]) == 4,
            "fixture acquisition commits all four exact pinned model identities")
    records = [record for model in manifest["models"] for record in model["files"]]
    t.check(len(records) == 20 and all(record["path"] == f"cache/sha256/{record['sha256']}" for record in records),
            "all files are content-addressed and recorded with their pinned hashes")
    t.check(next(model for model in manifest["models"] if model["id"] == "bonito")["tensor_inventory"]["format"] == "pytorch_bin",
            "Bonito opaque binary shards are inventoried without deserialization")
    committed_bytes = manifest_path.read_bytes()
    retry, _ = _invoke(t, config, "models-good", root=root)
    t.check(retry["exit_code"] == 0 and manifest_path.read_bytes() == committed_bytes,
            "same run and immutable config retry successfully")
    cache_blob = root / "artifacts/models" / records[0]["path"]
    cache_blob.write_bytes(b"tampered")
    _, _ = _invoke(t, config, "models-good", root=root, expected=2)
    t.check(cache_blob.read_bytes() == b"tampered",
            "retry detects a tampered content-addressed result and fails closed")


def test_models_reject_invalid_pins(t):
    config = _fixture(t, "reject")
    missing_tokenizer = json.loads(json.dumps(config))
    for model in missing_tokenizer["models"]:
        model["tokenizer_files"].remove("tokenizer.json")
    _, root = _invoke(t, missing_tokenizer, "models-missing-tokenizer", expected=2)
    t.check(not (root / "artifacts/models/manifests/models-missing-tokenizer.json").exists(),
            "missing tokenizer JSON fails before committing an acquisition manifest")

    oversized = json.loads(json.dumps(config))
    oversized["models"][0]["files"][0]["max_bytes"] = 64 * 1024 * 1024 + 1
    _, root = _invoke(t, oversized, "models-oversized-small-file", expected=2)
    t.check(not (root / "artifacts/models/manifests/models-oversized-small-file.json").exists(),
            "small config, tokenizer, and metadata pins have strict size bounds")

    changed = json.loads(json.dumps(config))
    changed["models"][0]["files"][0]["sha256"] = "0" * 64
    _, root = _invoke(t, changed, "models-bad-hash", expected=2)
    t.check(not (root / "artifacts/models/manifests/models-bad-hash.json").exists(),
            "hash mismatch leaves no committed manifest")

    wrong_arch = _fixture(t, "wrong-architecture")
    config_data = json.loads(Path(_pin_for(_model(wrong_arch, "bonito"), "config.json")["fixture_path"]).read_text())
    config_data["architectures"] = ["UnexpectedModel"]
    _replace(wrong_arch, "bonito", "config.json", json.dumps(config_data, sort_keys=True).encode() + b"\n")
    _, root = _invoke(t, wrong_arch, "models-wrong-architecture", expected=2)
    t.check(not (root / "artifacts/models/manifests/models-wrong-architecture.json").exists(),
            "rehashed config with a different architecture identity is rejected")

    duplicate_tokens = _fixture(t, "duplicate-token-id")
    token_model = _model(duplicate_tokens, "qwen3_8b")
    tokenizer_pin = _pin_for(token_model, "tokenizer.json")
    tokenizer_data = json.loads(Path(tokenizer_pin["fixture_path"]).read_text())
    tokenizer_data["added_tokens"].append(dict(tokenizer_data["added_tokens"][0]))
    _replace(duplicate_tokens, "qwen3_8b", "tokenizer.json", json.dumps(tokenizer_data, sort_keys=True).encode() + b"\n")
    _, root = _invoke(t, duplicate_tokens, "models-duplicate-token-id", expected=2)
    t.check(not (root / "artifacts/models/manifests/models-duplicate-token-id.json").exists(),
            "duplicate tokenizer added-token IDs or strings are rejected")

    template_mismatch = _fixture(t, "template-mismatch")
    template_model = _model(template_mismatch, "qwen35_9b")
    external = Path(_pin_for(template_model, "tokenizer_config.json")["fixture_path"]).parent / "chat_template.jinja"
    external.write_text("{{ different_messages }}\n", encoding="utf-8")
    template_model["tokenizer_files"].append("chat_template.jinja")
    template_model["files"].append(_pin("chat_template.jinja", "tokenizer", external))
    _, root = _invoke(t, template_mismatch, "models-template-mismatch", expected=2)
    t.check(not (root / "artifacts/models/manifests/models-template-mismatch.json").exists(),
            "external and embedded chat templates must have the same identity")

    bad_index = _fixture(t, "missing-tensor-index")
    _replace(bad_index, "qwen3_8b", _model(bad_index, "qwen3_8b")["index_path"],
             json.dumps({"weight_map": {"missing.tensor": "model-00001-of-00001.safetensors"}}, sort_keys=True).encode() + b"\n")
    _, root = _invoke(t, bad_index, "models-index-missing-tensor", expected=2)
    t.check(not (root / "artifacts/models/manifests/models-index-missing-tensor.json").exists(),
            "index tensor names must match the safetensors header inventory")

    extra_shard = _fixture(t, "extra-shard")
    extra_model = _model(extra_shard, "qwen3_8b")
    extra_file = Path(_pin_for(extra_model, "config.json")["fixture_path"]).parent / "model-00002-of-00002.safetensors"
    extra_file.write_bytes(_safetensors())
    extra_model["files"].append(_pin("model-00002-of-00002.safetensors", "weights", extra_file))
    _, root = _invoke(t, extra_shard, "models-index-extra-shard", expected=2)
    t.check(not (root / "artifacts/models/manifests/models-index-extra-shard.json").exists(),
            "explicit shard inventory must match the index exactly")


def test_models_verify_safetensors_and_concurrent_cache(t):
    config = _fixture(t, "safetensors")
    root = t.temporary / "models-project-concurrent"
    root.mkdir()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_invoke, t, config, f"models-concurrent-{i}", root=root) for i in range(2)]
        results = [future.result()[0] for future in futures]
    t.check(all(result["exit_code"] == 0 for result in results),
            "concurrent fixture runs safely share immutable content-addressed cache blobs")

    scalar_config = _fixture(t, "scalar-zero")
    model = _model(scalar_config, "qwen3_8b")
    shard = "model-00001-of-00001.safetensors"
    scalar = _safetensors_raw({
        "scalar": {"dtype": "F32", "shape": [], "data_offsets": [0, 4]},
        "empty": {"dtype": "F32", "shape": [0, 3], "data_offsets": [4, 4]},
    }, b"\x00\x00\x80?")
    _replace(scalar_config, "qwen3_8b", shard,
             scalar)
    _replace(scalar_config, "qwen3_8b", model["index_path"],
             json.dumps({"weight_map": {"scalar": shard, "empty": shard}}, sort_keys=True).encode() + b"\n")
    _, scalar_root = _invoke(t, scalar_config, "models-scalar-zero")
    scalar_manifest = json.loads((scalar_root / "artifacts/models/manifests/models-scalar-zero.json").read_text())
    scalar_inventory = next(item for item in scalar_manifest["models"] if item["id"] == "qwen3_8b")["tensor_inventory"]
    t.check(scalar_inventory["tensor_count"] == 2,
            "valid scalar and zero-dimension safetensors are accepted")

    # Replace one valid cache blob with a fully rehashed malformed safetensors
    # container whose dtype/shape claims more bytes than its payload.
    bad_header = json.dumps({"weight": {"dtype": "F32", "shape": [2], "data_offsets": [0, 4]}},
                            separators=(",", ":")).encode()
    bad_header += b" " * ((8 - len(bad_header) % 8) % 8)
    bad_bytes = struct.pack("<Q", len(bad_header)) + bad_header + b"\x00\x00\x80?"
    bad_sha = hashlib.sha256(bad_bytes).hexdigest()
    shard_pin = next(item for item in config["models"][1]["files"] if item["role"] == "weights")
    shard_pin.update({"sha256": bad_sha, "max_bytes": len(bad_bytes) + 8})
    source = Path(shard_pin["fixture_path"])
    source.write_bytes(bad_bytes)
    _, bad_root = _invoke(t, config, "models-bad-tensor-size", expected=2)
    t.check(not (bad_root / "artifacts/models/manifests/models-bad-tensor-size.json").exists(),
            "safetensors shape and dtype byte counts must exactly match the data span")

    for label, header, payload in (
        ("gap", {"weight": {"dtype": "F32", "shape": [1], "data_offsets": [1, 5]}}, b"\x00\x00\x80?x"),
        ("trailing", {"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}, b"\x00\x00\x80?x"),
    ):
        invalid = _fixture(t, f"span-{label}")
        _replace(invalid, "qwen3_8b", "model-00001-of-00001.safetensors", _safetensors_raw(header, payload))
        _, invalid_root = _invoke(t, invalid, f"models-span-{label}", expected=2)
        t.check(not (invalid_root / f"artifacts/models/manifests/models-span-{label}.json").exists(),
                f"safetensors {label} bytes cannot remain outside exact tensor spans")


def test_models_recover_fixture_partial_and_reject_symlinks(t):
    config = _fixture(t, "partial-recovery")
    first_pin = config["models"][0]["files"][0]
    root = t.temporary / "models-project-partial-recovery"
    partial = root / f"artifacts/models/cache/.partial/{first_pin['sha256']}.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"partial bytes from a killed fixture copier")
    result, root = _invoke(t, config, "models-partial-recovery", root=root)
    manifest = json.loads((root / "artifacts/models/manifests/models-partial-recovery.json").read_text())
    t.check(result["exit_code"] == 0 and len(manifest["models"]) == 4,
            "fixture retry can recover a leftover partial blob")
    t.check(not partial.exists(), "successful fixture recovery removes the partial file")

    complete_config = _fixture(t, "complete-partial")
    complete_pin = complete_config["models"][0]["files"][0]
    expected_bytes = Path(complete_pin["fixture_path"]).read_bytes()
    complete_pin["fixture_path"] = str(t.temporary / "missing-source-after-worker-crash")
    complete_root = t.temporary / "models-project-complete-partial"
    complete_partial = complete_root / f"artifacts/models/cache/.partial/{complete_pin['sha256']}.part"
    complete_partial.parent.mkdir(parents=True)
    complete_partial.write_bytes(expected_bytes)
    result, complete_root = _invoke(t, complete_config, "models-complete-partial", root=complete_root)
    t.check(result["exit_code"] == 0 and
            (complete_root / f"artifacts/models/cache/sha256/{complete_pin['sha256']}").read_bytes() == expected_bytes,
            "a complete verified partial is committed after a crash without rereading its source")

    symlink_config = _fixture(t, "symlink-source")
    pin = _model(symlink_config, "bonito")["files"][0]
    source = Path(pin["fixture_path"])
    linked = source.parent / "linked-config.json"
    linked.symlink_to(source)
    pin["fixture_path"] = str(linked)
    _, symlink_root = _invoke(t, symlink_config, "models-symlink-source", expected=2)
    t.check(not (symlink_root / "artifacts/models/manifests/models-symlink-source.json").exists(),
            "fixture source symlinks are rejected before manifest commitment")


SCENARIOS = {"models": test_models,
             "models-rejections": test_models_reject_invalid_pins,
             "models-integrity": test_models_verify_safetensors_and_concurrent_cache,
             "models-recovery": test_models_recover_fixture_partial_and_reject_symlinks}
