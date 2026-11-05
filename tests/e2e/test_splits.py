"""Public subprocess E2E for deterministic leakage grouping and split assignment."""
import hashlib
import json
from pathlib import Path


DOMAINS = ("esy", "ocaml", "melange", "reason")
REVISIONS = {domain: hashlib.sha1(("splits-fixture-" + domain).encode()).hexdigest() for domain in DOMAINS}


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


def _cid(candidates, domain, index):
    path = f"docs/{domain}-{index:02}.md"
    return next(row["id"] for row in candidates if row["source_domain"] == domain and row["source_path"] == path)


def _unique_text(domain, index):
    tokens = [f"qx{domain}{index}v{n}zz" for n in range(40)]
    return f"# {domain} reference {index}\n\n" + " ".join(tokens) + ".\n\n## Details\n\n" + " ".join(tokens) + "\n"


def _document_texts(count):
    docs = {domain: {} for domain in DOMAINS}
    if count == 1:
        for domain in DOMAINS:
            docs[domain][0] = _unique_text(domain, 0)
        return docs
    for domain in DOMAINS:
        for index in range(count):
            docs[domain][index] = _unique_text(domain, index)
    # A robust near duplicate: one differing token in a long repeated text.
    base = [f"commonqx{i}z" for i in range(120)]
    docs["reason"][3] = "# Near documentation\n\n" + " ".join(base) + "\n"
    near = list(base)
    near[22] = "changedtokenqz"
    docs["reason"][4] = "# Near documentation\n\n" + " ".join(near) + "\n"
    # Exact normalized prose after heading markers are removed.
    docs["ocaml"][5] = "# Exact duplicate\n\nThe same pinned explanation uses precise words and examples.\n"
    docs["ocaml"][6] = "## Exact duplicate\n\nThe same pinned explanation uses precise words and examples.\n"
    docs["reason"][8] += "\nThis page contains deprecated guidance and is retained for review only.\n"
    # One transitive include chain: esy 0 -> esy 1 -> esy 2.
    docs["esy"][0] += "\n!include esy-01.md\n"
    docs["esy"][1] += "\n!include esy-02.md\n"
    return docs


def _fixture(t, label="main", *, count=12, reverse=False, text_override=None):
    root = t.temporary / f"split-project-{label}"
    docs = _document_texts(count)
    if text_override is not None:
        docs["esy"][0] = text_override
    snapshot_dir = root / "artifacts/sources/snapshot"
    files, sources = [], []
    for domain in DOMAINS:
        repository = f"https://fixture.invalid/{domain}.git"
        sources.append({"domain": domain, "repository": repository, "revision": REVISIONS[domain], "prefixes": ["docs"]})
        for index in sorted(docs[domain]):
            path = f"docs/{domain}-{index:02}.md"
            content = docs[domain][index]
            raw = content.encode("utf-8")
            artifact = f"files/{domain}/{path}"
            source_file = _write(snapshot_dir / artifact, raw)
            files.append({"domain": domain, "path": path, "artifact": artifact, "revision": REVISIONS[domain], "repository": repository,
                          "hash": _sha(source_file), "git_blob": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest(),
                          "bytes": len(raw), "license_file": False})
    source_effective = {"schema_version": 1, "kind": "fixture", "sources": sources}
    source_manifest = {"schema_version": 1, "id": "snapshot-fixture", "kind": "fixture", "config_hash": _digest(source_effective),
                       "effective_config": source_effective, "files": sorted(files, key=lambda item: item["artifact"])}
    source_manifest_path = _write(snapshot_dir / "manifest.json", _canonical(source_manifest) + b"\n")
    domain_config = []
    for domain in DOMAINS:
        evidence_file = _write(root / "evidence" / f"{domain}.txt", f"Synthetic {domain} content category for fixture use.\n")
        evidence_scope = "prose" if domain == "ocaml" else "repository_content"
        domain_config.append({"domain": domain, "revision": REVISIONS[domain], "prefixes": ["docs"],
                              "exclude_paths": ["docs/esy-10.md"] if domain == "esy" and count > 10 else [],
                              "planned_profile_id": f"{domain}-fixture", "license_evidence": [{"category": "MIT", "spdx_license": "MIT",
                                                 "path": str(evidence_file.relative_to(root)), "sha256": _sha(evidence_file), "scope": evidence_scope}]})
    eligibility_config = {"schema_version": 1, "stage": "eligibility", "snapshot_manifest": str(source_manifest_path.relative_to(root)),
                         "snapshot_sha256": _sha(source_manifest_path), "domains": domain_config}
    eligibility_config_path = _write(root / "config/eligibility.json", _canonical(eligibility_config) + b"\n")
    t07_result = json.loads(t.cli("prepare", "--config", eligibility_config_path, "--run-id", "candidates", root=root)["stdout"])
    eligibility_path = Path(t07_result["manifest"])
    eligibility = json.loads(eligibility_path.read_text())
    candidates_path = root / eligibility["candidate_file"]
    candidates = [json.loads(line) for line in candidates_path.read_text(encoding="utf-8").splitlines()]
    candidate_by_path = {(row["source_domain"], row["source_path"]): row for row in candidates}

    rows = []
    for (domain, path), candidate in sorted(candidate_by_path.items()):
        content = (snapshot_dir / candidate["artifact_path"]).read_text(encoding="utf-8")
        if count > 2 and domain == "esy" and path == "docs/esy-00.md":
            one, two = candidate_by_path[("esy", "docs/esy-01.md")], candidate_by_path[("esy", "docs/esy-02.md")]
            dependencies = [{"candidate_id": one["id"], "source_path": one["source_path"], "source_file_sha256": one["source_file_sha256"],
                             "included_from_path": path, "include_line": len(content.split("\n")) - 1},
                            {"candidate_id": two["id"], "source_path": two["source_path"], "source_file_sha256": two["source_file_sha256"],
                             "included_from_path": one["source_path"], "include_line": len((snapshot_dir / one["artifact_path"]).read_text().split("\n")) - 1}]
        elif count > 2 and domain == "esy" and path == "docs/esy-01.md":
            two = candidate_by_path[("esy", "docs/esy-02.md")]
            dependencies = [{"candidate_id": two["id"], "source_path": two["source_path"], "source_file_sha256": two["source_file_sha256"],
                             "included_from_path": path, "include_line": len(content.split("\n")) - 1}]
        else:
            dependencies = []
        pieces = content.split("## Details\n")
        section_texts = [pieces[0], "## Details\n" + pieces[1]] if len(pieces) == 2 else [content]
        byte_start, line_start = 0, 1
        for ordinal, section_text in enumerate(section_texts):
            raw = section_text.encode("utf-8")
            line_count = section_text.count("\n")
            state = {"candidate_include": "extracted", "candidate_exclude": "candidate_exclude", "quarantine": "candidate_quarantine"}[candidate["candidate_status"]]
            row = {"schema_version": 1, "id": _digest({"candidate_id": candidate["id"], "section": ordinal}), "kind": "extraction",
                   "candidate_id": candidate["id"], "candidate_status": candidate["candidate_status"], "source_domain": domain,
                   "repository": candidate["repository"], "revision": candidate["revision"], "source_path": path,
                   "artifact_path": candidate["artifact_path"], "source_file_sha256": candidate["source_file_sha256"],
                   "section_ordinal": ordinal, "heading": None, "heading_ancestry": [],
                   "source_span": {"start_line": line_start, "end_line": line_start + max(line_count - 1, 0),
                                   "start_byte": byte_start, "end_byte": byte_start + len(raw)},
                   "source_text": section_text, "expanded_text": section_text,
                   "include_dependencies": dependencies if ordinal == 0 else [], "syntax_metadata": {"frontmatter_span": None},
                   "extraction_status": state, "reason_codes": candidate["reason_codes"], "version_compatibility": "UNVERIFIED",
                   "review_status": "PENDING", "generation_allowed": False}
            row["record_sha256"] = _digest(row)
            rows.append(row)
            byte_start += len(raw)
            line_start += line_count
    if reverse:
        rows.reverse()
    record_bytes = b"".join(_canonical(row) + b"\n" for row in rows)
    record_path = _write(root / "artifacts/extract/input/records.jsonl", record_bytes)
    extraction_effective = {"schema_version": 1, "stage": "extraction", "eligibility_manifest": str(eligibility_path.relative_to(root)),
                            "eligibility_manifest_sha256": _sha(eligibility_path)}
    extraction = {"schema_version": 1, "id": "extract-fixture", "kind": "extraction", "status": "QUARANTINED" if any(row["candidate_status"] == "quarantine" for row in candidates) else "PASSED",
                  "stage": "extraction", "eligibility_manifest": extraction_effective["eligibility_manifest"],
                  "eligibility_manifest_sha256": extraction_effective["eligibility_manifest_sha256"],
                  "snapshot_id": eligibility["snapshot_id"], "snapshot_manifest_sha256": eligibility["snapshot_manifest_sha256"],
                  "config_sha256": _digest(extraction_effective), "effective_config": extraction_effective, "implementation_sha256": "3" * 64,
                  "record_file": str(record_path.relative_to(root)), "record_file_sha256": hashlib.sha256(record_bytes).hexdigest(),
                  "record_count": len(rows), "source_candidate_count": len(candidates), "counts": {},
                  "review_status": "PENDING", "generation_allowed": False}
    extraction_path = _write(root / "artifacts/extract/input/manifest.json", _canonical(extraction) + b"\n")
    annotation_links = [
        {"id": "translation-fixture-01", "kind": "translation", "source_ids": [candidate_by_path[("esy", "docs/esy-00.md")]["id"], candidate_by_path[("ocaml", "docs/ocaml-00.md")]["id"]]},
        {"id": "task-family-fixture-01", "kind": "task_family", "source_ids": [candidate_by_path[("melange", "docs/melange-08.md")]["id"], candidate_by_path[("reason", "docs/reason-08.md")]["id"]]},
    ] if count > 8 else [{"id": "translation-fixture-01", "kind": "translation", "source_ids": [candidate_by_path[("esy", "docs/esy-00.md")]["id"], candidate_by_path[("ocaml", "docs/ocaml-00.md")]["id"]]}]
    if count > 10:
        annotation_links.append({"id": "excluded-variant-fixture", "kind": "variant", "source_ids": [candidate_by_path[("esy", "docs/esy-10.md")]["id"], candidate_by_path[("ocaml", "docs/ocaml-10.md")]["id"]]})
    annotation_value = {"schema_version": 1, "links": annotation_links}
    annotation_path = _write(root / "config/split-links.json", _canonical(annotation_value) + b"\n")
    config = {"schema_version": 1, "stage": "splits", "extraction_manifest": str(extraction_path.relative_to(root)),
              "extraction_manifest_sha256": _sha(extraction_path), "annotations_file": str(annotation_path.relative_to(root)),
              "annotations_sha256": _sha(annotation_path)}
    config_path = _write(t.temporary / f"split-config-{label}.json", _canonical(config) + b"\n")
    return root, config_path, candidates, rows


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def test_splits(t):
    root, config, candidates, input_rows = _fixture(t)
    result = json.loads(t.cli("prepare", "--config", config, "--run-id", "splits", root=root)["stdout"])
    groups_path = Path(result["groups"])
    groups = _records(groups_path)
    manifest = json.loads(Path(result["manifest"]).read_text())
    t.check(result["status"] == "PASSED" and result["kind"] == "splits" and not result["generation_allowed"],
            "split producer emits its own pending, generation-forbidden artifact")
    t.check(manifest["group_file_sha256"] == _sha(groups_path) and manifest["group_count"] == len(groups),
            "split manifest binds exact group JSONL bytes and count")
    members = [member for group in groups for member in group["members"]]
    t.check({member["candidate_id"] for member in members} == {candidate["id"] for candidate in candidates} and
            sum(len(member["section_ids"]) for member in members) == len(input_rows),
            "every source document and every section is represented once")
    t.check(all(group["record_sha256"] == _digest({key: value for key, value in group.items() if key != "record_sha256"}) and
                group["review_status"] == "PENDING" and group["generation_allowed"] is False for group in groups),
            "group rows carry valid hashes and remain pending and forbidden for generation")
    by_candidate = {member["candidate_id"]: member for member in members}
    include_members = [_cid(candidates, "esy", index) for index in (0, 1, 2)]
    t.check(len({by_candidate[cid]["split_group"] for cid in include_members}) == 1 and
            "include" in next(group for group in groups if _cid(candidates, "esy", 0) in group["member_candidate_ids"])["relation_types"],
            "transitive include ancestry keeps all linked source documents together")
    t.check(by_candidate[_cid(candidates, "esy", 0)]["split_group"] == by_candidate[_cid(candidates, "ocaml", 0)]["split_group"] and
            "translation-fixture-01" in next(group for group in groups if _cid(candidates, "esy", 0) in group["member_candidate_ids"])["annotation_ids"],
            "explicit translation annotation links variants without claiming automatic semantic discovery")
    t.check(by_candidate[_cid(candidates, "ocaml", 5)]["split_group"] == by_candidate[_cid(candidates, "ocaml", 6)]["split_group"] and
            "exact" in next(group for group in groups if _cid(candidates, "ocaml", 5) in group["member_candidate_ids"])["relation_types"],
            "normalized exact documents share one leakage group")
    t.check(by_candidate[_cid(candidates, "reason", 3)]["split_group"] == by_candidate[_cid(candidates, "reason", 4)]["split_group"] and
            "near_duplicate" in next(group for group in groups if _cid(candidates, "reason", 3) in group["member_candidate_ids"])["relation_types"],
            "five-token-shingle near duplicates above the fixed threshold share one leakage group")
    domain_summary = manifest["summary"]["domains"]
    t.check(all(domain_summary[domain]["train_groups"] > 0 and domain_summary[domain]["valid_groups"] > 0 for domain in DOMAINS),
            "cross-domain union leaves both train and valid eligible groups in every domain")
    t.check(all(member["split"] in {"train", "valid"} for member in members if member["eligible"]) and
            all(member["split"] is None and member["extraction_status"] in {"candidate_exclude", "candidate_quarantine"}
                for member in members if not member["eligible"]),
            "eligible documents receive assignments while excluded and quarantined documents remain unassigned with their status")
    content = groups_path.read_bytes()
    t.cli("prepare", "--config", config, "--run-id", "splits", root=root)
    t.check(groups_path.read_bytes() == content, "same pinned inputs and config replay byte-identically")

    order_root, order_config, _, _ = _fixture(t, "reordered", reverse=True)
    order_result = json.loads(t.cli("prepare", "--config", order_config, "--run-id", "splits", root=order_root)["stdout"])
    t.check(Path(order_result["groups"]).read_bytes() == content, "input JSONL ordering does not change deterministic groups or assignments")

    # A hash-bound unknown link target must fail before output commitment.
    unknown_root, unknown_config_path, _, _ = _fixture(t, "unknown-link")
    unknown_config = json.loads(unknown_config_path.read_text())
    annotation_path = unknown_root / "config/split-links.json"
    annotation = json.loads(annotation_path.read_text())
    annotation["links"][0]["source_ids"][1] = "missing-candidate-id"
    annotation_path.write_bytes(_canonical(annotation) + b"\n")
    unknown_config["annotations_sha256"] = _sha(annotation_path)
    unknown_config_path.write_bytes(_canonical(unknown_config) + b"\n")
    t.cli("prepare", "--config", unknown_config_path, "--run-id", "unknown-link", root=unknown_root, expected=2)
    t.check(not (unknown_root / "artifacts/splits/unknown-link/manifest.json").exists(), "unknown annotation source fails closed before commit")

    # Missing source sections cannot be hidden by rehashing the producer files.
    gap_root, gap_config_path, gap_candidates, _ = _fixture(t, "section-gap")
    gap_config = json.loads(gap_config_path.read_text())
    extraction_path = gap_root / gap_config["extraction_manifest"]
    extraction = json.loads(extraction_path.read_text())
    record_path = gap_root / extraction["record_file"]
    gap_rows = _records(record_path)
    removed = False
    for index, row in enumerate(gap_rows):
        if row["candidate_id"] == _cid(gap_candidates, "esy", 0) and row["section_ordinal"] == 1:
            gap_rows.pop(index)
            removed = True
            break
    gap_bytes = b"".join(_canonical(row) + b"\n" for row in gap_rows)
    record_path.write_bytes(gap_bytes)
    extraction["record_count"] = len(gap_rows)
    extraction["record_file_sha256"] = hashlib.sha256(gap_bytes).hexdigest()
    extraction_path.write_bytes(_canonical(extraction) + b"\n")
    gap_config["extraction_manifest_sha256"] = _sha(extraction_path)
    gap_config_path.write_bytes(_canonical(gap_config) + b"\n")
    t.check(removed, "fixture contains a multi-section source")
    t.cli("prepare", "--config", gap_config_path, "--run-id", "section-gap", root=gap_root, expected=2)
    t.check(not (gap_root / "artifacts/splits/section-gap/manifest.json").exists(), "incomplete section coverage fails source reconstruction")

    # A single linked component/domain cannot supply independent train and valid groups.
    small_root, small_config, _, _ = _fixture(t, "insufficient", count=1)
    blocked = t.cli("prepare", "--config", small_config, "--run-id", "insufficient", root=small_root, expected=3)
    t.check(json.loads(blocked["stdout"])["status"] == "BLOCKED" and
            not (small_root / "artifacts/splits/insufficient/manifest.json").exists(),
            "too few independent groups block without split artifacts")

    # Immutable output tampering is reported as a conflict and never overwritten.
    conflict_root, conflict_config, _, _ = _fixture(t, "output-conflict")
    conflict = json.loads(t.cli("prepare", "--config", conflict_config, "--run-id", "conflict", root=conflict_root)["stdout"])
    conflict_path = Path(conflict["groups"])
    conflict_path.write_bytes(conflict_path.read_bytes() + b"{}\n")
    changed = conflict_path.read_bytes()
    t.cli("prepare", "--config", conflict_config, "--run-id", "conflict", root=conflict_root, expected=2)
    t.check(conflict_path.read_bytes() == changed, "mutated immutable group output conflicts rather than being replaced")

    # Input record tampering invalidates the pinned extraction manifest.
    tamper_root, tamper_config, _, _ = _fixture(t, "tamper")
    tamper_value = json.loads(tamper_config.read_text())
    tamper_manifest = tamper_root / tamper_value["extraction_manifest"]
    tamper_record = tamper_root / json.loads(tamper_manifest.read_text())["record_file"]
    tamper_record.write_bytes(tamper_record.read_bytes().replace(b"candidate_include", b"candidate_exclude", 1))
    t.cli("prepare", "--config", tamper_config, "--run-id", "tampered-input", root=tamper_root, expected=2)
    t.check(not (tamper_root / "artifacts/splits/tampered-input/manifest.json").exists(), "tampered extraction records commit no split result")


SCENARIOS = {"splits": test_splits}
