"""Safely convert pinned Bonito PyTorch shards to safetensors and MLX BF16."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

from .artifacts import Invalid, canonical, digest, fields, file_hash, identifier, implementation_hash, loads, read_json, safe_path


SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_INDEX_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 ** 3
MODEL_REPOSITORY = "BatsResearch/bonito-v1"
MODEL_ID = "bonito"
MODEL_ARCHITECTURE = {"model_type": "mistral", "architectures": ["MistralForCausalLM"]}
EXPECTED_PACKAGES = {"torch": "2.14.1", "safetensors": "0.8.0", "mlx": "0.32.4", "mlx-lm": "0.32.2", "transformers": "5.20.1"}


def _sha(value, label):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise Invalid(f"invalid SHA256 in {label}")


def _safe_file(root, relative, label, limit=None):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise Invalid(f"{label} must be a safe root-relative file")
    path = safe_path(root, relative)
    if not path.is_file():
        raise Invalid(f"{label} is missing or not a regular file: {relative}")
    if limit is not None and path.stat().st_size > limit:
        raise Invalid(f"{label} exceeds size limit: {relative}")
    return path


def _json_file(path, limit, label):
    if path.stat().st_size > limit:
        raise Invalid(f"{label} exceeds size limit")
    try:
        value = read_json(path)
    except Exception as error:
        raise Invalid(f"invalid {label}: {error}") from error
    if not isinstance(value, dict):
        raise Invalid(f"{label} must be a JSON object")
    return value


def _validate_config(root, config):
    fields(config, ["schema_version", "stage", "acquisition_manifest", "acquisition_manifest_sha256",
                    "tokenizer_manifest", "tokenizer_manifest_sha256", "model_id"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["stage"] != "bonito_conversion":
        raise Invalid("unsupported Bonito conversion config")
    if config["model_id"] != MODEL_ID:
        raise Invalid("T12C converts only the pinned Bonito model")
    for key in ("acquisition_manifest_sha256", "tokenizer_manifest_sha256"):
        _sha(config[key], key)
    acquisition_path = _safe_file(root, config["acquisition_manifest"], "acquisition manifest", MAX_MANIFEST_BYTES)
    tokenizer_path = _safe_file(root, config["tokenizer_manifest"], "Bonito tokenizer manifest", MAX_MANIFEST_BYTES)
    if file_hash(acquisition_path) != config["acquisition_manifest_sha256"]:
        raise Invalid("T12B acquisition manifest hash mismatch")
    if file_hash(tokenizer_path) != config["tokenizer_manifest_sha256"]:
        raise Invalid("T12A tokenizer manifest hash mismatch")
    return acquisition_path, tokenizer_path


def _read_t12b(root, acquisition_path):
    manifest = _json_file(acquisition_path, MAX_MANIFEST_BYTES, "T12B acquisition manifest")
    fields(manifest, ["schema_version", "id", "kind", "config_hash", "implementation_hash", "models"])
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or
            not isinstance(manifest["id"], str) or not manifest["id"] or manifest["kind"] not in {"official", "fixture"}):
        raise Invalid("invalid T12B acquisition manifest identity")
    _sha(manifest["config_hash"], "T12B config_hash")
    _sha(manifest["implementation_hash"], "T12B implementation_hash")
    if not isinstance(manifest["models"], list):
        raise Invalid("T12B models must be a list")
    by_id = {}
    for model in manifest["models"]:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str) or model["id"] in by_id:
            raise Invalid("T12B model identities are malformed or duplicated")
        by_id[model["id"]] = model
    model = by_id.get(MODEL_ID)
    if model is None:
        raise Invalid("T12B manifest does not contain Bonito")
    fields(model, ["id", "repo_id", "revision", "weight_format", "config_sha256", "architecture", "index_path",
                   "index_sha256", "files", "tensor_inventory", "tokenizer"])
    if model["repo_id"] != MODEL_REPOSITORY or model["weight_format"] != "pytorch_bin" or not COMMIT.fullmatch(str(model["revision"])):
        raise Invalid("T12B Bonito repository, format, or immutable revision is invalid")
    _sha(model["config_sha256"], "Bonito config hash")
    _sha(model["index_sha256"], "Bonito index hash")
    if model["architecture"] != {**MODEL_ARCHITECTURE, "config_sha256": model["config_sha256"]}:
        raise Invalid("T12B Bonito architecture identity mismatch")
    if not isinstance(model["files"], list) or not model["files"]:
        raise Invalid("T12B Bonito file inventory is empty")
    records = {}
    total_bytes = 0
    for record in model["files"]:
        fields(record, ["source_path", "path", "sha256", "bytes", "max_bytes", "role"])
        source_path = record["source_path"]
        if not isinstance(source_path, str) or not source_path or source_path in records:
            raise Invalid("T12B Bonito file paths are malformed or duplicated")
        _sha(record["sha256"], f"T12B file {source_path}")
        if (type(record["bytes"]) is not int or type(record["max_bytes"]) is not int or record["bytes"] <= 0 or
                record["bytes"] > record["max_bytes"] or record["max_bytes"] > MAX_TOTAL_BYTES):
            raise Invalid(f"invalid T12B byte count for {source_path}")
        if record["path"] != f"cache/sha256/{record['sha256']}":
            raise Invalid(f"T12B file is not addressed by its pinned SHA256: {source_path}")
        artifact = _safe_file(root, f"artifacts/models/{record['path']}", f"T12B file {source_path}", record["max_bytes"])
        if artifact.stat().st_size != record["bytes"] or file_hash(artifact) != record["sha256"]:
            raise Invalid(f"T12B file bytes do not match the acquisition receipt: {source_path}")
        total_bytes += record["bytes"]
        records[source_path] = {**record, "absolute_path": artifact}
    if total_bytes > MAX_TOTAL_BYTES:
        raise Invalid("Bonito acquired-file total exceeds conversion safety limit")
    if model["index_path"] not in records or records[model["index_path"]]["role"] != "index":
        raise Invalid("T12B Bonito index file is absent from the pinned inventory")
    if records[model["index_path"]]["sha256"] != model["index_sha256"]:
        raise Invalid("T12B Bonito index hash differs from the pinned file record")
    if not any(record["role"] == "config" for record in records.values()):
        raise Invalid("T12B Bonito config is absent from the pinned inventory")
    if not isinstance(model["tensor_inventory"], dict) or model["tensor_inventory"].get("format") != "pytorch_bin":
        raise Invalid("T12B did not record Bonito as PyTorch .bin weights")
    return manifest, model, records


def _read_t12a(root, tokenizer_path, model, records):
    manifest = _json_file(tokenizer_path, MAX_MANIFEST_BYTES, "T12A tokenizer manifest")
    fields(manifest, ["schema_version", "id", "kind", "config_hash", "repo_id", "revision", "files", "special_tokens",
                      "protocol_tokens", "probes", "tokenizers_version", "implementation_hash"])
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["kind"] not in {"official", "fixture"} or
            manifest["repo_id"] != model["repo_id"] or manifest["revision"] != model["revision"]):
        raise Invalid("T12A tokenizer identity does not match the pinned T12B Bonito revision")
    _sha(manifest["config_hash"], "T12A config_hash")
    _sha(manifest["implementation_hash"], "T12A implementation_hash")
    if not isinstance(manifest["special_tokens"], dict) or not isinstance(manifest["protocol_tokens"], dict) or not manifest["protocol_tokens"]:
        raise Invalid("T12A special/protocol token identities are malformed")
    t12b_tokens = model.get("tokenizer")
    if not isinstance(t12b_tokens, dict) or t12b_tokens.get("special_tokens") != manifest["special_tokens"]:
        raise Invalid("T12A special-token IDs differ from T12B")
    token_files = t12b_tokens.get("tokenizer_files")
    if not isinstance(token_files, dict) or not token_files:
        raise Invalid("T12B tokenizer file identity is malformed")
    t12a_files = {}
    if not isinstance(manifest["files"], list):
        raise Invalid("T12A files must be a list")
    for record in manifest["files"]:
        fields(record, ["path", "sha256", "bytes", "max_bytes"])
        path = record["path"]
        _sha(record["sha256"], f"T12A tokenizer {path}")
        if path in t12a_files or type(record["bytes"]) is not int or type(record["max_bytes"]) is not int or record["bytes"] < 0 or record["bytes"] > record["max_bytes"]:
            raise Invalid("T12A tokenizer file records are malformed or duplicated")
        t12a_files[path] = record
        source = records.get(path)
        tokenizer_identity_matches = token_files.get(path) == record["sha256"]
        model_config_matches = path == "config.json" and source is not None and source["role"] == "config" and source["sha256"] == record["sha256"]
        if not tokenizer_identity_matches and not model_config_matches:
            raise Invalid(f"T12A tokenizer file differs from T12B identity: {path}")
        if source is None or source["role"] not in ({"tokenizer", "config"} if path == "config.json" else {"tokenizer"}) or source["sha256"] != record["sha256"]:
            raise Invalid(f"T12A tokenizer file is absent from T12B acquired files: {path}")
        asset = _safe_file(root, f"artifacts/models/tokenizers/{manifest['id']}/files/{path}", f"T12A asset {path}", record["max_bytes"])
        if asset.stat().st_size != record["bytes"] or file_hash(asset) != record["sha256"]:
            raise Invalid(f"T12A tokenizer bytes do not match its manifest: {path}")
    if not {"tokenizer.json", "config.json"} <= set(t12a_files):
        raise Invalid("T12A tokenizer proof lacks tokenizer.json or config.json")
    for path in token_files:
        record = records.get(path)
        if record is None or record["role"] != "tokenizer":
            raise Invalid(f"T12B tokenizer file missing from acquired file inventory: {path}")
    actual_dir = safe_path(root, f"artifacts/models/tokenizers/{manifest['id']}")
    actual_inventory = set()
    for path in actual_dir.rglob("*"):
        if path.is_symlink():
            raise Invalid("symlink found in T12A tokenizer directory")
        if path.is_file():
            if path == actual_dir / "manifest.json":
                actual_inventory.add("manifest.json")
            elif actual_dir / "files" in path.parents:
                actual_inventory.add(path.relative_to(actual_dir / "files").as_posix())
            else:
                actual_inventory.add(path.relative_to(actual_dir).as_posix())
    if actual_inventory != set(t12a_files) | {"manifest.json"}:
        raise Invalid("T12A tokenizer directory contains missing or unpinned files")
    return manifest


def _torch_dtype_name(tensor, torch):
    return str(tensor.dtype).removeprefix("torch.")


def _tensor_hash(tensor, torch):
    raw = tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()


def _load_shard(path, torch):
    try:
        value = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as error:
        raise Invalid(f"safe weights_only load rejected checkpoint shard {path.name}: {type(error).__name__}: {error}") from error
    if not isinstance(value, dict) or not value:
        raise Invalid(f"checkpoint shard {path.name} must be a nonempty flat tensor mapping")
    result = {}
    for name, tensor in value.items():
        if not isinstance(name, str) or not name or name in result or not isinstance(tensor, torch.Tensor):
            raise Invalid(f"checkpoint shard {path.name} contains a non-tensor or invalid key")
        if tensor.layout != torch.strided or tensor.device.type != "cpu":
            raise Invalid(f"checkpoint shard {path.name} contains unsupported tensor storage")
        if tensor.dtype != torch.bfloat16:
            raise Invalid(f"checkpoint tensor {name} dtype is {_torch_dtype_name(tensor, torch)}, expected bfloat16")
        result[name] = tensor.detach().contiguous()
    return result


def _check_device_and_packages():
    versions = {}
    for package, expected in EXPECTED_PACKAGES.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as error:
            raise Invalid(f"required conversion runtime package is unavailable: {package}") from error
        if actual != expected:
            raise Invalid(f"conversion runtime {package}={actual}, pinned {expected} required")
        versions[package] = actual
    return versions


def _copy_source_assets(root, records, destination):
    copied = {}
    for path, record in sorted(records.items()):
        if record["role"] in {"weights", "index"}:
            continue
        relative = PurePosixPath(path)
        target = safe_path(destination, relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(record["absolute_path"], target)
        if file_hash(target) != record["sha256"]:
            raise Invalid(f"staged Bonito asset changed while copying: {path}")
        copied[path] = {"sha256": record["sha256"], "bytes": record["bytes"], "role": record["role"]}
    return copied


def _convert_shards(model, records, staging, torch):
    index_record = records[model["index_path"]]
    index = _json_file(index_record["absolute_path"], MAX_INDEX_BYTES, "Bonito weight index")
    fields(index, ["weight_map"], ["metadata"])
    weight_map = index["weight_map"]
    if not isinstance(weight_map, dict) or not weight_map or any(not isinstance(k, str) or not k or not isinstance(v, str) for k, v in weight_map.items()):
        raise Invalid("Bonito weight index has an invalid weight_map")
    expected_names = set(weight_map)
    if hashlib.sha256(canonical(sorted(expected_names))).hexdigest() != model["tensor_inventory"].get("tensor_names_sha256"):
        raise Invalid("Bonito weight index tensor inventory differs from T12B")
    shards = sorted({record["source_path"] for record in records.values() if record["role"] == "weights"})
    if not shards or set(weight_map.values()) != set(shards):
        raise Invalid("Bonito index shard inventory differs from T12B pinned shards")
    converted_shards = []
    all_names = set()
    tensor_inventory = {}
    safe_map = {}
    total_tensor_bytes = 0
    for shard_index, source_name in enumerate(shards, 1):
        record = records[source_name]
        source_path = record["absolute_path"]
        state = _load_shard(source_path, torch)
        expected_shard_names = {name for name, filename in weight_map.items() if filename == source_name}
        if set(state) != expected_shard_names:
            raise Invalid(f"loaded tensor names do not exactly match pinned index for {source_name}")
        if all_names.intersection(state):
            raise Invalid("duplicate tensor name across pinned .bin shards")
        all_names.update(state)
        for name, tensor in sorted(state.items()):
            if name in tensor_inventory:
                raise Invalid(f"duplicate tensor key: {name}")
            tensor_inventory[name] = {"shape": list(tensor.shape), "dtype": _torch_dtype_name(tensor, torch),
                                      "sha256": _tensor_hash(tensor, torch), "source_shard": source_name}
            total_tensor_bytes += tensor.numel() * tensor.element_size()
        safe_name = f"model-{shard_index:05d}-of-{len(shards):05d}.safetensors"
        safe_path_out = safe_path(staging, safe_name)
        try:
            from safetensors.torch import save_file
            save_file(state, str(safe_path_out), metadata={"format": "pt"})
        except Exception as error:
            raise Invalid(f"cannot write safe tensor shard {safe_name}: {type(error).__name__}: {error}") from error
        safe_hash = file_hash(safe_path_out)
        converted_shards.append({"source_path": source_name, "source_sha256": record["sha256"],
                                 "output_path": safe_name, "output_sha256": safe_hash,
                                 "output_bytes": safe_path_out.stat().st_size, "tensor_count": len(state)})
        for name in state:
            safe_map[name] = safe_name
        del state
    if all_names != expected_names or set(tensor_inventory) != expected_names:
        raise Invalid("safe checkpoint tensor inventory is incomplete or contains extras")
    if total_tensor_bytes > MAX_TOTAL_BYTES:
        raise Invalid("total converted tensor bytes exceed safety limit")
    index_out = {"metadata": {"total_size": total_tensor_bytes}, "weight_map": {key: safe_map[key] for key in sorted(safe_map)}}
    index_path_out = safe_path(staging, "model.safetensors.index.json")
    index_path_out.write_bytes(canonical(index_out) + b"\n")
    # Re-open the written files through the safe tensor reader and check exact values.
    from safetensors import safe_open
    for shard in converted_shards:
        path = safe_path(staging, shard["output_path"])
        with safe_open(str(path), framework="pt", device="cpu") as stream:
            names = set(stream.keys())
            expected = {name for name, filename in safe_map.items() if filename == shard["output_path"]}
            if names != expected:
                raise Invalid(f"safetensors file inventory mismatch: {shard['output_path']}")
            for name in sorted(names):
                tensor = stream.get_tensor(name)
                item = tensor_inventory[name]
                if list(tensor.shape) != item["shape"] or _torch_dtype_name(tensor, torch) != item["dtype"] or _tensor_hash(tensor, torch) != item["sha256"]:
                    raise Invalid(f"safetensors values differ from safe-loaded .bin tensor: {name}")
    return {"index_path": "model.safetensors.index.json", "index_sha256": file_hash(index_path_out),
            "tensor_count": len(tensor_inventory), "tensor_inventory_sha256": hashlib.sha256(canonical([
                {"name": name, **tensor_inventory[name]} for name in sorted(tensor_inventory)])).hexdigest(),
            "tensors": tensor_inventory, "shards": converted_shards}


def _verify_mlx_output(output_dir, tensor_inventory, torch):
    from safetensors import safe_open
    index_path = safe_path(output_dir, "model.safetensors.index.json")
    if index_path.is_file():
        index = _json_file(index_path, MAX_INDEX_BYTES, "MLX safetensors index")
        fields(index, ["metadata", "weight_map"])
        weight_map = index["weight_map"]
        if not isinstance(weight_map, dict):
            raise Invalid("MLX safetensors index weight_map must be an object")
        files = sorted(set(weight_map.values()))
    else:
        files = [path.name for path in output_dir.glob("model*.safetensors")]
        if len(files) != 1:
            raise Invalid("MLX output must have an index or exactly one model safetensors file")
        weight_map = None
    if not files:
        raise Invalid("MLX converter wrote no safetensors weights")
    observed = {}
    for filename in files:
        if PurePosixPath(filename).name != filename or not filename.startswith("model") or not filename.endswith(".safetensors"):
            raise Invalid("MLX weight index contains an unsafe or unexpected filename")
        path = _safe_file(output_dir, filename, "MLX safetensors shard", MAX_TOTAL_BYTES)
        with safe_open(str(path), framework="pt", device="cpu") as stream:
            for name in stream.keys():
                if name in observed:
                    raise Invalid(f"duplicate MLX tensor name: {name}")
                tensor = stream.get_tensor(name)
                source = tensor_inventory.get(name)
                if source is None:
                    raise Invalid(f"MLX converter introduced unexpected tensor: {name}")
                if list(tensor.shape) != source["shape"] or _torch_dtype_name(tensor, torch) != "bfloat16":
                    raise Invalid(f"MLX tensor shape/dtype differs from BF16 source: {name}")
                if _tensor_hash(tensor, torch) != source["sha256"]:
                    raise Invalid(f"MLX tensor values differ from source BF16 values: {name}")
                observed[name] = filename
    if set(observed) != set(tensor_inventory):
        missing = sorted(set(tensor_inventory) - set(observed))[:4]
        raise Invalid(f"MLX tensor inventory is incomplete; missing {missing}")
    if weight_map is not None and weight_map != observed:
        raise Invalid("MLX safetensors index does not match actual output tensor names/shards")
    return {"tensor_count": len(observed), "tensor_inventory_sha256": hashlib.sha256(canonical([
        {"name": name, "shape": tensor_inventory[name]["shape"], "dtype": "bfloat16", "sha256": tensor_inventory[name]["sha256"], "shard": observed[name]}
        for name in sorted(observed)])).hexdigest(),
        "shards": [{"path": filename, "sha256": file_hash(safe_path(output_dir, filename)),
                    "bytes": safe_path(output_dir, filename).stat().st_size} for filename in files]}


def _copy_tokenizer_exact(root, records, destination):
    files = []
    for name, record in sorted(records.items()):
        if record["role"] != "tokenizer":
            continue
        target = safe_path(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(record["absolute_path"], target)
        files.append({"path": name, "sha256": file_hash(target), "bytes": target.stat().st_size})
    return files


def _file_inventory(directory):
    inventory = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise Invalid("symlink found in conversion output")
        if path.is_file() and path.name != "manifest.json":
            inventory.append({"path": path.relative_to(directory).as_posix(), "sha256": file_hash(path), "bytes": path.stat().st_size})
    return inventory


def _verify_existing(output, effective, config_hash):
    manifest_path = safe_path(output, "manifest.json")
    if not output.is_dir() or not manifest_path.is_file():
        raise Invalid("conversion output path exists without a committed manifest")
    manifest = _json_file(manifest_path, MAX_MANIFEST_BYTES, "conversion manifest")
    fields(manifest, ["schema_version", "id", "kind", "stage", "status", "config_sha256", "effective_config",
                      "acquisition_manifest_sha256", "tokenizer_manifest_sha256", "model_id", "repo_id", "revision",
                      "runtime", "source_tensor_count", "source_tensor_inventory_sha256", "safetensors", "mlx",
                      "tokenizer", "files", "implementation_sha256", "review_status", "generation_allowed"])
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["id"] != output.name or
            manifest["kind"] != "bonito_conversion" or manifest["stage"] != "bonito_conversion" or manifest["status"] != "PASSED" or
            manifest["config_sha256"] != config_hash or manifest["effective_config"] != effective or
            manifest["review_status"] != "PENDING" or manifest["generation_allowed"] is not False):
        raise Invalid("conversion run ID already has a different immutable identity")
    expected_files = manifest["files"]
    if not isinstance(expected_files, list):
        raise Invalid("conversion file inventory is malformed")
    actual_files = _file_inventory(output)
    if actual_files != expected_files:
        raise Invalid("committed conversion files are missing, changed, or untracked")
    return manifest


def prepare(root, config, run_id):
    """Convert the exact acquired Bonito checkpoint, preserving BF16 and tokenizer identity."""
    root = Path(root).resolve()
    identifier(run_id)
    acquisition_path, tokenizer_path = _validate_config(root, config)
    t12b, model, records = _read_t12b(root, acquisition_path)
    t12a = _read_t12a(root, tokenizer_path, model, records)
    effective = {key: value for key, value in config.items()}
    config_hash = digest(effective)
    store = safe_path(root, "artifacts/models/conversions")
    store.mkdir(parents=True, exist_ok=True)
    output = safe_path(store, run_id)
    if output.exists():
        manifest = _verify_existing(output, effective, config_hash)
        return {"status": "PASSED", "id": run_id, "manifest": str(safe_path(output, "manifest.json")),
                "mlx_model": str(safe_path(output, "mlx")), "tensor_count": manifest["source_tensor_count"]}, 0

    versions = _check_device_and_packages()
    config_record = next(record for record in records.values() if record["role"] == "config")
    model_config = _json_file(config_record["absolute_path"], MAX_MANIFEST_BYTES, "Bonito model config")
    if model_config.get("model_type") != "mistral" or model_config.get("architectures") != ["MistralForCausalLM"] or model_config.get("torch_dtype") != "bfloat16":
        raise Invalid("Bonito config must pin MistralForCausalLM with bfloat16 weights")
    tensor_total = sum(record["bytes"] for record in records.values() if record["role"] == "weights")
    free = shutil.disk_usage(store).free
    if free < tensor_total * 2 + 256 * 1024 * 1024:
        raise Invalid(f"insufficient free space for immutable conversion staging: need about {tensor_total * 2} bytes, have {free}")

    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}-pending-", dir=store))
    try:
        hf_source = safe_path(temporary, "hf-safetensors")
        hf_source.mkdir()
        staged_files = _copy_source_assets(root, records, hf_source)
        inventory = _convert_shards(model, records, hf_source, __import__("torch"))
        from safetensors.torch import load_file
        # The MLX importer consumes a standard local HF directory. Never pass a
        # model ID, enable custom code, quantize, or permit upload/network work.
        if os.environ.get("HF_HUB_OFFLINE") != "1" or os.environ.get("TRANSFORMERS_OFFLINE") != "1":
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            import mlx.core as mx
            mx.set_default_device(mx.cpu)
            import mlx_lm
            from mlx_lm.convert import convert as mlx_convert
            import mlx_lm.utils as mlx_utils
            if mlx_utils.MODEL_REMAPPING.get("mistral") != "llama":
                raise Invalid("pinned MLX-LM does not provide the expected Mistral-to-Llama mapping")
            mlx_output = safe_path(temporary, "mlx")
            mlx_convert(hf_path=str(hf_source), mlx_path=str(mlx_output), quantize=False,
                        dtype="bfloat16", trust_remote_code=False)
        except Invalid:
            raise
        except Exception as error:
            raise Invalid(f"pinned MLX conversion failed: {type(error).__name__}: {error}") from error
        converted_config = _json_file(safe_path(mlx_output, "config.json"), MAX_MANIFEST_BYTES, "MLX model config")
        if converted_config.get("model_type") != "mistral" or converted_config.get("architectures") != ["MistralForCausalLM"]:
            raise Invalid("MLX conversion changed the Mistral architecture identity")
        mlx_inventory = _verify_mlx_output(mlx_output, inventory["tensors"], __import__("torch"))
        copied_tokenizer = _copy_tokenizer_exact(root, records, mlx_output)
        for item in copied_tokenizer:
            expected = records[item["path"]]["sha256"]
            if item["sha256"] != expected:
                raise Invalid(f"MLX tokenizer byte identity differs from T12B/T12A: {item['path']}")
        tokenizer_receipt = {"t12a_manifest_sha256": config["tokenizer_manifest_sha256"],
                             "t12b_tokenizer_sha256": model["tokenizer"]["tokenizer_sha256"],
                             "special_tokens": t12a["special_tokens"], "protocol_tokens": t12a["protocol_tokens"],
                             "files": copied_tokenizer}
        result = {"schema_version": 1, "id": run_id, "kind": "bonito_conversion", "stage": "bonito_conversion", "status": "PASSED",
                  "config_sha256": config_hash, "effective_config": effective,
                  "acquisition_manifest_sha256": config["acquisition_manifest_sha256"],
                  "tokenizer_manifest_sha256": config["tokenizer_manifest_sha256"], "model_id": MODEL_ID,
                  "repo_id": model["repo_id"], "revision": model["revision"], "runtime": versions,
                  "source_tensor_count": inventory["tensor_count"],
                  "source_tensor_inventory_sha256": inventory["tensor_inventory_sha256"],
                  "safetensors": {key: value for key, value in inventory.items() if key != "tensors"},
                  "mlx": mlx_inventory, "tokenizer": tokenizer_receipt,
                  "files": _file_inventory(temporary),
                  "implementation_sha256": file_hash(Path(__file__)), "review_status": "PENDING", "generation_allowed": False}
        from .artifacts import atomic_json
        atomic_json(safe_path(temporary, "manifest.json"), result)
        try:
            os.rename(temporary, output)
            parent_fd = os.open(store, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except FileExistsError:
            shutil.rmtree(temporary, ignore_errors=True)
        manifest = _verify_existing(output, effective, config_hash)
        return {"status": "PASSED", "id": run_id, "manifest": str(safe_path(output, "manifest.json")),
                "mlx_model": str(safe_path(output, "mlx")), "tensor_count": manifest["source_tensor_count"]}, 0
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
