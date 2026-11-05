"""Public CLI subprocess coverage for lossless T08 Markdown extraction."""
import hashlib
import json
from pathlib import Path


DOMAINS = ("esy", "ocaml", "melange", "reason")
REVISIONS = {name: hashlib.sha1(("extract-fixture-" + name).encode()).hexdigest() for name in DOMAINS}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    path.write_bytes(raw)
    return path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob(raw):
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def _fixture(t, label="main", text=None):
    root = t.temporary / f"extract-project-{label}"
    snapshot_dir = root / "artifacts/sources/snapshot"
    primary = text if text is not None else (
        "---\n"
        "title: \"Unicode λ — guide\"\n"
        "description: >\n"
        "  Folded metadata remains exact across lines.\n"
        "  No YAML normalization happens here.\n"
        "snippet: |\n"
        "  ```ocaml\n"
        "  let yaml = \"--- is data\"\n"
        "  ```\n"
        "summary: |\n"
        "  Literal line one.\n"
        "  Literal line two.\n"
        "---\n"
        "\n"
        "# Guide\n"
        "\n"
        "A [reference][api] and a footnote[^n].\n"
        "Unicode separator remains content: U+2028: \u2028 follows this text.\n"
        "\n"
        "api and footnote definitions stay with document context.\n"
        "\n"
        "## Examples\n"
        "\n"
        "<!--#prelude# open Runtime\n"
        "let seed = 4\n"
        "-->\n"
        "<!-- $MDX skip -->\n"
        "```ocaml\n"
        "let x = seed + 1\n"
        "```\n"
        "\n"
        "```reasonml\n"
        "let x = seed + 1;\n"
        "```\n"
        "\n"
        "<div class=\"note text-ocaml\">\n"
        "### Kept inside the wrapper\n"
        "Unicode: λ雪.\n"
        "</div>\n"
        "\n"
        "A setext heading\n"
        "----------------\n"
        "\n"
        "- Nested command:\n"
        "\n"
        "  ```shell\n"
        "  dune build\n"
        "  ```\n"
        "\n"
        "[api]: https://example.invalid/api\n"
        "[^n]: preserved footnote definition\n"
        "\n"
        "!include include.md\n"
    )
    extra = "# Included material\n\nThis included content remains verbatim.\n"
    if label == "missing-include":
        primary = "# Root\n\n!include missing.md\n"
    elif label == "include-cycle":
        primary = "# Root\n\n!include include.md\n"
        extra = "# Child\n\n!include docs/root.md\n"
    elif label == "include-traversal":
        primary = "# Root\n\n!include ../../escape.md\n"
    elif label == "include-in-code":
        primary = "# Root\n\n```text\n!include missing.md\n```\n"
    files, sources = [], []
    docs = {"esy": {"docs/root.md": primary, "docs/include.md": extra}}
    for domain in DOMAINS:
        sources.append({"domain": domain, "repository": f"https://fixture.invalid/{domain}.git", "revision": REVISIONS[domain], "prefixes": ["docs"]})
        docs.setdefault(domain, {"docs/guide.md": f"# {domain}\n\nPinned example.\n"})
        for source_path, source_text in docs[domain].items():
            raw = source_text.encode("utf-8")
            artifact = f"files/{domain}/{source_path}"
            path = _write(snapshot_dir / artifact, raw)
            files.append({"domain": domain, "path": source_path, "artifact": artifact, "revision": REVISIONS[domain],
                          "repository": f"https://fixture.invalid/{domain}.git", "hash": _sha(path), "git_blob": _git_blob(raw),
                          "bytes": len(raw), "license_file": False})
        license_raw = b"Fixture license, indexed only as evidence.\n"
        license_path = _write(snapshot_dir / f"files/{domain}/LICENSE", license_raw)
        files.append({"domain": domain, "path": "LICENSE", "artifact": f"files/{domain}/LICENSE", "revision": REVISIONS[domain],
                      "repository": f"https://fixture.invalid/{domain}.git", "hash": _sha(license_path), "git_blob": _git_blob(license_raw),
                      "bytes": len(license_raw), "license_file": True})
    source_effective = {"schema_version": 1, "kind": "fixture", "sources": sources}
    source_manifest = {"schema_version": 1, "id": "snapshot-fixture", "kind": "fixture", "config_hash": _digest(source_effective),
                       "effective_config": source_effective, "files": sorted(files, key=lambda item: item["artifact"])}
    source_manifest_path = _write(snapshot_dir / "manifest.json", _canonical(source_manifest) + b"\n")
    domains = [{"domain": domain, "revision": REVISIONS[domain], "prefixes": ["docs"], "exclude_paths": [],
                "planned_profile_id": f"{domain}-pending", "license_evidence": []} for domain in DOMAINS]
    eligibility_config = {"schema_version": 1, "stage": "eligibility", "snapshot_manifest": str(source_manifest_path.relative_to(root)),
                          "snapshot_sha256": _sha(source_manifest_path), "domains": domains}
    candidate_rows = []
    for item in files:
        if item["license_file"]:
            continue
        candidate = {"schema_version": 1, "snapshot_id": source_manifest["id"], "snapshot_manifest_sha256": eligibility_config["snapshot_sha256"],
                     "source_domain": item["domain"], "repository": item["repository"], "revision": item["revision"],
                     "source_path": item["path"], "artifact_path": item["artifact"], "source_file_sha256": item["hash"],
                     "license_evidence": [], "candidate_status": "candidate_include", "reason_codes": [], "content_flags": [],
                     "planned_profile_id": f"{item['domain']}-pending", "version_compatibility": "UNVERIFIED",
                     "review_status": "PENDING", "generation_allowed": False,
                     "id": _digest({"snapshot_manifest_sha256": eligibility_config["snapshot_sha256"], "domain": item["domain"], "source_path": item["path"]})}
        candidate["record_sha256"] = _digest(candidate)
        candidate_rows.append(candidate)
    row_bytes = b"".join(_canonical(row) + b"\n" for row in candidate_rows)
    candidate_path = _write(root / "artifacts/prepare/eligibility-fixture/candidates.jsonl", row_bytes)
    eligibility_manifest = {"schema_version": 1, "id": "eligibility-fixture", "kind": "fixture", "status": "PASSED", "stage": "eligibility",
                            "snapshot_id": source_manifest["id"], "snapshot_manifest_sha256": eligibility_config["snapshot_sha256"],
                            "config_sha256": _digest(eligibility_config), "effective_config": eligibility_config,
                            "implementation_sha256": "0" * 64, "candidate_file": str(candidate_path.relative_to(root)),
                            "candidate_file_sha256": hashlib.sha256(row_bytes).hexdigest(), "record_count": len(candidate_rows),
                            "counts": {"candidate_include": len(candidate_rows), "candidate_exclude": 0, "quarantine": 0},
                            "license_evidence_index": [], "review_status": "PENDING", "generation_allowed": False}
    eligibility_path = _write(root / "artifacts/prepare/eligibility-fixture/manifest.json", _canonical(eligibility_manifest) + b"\n")
    extract_config = {"schema_version": 1, "stage": "extraction", "eligibility_manifest": str(eligibility_path.relative_to(root)),
                      "eligibility_manifest_sha256": _sha(eligibility_path)}
    config_path = _write(t.temporary / f"extract-config-{label}.json", _canonical(extract_config) + b"\n")
    return root, config_path, candidate_rows, primary


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def _rewrite_eligibility(root, config_path, manifest, rows):
    """Rebind a synthetic T07 fixture after an intentional integrity mutation."""
    candidate_path = root / manifest["candidate_file"]
    row_bytes = b"".join(_canonical(row) + b"\n" for row in rows)
    candidate_path.write_bytes(row_bytes)
    manifest["candidate_file_sha256"] = hashlib.sha256(row_bytes).hexdigest()
    manifest["record_count"] = len(rows)
    manifest["counts"] = {
        "candidate_include": sum(row["candidate_status"] == "candidate_include" for row in rows),
        "candidate_exclude": sum(row["candidate_status"] == "candidate_exclude" for row in rows),
        "quarantine": sum(row["candidate_status"] == "quarantine" for row in rows),
    }
    manifest["config_sha256"] = _digest(manifest["effective_config"])
    eligibility_path = root / "artifacts/prepare/eligibility-fixture/manifest.json"
    eligibility_path.write_bytes(_canonical(manifest) + b"\n")
    config = json.loads(config_path.read_text())
    config["eligibility_manifest_sha256"] = _sha(eligibility_path)
    config_path.write_bytes(_canonical(config) + b"\n")


def _reseal_candidate(row):
    row.pop("record_sha256", None)
    row["record_sha256"] = _digest(row)


def test_extraction(t):
    root, config_path, candidates, original = _fixture(t)
    result = t.cli("prepare", "--config", config_path, "--run-id", "extract", root=root)
    output = json.loads(result["stdout"])
    records = _records(Path(output["records"]))
    output_manifest = json.loads(Path(output["manifest"]).read_text())
    t.check(output_manifest["record_count"] == len(records) and output_manifest["record_file_sha256"] == _sha(Path(output["records"])),
            "extraction manifest binds the exact emitted JSONL bytes and row count")
    t.check(output["kind"] == "extraction" and output["stage"] == "extraction" and output["status"] == "PASSED",
            "T08 writes its own successful extraction artifact kind")
    t.check(output["source_candidate_count"] == len(candidates) and output["record_count"] >= len(candidates),
            "every T07 candidate is accounted for and documents split into sections")
    candidate_by_id = {row["id"]: row for row in candidates}
    pairs = [(row["candidate_id"], row["section_ordinal"]) for row in records]
    t.check({row["candidate_id"] for row in records} == set(candidate_by_id) and len(pairs) == len(set(pairs)) and
            all(sorted(row["section_ordinal"] for row in records if row["candidate_id"] == candidate_id) ==
                list(range(sum(item["candidate_id"] == candidate_id for item in records))) for candidate_id in candidate_by_id),
            "every candidate has unique, contiguous section ordinals")
    source_coverage = True
    for candidate_id, candidate in candidate_by_id.items():
        emitted = sorted((row for row in records if row["candidate_id"] == candidate_id), key=lambda row: row["section_ordinal"])
        source_path = root / "artifacts/sources/snapshot" / candidate["artifact_path"]
        source_text = source_path.read_bytes().decode("utf-8")
        source_coverage = source_coverage and "".join(row["source_text"] for row in emitted) == source_text
        source_coverage = source_coverage and all(
            row["source_domain"] == candidate["source_domain"] and row["source_path"] == candidate["source_path"] and
            row["revision"] == candidate["revision"] and row["source_file_sha256"] == candidate["source_file_sha256"]
            for row in emitted)
    t.check(source_coverage, "each candidate's ordered sections reconstruct its exact source and provenance")
    t.check(all(row["record_sha256"] == _digest({key: value for key, value in row.items() if key != "record_sha256"}) for row in records),
            "each emitted section binds its record hash")
    t.check(all(not row["generation_allowed"] and row["review_status"] == "PENDING" and row["version_compatibility"] == "UNVERIFIED" for row in records),
            "extracted sections remain unreviewed and forbidden for generation")
    esy = [row for row in records if row["source_domain"] == "esy" and row["source_path"] == "docs/root.md"]
    t.check(bool(esy), "primary Markdown fixture is emitted")
    t.check("".join(row["source_text"] for row in esy) == original, "section extraction preserves the source document byte-for-byte as UTF-8")
    t.check(all(row["syntax_metadata"].get("frontmatter_span") == {"start_line": 1, "end_line": 13} for row in esy),
            "every section carries the exact raw frontmatter line span")
    examples = next(row for row in esy if row["heading"] and row["heading"]["title"] == "Examples")
    t.check(examples["syntax_metadata"]["paired_language_examples"][0]["languages"] == ["ocaml", "reasonml"],
            "paired OCaml and ReasonML code fences are annotated as language examples")
    t.check({item["kind"] for item in examples["syntax_metadata"]["example_directives"]} == {"melange_prelude", "mdx_skip"},
            "Melange prelude and MDX skip comments remain associated with following examples")
    t.check(any("text-ocaml" in item["classes"] for item in examples["syntax_metadata"]["html_wrappers"]),
            "HTML note and language wrappers remain intact and are annotated")
    t.check(any(item["kind"] == "footnote_definition" for item in esy[0]["syntax_metadata"]["document_reference_context"]["definitions"]),
            "reference and footnote definitions are indexed at document scope")
    t.check(any(row["heading"] and row["heading"]["style"] == "setext" for row in esy), "Setext headings are recognized without altering text")
    t.check(len(esy[0]["syntax_metadata"]["fences"]) == 3,
            "fence-like text inside YAML frontmatter is retained as metadata, not parsed as code")
    t.check(sum(len(row["include_dependencies"]) for row in esy) == 1 and
            sum(row["expanded_text"].count("Included material") for row in esy) == 1,
            "relative pinned include expands once in its own section with dependency identity")
    before = Path(output["records"]).read_bytes()
    t.cli("prepare", "--config", config_path, "--run-id", "extract", root=root)
    t.check(Path(output["records"]).read_bytes() == before, "same extraction inputs retry idempotently")

    conflict_root, conflict_config, _, _ = _fixture(t, "output-conflict")
    conflict = json.loads(t.cli("prepare", "--config", conflict_config, "--run-id", "extract", root=conflict_root)["stdout"])
    conflict_path = Path(conflict["records"])
    original_records = conflict_path.read_bytes()
    conflict_path.write_bytes(original_records + b"{}\n")
    t.cli("prepare", "--config", conflict_config, "--run-id", "extract", root=conflict_root, expected=2)
    t.check(conflict_path.read_bytes() == original_records + b"{}\n", "mutated immutable output conflicts rather than being overwritten")

    code_root, code_config, _, code_text = _fixture(t, "include-in-code")
    code_output = json.loads(t.cli("prepare", "--config", code_config, "--run-id", "code", root=code_root)["stdout"])
    code_rows = _records(Path(code_output["records"]))
    code_doc = [row for row in code_rows if row["source_domain"] == "esy" and row["source_path"] == "docs/root.md"]
    t.check(code_output["status"] == "PASSED" and "!include missing.md" in "".join(row["source_text"] for row in code_doc) and
            not code_doc[0]["include_dependencies"], "include-looking text inside fenced code remains literal and does not resolve")

    for label, needle in (("missing-include", "include_resolution_failed"), ("include-cycle", "include_resolution_failed"),
                          ("include-traversal", "include_resolution_failed"), ("malformed-fence", "malformed_fence"),
                          ("malformed-frontmatter", "malformed_frontmatter"),
                          ("malformed-wrapper", "unbalanced_html_wrapper"),
                          ("control-token", "control_token_collision")):
        malformed_text = "# Broken\n\n```ocaml\nlet x = 1\n" if label == "malformed-fence" else "---\ntitle: unclosed\n" if label == "malformed-frontmatter" else None
        if label == "malformed-wrapper":
            malformed_text = "# Broken\n\n<div class=\"note\">\n## Inside but unclosed\n"
        if label == "control-token":
            malformed_text = "# Token\n\nExample output: <|im_start|>assistant\n"
        bad_root, bad_config, _, raw_text = _fixture(t, label, malformed_text)
        bad_result = t.cli("prepare", "--config", bad_config, "--run-id", "extract", root=bad_root)
        bad_output = json.loads(bad_result["stdout"])
        bad_rows = _records(Path(bad_output["records"]))
        root_rows = [row for row in bad_rows if row["source_domain"] == "esy" and row["source_path"] == "docs/root.md"]
        t.check(bad_output["status"] == "QUARANTINED" and any(needle in row["reason_codes"] for row in root_rows),
                f"{label} is explicit quarantine rather than silent loss")
        t.check("".join(row["source_text"] for row in root_rows) == raw_text, f"{label} retains original raw source")

    unsafe_root, unsafe_config, _, _ = _fixture(t, "candidate-tamper")
    candidate_path = unsafe_root / "artifacts/prepare/eligibility-fixture/candidates.jsonl"
    candidate_path.write_text(candidate_path.read_text().replace("candidate_include", "candidate_exclude", 1))
    t.cli("prepare", "--config", unsafe_config, "--run-id", "tampered", root=unsafe_root, expected=2)
    t.check(not (unsafe_root / "artifacts/extract/tampered/manifest.json").exists(), "modified T07 rows commit no extraction")

    duplicate_root, duplicate_config, _, _ = _fixture(t, "duplicate-candidate-path")
    duplicate_manifest_path = duplicate_root / "artifacts/prepare/eligibility-fixture/manifest.json"
    duplicate_manifest = json.loads(duplicate_manifest_path.read_text())
    duplicate_rows = _records(duplicate_root / duplicate_manifest["candidate_file"])
    duplicate = dict(duplicate_rows[0])
    duplicate["id"] = _digest({"duplicate_candidate_id": duplicate["id"]})
    _reseal_candidate(duplicate)
    duplicate_rows.append(duplicate)
    _rewrite_eligibility(duplicate_root, duplicate_config, duplicate_manifest, duplicate_rows)
    t.cli("prepare", "--config", duplicate_config, "--run-id", "duplicate", root=duplicate_root, expected=2)
    t.check(not (duplicate_root / "artifacts/extract/duplicate/manifest.json").exists(),
            "duplicate candidate domain/path is rejected even with valid row and file hashes")

    blob_root, blob_config, _, _ = _fixture(t, "bad-git-blob")
    blob_manifest_path = blob_root / "artifacts/prepare/eligibility-fixture/manifest.json"
    blob_manifest = json.loads(blob_manifest_path.read_text())
    blob_rows = _records(blob_root / blob_manifest["candidate_file"])
    eligibility_config = blob_manifest["effective_config"]
    source_manifest_path = blob_root / eligibility_config["snapshot_manifest"]
    source_manifest = json.loads(source_manifest_path.read_text())
    bad_blob_item = next(item for item in source_manifest["files"]
                         if item["domain"] == "esy" and item["path"] == "docs/root.md")
    bad_blob_item["git_blob"] = "0" * 40
    source_manifest_path.write_bytes(_canonical(source_manifest) + b"\n")
    source_hash = _sha(source_manifest_path)
    eligibility_config["snapshot_sha256"] = source_hash
    blob_manifest["snapshot_manifest_sha256"] = source_hash
    blob_manifest["effective_config"] = eligibility_config
    for row in blob_rows:
        row["snapshot_manifest_sha256"] = source_hash
        _reseal_candidate(row)
    _rewrite_eligibility(blob_root, blob_config, blob_manifest, blob_rows)
    t.cli("prepare", "--config", blob_config, "--run-id", "bad-blob", root=blob_root, expected=2)
    t.check(not (blob_root / "artifacts/extract/bad-blob/manifest.json").exists(),
            "wrong Git blob ID is rejected even when source bytes and SHA256 are valid")

    budget_text = "# Root\n\n" + "!include include.md\n" * 65
    budget_root, budget_config, _, _ = _fixture(t, "include-budget", budget_text)
    budget_output = json.loads(t.cli("prepare", "--config", budget_config, "--run-id", "budget", root=budget_root)["stdout"])
    budget_rows = [row for row in _records(Path(budget_output["records"]))
                   if row["source_domain"] == "esy" and row["source_path"] == "docs/root.md"]
    t.check(budget_output["status"] == "QUARANTINED" and
            any("include_resolution_failed" in row["reason_codes"] for row in budget_rows) and
            "".join(row["source_text"] for row in budget_rows) == budget_text,
            "include-count budget overflow is quarantined with raw source preserved")

    symlink_root, symlink_config, _, _ = _fixture(t, "source-symlink")
    source = symlink_root / "artifacts/sources/snapshot/files/reason/docs/guide.md"
    source.unlink()
    outside = t.temporary / "outside-extract.md"
    outside.write_text("# Outside\n")
    source.symlink_to(outside)
    t.cli("prepare", "--config", symlink_config, "--run-id", "symlink", root=symlink_root, expected=2)
    t.check(not (symlink_root / "artifacts/extract/symlink/manifest.json").exists(), "symlinked source cannot enter extraction")

    state_root, state_config, _, _ = _fixture(t, "candidate-states")
    eligibility_path = state_root / "artifacts/prepare/eligibility-fixture/manifest.json"
    state_manifest = json.loads(eligibility_path.read_text())
    state_candidates_path = state_root / state_manifest["candidate_file"]
    state_candidates = _records(state_candidates_path)
    state_candidates[0]["candidate_status"] = "candidate_exclude"
    state_candidates[0]["reason_codes"] = ["fixture_exclude"]
    state_candidates[1]["candidate_status"] = "quarantine"
    state_candidates[1]["reason_codes"] = ["fixture_review"]
    for candidate in state_candidates[:2]:
        candidate.pop("record_sha256")
        candidate["record_sha256"] = _digest(candidate)
    state_bytes = b"".join(_canonical(row) + b"\n" for row in state_candidates)
    state_candidates_path.write_bytes(state_bytes)
    state_manifest["candidate_file_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    state_manifest["counts"] = {"candidate_include": len(state_candidates) - 2, "candidate_exclude": 1, "quarantine": 1}
    eligibility_path.write_bytes(_canonical(state_manifest) + b"\n")
    state_extract_config = json.loads(state_config.read_text())
    state_extract_config["eligibility_manifest_sha256"] = _sha(eligibility_path)
    state_config.write_bytes(_canonical(state_extract_config) + b"\n")
    state_output = json.loads(t.cli("prepare", "--config", state_config, "--run-id", "states", root=state_root)["stdout"])
    state_records = _records(Path(state_output["records"]))
    t.check(state_output["counts"]["candidate_exclude"] == 1 and state_output["counts"]["candidate_quarantine"] == 1 and
            all(row["generation_allowed"] is False for row in state_records),
            "T07 exclude and quarantine rows remain represented without promotion")

    crlf_text = "# CRLF\r\n\r\nUnicode λ\u2028 stays on this physical line.\r\n## Child\r\nbody\r\n"
    crlf_root, crlf_config, _, _ = _fixture(t, "crlf-unicode", crlf_text)
    crlf_output = json.loads(t.cli("prepare", "--config", crlf_config, "--run-id", "crlf", root=crlf_root)["stdout"])
    crlf_rows = [row for row in _records(Path(crlf_output["records"])) if row["source_domain"] == "esy" and row["source_path"] == "docs/root.md"]
    t.check("".join(row["source_text"] for row in crlf_rows) == crlf_text and len(crlf_rows) == 2,
            "CRLF, Unicode line separator, and exact byte spans survive physical-line parsing")


SCENARIOS = {"extraction": test_extraction}
