"""Subprocess E2E for candidate eligibility; no internal imports or mocks."""
import hashlib
import json
from pathlib import Path


DOMAINS = ("esy", "ocaml", "melange", "reason")
REVISIONS = {domain: hashlib.sha1(("fixture-" + domain).encode()).hexdigest() for domain in DOMAINS}


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(raw, str):
        raw = raw.encode()
    path.write_bytes(raw)
    return path


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _git_blob(path):
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def _fixture(t, tag="main"):
    root = t.temporary / f"eligibility-project-{tag}"
    source_root = root / "artifacts/sources/snapshot"
    files, source_config = [], []
    texts = {
        "esy": {"docs/guide.md": "# Setup\n\nInstall the pinned package and run the example.\n",
                "docs/community.md": "# Community\n\nContact the project community.\n"},
        "ocaml": {"data/tutorials/guide.md": "# Values\n\n```ocaml\nlet x = 1\n```\n"},
        "melange": {"docs/guide.md": "# JavaScript interop\n\nBind a JavaScript value with an external declaration.\n",
                    "docs/comparison.md": "# Migration note\n\nThis comparison mentions ReScript historically.\n"},
        "reason": {"docs/guide.md": "# Pattern matching\n\nMatch a value with exhaustive cases.\n",
                   "docs/tuple.md": "Redirect: This page moved to https://example.invalid/tuple-guide\n",
                   "docs/short.md": "Use a tuple here, as described by [the guide](https://example.invalid/tuple).\n"},
    }
    for domain in DOMAINS:
        source_config.append({"domain": domain, "repository": f"https://fixture.invalid/{domain}", "revision": REVISIONS[domain],
                              "prefixes": ["data/tutorials"] if domain == "ocaml" else ["docs"]})
        for rel, text in texts[domain].items():
            path = _write(source_root / "files" / domain / rel, text.encode())
            files.append({"domain": domain, "path": rel, "artifact": str(path.relative_to(source_root)),
                          "revision": REVISIONS[domain], "repository": f"https://fixture.invalid/{domain}",
                          "hash": _hash(path), "git_blob": _git_blob(path), "bytes": path.stat().st_size,
                          "license_file": False})
        # A license artifact is evidence-indexed but never emitted as content.
        license_path = _write(source_root / "files" / domain / "LICENSE", f"Synthetic {domain} license evidence\n".encode())
        files.append({"domain": domain, "path": "LICENSE", "artifact": str(license_path.relative_to(source_root)),
                      "revision": REVISIONS[domain], "repository": f"https://fixture.invalid/{domain}",
                      "hash": _hash(license_path), "git_blob": _git_blob(license_path), "bytes": license_path.stat().st_size,
                      "license_file": True})
    effective_config = {"schema_version": 1, "kind": "fixture", "sources": source_config}
    snapshot = {"schema_version": 1, "id": "snapshot", "kind": "fixture", "config_hash": hashlib.sha256(_canonical(effective_config)).hexdigest(),
                "effective_config": effective_config,
                "files": sorted(files, key=lambda row: row["artifact"])}
    manifest_path = _write(source_root / "manifest.json", _canonical(snapshot) + b"\n")
    manifest_hash = _hash(manifest_path)

    evidence = {}
    for domain in DOMAINS:
        if domain == "melange":
            decision = {"authority": "user statement in this conversation", "decision": "Proceed with the pinned documentation in the requested local pipeline based on user confirmation.",
                        "domain": "melange", "id": "melange-user-confirmation-fixture", "repository": f"https://fixture.invalid/{domain}",
                        "revision": REVISIONS[domain], "schema_version": 1, "scope": "Source permission decision only",
                        "snapshot_manifest_hash": manifest_hash, "spdx_license": None, "statement": "It's copyright free - you can go ahead and fetch it",
                        "upstream_license_verified": False}
            path = _write(root / "artifacts/decisions/melange.json", _canonical(decision) + b"\n")
            evidence[domain] = [{"category": "user_confirmed_copyright_free", "spdx_license": None,
                                 "path": str(path.relative_to(root)), "sha256": _hash(path), "scope": "user_decision"}]
        elif domain == "ocaml":
            license_path = _write(root / "evidence/ocaml-LICENSE", b"Content prose: CC BY-SA 4.0\nCode examples: UNLICENSE\n")
            evidence[domain] = [
                {"category": "CC-BY-SA-4.0", "spdx_license": "CC-BY-SA-4.0", "path": str(license_path.relative_to(root)), "sha256": _hash(license_path), "scope": "prose"},
                {"category": "Unlicense", "spdx_license": "Unlicense", "path": str(license_path.relative_to(root)), "sha256": _hash(license_path), "scope": "code_example"},
            ]
        else:
            category = "BSD-2-Clause" if domain == "esy" else "MIT"
            path = _write(root / "evidence" / f"{domain}.txt", f"Repository content license: {category}\n".encode())
            evidence[domain] = [{"category": category, "spdx_license": category, "path": str(path.relative_to(root)),
                                 "sha256": _hash(path), "scope": "repository_content"}]
    domains = []
    prefixes = {"esy": ["docs"], "ocaml": ["data/tutorials"], "melange": ["docs"], "reason": ["docs"]}
    for domain in DOMAINS:
        domains.append({"domain": domain, "revision": REVISIONS[domain], "prefixes": prefixes[domain],
                        "exclude_paths": ["docs/community.md"] if domain == "esy" else [],
                        "planned_profile_id": f"{domain}-profile-pending", "license_evidence": evidence[domain]})
    config = {"schema_version": 1, "stage": "eligibility", "snapshot_manifest": str(manifest_path.relative_to(root)),
              "snapshot_sha256": manifest_hash, "domains": domains}
    config_path = _write(t.temporary / f"eligibility-config-{tag}.json", json.dumps(config))
    return root, source_root, config_path, config, manifest_path, files


def _records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_eligibility(t):
    root, source_root, config_path, config, manifest_path, files = _fixture(t)
    result = t.cli("prepare", "--config", config_path, "--run-id", "eligibility", root=root)
    output = json.loads(result["stdout"])
    candidate_path = Path(output["candidates"])
    manifest_out = Path(output["manifest"])
    records = _records(candidate_path)
    t.check(output["status"] == "PASSED" and output["kind"] == "fixture", "complete fixture snapshot produces a passing fixture-kind triage")
    t.check(len(records) == 8, "all manifest content files appear exactly once; license files do not become candidates")
    t.check(all(not row["generation_allowed"] and row["review_status"] == "PENDING" and row["version_compatibility"] == "UNVERIFIED" for row in records),
            "candidate rows remain pending, version-unverified and forbidden for generation")
    t.check(all(len(row["record_sha256"]) == 64 and row["source_file_sha256"] for row in records), "candidate rows bind immutable source and row hashes")
    by_path = {row["source_domain"] + "/" + row["source_path"]: row for row in records}
    t.check({e["scope"] for e in by_path["ocaml/data/tutorials/guide.md"]["license_evidence"]} == {"prose", "code_example"},
            "OCaml code and prose keep distinct license evidence")
    melange = by_path["melange/docs/guide.md"]["license_evidence"][0]
    t.check(melange["category"] == "user_confirmed_copyright_free" and melange["spdx_license"] is None,
            "Melange user permission remains a separate category without invented SPDX")
    t.check(by_path["esy/docs/community.md"]["candidate_status"] == "candidate_exclude", "explicit path exclusion is recorded")
    t.check(by_path["reason/docs/tuple.md"]["reason_codes"] == ["redirect_stub"], "explicitly marked redirect documentation is excluded")
    t.check(by_path["reason/docs/short.md"]["candidate_status"] == "quarantine" and
            by_path["reason/docs/short.md"]["reason_codes"] == ["short_document_review"],
            "substantive short documentation with a URL is quarantined for review")
    t.check(by_path["melange/docs/comparison.md"]["candidate_status"] == "quarantine" and
            by_path["melange/docs/comparison.md"]["content_flags"][0]["code"] == "rescript_reference",
            "ReScript comparison is retained as an excerpted review flag")
    t.check(json.loads(manifest_out.read_text())["license_evidence_index"] and
            all("LICENSE" in row["source_path"] for row in json.loads(manifest_out.read_text())["license_evidence_index"]),
            "license files are indexed separately from candidate records")
    candidate_bytes = candidate_path.read_bytes()
    t.cli("prepare", "--config", config_path, "--run-id", "eligibility", root=root)
    t.check(candidate_path.read_bytes() == candidate_bytes, "same input and config retry is byte-identical")

    # Unknown config keys are rejected before a run artifact is committed.
    bad = json.loads(config_path.read_text())
    bad["surprise"] = True
    bad_path = t.temporary / "eligibility-unknown.json"
    bad_path.write_text(json.dumps(bad))
    t.cli("prepare", "--config", bad_path, "--run-id", "unknown-config", root=root, expected=2)
    t.check(not (root / "artifacts/prepare/unknown-config/manifest.json").exists(), "unknown config fields commit no result")

    # A changed user receipt is hash-bound, then rejected if its decision cites
    # a different source revision even when the evidence hash is updated.
    receipt_root, _, receipt_config_path, _, _, _ = _fixture(t, "receipt")
    receipt = receipt_root / "artifacts/decisions/melange.json"
    decision = json.loads(receipt.read_text())
    decision["revision"] = "f" * 40
    _write(receipt, _canonical(decision) + b"\n")
    receipt_config = json.loads(receipt_config_path.read_text())
    next(e for e in next(d for d in receipt_config["domains"] if d["domain"] == "melange")["license_evidence"])["sha256"] = _hash(receipt)
    receipt_path = t.temporary / "eligibility-receipt-mismatch.json"
    receipt_path.write_text(json.dumps(receipt_config))
    t.cli("prepare", "--config", receipt_path, "--run-id", "receipt-mismatch", root=receipt_root, expected=2)
    t.check(not (receipt_root / "artifacts/prepare/receipt-mismatch/manifest.json").exists(), "user permission receipt with a mismatched revision commits no result")

    # Category and SPDX evidence must agree. Unknown is a valid category but
    # always yields quarantine, never inclusion.
    spdx_config = json.loads(config_path.read_text())
    esy_license = next(d for d in spdx_config["domains"] if d["domain"] == "esy")["license_evidence"][0]
    esy_license["spdx_license"] = "MIT"
    spdx_path = t.temporary / "eligibility-spdx-mismatch.json"
    spdx_path.write_text(json.dumps(spdx_config))
    t.cli("prepare", "--config", spdx_path, "--run-id", "spdx-mismatch", root=root, expected=2)
    t.check(not (root / "artifacts/prepare/spdx-mismatch/manifest.json").exists(), "mismatched category and SPDX commit no result")
    unknown_config = json.loads(config_path.read_text())
    esy_license = next(d for d in unknown_config["domains"] if d["domain"] == "esy")["license_evidence"][0]
    esy_license.update(category="unknown", spdx_license=None)
    unknown_license_path = t.temporary / "eligibility-license-unknown.json"
    unknown_license_path.write_text(json.dumps(unknown_config))
    unknown_result = t.cli("prepare", "--config", unknown_license_path, "--run-id", "unknown-license", root=root)
    unknown_records = _records(Path(json.loads(unknown_result["stdout"])["candidates"]))
    esy_guide = next(row for row in unknown_records if row["source_domain"] == "esy" and row["source_path"] == "docs/guide.md")
    t.check(esy_guide["candidate_status"] == "quarantine" and "license_unknown" in esy_guide["reason_codes"],
            "unknown license evidence is quarantined")

    # A changed source byte invalidates the manifest and is caught before output.
    source = source_root / files[0]["artifact"]
    source.write_text("tampered\n")
    t.cli("prepare", "--config", config_path, "--run-id", "tampered", root=root, expected=2)
    t.check(not (root / "artifacts/prepare/tampered/manifest.json").exists(), "modified snapshot file commits no result")

    missing = json.loads(config_path.read_text())
    missing["domains"] = missing["domains"][:-1]
    missing_path = t.temporary / "eligibility-missing-domain.json"
    missing_path.write_text(json.dumps(missing))
    t.cli("prepare", "--config", missing_path, "--run-id", "missing-domain", root=root, expected=2)
    t.check(not (root / "artifacts/prepare/missing-domain/manifest.json").exists(), "missing domain blocks before commit")

    # Unsafe manifest provenance cases are re-bound so the tested failure is
    # the path/duplicate validation rather than a stale manifest checksum.
    traversal_root, _, traversal_config_path, traversal_config, traversal_manifest, _ = _fixture(t, "traversal")
    traversal_value = json.loads(traversal_manifest.read_text())
    traversal_value["files"][0]["artifact"] = "../escape.md"
    _write(traversal_manifest, _canonical(traversal_value) + b"\n")
    traversal_config["snapshot_sha256"] = _hash(traversal_manifest)
    mel_decision_path = traversal_root / "artifacts/decisions/melange.json"
    mel_decision = json.loads(mel_decision_path.read_text())
    mel_decision["snapshot_manifest_hash"] = traversal_config["snapshot_sha256"]
    _write(mel_decision_path, _canonical(mel_decision) + b"\n")
    mel_evidence = next(d for d in traversal_config["domains"] if d["domain"] == "melange")["license_evidence"][0]
    mel_evidence["sha256"] = _hash(mel_decision_path)
    traversal_config_path.write_text(json.dumps(traversal_config))
    t.cli("prepare", "--config", traversal_config_path, "--run-id", "source-traversal", root=traversal_root, expected=2)
    t.check(not (traversal_root / "artifacts/prepare/source-traversal/manifest.json").exists(), "source traversal is rejected before commit")

    symlink_root, symlink_sources, symlink_config, _, _, symlink_files = _fixture(t, "symlink")
    symlink_file = symlink_sources / symlink_files[0]["artifact"]
    symlink_file.unlink()
    target = t.temporary / "external.md"
    target.write_text("# External\n\nThis is outside the immutable snapshot.\n")
    symlink_file.symlink_to(target)
    t.cli("prepare", "--config", symlink_config, "--run-id", "source-symlink", root=symlink_root, expected=2)
    t.check(not (symlink_root / "artifacts/prepare/source-symlink/manifest.json").exists(), "symlinked source is rejected before commit")

    duplicate_root, _, duplicate_config_path, duplicate_config, duplicate_manifest, _ = _fixture(t, "duplicate")
    duplicate_value = json.loads(duplicate_manifest.read_text())
    duplicate_value["files"].append(dict(duplicate_value["files"][0]))
    _write(duplicate_manifest, _canonical(duplicate_value) + b"\n")
    duplicate_config["snapshot_sha256"] = _hash(duplicate_manifest)
    duplicate_decision_path = duplicate_root / "artifacts/decisions/melange.json"
    duplicate_decision = json.loads(duplicate_decision_path.read_text())
    duplicate_decision["snapshot_manifest_hash"] = duplicate_config["snapshot_sha256"]
    _write(duplicate_decision_path, _canonical(duplicate_decision) + b"\n")
    duplicate_evidence = next(d for d in duplicate_config["domains"] if d["domain"] == "melange")["license_evidence"][0]
    duplicate_evidence["sha256"] = _hash(duplicate_decision_path)
    duplicate_config_path.write_text(json.dumps(duplicate_config))
    t.cli("prepare", "--config", duplicate_config_path, "--run-id", "duplicate-path", root=duplicate_root, expected=2)
    t.check(not (duplicate_root / "artifacts/prepare/duplicate-path/manifest.json").exists(), "duplicate source path is rejected before commit")


SCENARIOS = {"eligibility": test_eligibility}
