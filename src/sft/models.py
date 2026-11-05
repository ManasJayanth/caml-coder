"""Acquire explicitly pinned model files into a content-addressed local cache.

This module never imports model repository code and never deserializes PyTorch
weights. Safetensors are inspected through their bounded JSON headers only.
"""
import hashlib
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .artifacts import Invalid, atomic_json, canonical, digest, fields, file_hash, identifier, implementation_hash, loads, read_json, safe_path


COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
HASH_DIR = re.compile(r"^[0-9a-f]{64}$")
MAX_FILE_BYTES = 100 * 1024 ** 3
MODEL_REPOSITORIES = {
    "bonito": ("BatsResearch/bonito-v1", "pytorch_bin"),
    "qwen35_9b": ("Qwen/Qwen3.5-9B", "safetensors"),
    "qwen3_8b": ("Qwen/Qwen3-8B", "safetensors"),
    "qwen3_coder_teacher": ("Qwen/Qwen3-Coder-30B-A3B-Instruct", "safetensors"),
}
MODEL_ARCHITECTURES = {
    "bonito": ("mistral", ["MistralForCausalLM"]),
    "qwen3_8b": ("qwen3", ["Qwen3ForCausalLM"]),
    "qwen35_9b": ("qwen3_5", ["Qwen3_5ForConditionalGeneration"]),
    "qwen3_coder_teacher": ("qwen3_moe", ["Qwen3MoeForCausalLM"]),
}
MANIFEST_FIELDS = ["schema_version", "id", "kind", "config_hash", "implementation_hash", "models"]
FILE_ROLES = {"config", "tokenizer", "index", "weights", "metadata"}
TOKENIZER_FILENAMES = {"tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "merges.txt", "vocab.json", "vocab.txt", "tokenizer.model", "chat_template.jinja"}
METADATA_FILENAMES = TOKENIZER_FILENAMES | {"LICENSE", "LICENSE.txt", "generation_config.json", "preprocessor_config.json", "processor_config.json", "video_preprocessor_config.json"}
SMALL_ROLE_LIMIT = 64 * 1024 * 1024
INDEX_ROLE_LIMIT = 128 * 1024 * 1024
DTYPE_BYTES = {"BOOL": 1, "U8": 1, "I8": 1, "F8_E4M3": 1, "F8_E4M3FN": 1,
               "F8_E4M3FNUZ": 1, "F8_E5M2": 1, "F8_E5M2FNUZ": 1, "F8_E8M0": 1,
               "U16": 2, "I16": 2, "F16": 2, "BF16": 2, "U32": 4, "I32": 4,
               "F32": 4, "U64": 8, "I64": 8, "F64": 8}


def _safe_rel(path, label="path"):
    if (not isinstance(path, str) or not path or "\x00" in path or "\\" in path or path.startswith("/") or
        any(part in {"", ".", ".."} for part in path.split("/"))):
        raise Invalid(f"unsafe {label}")
    return path


def _validate(root, config):
    fields(config, ["schema_version", "stage", "kind", "models"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["stage"] != "models":
        raise Invalid("unsupported model acquisition config")
    if not isinstance(config["kind"], str) or config["kind"] not in {"official", "fixture"}:
        raise Invalid("model acquisition kind must be official or fixture")
    if not isinstance(config["models"], list) or len(config["models"]) != len(MODEL_REPOSITORIES):
        raise Invalid("model acquisition must pin all four model identities")
    seen_ids = set()
    normalized_models = []
    for model in config["models"]:
        fields(model, ["id", "repo_id", "revision", "weight_format", "config_path", "index_path", "tokenizer_files", "special_tokens", "chat_template_sha256", "files"])
        model_id = model["id"]
        if not isinstance(model_id, str) or model_id not in MODEL_REPOSITORIES or model_id in seen_ids:
            raise Invalid("unknown or duplicate model identity")
        expected_repo, expected_format = MODEL_REPOSITORIES[model_id]
        if not isinstance(model["repo_id"], str) or not isinstance(model["weight_format"], str) or model["repo_id"] != expected_repo or model["weight_format"] != expected_format:
            raise Invalid(f"repository or weight format mismatch for {model_id}")
        if not isinstance(model["revision"], str) or not COMMIT.fullmatch(model["revision"]):
            raise Invalid(f"{model_id}: revision must be a full immutable commit")
        config_path = _safe_rel(model["config_path"], "config path")
        index_path = _safe_rel(model["index_path"], "index path")
        if PurePosixPath(config_path).name != "config.json" or not PurePosixPath(index_path).name.endswith(".index.json"):
            raise Invalid(f"{model_id}: config/index path has unexpected filename")
        if not isinstance(model["tokenizer_files"], list) or not model["tokenizer_files"]:
            raise Invalid(f"{model_id}: tokenizer files are required")
        tokenizer_paths = [_safe_rel(path, "tokenizer path") for path in model["tokenizer_files"]]
        if len(set(tokenizer_paths)) != len(tokenizer_paths):
            raise Invalid(f"{model_id}: duplicate tokenizer file path")
        if not isinstance(model["special_tokens"], dict) or not model["special_tokens"]:
            raise Invalid(f"{model_id}: special-token IDs are required")
        for token, token_id in model["special_tokens"].items():
            if not isinstance(token, str) or not token or type(token_id) is not int or token_id < 0:
                raise Invalid(f"{model_id}: invalid special-token ID pin")
        if model["id"] == "bonito":
            if model["chat_template_sha256"] is not None:
                raise Invalid("Bonito has no chat template identity")
        elif not isinstance(model["chat_template_sha256"], str) or not SHA256.fullmatch(model["chat_template_sha256"]):
            raise Invalid(f"{model_id}: chat template SHA256 is required")
        if not isinstance(model["files"], list) or not model["files"]:
            raise Invalid(f"{model_id}: explicit file inventory is required")
        file_paths = set()
        normalized_files = []
        for item in model["files"]:
            fields(item, ["path", "sha256", "max_bytes", "role"], ["fixture_path"])
            path = _safe_rel(item["path"], "model file path")
            if path in file_paths:
                raise Invalid(f"{model_id}: duplicate file pin")
            file_paths.add(path)
            if not isinstance(item["sha256"], str) or not SHA256.fullmatch(item["sha256"]):
                raise Invalid(f"{model_id}: every file requires an explicit SHA256")
            if type(item["max_bytes"]) is not int or not 1 <= item["max_bytes"] <= MAX_FILE_BYTES:
                raise Invalid(f"{model_id}: every file requires a positive size limit no larger than 100 GiB")
            role = item["role"]
            if not isinstance(role, str) or role not in FILE_ROLES:
                raise Invalid(f"{model_id}: invalid file role")
            base = PurePosixPath(path).name
            role_limit = INDEX_ROLE_LIMIT if role == "index" else SMALL_ROLE_LIMIT if role in {"config", "tokenizer", "metadata"} else MAX_FILE_BYTES
            if item["max_bytes"] > role_limit:
                raise Invalid(f"{model_id}: {role} file max_bytes exceeds bounded limit")
            if role == "config" and (path != config_path or base != "config.json"):
                raise Invalid(f"{model_id}: config role does not match config_path")
            if role == "index" and (path != index_path or not base.endswith(".index.json")):
                raise Invalid(f"{model_id}: index role does not match index_path")
            if role == "tokenizer" and base not in TOKENIZER_FILENAMES:
                raise Invalid(f"{model_id}: unapproved tokenizer filename")
            if role == "metadata" and base not in METADATA_FILENAMES:
                raise Invalid(f"{model_id}: unapproved metadata filename")
            if role == "weights":
                expected_ext = ".bin" if expected_format == "pytorch_bin" else ".safetensors"
                if not base.endswith(expected_ext) or not base.startswith(("pytorch_model-", "model-", "model.")):
                    raise Invalid(f"{model_id}: weight shard extension/name mismatch")
            if config["kind"] == "fixture":
                if not isinstance(item.get("fixture_path"), str) or "\x00" in item["fixture_path"] or not Path(item["fixture_path"]).is_absolute():
                    raise Invalid(f"{model_id}: fixture files require absolute local fixture_path values")
            elif "fixture_path" in item:
                raise Invalid("official model pins cannot contain fixture paths")
            normalized_files.append({key: value for key, value in item.items() if key != "fixture_path"})
        if config_path not in file_paths or index_path not in file_paths:
            raise Invalid(f"{model_id}: pinned config/index file missing from inventory")
        if not any(item["role"] == "weights" for item in normalized_files):
            raise Invalid(f"{model_id}: pinned weight shards are required")
        if "tokenizer.json" not in tokenizer_paths:
            raise Invalid(f"{model_id}: tokenizer.json is required for special-token verification")
        if set(tokenizer_paths) != {item["path"] for item in normalized_files if item["role"] == "tokenizer"} or any(
            next(item for item in normalized_files if item["path"] == path)["role"] != "tokenizer"
            for path in tokenizer_paths
        ):
            raise Invalid(f"{model_id}: tokenizer file list does not match tokenizer-role pins")
        if config["kind"] == "official" and set(item["role"] for item in normalized_files) - FILE_ROLES:
            raise Invalid(f"{model_id}: unknown file role")
        if not any(item["path"] == config_path and item["role"] == "config" for item in normalized_files):
            raise Invalid(f"{model_id}: config.json must be pinned as config")
        if not any(item["path"] == index_path and item["role"] == "index" for item in normalized_files):
            raise Invalid(f"{model_id}: weight index must be pinned as index")
        seen_ids.add(model_id)
        normalized_models.append({**{key: value for key, value in model.items() if key != "files"}, "files": normalized_files})
    if seen_ids != set(MODEL_REPOSITORIES):
        raise Invalid("all four required model identities must be pinned")
    return {"schema_version": 1, "stage": "models", "kind": config["kind"], "models": normalized_models}


class _PinnedRedirect(HTTPRedirectHandler):
    HOSTS = {"huggingface.co", "cdn-lfs.huggingface.co", "cas-bridge.xethub.hf.co", "us.aws.cdn.hf.co"}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in self.HOSTS or parsed.username or parsed.password:
            raise Invalid("model download redirected outside approved HTTPS hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _url(repo_id, revision, path):
    repo = "/".join(quote(part, safe="") for part in repo_id.split("/"))
    filename = "/".join(quote(part, safe="") for part in path.split("/"))
    return f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"


def _hash_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _copy_fixture(source, partial, maximum):
    path = Path(source)
    for node in (path, *path.parents):
        if node.is_symlink():
            raise Invalid("fixture source paths cannot contain symlinks")
    if not path.is_file() or path.stat().st_size > maximum:
        raise Invalid("fixture source is missing or exceeds max_bytes")
    with path.open("rb") as src, partial.open("wb") as dst:
        copied = 0
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            copied += len(block)
            if copied > maximum:
                raise Invalid("fixture file exceeds max_bytes")
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())


def _fetch_official(repo_id, revision, path, maximum, partial):
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > maximum:
        partial.unlink()
        offset = 0
    headers = {"User-Agent": "ocaml-rl-sft-model-acquisition/1", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    opener = build_opener(_PinnedRedirect())
    request = Request(_url(repo_id, revision, path), headers=headers)
    try:
        with opener.open(request, timeout=60) as response:
            status = getattr(response, "status", 200)
            content_range = response.headers.get("Content-Range")
            append = False
            if status == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range or "")
                if not match or int(match.group(1)) != offset or int(match.group(3)) > maximum:
                    raise Invalid("invalid range response for pinned model file")
                append = True
                total = int(match.group(3))
            elif status == 200:
                total = int(response.headers["Content-Length"]) if response.headers.get("Content-Length") else None
                if total is not None and total > maximum:
                    raise Invalid("remote model file exceeds max_bytes")
                offset = 0
            else:
                raise Invalid(f"unexpected status while downloading model file: {status}")
            mode = "ab" if append else "wb"
            with partial.open(mode) as stream:
                written = offset
                while True:
                    block = response.read(min(1024 * 1024, maximum + 1 - written))
                    if not block:
                        break
                    stream.write(block)
                    written += len(block)
                    if written > maximum or (total is not None and written > total):
                        raise Invalid("remote model file exceeded declared bounds")
                stream.flush()
                os.fsync(stream.fileno())
            if total is not None and partial.stat().st_size != total:
                raise Invalid("remote model file ended before its declared size")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        raise Invalid(f"pinned model file download failed: {path}: {error}") from error


def _blob(root, pin, transport_pin, kind, repo_id, revision):
    sha = pin["sha256"]
    blob = safe_path(root, f"artifacts/models/cache/sha256/{sha}")
    blob.parent.mkdir(parents=True, exist_ok=True)
    partial = safe_path(root, f"artifacts/models/cache/.partial/{sha}.part")
    partial.parent.mkdir(parents=True, exist_ok=True)
    lock_path = safe_path(root, f"artifacts/models/cache/.partial/{sha}.lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if blob.exists():
            if not blob.is_file() or blob.stat().st_size > pin["max_bytes"] or _hash_file(blob) != sha:
                raise Invalid(f"content-addressed model cache blob is corrupt: {sha}")
            return {"path": f"cache/sha256/{sha}", "sha256": sha, "bytes": blob.stat().st_size,
                    "max_bytes": pin["max_bytes"], "role": pin["role"], "source_path": pin["path"]}
        if partial.exists():
            partial_size = partial.stat().st_size
            if partial_size > pin["max_bytes"]:
                raise Invalid(f"partial model file exceeds configured max_bytes: {pin['path']}")
            if _hash_file(partial) == sha:
                os.link(partial, blob)
                partial.unlink()
                return {"path": f"cache/sha256/{sha}", "sha256": sha, "bytes": partial_size,
                        "max_bytes": pin["max_bytes"], "role": pin["role"], "source_path": pin["path"]}
            if partial_size == pin["max_bytes"]:
                # A complete but invalid file cannot be resumed with a Range
                # request at EOF. Remove it before an explicit fresh fetch.
                partial.unlink()
        if kind == "fixture":
            _copy_fixture(transport_pin["fixture_path"], partial, pin["max_bytes"])
        else:
            _fetch_official(repo_id, revision, pin["path"], pin["max_bytes"], partial)
        actual_size = partial.stat().st_size
        if actual_size > pin["max_bytes"]:
            raise Invalid(f"model file exceeds configured max_bytes: {pin['path']}")
        if _hash_file(partial) != sha:
            partial.unlink(missing_ok=True)
            raise Invalid(f"model file SHA256 mismatch: {repo_id}/{pin['path']}")
        try:
            os.link(partial, blob)
            partial.unlink()
        except FileExistsError:
            if not blob.is_file() or _hash_file(blob) != sha:
                raise Invalid(f"concurrent model cache conflict: {sha}")
            partial.unlink(missing_ok=True)
        return {"path": f"cache/sha256/{sha}", "sha256": sha, "bytes": actual_size,
                "max_bytes": pin["max_bytes"], "role": pin["role"], "source_path": pin["path"]}


def _index_and_tensors(root, model, file_records):
    by_path = {record["source_path"]: record for record in file_records}
    index_record = by_path[model["index_path"]]
    index_path = safe_path(root, f"artifacts/models/{index_record['path']}")
    index = read_json(index_path)
    if not isinstance(index, dict) or not isinstance(index.get("weight_map"), dict) or not index["weight_map"]:
        raise Invalid(f"{model['id']}: weight index lacks a nonempty weight_map")
    weight_map = index["weight_map"]
    if any(not isinstance(name, str) or not name or not isinstance(filename, str) for name, filename in weight_map.items()):
        raise Invalid(f"{model['id']}: malformed weight_map")
    shards = {filename for filename in weight_map.values()}
    pinned_shards = {path for path, record in by_path.items() if record["role"] == "weights"}
    if shards != pinned_shards:
        raise Invalid(f"{model['id']}: index shard set differs from explicit pinned files")
    for shard in shards:
        _safe_rel(shard, "weight shard path")

    if model["weight_format"] == "pytorch_bin":
        return {"format": "pytorch_bin", "tensor_count": len(weight_map),
                "tensor_names_sha256": hashlib.sha256(canonical(sorted(weight_map))).hexdigest(),
                "shards": sorted(shards), "header_sha256": None, "dtype_counts": None}

    header_records = []
    dtype_counts = {}
    tensor_names = set()
    for shard in sorted(shards):
        record = by_path[shard]
        path = safe_path(root, f"artifacts/models/{record['path']}")
        with path.open("rb") as stream:
            prefix = stream.read(8)
            if len(prefix) != 8:
                raise Invalid(f"{model['id']}: truncated safetensors header in {shard}")
            header_size = struct.unpack("<Q", prefix)[0]
            if header_size < 2 or header_size > min(record["bytes"] - 8, 16 * 1024 * 1024):
                raise Invalid(f"{model['id']}: invalid safetensors header size in {shard}")
            raw_header = stream.read(header_size)
            if len(raw_header) != header_size:
                raise Invalid(f"{model['id']}: truncated safetensors metadata in {shard}")
        header = loads(raw_header.decode("utf-8"))
        if not isinstance(header, dict):
            raise Invalid(f"{model['id']}: safetensors header is not an object")
        data_size = record["bytes"] - 8 - header_size
        spans = []
        shard_names = set()
        for name, item in header.items():
            if name == "__metadata__":
                if not isinstance(item, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item.items()):
                    raise Invalid(f"{model['id']}: malformed safetensors metadata")
                continue
            if not isinstance(name, str) or not name or not isinstance(item, dict):
                raise Invalid(f"{model['id']}: malformed safetensors tensor header")
            fields(item, ["dtype", "shape", "data_offsets"])
            dtype, shape, offsets = item["dtype"], item["shape"], item["data_offsets"]
            if not isinstance(dtype, str) or dtype not in DTYPE_BYTES:
                raise Invalid(f"{model['id']}: invalid tensor dtype in {shard}")
            if not isinstance(shape, list) or any(type(dim) is not int or dim < 0 for dim in shape):
                raise Invalid(f"{model['id']}: invalid tensor shape in {shard}")
            if not isinstance(offsets, list) or len(offsets) != 2 or any(type(x) is not int for x in offsets):
                raise Invalid(f"{model['id']}: invalid tensor data offsets in {shard}")
            start, end = offsets
            if start < 0 or end < start or end > data_size:
                raise Invalid(f"{model['id']}: tensor data offsets exceed shard size in {shard}")
            elements = 1
            for dimension in shape:
                elements *= dimension
            if elements * DTYPE_BYTES[dtype] != end - start:
                raise Invalid(f"{model['id']}: tensor shape/dtype size mismatch in {shard}")
            spans.append((start, end))
            shard_names.add(name)
            dtype_counts[dtype] = dtype_counts.get(dtype, 0) + 1
            tensor_names.add(name)
            if weight_map.get(name) != shard:
                raise Invalid(f"{model['id']}: tensor-to-shard index mismatch for {name}")
        if not shard_names:
            raise Invalid(f"{model['id']}: empty safetensors shard")
        ordered = sorted(spans)
        cursor = 0
        for start, end in ordered:
            if start != cursor:
                raise Invalid(f"{model['id']}: tensor data spans have a gap or overlap in {shard}")
            cursor = end
        if cursor != data_size:
            raise Invalid(f"{model['id']}: unclaimed trailing tensor data in {shard}")
        header_records.append({"shard": shard, "header_sha256": hashlib.sha256(raw_header).hexdigest(),
                              "tensor_count": len(shard_names), "dtypes": sorted({
                                  item["dtype"] for name, item in header.items() if name != "__metadata__"})})
    if tensor_names != set(weight_map):
        raise Invalid(f"{model['id']}: safetensors headers and index have different tensor inventories")
    inventory = []
    for shard in sorted(shards):
        path = safe_path(root, f"artifacts/models/{by_path[shard]['path']}")
        with path.open("rb") as stream:
            header_size = struct.unpack("<Q", stream.read(8))[0]
            header = loads(stream.read(header_size).decode("utf-8"))
        for name, item in header.items():
            if name != "__metadata__":
                inventory.append({"name": name, "shard": shard, "dtype": item["dtype"], "shape": item["shape"]})
    tensor_identity = hashlib.sha256(canonical(sorted(inventory, key=lambda row: row["name"]))).hexdigest()
    return {"format": "safetensors", "tensor_count": len(tensor_names), "tensor_inventory_sha256": tensor_identity,
            "shards": sorted(shards), "headers": header_records, "dtype_counts": dict(sorted(dtype_counts.items()))}


def _tokenizer_identity(root, model, file_records):
    by_path = {record["source_path"]: record for record in file_records}
    token_files = {path: by_path[path]["sha256"] for path in model["tokenizer_files"]}
    token_hash = digest(token_files)
    tokenizer_json = next((path for path in model["tokenizer_files"] if PurePosixPath(path).name == "tokenizer.json"), None)
    if not tokenizer_json:
        raise Invalid(f"{model['id']}: tokenizer.json is required")
    record = by_path[tokenizer_json]
    tokenizer_path = safe_path(root, f"artifacts/models/{record['path']}")
    parsed = read_json(tokenizer_path)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("added_tokens"), list):
        raise Invalid(f"{model['id']}: tokenizer.json has no added_tokens list")
    ids, seen_ids, seen_tokens = {}, set(), set()
    for row in parsed["added_tokens"]:
        if not isinstance(row, dict) or type(row.get("id")) is not int or not isinstance(row.get("content"), str) or not row["content"]:
            raise Invalid(f"{model['id']}: malformed tokenizer added_tokens entry")
        if row["id"] in seen_ids or row["content"] in seen_tokens:
            raise Invalid(f"{model['id']}: duplicate tokenizer added-token ID or string")
        seen_ids.add(row["id"])
        seen_tokens.add(row["content"])
        ids[row["content"]] = row["id"]
    try:
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
    except Exception as error:
        raise Invalid(f"{model['id']}: tokenizer.json cannot be loaded by tokenizers: {error}") from error
    for token, expected in model["special_tokens"].items():
        if ids.get(token) != expected or tokenizer.token_to_id(token) != expected:
            raise Invalid(f"{model['id']}: special-token ID mismatch for {token}")
    template_candidates = []
    for path in model["tokenizer_files"]:
        record = by_path[path]
        artifact = safe_path(root, f"artifacts/models/{record['path']}")
        base = PurePosixPath(path).name
        if base == "tokenizer_config.json":
            value = read_json(artifact)
            if not isinstance(value, dict):
                raise Invalid(f"{model['id']}: tokenizer_config.json must be an object")
            template = value.get("chat_template")
            if template is not None:
                if not isinstance(template, str):
                    raise Invalid(f"{model['id']}: chat_template must be a string")
                template_candidates.append(hashlib.sha256(template.encode("utf-8")).hexdigest())
        if base == "chat_template.jinja":
            template_candidates.append(_hash_file(artifact))
    if len(set(template_candidates)) > 1:
        raise Invalid(f"{model['id']}: tokenizer config and external chat template disagree")
    actual_template = template_candidates[0] if template_candidates else None
    if actual_template != model["chat_template_sha256"]:
        raise Invalid(f"{model['id']}: chat template identity mismatch")
    return {"tokenizer_files": token_files, "tokenizer_sha256": token_hash,
            "special_tokens": model["special_tokens"], "chat_template_sha256": actual_template}


def _model_record(root, model, file_records):
    by_path = {record["source_path"]: record for record in file_records}
    config_record = by_path[model["config_path"]]
    config_data = read_json(safe_path(root, f"artifacts/models/{config_record['path']}"))
    if not isinstance(config_data, dict):
        raise Invalid(f"{model['id']}: config.json must be an object")
    expected_type, expected_architectures = MODEL_ARCHITECTURES[model["id"]]
    if (config_data.get("model_type") != expected_type or
        config_data.get("architectures") != expected_architectures):
        raise Invalid(f"{model['id']}: model architecture identity mismatch")
    tensor_info = _index_and_tensors(root, model, file_records)
    tokenizer = _tokenizer_identity(root, model, file_records)
    return {"id": model["id"], "repo_id": model["repo_id"], "revision": model["revision"],
            "weight_format": model["weight_format"], "config_sha256": config_record["sha256"],
            "architecture": {"model_type": config_data.get("model_type"), "architectures": config_data.get("architectures"),
                             "config_sha256": config_record["sha256"]},
            "index_path": model["index_path"], "index_sha256": by_path[model["index_path"]]["sha256"],
            "files": sorted(file_records, key=lambda row: row["source_path"]),
            "tensor_inventory": tensor_info, "tokenizer": tokenizer}


def _verify(root, output, effective):
    manifest = read_json(output)
    fields(manifest, MANIFEST_FIELDS)
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or
        manifest["id"] != output.stem or manifest["kind"] != effective["kind"] or
        manifest["config_hash"] != digest(effective)):
        raise Invalid("model acquisition run ID is bound to a different config")
    expected_impl = implementation_hash(Path(__file__).resolve().parents[2])
    if manifest["implementation_hash"] != expected_impl:
        raise Invalid("model acquisition implementation changed since manifest creation")
    if not isinstance(manifest["models"], list) or len(manifest["models"]) != len(effective["models"]):
        raise Invalid("model manifest inventory mismatch")
    for config_model, actual_model in zip(effective["models"], manifest["models"]):
        fields(actual_model, ["id", "repo_id", "revision", "weight_format", "config_sha256", "architecture", "index_path", "index_sha256", "files", "tensor_inventory", "tokenizer"])
        if (actual_model["id"] != config_model["id"] or actual_model["repo_id"] != config_model["repo_id"] or
            actual_model["revision"] != config_model["revision"] or actual_model["weight_format"] != config_model["weight_format"]):
            raise Invalid("model identity differs from pinned config")
        if not isinstance(actual_model["files"], list) or len(actual_model["files"]) != len(config_model["files"]):
            raise Invalid("model file manifest differs from pinned inventory")
        expected_files = {item["path"]: item for item in config_model["files"]}
        seen = set()
        for record in actual_model["files"]:
            fields(record, ["source_path", "path", "sha256", "bytes", "max_bytes", "role"])
            if not isinstance(record["source_path"], str) or not isinstance(record["path"], str):
                raise Invalid("invalid model file record path")
            pin = expected_files.get(record["source_path"])
            if (not pin or record["source_path"] in seen or record["sha256"] != pin["sha256"] or
                record["max_bytes"] != pin["max_bytes"] or record["role"] != pin["role"] or
                type(record["bytes"]) is not int or record["bytes"] > pin["max_bytes"]):
                raise Invalid("model file record does not match explicit pins")
            seen.add(record["source_path"])
            expected_cache = f"cache/sha256/{pin['sha256']}"
            if record["path"] != expected_cache:
                raise Invalid("model blob path is not content-addressed by pinned SHA256")
            blob = safe_path(root, f"artifacts/models/{record['path']}")
            if not blob.is_file() or blob.stat().st_size != record["bytes"] or _hash_file(blob) != record["sha256"]:
                raise Invalid(f"model cache blob missing or corrupt: {pin['path']}")
        if seen != set(expected_files):
            raise Invalid("model file manifest omitted pinned files")
        rebuilt = _model_record(root, config_model, actual_model["files"])
        if rebuilt != actual_model:
            raise Invalid("model metadata manifest differs from verified model files")
    return manifest


def prepare(root, config, run_id):
    """Acquire four fully pinned models into a SHA256-addressed cache."""
    root = Path(root).resolve()
    identifier(run_id)
    effective = _validate(root, config)
    fixture_paths = {model["id"]: {item["path"]: item for item in model["files"]}
                     for model in config["models"]} if config["kind"] == "fixture" else {}
    manifest_path = safe_path(root, f"artifacts/models/manifests/{run_id}.json")
    if manifest_path.exists():
        manifest = _verify(root, manifest_path, effective)
        return {"status": "PASSED", "id": run_id, "manifest": str(manifest_path), "models": len(manifest["models"])}, 0

    cache = safe_path(root, "artifacts/models/cache")
    cache.mkdir(parents=True, exist_ok=True)
    unique_pins = {item["sha256"]: item for model in effective["models"] for item in model["files"]}
    missing = []
    for sha, pin in unique_pins.items():
        blob = safe_path(root, f"artifacts/models/cache/sha256/{sha}")
        if blob.exists():
            if not blob.is_file() or blob.stat().st_size > pin["max_bytes"] or _hash_file(blob) != sha:
                raise Invalid(f"content-addressed model cache blob is corrupt: {sha}")
        else:
            missing.append(pin["max_bytes"])
    required = sum(missing)
    free = shutil.disk_usage(cache).free
    if free < required:
        raise Invalid(f"insufficient disk space for pinned model assets: need {required} bytes, have {free}")

    records = []
    for model in effective["models"]:
        file_records = []
        for pin in model["files"]:
            transport_pin = fixture_paths.get(model["id"], {}).get(pin["path"], pin)
            file_records.append(_blob(root, pin, transport_pin, effective["kind"], model["repo_id"], model["revision"]))
        records.append(_model_record(root, model, file_records))
    manifest = {"schema_version": 1, "id": run_id, "kind": effective["kind"],
                "config_hash": digest(effective),
                "implementation_hash": implementation_hash(Path(__file__).resolve().parents[2]),
                "models": records}
    atomic_json(manifest_path, manifest)
    manifest = _verify(root, manifest_path, effective)
    return {"status": "PASSED", "id": run_id, "manifest": str(manifest_path), "models": len(manifest["models"])}, 0
