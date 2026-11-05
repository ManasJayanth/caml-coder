"""Fail-closed candidate eligibility for immutable documentation snapshots.

This stage records triage only. Nothing it emits is reviewed or usable for
generation; later review and offline toolchain evidence are separate gates.
"""
import hashlib
import json
import re
from pathlib import Path

from .artifacts import Invalid, atomic_bytes, atomic_json, canonical, digest, fields, file_hash, identifier, implementation_hash, read_json, safe_path


DOMAINS = {"esy", "ocaml", "melange", "reason"}
CATEGORIES = {"BSD-2-Clause", "CC-BY-SA-4.0", "Unlicense", "MIT", "user_confirmed_copyright_free", "unknown"}
SCOPES = {"repository_content", "prose", "code_example", "embedded_notice", "third_party", "user_decision"}
SPDX_BY_CATEGORY = {"BSD-2-Clause": "BSD-2-Clause", "CC-BY-SA-4.0": "CC-BY-SA-4.0", "Unlicense": "Unlicense", "MIT": "MIT", "user_confirmed_copyright_free": None, "unknown": None}
HASH = re.compile(r"^[0-9a-f]{64}$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")

# These are review flags, not sufficient grounds to reject a whole document.
CONTENT_FLAGS = (
    ("obsolete_guidance", re.compile(r"\b(obsolete|no longer supported|deprecated|superseded)\b", re.I)),
    ("experimental_guidance", re.compile(r"\b(experimental|unstable|preview)\b", re.I)),
    ("rescript_reference", re.compile(r"\brescript\b|bucklescript", re.I)),
    ("third_party_reference", re.compile(r"third[ -]party|copyright (?:notice|holder)|all rights reserved", re.I)),
    ("embedded_license_notice", re.compile(r"\b(?:MIT|BSD|Apache|ISC) License\b|SPDX-License-Identifier", re.I)),
)


def _relative(root, value, label):
    if not isinstance(value, str) or not value:
        raise Invalid(f"{label} must be a nonempty root-relative path")
    path = safe_path(root, value)
    if not path.is_file():
        raise Invalid(f"{label} is missing or not a regular file: {value}")
    return path


def _valid_hash(value, label):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise Invalid(f"invalid SHA256 in {label}")


def _validate_config(root, config):
    fields(config, ["schema_version", "stage", "snapshot_manifest", "snapshot_sha256", "domains"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["stage"] != "eligibility":
        raise Invalid("unsupported eligibility config")
    _valid_hash(config["snapshot_sha256"], "snapshot_sha256")
    manifest_path = _relative(root, config["snapshot_manifest"], "snapshot_manifest")
    if file_hash(manifest_path) != config["snapshot_sha256"]:
        raise Invalid("snapshot manifest hash mismatch")
    if not isinstance(config["domains"], list) or len(config["domains"]) != 4:
        raise Invalid("eligibility config must represent all four domains")
    domains = {}
    for entry in config["domains"]:
        fields(entry, ["domain", "revision", "prefixes", "exclude_paths", "planned_profile_id", "license_evidence"])
        domain = entry["domain"]
        if domain not in DOMAINS or domain in domains:
            raise Invalid("unknown or duplicate eligibility domain")
        if not isinstance(entry["revision"], str) or not SHA1.fullmatch(entry["revision"]):
            raise Invalid(f"{domain}: revision must be a full immutable Git SHA")
        if not isinstance(entry["planned_profile_id"], str) or not entry["planned_profile_id"]:
            raise Invalid(f"{domain}: planned_profile_id is required")
        identifier(entry["planned_profile_id"])
        if not isinstance(entry["prefixes"], list) or not entry["prefixes"]:
            raise Invalid(f"{domain}: at least one prefix is required")
        for prefix in entry["prefixes"]:
            if not isinstance(prefix, str) or not prefix or prefix.startswith("/") or ".." in Path(prefix).parts:
                raise Invalid(f"{domain}: invalid prefix")
        if not isinstance(entry["exclude_paths"], list) or any(not isinstance(x, str) or not x or x.startswith("/") or ".." in Path(x).parts for x in entry["exclude_paths"]):
            raise Invalid(f"{domain}: invalid exclude_paths")
        if len(set(entry["exclude_paths"])) != len(entry["exclude_paths"]):
            raise Invalid(f"{domain}: duplicate exclude path")
        if not isinstance(entry["license_evidence"], list) or not entry["license_evidence"]:
            raise Invalid(f"{domain}: license_evidence is required")
        evidence_ids = set()
        for evidence in entry["license_evidence"]:
            fields(evidence, ["category", "spdx_license", "path", "sha256", "scope"])
            if evidence["category"] not in CATEGORIES or evidence["scope"] not in SCOPES:
                raise Invalid(f"{domain}: unsupported license category or scope")
            if evidence["spdx_license"] != SPDX_BY_CATEGORY[evidence["category"]]:
                raise Invalid(f"{domain}: SPDX value does not match license evidence category")
            _valid_hash(evidence["sha256"], f"{domain}.license_evidence.sha256")
            evidence_path = _relative(root, evidence["path"], f"{domain} license evidence")
            if file_hash(evidence_path) != evidence["sha256"]:
                raise Invalid(f"{domain}: license evidence hash mismatch: {evidence['path']}")
            evidence_identity = (evidence["path"], evidence["scope"], evidence["category"])
            if evidence_identity in evidence_ids:
                raise Invalid(f"{domain}: duplicate license evidence identity")
            evidence_ids.add(evidence_identity)
            if evidence["category"] == "user_confirmed_copyright_free":
                if domain != "melange" or evidence["scope"] != "user_decision" or evidence["spdx_license"] is not None:
                    raise Invalid("user copyright confirmation is only valid for Melange with null SPDX")
                authority = read_json(evidence_path)
                fields(authority, ["authority", "decision", "domain", "id", "repository", "revision", "schema_version", "scope", "snapshot_manifest_hash", "spdx_license", "statement", "upstream_license_verified"])
                manifest = read_json(manifest_path)
                source_cfg = next((s for s in manifest.get("effective_config", {}).get("sources", []) if s.get("domain") == domain), None)
                if (type(authority["schema_version"]) is not int or authority["schema_version"] != 1 or
                    not isinstance(authority["authority"], str) or not isinstance(authority["decision"], str) or
                    not isinstance(authority["id"], str) or not isinstance(authority["scope"], str) or
                    not isinstance(authority["statement"], str) or not isinstance(authority["domain"], str) or
                    not isinstance(authority["repository"], str) or not isinstance(authority["revision"], str) or
                    not HASH.fullmatch(authority["snapshot_manifest_hash"] if isinstance(authority["snapshot_manifest_hash"], str) else "") or
                    authority["domain"] != domain or authority["revision"] != entry["revision"] or
                    authority["snapshot_manifest_hash"] != config["snapshot_sha256"] or
                    authority["spdx_license"] is not None or authority["upstream_license_verified"] is not False or
                    not source_cfg or authority["repository"] != source_cfg.get("repository")):
                    raise Invalid("Melange user authority does not match pinned source and snapshot")
        domains[domain] = entry
    if set(domains) != DOMAINS:
        raise Invalid("eligibility config must represent all four domains")
    return manifest_path, domains


def _prefix_match(path, prefix):
    return path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")


def _license_evidence(root, domain, entry, has_code):
    evidence = []
    scopes = {"prose", "code_example"} if domain == "ocaml" else {"repository_content", "user_decision", "embedded_notice"}
    for item in entry["license_evidence"]:
        if item["scope"] in scopes:
            evidence.append({"category": item["category"], "spdx_license": item["spdx_license"], "path": item["path"], "sha256": item["sha256"], "scope": item["scope"]})
    if domain == "ocaml":
        required = {"prose"} | ({"code_example"} if has_code else set())
        if not required.issubset({e["scope"] for e in evidence}):
            return evidence, "license_evidence_incomplete"
    if not evidence or any(e["category"] == "unknown" for e in evidence):
        return evidence, "license_unknown"
    return evidence, None


def _content_triage(text, path):
    flags = []
    lines = text.splitlines()
    for code, pattern in CONTENT_FLAGS:
        for number, line in enumerate(lines, 1):
            if pattern.search(line):
                flags.append({"code": code, "line": number, "excerpt": line.strip()[:240]})
                break
    stripped = text.strip()
    if len(stripped) < 220 and re.search(r"\b(?:redirect(?:ed)?|this page (?:has )?moved|moved to)\b", stripped, re.I):
        return "candidate_exclude", ["redirect_stub"], flags
    if flags:
        return "quarantine", sorted({flag["code"] for flag in flags}), flags
    if len(stripped) < 220 and re.search(r"https?://", stripped, re.I):
        return "quarantine", ["short_document_review"], flags
    if not re.search(r"^#{1,6}\s+\S|```|~~~", text, re.M) and len(stripped) < 120:
        return "quarantine", ["path_unrecognized"], flags
    return "candidate_include", [], flags


def _is_excluded(path, excludes):
    return any(path == item or (item.endswith("/") and path.startswith(item)) for item in excludes)


def prepare(root, config, run_id):
    """Create immutable candidate eligibility JSONL and run manifest.

    Return `(result, exitcode)`. Input/config and snapshot errors fail before
    either committed output is written. All outputs remain generation-forbidden.
    """
    root = Path(root).resolve()
    identifier(run_id)
    manifest_path, domains = _validate_config(root, config)
    manifest = read_json(manifest_path)
    fields(manifest, ["schema_version", "id", "kind", "config_hash", "effective_config", "files"])
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["kind"] not in {"official", "fixture"}:
        raise Invalid("unsupported or incomplete snapshot manifest")
    if not isinstance(manifest["files"], list):
        raise Invalid("snapshot manifest files must be a list")
    if not isinstance(manifest["effective_config"], dict) or manifest.get("config_hash") != digest(manifest["effective_config"]):
        raise Invalid("snapshot config hash does not match effective config")
    source_config = manifest["effective_config"]
    fields(source_config, ["schema_version", "kind", "sources"])
    if type(source_config["schema_version"]) is not int or source_config["schema_version"] != 1 or source_config["kind"] != manifest["kind"] or not isinstance(source_config["sources"], list):
        raise Invalid("invalid effective snapshot config")
    sources_by_domain = {}
    for source in source_config["sources"]:
        fields(source, ["domain", "repository", "revision", "prefixes"])
        if source["domain"] not in DOMAINS or source["domain"] in sources_by_domain:
            raise Invalid("unknown or duplicate source domain in snapshot config")
        if not isinstance(source["repository"], str) or not isinstance(source["revision"], str) or not SHA1.fullmatch(source["revision"]):
            raise Invalid("invalid repository or revision in snapshot config")
        sources_by_domain[source["domain"]] = source
    if set(sources_by_domain) != DOMAINS:
        raise Invalid("snapshot config must represent all four domains")
    for domain, entry in domains.items():
        source = sources_by_domain[domain]
        if source["revision"] != entry["revision"] or source["prefixes"] != entry["prefixes"]:
            raise Invalid(f"eligibility config revision/prefix mismatch for {domain}")
    if manifest["kind"] == "official" and set(domains) != DOMAINS:
        raise Invalid("official eligibility snapshot requires all four domains")
    snapshot_dir = manifest_path.parent
    seen = set()
    seen_artifacts = set()
    content_domains_seen = set()
    prepared = []
    license_index = []
    for item in manifest["files"]:
        fields(item, ["domain", "path", "artifact", "revision", "repository", "hash", "git_blob", "bytes", "license_file"])
        domain, source_path = item["domain"], item["path"]
        if domain not in domains:
            raise Invalid("manifest contains missing or unknown domain")
        if not isinstance(source_path, str) or source_path.startswith("/") or ".." in Path(source_path).parts:
            raise Invalid("unsafe manifest source path")
        pair = (domain, source_path)
        if pair in seen:
            raise Invalid("duplicate manifest domain/path")
        seen.add(pair)
        if item["artifact"] in seen_artifacts:
            raise Invalid("duplicate manifest artifact path")
        seen_artifacts.add(item["artifact"])
        entry = domains[domain]
        source = sources_by_domain[domain]
        if item["revision"] != entry["revision"]:
            raise Invalid(f"snapshot revision mismatch for {domain}")
        if item["repository"] != source["repository"]:
            raise Invalid(f"snapshot repository mismatch for {domain}")
        if not isinstance(item["hash"], str) or not HASH.fullmatch(item["hash"]):
            raise Invalid("manifest file has invalid SHA256")
        if not isinstance(item["artifact"], str) or item["artifact"].startswith("/") or ".." in Path(item["artifact"]).parts:
            raise Invalid("unsafe manifest artifact path")
        if item["artifact"] != f"files/{domain}/{source_path}":
            raise Invalid("manifest artifact path does not match source domain/path")
        if type(item["bytes"]) is not int or item["bytes"] < 0:
            raise Invalid("invalid manifest byte count")
        source_file = safe_path(snapshot_dir, item["artifact"])
        if not source_file.is_file() or source_file.stat().st_size != item["bytes"] or file_hash(source_file) != item["hash"]:
            raise Invalid(f"modified or missing snapshot file: {item['artifact']}")
        if type(item["license_file"]) is not bool:
            raise Invalid("invalid license_file marker")
        if item["license_file"]:
            license_index.append({"domain": domain, "source_path": source_path, "source_file_sha256": item["hash"], "artifact": item["artifact"]})
            continue
        content_domains_seen.add(domain)
        if not any(_prefix_match(source_path, prefix) for prefix in entry["prefixes"]):
            raise Invalid(f"manifest content outside configured domain prefix: {domain}/{source_path}")
        raw = source_file.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Invalid(f"source is not UTF-8: {domain}/{source_path}") from exc
        has_code = bool(re.search(r"^\s*(```|~~~)", text, re.M))
        evidence, license_reason = _license_evidence(root, domain, entry, has_code)
        if _is_excluded(source_path, entry["exclude_paths"]):
            status, reasons, flags = "candidate_exclude", ["explicit_exclude_path"], []
        else:
            status, reasons, flags = _content_triage(text, source_path)
            if license_reason:
                status, reasons = "quarantine", sorted(set(reasons + [license_reason]))
        record = {
            "schema_version": 1,
            "snapshot_id": manifest["id"],
            "snapshot_manifest_sha256": config["snapshot_sha256"],
            "source_domain": domain,
            "repository": item["repository"],
            "revision": item["revision"],
            "source_path": source_path,
            "artifact_path": item["artifact"],
            "source_file_sha256": item["hash"],
            "license_evidence": evidence,
            "candidate_status": status,
            "reason_codes": reasons,
            "content_flags": flags,
            "planned_profile_id": entry["planned_profile_id"],
            "version_compatibility": "UNVERIFIED",
            "review_status": "PENDING",
            "generation_allowed": False,
        }
        record["id"] = digest({"snapshot_manifest_sha256": config["snapshot_sha256"], "domain": domain, "source_path": source_path})
        record["record_sha256"] = digest(record)
        prepared.append(record)
    if content_domains_seen != DOMAINS:
        raise Invalid("snapshot is missing one or more required domains")
    if not prepared:
        raise Invalid("snapshot has no content files")
    prepared.sort(key=lambda row: (row["source_domain"], row["source_path"]))
    rows = b"".join(canonical(row) + b"\n" for row in prepared)
    outdir = safe_path(root, f"artifacts/prepare/{run_id}")
    candidate_path = outdir / "candidates.jsonl"
    output_manifest = outdir / "manifest.json"
    counts = {state: sum(row["candidate_status"] == state for row in prepared) for state in ("candidate_include", "candidate_exclude", "quarantine")}
    result_manifest = {
        "schema_version": 1,
        "id": run_id,
        "kind": manifest["kind"],
        "status": "PASSED",
        "stage": "eligibility",
        "snapshot_id": manifest["id"],
        "snapshot_manifest_sha256": config["snapshot_sha256"],
        "config_sha256": digest(config),
        "effective_config": config,
        "implementation_sha256": implementation_hash(root),
        "candidate_file": f"artifacts/prepare/{run_id}/candidates.jsonl",
        "candidate_file_sha256": hashlib.sha256(rows).hexdigest(),
        "record_count": len(prepared),
        "counts": counts,
        "license_evidence_index": license_index,
        "review_status": "PENDING",
        "generation_allowed": False,
    }
    atomic_bytes(candidate_path, rows)
    atomic_json(output_manifest, result_manifest)
    return {**result_manifest, "manifest": str(output_manifest), "candidates": str(candidate_path)}, 0
