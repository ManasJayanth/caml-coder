"""Pinned public Git sources; never execute source repository code."""
import hashlib
from pathlib import Path
import os
import re
import subprocess
import tempfile

from .artifacts import Invalid, atomic_bytes, atomic_json, canonical, digest, fields, file_hash, read_json, safe_path
from .process import run


OFFICIAL = {"esy": "https://github.com/esy/esy.git", "ocaml": "https://github.com/ocaml/ocaml.org.git", "melange": "https://github.com/melange-re/melange-re.github.io.git", "reason": "https://github.com/reasonml/reasonml.github.io.git"}
MANIFEST_FIELDS = ["schema_version", "id", "kind", "config_hash", "effective_config", "files"]
RECORD_FIELDS = ["domain", "path", "artifact", "revision", "repository", "hash", "git_blob", "bytes", "license_file"]
RECEIPT_FIELDS = ["schema_version", "id", "kind", "config_hash", "manifest_sha256"]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def _acquisition_config(config):
    """The optional manifest pin is an external trust anchor, not input identity."""
    return {key: value for key, value in config.items() if key != "expected_manifest_sha256"}


def _encoded_manifest(manifest):
    return canonical(manifest) + b"\n"


def _validate_source_config(config):
    fields(config, ["schema_version", "kind", "sources"], ["expected_manifest_sha256"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["kind"] not in {"official", "fixture"}:
        raise Invalid("unsupported source config")
    expected = config.get("expected_manifest_sha256")
    if expected is not None and (not isinstance(expected, str) or not SHA256_RE.fullmatch(expected)):
        raise Invalid("expected_manifest_sha256 must be a lowercase SHA256")
    if not isinstance(config["sources"], list) or not config["sources"]:
        raise Invalid("empty source list")
    seen = set()
    for source in config["sources"]:
        fields(source, ["domain", "repository", "revision", "prefixes"])
        domain = source["domain"]
        if domain not in OFFICIAL or domain in seen:
            raise Invalid("unknown or duplicate source domain")
        seen.add(domain)
        if not isinstance(source["revision"], str) or not SHA1_RE.fullmatch(source["revision"]):
            raise Invalid("source revision must be a full immutable Git SHA")
        if not isinstance(source["repository"], str):
            raise Invalid("source repository must be a string")
        if config["kind"] == "official" and source["repository"] != OFFICIAL[domain]:
            raise Invalid("source is not the approved official repository")
        if config["kind"] == "fixture" and not Path(source["repository"]).is_absolute():
            raise Invalid("fixture repository must be an absolute local path")
        if not isinstance(source["prefixes"], list) or not source["prefixes"]:
            raise Invalid("source prefixes missing")
        for prefix in source["prefixes"]:
            if not isinstance(prefix, str) or not prefix or prefix.startswith("/") or ".." in Path(prefix).parts:
                raise Invalid("invalid source prefix")
    if config["kind"] == "official" and seen != set(OFFICIAL):
        raise Invalid("official snapshot requires all four domains")
    return _acquisition_config(config)


def _verify_receipt(receipt_path, run_id, kind, config_hash, manifest_hash):
    receipt = read_json(receipt_path)
    fields(receipt, RECEIPT_FIELDS)
    if (type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1 or
        receipt["id"] != run_id or receipt["kind"] != kind or
        receipt["config_hash"] != config_hash or receipt["manifest_sha256"] != manifest_hash):
        raise Invalid("snapshot manifest commitment is missing or inconsistent")


def fetch(root, config, run_id):
    acquisition_config = _validate_source_config(config)
    expected_manifest_sha256 = config.get("expected_manifest_sha256")
    root = Path(root).resolve()
    output = safe_path(root, f"artifacts/sources/{run_id}")
    manifest_path = safe_path(output, "manifest.json")
    receipt_path = safe_path(output, "manifest.receipt.json")
    config_hash = digest(acquisition_config)

    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise Invalid("snapshot manifest must be an object")
        manifest_hash = file_hash(manifest_path)
        if expected_manifest_sha256 is not None and manifest_hash != expected_manifest_sha256:
            raise Invalid("snapshot manifest does not match independently pinned expected hash")
        if manifest.get("config_hash") != config_hash:
            raise Invalid("snapshot run ID already bound to another config")
        if receipt_path.exists():
            _verify_receipt(receipt_path, run_id, acquisition_config["kind"], config_hash, manifest_hash)
        elif expected_manifest_sha256 is None or manifest_hash != expected_manifest_sha256:
            raise Invalid("legacy snapshot reuse requires an independently pinned expected_manifest_sha256")
        verify_snapshot(output, manifest, run_id, acquisition_config)
        return manifest, manifest_path
    if receipt_path.exists():
        raise Invalid("snapshot has a manifest commitment but no committed manifest")
    if output.exists():
        if not output.is_dir():
            raise Invalid("snapshot output path exists and is not a directory")
        if any(output.iterdir()):
            raise Invalid("uncommitted snapshot output already contains data")

    output.mkdir(parents=True, exist_ok=True)
    records = []
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=output) as temporary:
        for source in acquisition_config["sources"]:
            repository = Path(temporary) / source["domain"]

            def git(*args, timeout=120):
                result = run(["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=", *args], env=env, timeout=timeout, output_limit=8 * 1024 * 1024)
                if result["exit_code"] != 0 or result["timeout"] or result["output_truncated"]:
                    raise Invalid(f"Git source operation failed: {result['stderr'][:2000]}")
                return result["stdout"]

            git("init", "--bare", str(repository))
            git("-C", str(repository), "fetch", "--depth=1", "--no-tags", source["repository"], source["revision"], timeout=300)
            actual = git("-C", str(repository), "rev-parse", "FETCH_HEAD").strip()
            if actual != source["revision"]:
                raise Invalid("fetched commit differs from pinned revision")
            entries = git("-C", str(repository), "ls-tree", "-rz", "--long", actual).split("\0")
            count = 0
            for entry in entries:
                if not entry:
                    continue
                header, path = entry.split("\t", 1)
                mode, kind, oid, size = header.split()
                license_file = Path(path).name.lower().startswith(("license", "copying", "copyright"))
                eligible = any(path == p or path.startswith(p.rstrip("/") + "/") for p in source["prefixes"])
                if not license_file and not (eligible and Path(path).suffix in {".md", ".mdx", ".rst"}):
                    continue
                if kind != "blob" or mode not in {"100644", "100755"}:
                    raise Invalid(f"unsafe source entry: {path}")
                if int(size) > 10 * 1024 * 1024:
                    raise Invalid(f"oversized source: {path}")
                target = safe_path(output, f"files/{source['domain']}/{path}")
                result = subprocess.run(["git", "-C", str(repository), "cat-file", "blob", oid], env=env, capture_output=True, timeout=30, check=True)
                raw = result.stdout
                if len(raw) != int(size):
                    raise Invalid("blob size mismatch")
                actual_oid = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
                if actual_oid != oid:
                    raise Invalid("Git blob hash mismatch")
                atomic_bytes(target, raw)
                records.append({"domain": source["domain"], "path": path, "artifact": str(target.relative_to(output)), "revision": actual, "repository": source["repository"], "hash": file_hash(target), "git_blob": oid, "bytes": len(raw), "license_file": license_file})
                count += int(eligible and not license_file)
            if count == 0:
                raise Invalid(f"no documentation under configured prefixes for {source['domain']}")

    manifest = {"schema_version": 1, "id": run_id, "kind": acquisition_config["kind"], "config_hash": config_hash, "effective_config": acquisition_config, "files": sorted(records, key=lambda r: r["artifact"])}
    manifest_bytes = _encoded_manifest(manifest)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_manifest_sha256 is not None and manifest_hash != expected_manifest_sha256:
        raise Invalid("new snapshot does not match independently pinned expected_manifest_sha256")
    verify_snapshot(output, manifest, run_id, acquisition_config)
    # This separate commit marker binds the exact initial manifest, including
    # its complete file inventory. A marker without a manifest is fail-closed.
    atomic_json(receipt_path, {"schema_version": 1, "id": run_id, "kind": acquisition_config["kind"], "config_hash": config_hash, "manifest_sha256": manifest_hash})
    atomic_bytes(manifest_path, manifest_bytes)
    return manifest, manifest_path


def verify_snapshot(output, manifest, run_id=None, acquisition_config=None):
    """Validate manifest identity, its complete inventory, and every source byte."""
    output = Path(output).resolve()
    if not isinstance(manifest, dict):
        raise Invalid("snapshot manifest must be an object")
    fields(manifest, MANIFEST_FIELDS)
    run_id = manifest["id"] if run_id is None else run_id
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or
        not isinstance(manifest["id"], str) or manifest["id"] != run_id or manifest["kind"] not in {"official", "fixture"}):
        raise Invalid("snapshot manifest identity or schema mismatch")
    effective = manifest["effective_config"]
    if not isinstance(effective, dict) or manifest["config_hash"] != digest(effective):
        raise Invalid("snapshot config hash does not match effective config")
    if acquisition_config is not None and effective != acquisition_config:
        raise Invalid("snapshot effective config differs from requested acquisition config")
    fields(effective, ["schema_version", "kind", "sources"])
    if (type(effective["schema_version"]) is not int or effective["schema_version"] != 1 or
        effective["kind"] != manifest["kind"] or not isinstance(effective["sources"], list) or not effective["sources"]):
        raise Invalid("invalid snapshot effective config")
    sources = {}
    for source in effective["sources"]:
        fields(source, ["domain", "repository", "revision", "prefixes"])
        domain = source["domain"]
        if domain not in OFFICIAL or domain in sources or not isinstance(source["repository"], str):
            raise Invalid("invalid or duplicate source identity in manifest")
        if not isinstance(source["revision"], str) or not SHA1_RE.fullmatch(source["revision"]):
            raise Invalid("manifest source revision is not pinned")
        if not isinstance(source["prefixes"], list) or not source["prefixes"]:
            raise Invalid("manifest source prefixes are missing")
        sources[domain] = source
    if manifest["kind"] == "official" and set(sources) != set(OFFICIAL):
        raise Invalid("official manifest config must contain all four domains")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise Invalid("snapshot manifest has empty or invalid file inventory")

    seen_paths, seen_artifacts, doc_domains = set(), set(), set()
    expected_artifacts = set()
    for record in manifest["files"]:
        fields(record, RECORD_FIELDS)
        domain = record["domain"]
        if domain not in sources:
            raise Invalid("snapshot record has an unconfigured domain")
        source = sources[domain]
        source_path = record["path"]
        if not isinstance(source_path, str) or not source_path or source_path.startswith("/") or ".." in Path(source_path).parts:
            raise Invalid("unsafe source path in snapshot manifest")
        identity = (domain, source_path)
        if identity in seen_paths:
            raise Invalid("duplicate source path in snapshot manifest")
        seen_paths.add(identity)
        if record["revision"] != source["revision"] or record["repository"] != source["repository"]:
            raise Invalid(f"snapshot record source identity mismatch: {domain}/{source_path}")
        artifact = record["artifact"]
        if not isinstance(artifact, str) or artifact != f"files/{domain}/{source_path}" or artifact in seen_artifacts:
            raise Invalid("snapshot artifact path is invalid or duplicated")
        seen_artifacts.add(artifact)
        expected_artifacts.add(artifact)
        if not isinstance(record["hash"], str) or not SHA256_RE.fullmatch(record["hash"]):
            raise Invalid("invalid snapshot content SHA256")
        if not isinstance(record["git_blob"], str) or not SHA1_RE.fullmatch(record["git_blob"]):
            raise Invalid("invalid snapshot Git blob hash")
        if type(record["bytes"]) is not int or record["bytes"] < 0 or type(record["license_file"]) is not bool:
            raise Invalid("invalid snapshot size or license marker")
        expected_license_marker = Path(source_path).name.lower().startswith(("license", "copying", "copyright"))
        if record["license_file"] is not expected_license_marker:
            raise Invalid(f"snapshot license marker does not match source filename: {domain}/{source_path}")
        in_prefix = any(source_path == prefix or source_path.startswith(prefix.rstrip("/") + "/") for prefix in source["prefixes"])
        if not record["license_file"] and (not in_prefix or Path(source_path).suffix not in {".md", ".mdx", ".rst"}):
            raise Invalid(f"documentation record outside configured prefix or extension: {domain}/{source_path}")
        if not record["license_file"]:
            doc_domains.add(domain)
        path = safe_path(output, artifact)
        if not path.is_file():
            raise Invalid(f"snapshot content missing: {artifact}")
        raw = path.read_bytes()
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["hash"]:
            raise Invalid(f"snapshot content size/hash mismatch: {artifact}")
        actual_blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        if actual_blob != record["git_blob"]:
            raise Invalid(f"snapshot Git blob mismatch: {artifact}")
    if doc_domains != set(sources):
        raise Invalid("snapshot documentation inventory is missing a configured domain")

    files_root = safe_path(output, "files")
    if not files_root.is_dir():
        raise Invalid("snapshot files directory is missing")
    actual_artifacts = set()
    for path in files_root.rglob("*"):
        if path.is_symlink():
            raise Invalid(f"symlink in snapshot inventory: {path.relative_to(output)}")
        if path.is_file():
            actual_artifacts.add(path.relative_to(output).as_posix())
        elif not path.is_dir():
            raise Invalid(f"non-regular file in snapshot inventory: {path.relative_to(output)}")
    if actual_artifacts != expected_artifacts:
        raise Invalid("on-disk snapshot inventory differs from manifest")
