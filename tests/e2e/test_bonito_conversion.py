"""Public subprocess E2Es for safe, pinned Bonito conversion."""
import hashlib
import json
import os
from pathlib import Path
import struct

import torch
from tokenizers import AddedToken, Tokenizer, models, pre_tokenizers


REPOSITORY = "BatsResearch/bonito-v1"
REVISION = "0b70064ffa8956ab6bec867b87fc85762dd26d81"
SPECIAL = {"<unk>": 0, "<s>": 1, "</s>": 2}
PROTOCOL = {"<|tasktype|>": [3], "<|context|>": [4], "<|task|>": [5], "<|pipe|>": [6]}
MODEL_IDS = {
    "bonito": (REPOSITORY, "pytorch_bin", "mistral", ["MistralForCausalLM"]),
    "qwen3_8b": ("Qwen/Qwen3-8B", "safetensors", "qwen3", ["Qwen3ForCausalLM"]),
    "qwen35_9b": ("Qwen/Qwen3.5-9B", "safetensors", "qwen3_5", ["Qwen3_5ForConditionalGeneration"]),
    "qwen3_coder_teacher": ("Qwen/Qwen3-Coder-30B-A3B-Instruct", "safetensors", "qwen3_moe", ["Qwen3MoeForCausalLM"]),
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")
    return path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pin(path, role, fixture):
    fixture = Path(fixture)
    return {"path": path, "sha256": _sha(fixture), "max_bytes": max(1024, fixture.stat().st_size + 32),
            "role": role, "fixture_path": str(fixture.resolve())}


def _safetensors_f32():
    header = {"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    raw += b" " * ((8 - len(raw) % 8) % 8)
    return struct.pack("<Q", len(raw)) + raw + struct.pack("<f", 0.5)


def _tiny_state(*, omitted=None, wrong_dtype=False):
    torch.manual_seed(41)
    hidden, kv, intermediate, vocab = 8, 4, 16, 9
    dims = {
        "model.embed_tokens.weight": (vocab, hidden),
        "model.layers.0.self_attn.q_proj.weight": (hidden, hidden),
        "model.layers.0.self_attn.k_proj.weight": (kv, hidden),
        "model.layers.0.self_attn.v_proj.weight": (kv, hidden),
        "model.layers.0.self_attn.o_proj.weight": (hidden, hidden),
        "model.layers.0.mlp.gate_proj.weight": (intermediate, hidden),
        "model.layers.0.mlp.up_proj.weight": (intermediate, hidden),
        "model.layers.0.mlp.down_proj.weight": (hidden, intermediate),
        "model.layers.0.input_layernorm.weight": (hidden,),
        "model.layers.0.post_attention_layernorm.weight": (hidden,),
        "model.norm.weight": (hidden,),
        "lm_head.weight": (vocab, hidden),
    }
    state = {}
    for index, (name, shape) in enumerate(dims.items()):
        if name == omitted:
            continue
        dtype = torch.float32 if wrong_dtype and index == 0 else torch.bfloat16
        state[name] = torch.arange(1, 1 + int(torch.tensor(shape).prod()), dtype=torch.float32).reshape(shape).to(dtype) / 17
    return state


class _UnsafePayload:
    def __init__(self, sentinel):
        self.sentinel = str(sentinel)

    def __reduce__(self):
        return (os.system, (f"touch {self.sentinel}",))


def _fixture(t, label, *, unsafe=False, omitted=None, wrong_dtype=False, wrong_architecture=False):
    src = t.temporary / f"bonito-conversion-source-{label}"
    src.mkdir(parents=True)
    # A tiny real fast tokenizer shared by T12A and T12B.
    vocab = {"<unk>": 0, "<s>": 1, "</s>": 2, "<|tasktype|>": 3, "<|context|>": 4,
             "<|task|>": 5, "<|pipe|>": 6, "small": 7, "fixture": 8}
    tokenizer = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    added = [AddedToken(token, special=True) for token in (*SPECIAL, *PROTOCOL)]
    tokenizer.add_special_tokens(added)
    tokenizer_json = src / "tokenizer.json"
    tokenizer_json.write_text(tokenizer.to_str(), encoding="utf-8")
    tokenizer_config = _write_json(src / "tokenizer_config.json", {
        "added_tokens_decoder": {str(token_id): {"content": token, "special": True} for token, token_id in SPECIAL.items()},
        "bos_token": "<s>", "eos_token": "</s>", "unk_token": "<unk>"})
    special_map = _write_json(src / "special_tokens_map.json", {"bos_token": "<s>", "eos_token": "</s>", "unk_token": "<unk>"})
    added_tokens = _write_json(src / "added_tokens.json", SPECIAL)
    files_by_model = {}
    models_config = []
    hidden, kv, intermediate, vocab_size = 8, 4, 16, len(vocab)
    for model_id, (repo, weight_format, model_type, architectures) in MODEL_IDS.items():
        directory = src / model_id
        directory.mkdir()
        config_value = {"model_type": model_type, "architectures": architectures, "torch_dtype": "bfloat16" if model_id == "bonito" else "float32"}
        if model_id == "bonito":
            config_value.update({"hidden_size": hidden, "num_hidden_layers": 1, "intermediate_size": intermediate,
                                 "num_attention_heads": 2, "num_key_value_heads": 1, "rms_norm_eps": 1e-5,
                                 "vocab_size": vocab_size, "max_position_embeddings": 64, "sliding_window": 32,
                                 "rope_theta": 10000.0, "tie_word_embeddings": False,
                                 "bos_token_id": 1, "eos_token_id": 2, "hidden_act": "silu"})
            if wrong_architecture:
                config_value["architectures"] = ["UnexpectedForCausalLM"]
        config_path = _write_json(directory / "config.json", config_value)
        index_name = "pytorch_model.bin.index.json" if weight_format == "pytorch_bin" else "model.safetensors.index.json"
        token_names = ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json"]
        if model_id == "bonito":
            complete_state = _tiny_state()
            state = _tiny_state(omitted=omitted, wrong_dtype=wrong_dtype)
            ordered = sorted(complete_state)
            midpoint = len(ordered) // 2
            shard_names = ["pytorch_model-00001-of-00002.bin", "pytorch_model-00002-of-00002.bin"]
            state_by_shard = [dict((name, state[name]) for name in ordered[:midpoint] if name in state),
                              dict((name, state[name]) for name in ordered[midpoint:] if name in state)]
            if unsafe:
                state_by_shard[0] = {"unsafe": _UnsafePayload(t.temporary / f"unsafe-side-effect-{label}")}
            shard_paths = []
            for shard_name, shard_state in zip(shard_names, state_by_shard):
                shard_path = directory / shard_name
                torch.save(shard_state, shard_path)
                shard_paths.append(shard_path)
            weight_map = {name: shard_names[0] if name in ordered[:midpoint] else shard_names[1] for name in complete_state}
        else:
            shard_name = "model-00001-of-00001.safetensors"
            shard_path = directory / shard_name
            shard_path.write_bytes(_safetensors_f32())
            shard_paths = [shard_path]
            weight_map = {"weight": shard_name}
        index_path = _write_json(directory / index_name, {"metadata": {"total_size": 4}, "weight_map": weight_map})
        token_paths = {}
        for name, source in (("tokenizer.json", tokenizer_json), ("tokenizer_config.json", tokenizer_config),
                             ("special_tokens_map.json", special_map), ("added_tokens.json", added_tokens)):
            target = directory / name
            target.write_bytes(source.read_bytes())
            token_paths[name] = target
        if model_id != "bonito":
            # Student tokenizers in the acquisition fixture are unused here but
            # still satisfy the exact four-model T12B inventory contract.
            tc = token_paths["tokenizer_config.json"]
            template = "{{ messages }}\n"
            _write_json(tc, {"chat_template": template})
        pins = [_pin("config.json", "config", config_path), _pin(index_name, "index", index_path)]
        pins.extend(_pin(path.name, "weights", path) for path in shard_paths)
        pins.extend(_pin(name, "tokenizer", path) for name, path in token_paths.items())
        files_by_model[model_id] = pins
        chat_hash = None if model_id == "bonito" else hashlib.sha256(b"{{ messages }}\n").hexdigest()
        models_config.append({"id": model_id, "repo_id": repo,
                              "revision": REVISION if model_id == "bonito" else hashlib.sha1(model_id.encode()).hexdigest(),
                              "weight_format": weight_format, "config_path": "config.json", "index_path": index_name,
                              "tokenizer_files": token_names, "special_tokens": SPECIAL,
                              "chat_template_sha256": chat_hash, "files": pins})
    acquisition_config = {"schema_version": 1, "stage": "models", "kind": "fixture", "models": models_config}
    acquisition_config_path = _write_json(t.temporary / f"acquisition-config-{label}.json", acquisition_config)
    project = t.temporary / f"conversion-project-{label}"
    project.mkdir()
    acquisition = t.cli("prepare", "--config", acquisition_config_path, "--run-id", "t12b", root=project)
    t.check(acquisition["exit_code"] == 0, f"T12B fixture acquisition succeeds: {acquisition['stdout']}")
    acquisition_manifest = project / "artifacts/models/manifests/t12b.json"

    assets = []
    for name, path in (("tokenizer.json", tokenizer_json), ("tokenizer_config.json", tokenizer_config),
                       ("special_tokens_map.json", special_map), ("added_tokens.json", added_tokens),
                       ("config.json", src / "bonito/config.json")):
        assets.append({"path": name, "sha256": _sha(path), "max_bytes": max(1024, path.stat().st_size + 32),
                       "fixture_path": str(path.resolve())})
    assets_config = {"schema_version": 1, "stage": "model_assets", "kind": "fixture", "repo_id": REPOSITORY,
                     "revision": REVISION, "files": assets, "special_tokens": SPECIAL, "protocol_tokens": PROTOCOL,
                     "probe_texts": ["small fixture", "<|context|> small <|task|>"]}
    assets_config_path = _write_json(t.temporary / f"tokenizer-config-{label}.json", assets_config)
    assets_result = t.cli("prepare", "--config", assets_config_path, "--run-id", "t12a", root=project)
    t.check(assets_result["exit_code"] == 0, f"T12A fixture acquisition succeeds: {assets_result['stdout']}")
    tokenizer_manifest = project / "artifacts/models/tokenizers/t12a/manifest.json"
    conversion_config = {"schema_version": 1, "stage": "bonito_conversion",
                         "acquisition_manifest": "artifacts/models/manifests/t12b.json",
                         "acquisition_manifest_sha256": _sha(acquisition_manifest),
                         "tokenizer_manifest": "artifacts/models/tokenizers/t12a/manifest.json",
                         "tokenizer_manifest_sha256": _sha(tokenizer_manifest), "model_id": "bonito"}
    config_path = _write_json(t.temporary / f"conversion-config-{label}.json", conversion_config)
    return project, config_path, src, conversion_config


def test_bonito_conversion(t):
    root, config_path, source, config = _fixture(t, "success")
    result = t.cli("prepare", "--config", config_path, "--run-id", "convert", root=root)
    t.check(result["exit_code"] == 0, f"tiny real Torch BF16 shards convert safely: {result['stdout']}")
    output = root / "artifacts/models/conversions/convert"
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    t.check(manifest["status"] == "PASSED" and manifest["source_tensor_count"] == len(_tiny_state()) and
            manifest["review_status"] == "PENDING" and manifest["generation_allowed"] is False,
            "conversion receipt records full tensor parity but remains pending and generation-forbidden")
    t.check(manifest["safetensors"]["tensor_count"] == manifest["mlx"]["tensor_count"] == len(_tiny_state()) and
            manifest["source_tensor_inventory_sha256"] == manifest["safetensors"]["tensor_inventory_sha256"],
            "intermediate safetensors and MLX inventories contain every source tensor")
    from safetensors.torch import load_file
    expected_tensors = _tiny_state()
    for directory in ("hf-safetensors", "mlx"):
        observed = {}
        for shard in sorted((output / directory).glob("model*.safetensors")):
            tensors = load_file(str(shard))
            t.check(not set(observed).intersection(tensors), "output shards have no duplicate tensors")
            observed.update(tensors)
        t.check(set(observed) == set(expected_tensors) and all(
                    observed[name].dtype == torch.bfloat16 and
                    observed[name].shape == expected.shape and
                    torch.equal(observed[name].view(torch.uint8), expected.view(torch.uint8))
                    for name, expected in expected_tensors.items()),
                f"{directory} files preserve every expected tensor's shape, BF16 dtype and exact bits")
    t12b = json.loads((root / config["acquisition_manifest"]).read_text())
    bonito = next(model for model in t12b["models"] if model["id"] == "bonito")
    t.check(all(_sha(source / "bonito" / item["source_path"]) == item["source_sha256"] for item in manifest["safetensors"]["shards"]) and
            all((root / "artifacts/models" / record["path"]).exists() for record in bonito["files"] if record["role"] == "weights"),
            "conversion preserves the pinned raw .bin inputs unchanged")
    t.check(all(_sha(output / "mlx" / item["path"]) == item["sha256"] for item in manifest["tokenizer"]["files"]) and
            manifest["tokenizer"]["special_tokens"] == SPECIAL and manifest["tokenizer"]["protocol_tokens"] == PROTOCOL,
            "MLX output preserves T12A/T12B tokenizer bytes and special/protocol token IDs")
    committed = manifest_path.read_bytes()
    retry = t.cli("prepare", "--config", config_path, "--run-id", "convert", root=root)
    t.check(retry["exit_code"] == 0 and manifest_path.read_bytes() == committed,
            "identical conversion retries verify and preserve the immutable receipt")


def test_bonito_conversion_rejects_unsafe_and_invalid_inputs(t):
    unsafe_root, unsafe_config, source, _ = _fixture(t, "unsafe", unsafe=True)
    unsafe_result = t.cli("prepare", "--config", unsafe_config, "--run-id", "unsafe", root=unsafe_root, expected=2)
    sentinel = t.temporary / "unsafe-side-effect-unsafe"
    t.check(unsafe_result["exit_code"] == 2 and not sentinel.exists() and
            not (unsafe_root / "artifacts/models/conversions/unsafe/manifest.json").exists(),
            "weights_only rejects an unsafe pickle global without executing it or committing output")

    omitted_root, omitted_config, _, _ = _fixture(t, "missing-tensor", omitted="model.layers.0.mlp.up_proj.weight")
    missing = t.cli("prepare", "--config", omitted_config, "--run-id", "missing-tensor", root=omitted_root, expected=2)
    t.check(missing["exit_code"] == 2 and not (omitted_root / "artifacts/models/conversions/missing-tensor/manifest.json").exists(),
            "a shard missing an indexed tensor fails before conversion commit")

    dtype_root, dtype_config, _, _ = _fixture(t, "wrong-dtype", wrong_dtype=True)
    wrong_dtype = t.cli("prepare", "--config", dtype_config, "--run-id", "wrong-dtype", root=dtype_root, expected=2)
    t.check(wrong_dtype["exit_code"] == 2 and "dtype" in wrong_dtype["stdout"].lower() and
            not (dtype_root / "artifacts/models/conversions/wrong-dtype/manifest.json").exists(),
            "non-BF16 source tensor dtypes are rejected without implicit casting")

    corrupt_root, corrupt_config, _, config = _fixture(t, "corrupt")
    receipt = json.loads((corrupt_root / config["acquisition_manifest"]).read_text())
    bonito = next(model for model in receipt["models"] if model["id"] == "bonito")
    first_shard = next(record for record in bonito["files"] if record["role"] == "weights")
    blob = corrupt_root / "artifacts/models" / first_shard["path"]
    blob.write_bytes(blob.read_bytes() + b"corrupt")
    corrupt = t.cli("prepare", "--config", corrupt_config, "--run-id", "corrupt", root=corrupt_root, expected=2)
    t.check(corrupt["exit_code"] == 2 and not (corrupt_root / "artifacts/models/conversions/corrupt/manifest.json").exists(),
            "tampered raw shard hash is rejected before deserialization")


SCENARIOS = {"bonito-conversion": test_bonito_conversion, "bonito_conversion_rejects": test_bonito_conversion_rejects_unsafe_and_invalid_inputs}
