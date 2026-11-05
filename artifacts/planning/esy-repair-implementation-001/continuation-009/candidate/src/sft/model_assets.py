"""Fetch and verify pinned Bonito tokenizer assets without executing model code."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .artifacts import Invalid, atomic_bytes, atomic_json, canonical, digest, fields, file_hash, identifier, implementation_hash, read_json, safe_path


COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SPECIAL = re.compile(r"^<[^<>\s]{1,64}>$")
PROTOCOL_MARKER = re.compile(r"^<\|[A-Za-z0-9_]+\|>$")
ALLOWED_FILES = {"tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "config.json", "generation_config.json"}
MAX_FILE_SIZE = 50 * 1024 * 1024
OFFICIAL_REPOSITORY = "BatsResearch/bonito-v1"
MANIFEST_FIELDS = ["schema_version", "id", "kind", "config_hash", "repo_id", "revision", "files", "special_tokens", "protocol_tokens", "probes", "tokenizers_version", "implementation_hash"]


def _validate(root, config):
    fields(config, ["schema_version", "stage", "kind", "repo_id", "revision", "files", "special_tokens", "protocol_tokens", "probe_texts"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["stage"] != "model_assets":
        raise Invalid("unsupported model-assets config")
    if not isinstance(config["kind"], str) or config["kind"] not in {"official", "fixture"}:
        raise Invalid("model-assets kind must be official or fixture")
    if not isinstance(config["repo_id"], str) or not REPO.fullmatch(config["repo_id"]):
        raise Invalid("repository must be a Hugging Face namespace/name")
    if config["kind"] == "official" and config["repo_id"] != OFFICIAL_REPOSITORY:
        raise Invalid("official tokenizer must use the approved Bonito repository")
    if not isinstance(config["revision"], str) or not COMMIT.fullmatch(config["revision"]):
        raise Invalid("revision must be a full immutable 40-character commit")
    if not isinstance(config["files"], list) or not config["files"]:
        raise Invalid("explicit tokenizer asset file pins are required")
    paths = set()
    for item in config["files"]:
        fields(item, ["path", "sha256", "max_bytes"], ["fixture_path"])
        name = item["path"]
        if (not isinstance(name, str) or "\x00" in name or "\\" in name or name.startswith("/") or
            any(part in {"", ".", ".."} for part in name.split("/")) or
            not PurePosixPath(name).parts or PurePosixPath(name).name not in ALLOWED_FILES):
            raise Invalid("asset path must name an approved tokenizer/config JSON file")
        if name in paths:
            raise Invalid("duplicate tokenizer asset path")
        paths.add(name)
        if not isinstance(item["sha256"], str) or not SHA256.fullmatch(item["sha256"]):
            raise Invalid("each asset requires an explicit lowercase SHA256")
        if type(item["max_bytes"]) is not int or not 1 <= item["max_bytes"] <= MAX_FILE_SIZE:
            raise Invalid("each asset requires a positive explicit size limit at most 50 MiB")
        if config["kind"] == "fixture":
            if (not isinstance(item.get("fixture_path"), str) or "\x00" in item["fixture_path"] or
                not Path(item["fixture_path"]).is_absolute()):
                raise Invalid("fixture assets require an absolute local fixture_path")
        elif "fixture_path" in item:
            raise Invalid("official asset pins cannot contain fixture paths")
    if "tokenizer.json" not in paths or "config.json" not in paths:
        raise Invalid("pinned tokenizer.json and config.json are required")
    if not isinstance(config["special_tokens"], dict) or not config["special_tokens"]:
        raise Invalid("special-token ID pins are required")
    ids = set()
    for token, token_id in config["special_tokens"].items():
        if not isinstance(token, str) or not SPECIAL.fullmatch(token) or type(token_id) is not int or token_id < 0:
            raise Invalid("special_tokens must map strings to nonnegative integer IDs")
        if token_id in ids:
            raise Invalid("special-token IDs must be distinct")
        ids.add(token_id)
    if not isinstance(config["protocol_tokens"], dict) or not config["protocol_tokens"]:
        raise Invalid("Bonito protocol token sequences are required")
    for text, expected in config["protocol_tokens"].items():
        if not isinstance(text, str) or not PROTOCOL_MARKER.fullmatch(text) or len(text.encode("utf-8")) > 128:
            raise Invalid("protocol token text must be a nonempty bounded string")
        if not isinstance(expected, list) or not expected or any(type(i) is not int or i < 0 for i in expected):
            raise Invalid("protocol tokens must map to nonempty integer-ID sequences")
    if not isinstance(config["probe_texts"], list) or not config["probe_texts"] or len(config["probe_texts"]) > 32:
        raise Invalid("one to 32 deterministic tokenizer probe texts are required")
    if any(not isinstance(text, str) or not text or len(text.encode("utf-8")) > 8192 for text in config["probe_texts"]):
        raise Invalid("probe texts must be nonempty strings no larger than 8 KiB")
    return {key: value for key, value in config.items() if key != "files"} | {
        "files": [{key: value for key, value in item.items() if key != "fixture_path"} for item in config["files"]]
    }


def _approved_url(repository, revision, path):
    encoded_repo = "/".join(quote(part, safe="") for part in repository.split("/"))
    encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
    return f"https://huggingface.co/{encoded_repo}/resolve/{revision}/{encoded_path}"


class _PinnedRedirect(HTTPRedirectHandler):
    HOSTS = {"huggingface.co", "cdn-lfs.huggingface.co", "cas-bridge.xethub.hf.co"}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in self.HOSTS or parsed.username or parsed.password:
            raise Invalid("tokenizer download redirected outside approved HTTPS hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_fixture(path, maximum):
    source = Path(path)
    if not source.is_absolute():
        raise Invalid("fixture source path must be absolute")
    for node in (source, *source.parents):
        if node.is_symlink():
            raise Invalid("fixture source paths cannot contain symlinks")
    if not source.is_file():
        raise Invalid("fixture asset is missing or not a regular file")
    if source.stat().st_size > maximum:
        raise Invalid("fixture asset exceeds pinned max_bytes")
    data = source.read_bytes()
    if len(data) > maximum:
        raise Invalid("fixture asset exceeds pinned max_bytes")
    return data


def _download(repository, revision, path, maximum):
    url = _approved_url(repository, revision, path)
    opener = build_opener(_PinnedRedirect())
    request = Request(url, headers={"User-Agent": "ocaml-rl-sft-tokenizer/1", "Accept-Encoding": "identity"})
    try:
        with opener.open(request, timeout=45) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in _PinnedRedirect.HOSTS:
                raise Invalid("tokenizer download ended outside approved HTTPS hosts")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > maximum:
                raise Invalid("downloaded asset exceeds pinned max_bytes")
            result = bytearray()
            while True:
                part = response.read(min(65536, maximum + 1 - len(result)))
                if not part:
                    break
                result.extend(part)
                if len(result) > maximum:
                    raise Invalid("downloaded asset exceeds pinned max_bytes")
            return bytes(result)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        raise Invalid(f"pinned tokenizer asset download failed: {path}: {error}") from error


def _load_tokenizer(directory, config):
    try:
        from tokenizers import Tokenizer, __version__ as tokenizers_version
    except ImportError as error:
        raise Invalid("the pinned tokenizers runtime dependency is unavailable") from error
    tokenizer_path = safe_path(directory, "files/tokenizer.json")
    try:
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        tokenizer_data = read_json(tokenizer_path)
    except Exception as error:
        raise Invalid(f"cannot load pinned tokenizer.json safely: {error}") from error
    if not isinstance(tokenizer_data, dict) or not isinstance(tokenizer_data.get("added_tokens"), list):
        raise Invalid("tokenizer.json has no valid added_tokens inventory")
    added = {}
    for item in tokenizer_data["added_tokens"]:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str) or type(item.get("id")) is not int or type(item.get("special")) is not bool:
            raise Invalid("malformed tokenizer added-token record")
        if item["content"] in added:
            raise Invalid("duplicate added token in tokenizer.json")
        added[item["content"]] = item
    for token, expected_id in config["special_tokens"].items():
        row = added.get(token)
        if not row or row["special"] is not True or row["id"] != expected_id or tokenizer.token_to_id(token) != expected_id:
            raise Invalid(f"special-token ID mismatch for {token}")
    for token, expected_ids in config["protocol_tokens"].items():
        try:
            actual_ids = tokenizer.encode(token, add_special_tokens=False).ids
        except Exception as error:
            raise Invalid(f"protocol tokenization failed for {token}: {error}") from error
        if actual_ids != expected_ids:
            raise Invalid(f"protocol token sequence mismatch for {token}")
    probes = []
    try:
        for text in config["probe_texts"]:
            first = tokenizer.encode(text, add_special_tokens=False).ids
            second = tokenizer.encode(text, add_special_tokens=False).ids
            with_special = tokenizer.encode(text, add_special_tokens=True).ids
            with_special_repeat = tokenizer.encode(text, add_special_tokens=True).ids
            decoded_a = tokenizer.decode(first, skip_special_tokens=False)
            decoded_b = tokenizer.decode(first, skip_special_tokens=False)
            if (not first or first != second or not with_special or with_special != with_special_repeat or
                decoded_a != decoded_b):
                raise Invalid("tokenizer probe is empty or nondeterministic")
            probes.append({"input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                           "token_count": len(first),
                           "token_ids_sha256": hashlib.sha256(canonical(first)).hexdigest(),
                           "with_special_tokens_count": len(with_special),
                           "with_special_tokens_ids_sha256": hashlib.sha256(canonical(with_special)).hexdigest(),
                           "decoded_sha256": hashlib.sha256(decoded_a.encode("utf-8")).hexdigest()})
    except Invalid:
        raise
    except Exception as error:
        raise Invalid(f"tokenizer probe failed: {error}") from error
    return probes, tokenizers_version


def _verify(root, output, config, effective):
    manifest_path = safe_path(output, "manifest.json")
    manifest = read_json(manifest_path)
    fields(manifest, MANIFEST_FIELDS)
    expected_config_hash = digest(effective)
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or
        manifest["id"] != output.name or manifest["kind"] != config["kind"] or
        manifest["config_hash"] != expected_config_hash or manifest["repo_id"] != config["repo_id"] or
        manifest["revision"] != config["revision"] or manifest["special_tokens"] != config["special_tokens"] or
        manifest["protocol_tokens"] != config["protocol_tokens"]):
        raise Invalid("tokenizer run ID already has a different immutable identity")
    if not isinstance(manifest["files"], list) or len(manifest["files"]) != len(effective["files"]):
        raise Invalid("tokenizer manifest file inventory mismatch")
    expected = {item["path"]: item for item in effective["files"]}
    seen = set()
    for record in manifest["files"]:
        fields(record, ["path", "sha256", "bytes", "max_bytes"])
        if not isinstance(record["path"], str) or not isinstance(record["sha256"], str):
            raise Invalid("tokenizer manifest path or hash has the wrong type")
        item = expected.get(record["path"])
        if (not item or record["path"] in seen or not SHA256.fullmatch(record["sha256"]) or record["sha256"] != item["sha256"] or
            record["max_bytes"] != item["max_bytes"] or type(record["bytes"]) is not int or
            record["bytes"] < 0 or record["bytes"] > item["max_bytes"]):
            raise Invalid("tokenizer manifest file pin mismatch")
        seen.add(record["path"])
        path = safe_path(output, f"files/{record['path']}")
        if not path.is_file() or path.stat().st_size != record["bytes"] or file_hash(path) != record["sha256"]:
            raise Invalid("committed tokenizer asset is missing or corrupt")
        if PurePosixPath(record["path"]).name in {"config.json", "generation_config.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json"}:
            data = read_json(path)
            if not isinstance(data, dict):
                raise Invalid(f"pinned tokenizer/config JSON must be an object: {record['path']}")
    if seen != set(expected):
        raise Invalid("tokenizer manifest omitted a pinned asset")
    inventory = set()
    for path in output.rglob("*"):
        if path.is_symlink():
            raise Invalid("symlink found inside committed tokenizer assets")
        if path.is_file():
            inventory.add(path.relative_to(output).as_posix())
    if inventory != {"manifest.json", *(f"files/{path}" for path in expected)}:
        raise Invalid("committed tokenizer directory contains untracked files")
    probes, tokenizers_version = _load_tokenizer(output, config)
    if probes != manifest["probes"]:
        raise Invalid("tokenizer probe evidence does not match verified assets")
    current_implementation_hash = implementation_hash(Path(__file__).resolve().parents[2])
    if manifest["tokenizers_version"] != tokenizers_version or manifest["implementation_hash"] != current_implementation_hash:
        raise Invalid("tokenizer runtime or implementation changed since asset verification")
    return manifest, manifest_path


def prepare(root, config, run_id):
    """Fetch only explicitly pinned tokenizer/config files and commit them immutably."""
    root = Path(root).resolve()
    identifier(run_id)
    effective = _validate(root, config)
    store = safe_path(root, "artifacts/models/tokenizers")
    store.mkdir(parents=True, exist_ok=True)
    output = safe_path(store, run_id)
    if output.exists():
        if not output.is_dir() or not safe_path(output, "manifest.json").is_file():
            raise Invalid("uncommitted tokenizer output already exists")
        manifest, manifest_path = _verify(root, output, config, effective)
        return {"status": "PASSED", "id": run_id, "manifest": str(manifest_path), "files": len(manifest["files"])}, 0

    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}-pending-", dir=store))
    try:
        file_records = []
        for item, pin in zip(config["files"], effective["files"]):
            raw = (_read_fixture(item["fixture_path"], item["max_bytes"]) if config["kind"] == "fixture"
                   else _download(config["repo_id"], config["revision"], item["path"], item["max_bytes"]))
            actual_hash = hashlib.sha256(raw).hexdigest()
            if actual_hash != pin["sha256"]:
                raise Invalid(f"tokenizer asset SHA256 mismatch: {pin['path']}")
            if len(raw) > pin["max_bytes"]:
                raise Invalid(f"tokenizer asset exceeds max_bytes: {pin['path']}")
            target = safe_path(temporary, f"files/{pin['path']}")
            atomic_bytes(target, raw)
            if PurePosixPath(pin["path"]).name in {"config.json", "generation_config.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json"}:
                parsed = read_json(target)
                if not isinstance(parsed, dict):
                    raise Invalid(f"pinned tokenizer/config JSON must be an object: {pin['path']}")
            file_records.append({"path": pin["path"], "sha256": actual_hash, "bytes": len(raw), "max_bytes": pin["max_bytes"]})

        probes, tokenizers_version = _load_tokenizer(temporary, config)
        manifest = {"schema_version": 1, "id": run_id, "kind": config["kind"], "config_hash": digest(effective),
                    "repo_id": config["repo_id"], "revision": config["revision"], "files": file_records,
                    "special_tokens": config["special_tokens"], "protocol_tokens": config["protocol_tokens"], "probes": probes,
                    "tokenizers_version": tokenizers_version,
                    "implementation_hash": implementation_hash(Path(__file__).resolve().parents[2])}
        atomic_json(safe_path(temporary, "manifest.json"), manifest)
        # Rename the fully assembled directory as the single commit point.
        try:
            os.rename(temporary, output)
            parent_fd = os.open(store, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except FileExistsError:
            shutil.rmtree(temporary, ignore_errors=True)
        manifest, manifest_path = _verify(root, output, config, effective)
        return {"status": "PASSED", "id": run_id, "manifest": str(manifest_path), "files": len(manifest["files"])}, 0
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
