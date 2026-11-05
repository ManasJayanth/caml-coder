"""Public subprocess E2Es for bounded, lineage-preserving Bonito chunks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


TASKS = ("question answering without choices", "extractive question answering", "summarization")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")
    return path


def _split_helper():
    path = Path(__file__).with_name("test_splits.py")
    spec = importlib.util.spec_from_file_location("sft_chunk_split_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stage(t, label, text_override=None, *, detach_includes=False):
    helper = _split_helper()
    root, split_config_path, candidates, initial_rows = helper._fixture(t, label, text_override=text_override)
    extraction_path = root / "artifacts/extract/input/manifest.json"
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    records_path = root / extraction["record_file"]
    rows = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    if detach_includes:
        target = next(row for row in rows if row["source_domain"] == "esy" and row["source_path"] == "docs/esy-00.md")
        target["include_dependencies"] = []
        target["record_sha256"] = hashlib.sha256(_canonical({key: value for key, value in target.items() if key != "record_sha256"})).hexdigest()
        raw = b"".join(_canonical(row) + b"\n" for row in rows)
        records_path.write_bytes(raw)
        extraction["record_file_sha256"] = hashlib.sha256(raw).hexdigest()
        _write(extraction_path, extraction)
        split_config = json.loads(split_config_path.read_text(encoding="utf-8"))
        split_config["extraction_manifest_sha256"] = _sha(extraction_path)
        split_config_path = _write(t.temporary / f"chunk-split-{label}.json", split_config)
    split_result = json.loads(t.cli("prepare", "--config", split_config_path, "--run-id", f"split-{label}", root=root)["stdout"])
    tokenizer_source = t.root / "artifacts/models/tokenizers/bonito-tokenizer-002"
    tokenizer_dest = root / "artifacts/models/tokenizers/bonito-tokenizer-002"
    shutil.copytree(tokenizer_source, tokenizer_dest)
    tokenizer_manifest = tokenizer_dest / "manifest.json"
    config = {"schema_version": 1, "stage": "chunks",
              "extraction_manifest": str(extraction_path.relative_to(root)),
              "extraction_manifest_sha256": _sha(extraction_path),
              "split_manifest": str(Path(split_result["manifest"]).relative_to(root)),
              "split_manifest_sha256": _sha(Path(split_result["manifest"])),
              "tokenizer_manifest": str(tokenizer_manifest.relative_to(root)),
              "tokenizer_manifest_sha256": _sha(tokenizer_manifest)}
    config_path = _write(t.temporary / f"chunk-config-{label}.json", config)
    return root, config_path, rows


def _run_chunks(t, root, config, run_id, expected=0):
    return t.cli("prepare", "--config", config, "--run-id", run_id, root=root, expected=expected)


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_chunks(t):
    root, config, rows = _stage(t, "main")
    result = json.loads(_run_chunks(t, root, config, "chunks-main")["stdout"])
    manifest_path = Path(result["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk_path = root / manifest["chunk_file"]
    chunks = _records(chunk_path)
    quarantine = _records(root / manifest["quarantine_file"])
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(root / "artifacts/models/tokenizers/bonito-tokenizer-002/files/tokenizer.json"))
    for chunk in chunks:
        t.check(chunk["source_token_count"] == len(tokenizer.encode(chunk["passage"], add_special_tokens=False).ids),
                "source-only counts exclude special tokens")
        for item in chunk["task_prompt_counts"]:
            prompt = f'<|tasktype|>\n{item["task"]}\n<|context|>\n{chunk["passage"]}\n<|task|>\n'
            ids = tokenizer.encode(prompt, add_special_tokens=True).ids
            plain = tokenizer.encode(prompt, add_special_tokens=False).ids
            t.check(ids == [1] + plain and item["prompt_tokens"] == len(ids) and
                    item["input_ids_sha256"] == hashlib.sha256(_canonical(ids)).hexdigest(),
                    "complete Bonito prompt includes exactly one BOS and binds its full input IDs")
    config_value = json.loads(config.read_text())
    split_manifest = json.loads((root / config_value["split_manifest"]).read_text())
    groups = _records(root / split_manifest["group_file"])
    mixed = [group for group in groups if any(m["eligible"] for m in group["members"]) and
             any(not m["eligible"] for m in group["members"])]
    t.check(bool(mixed), "fixture exercises eligible and excluded members in one split group")
    emitted = {chunk["candidate_id"] for chunk in chunks}
    t.check(all(m["split"] is None and m["candidate_id"] not in emitted
                for group in mixed for m in group["members"] if not m["eligible"]),
            "excluded members of assigned groups remain unassigned and never emit chunks")
    t.check(result["status"] == "PASSED" and manifest["generation_allowed"] is False and manifest["review_status"] == "PENDING",
            "chunks are committed as pending input and never generation-ready")
    t.check(manifest["tokenizer"]["repo_id"] == "BatsResearch/bonito-v1" and
            manifest["tokenizer"]["revision"] == "0b70064ffa8956ab6bec867b87fc85762dd26d81" and
            manifest["tokenizer"]["tokenizer_sha256"],
            "chunk run binds the actual pinned Bonito tokenizer receipt and file hash")
    t.check(not quarantine and chunks and all(row["record_sha256"] == hashlib.sha256(_canonical({key: value for key, value in row.items() if key != "record_sha256"})).hexdigest() for row in chunks),
            "all eligible fixture sections produce hash-valid chunk records without quarantine")
    t.check(all(row["review_status"] == "PENDING" and row["generation_allowed"] is False and row["split"] in {"train", "valid"} and row["split_group"] for row in chunks),
            "chunks retain split-group lineage and the pending generation gate")
    t.check(all(row["source_token_count"] <= 1536 and len(row["task_prompt_counts"]) == 3 and
                [item["task"] for item in row["task_prompt_counts"]] == list(TASKS) and
                all(item["prompt_tokens"] <= 2048 and item["prompt_tokens"] + row["generation_reserve"] <= 4096 and item["within_bounds"] for item in row["task_prompt_counts"])
                for row in chunks),
            "actual-tokenizer source and all three exact prompt wrappers stay within recorded limits")
    included = next(row for row in rows if row["source_domain"] == "esy" and row["source_path"] == "docs/esy-00.md")
    chunk = next(row for row in chunks if row["section_id"] == included["id"])
    t.check(chunk["source_kind"] == "whole_root_section_with_whole_source_dependencies" and
            chunk["source_span"] == included["source_span"] and
            [dep["source_path"] for dep in chunk["source_dependencies"]] == [dep["source_path"] for dep in included["include_dependencies"]],
            "include-bearing sections remain indivisible and carry the full explicit dependency references with exact root span")
    by_section = {}
    for chunk in chunks:
        by_section.setdefault(chunk["section_id"], []).append(chunk)
    for section_id, section_chunks in by_section.items():
        section_chunks.sort(key=lambda row: row["chunk_ordinal"])
        original = next(row["source_text"] for row in rows if row["id"] == section_id)
        t.check("".join(row["source_text"] for row in section_chunks) == original,
                f"source bytes reconstruct exactly for section {section_id}")
    chunk_bytes = chunk_path.read_bytes()
    _run_chunks(t, root, config, "chunks-main")
    t.check(chunk_path.read_bytes() == chunk_bytes, "same config and run ID replay byte-identically")


def test_chunk_boundaries_and_oversized_structure(t):
    from tokenizers import Tokenizer
    source_tokenizer = t.root / "artifacts/models/tokenizers/bonito-tokenizer-002/files/tokenizer.json"
    tokenizer = Tokenizer.from_file(str(source_tokenizer))
    low, high = 1, 10000
    while low < high:
        mid = (low + high) // 2
        passage = ("# Boundary\n\n" + ("a " * mid).rstrip()).strip()
        if len(tokenizer.encode(passage, add_special_tokens=False).ids) >= 1536:
            high = mid
        else:
            low = mid + 1
    candidates = [max(1, low - 3), low - 2, low - 1, low, low + 1]
    chosen = None
    for count in candidates:
        text = "# Boundary\n\n" + ("a " * count).rstrip() + "\n"
        if len(tokenizer.encode(text.strip(), add_special_tokens=False).ids) == 1536:
            chosen = text
            break
    t.check(chosen is not None, "fixture tokenizer can exercise the exact 1536-token source boundary")
    boundary_root, boundary_config, _ = _stage(t, "boundary", chosen, detach_includes=True)
    boundary_result = json.loads(_run_chunks(t, boundary_root, boundary_config, "chunks-boundary")["stdout"])
    boundary_manifest = json.loads(Path(boundary_result["manifest"]).read_text(encoding="utf-8"))
    boundary_rows = _records(boundary_root / boundary_manifest["chunk_file"])
    boundary_chunk = next(row for row in boundary_rows if row["source_path"] == "docs/esy-00.md")
    t.check(boundary_chunk["source_token_count"] == 1536 and boundary_chunk["source_span"]["start_byte"] == 0,
            "exact token-boundary chunk preserves its original root byte span")

    large = "# Large code\n\n```ocaml\nlet data = \"" + ("λ " * 5000) + "\"\n```\n"
    large_root, large_config, _ = _stage(t, "large-fence", large, detach_includes=True)
    large_result = json.loads(_run_chunks(t, large_root, large_config, "chunks-large-fence")["stdout"])
    large_manifest = json.loads(Path(large_result["manifest"]).read_text(encoding="utf-8"))
    large_chunks = _records(large_root / large_manifest["chunk_file"])
    large_quarantine = _records(large_root / large_manifest["quarantine_file"])
    t.check(any(row["source_path"] == "docs/esy-00.md" and row["reason"] == "oversized_indivisible_block" for row in large_quarantine) and
            not any(row["source_path"] == "docs/esy-00.md" for row in large_chunks),
            "an oversized intact code fence quarantines its whole section without partial chunks or truncation")


def test_chunk_control_collision_and_stale_inputs(t):
    control_root, control_config, _ = _stage(t, "control-collision", "# Token\n\nThe literal <|task|> is not safe content.\n", detach_includes=True)
    control_result = json.loads(_run_chunks(t, control_root, control_config, "chunks-control")["stdout"])
    control_manifest = json.loads(Path(control_result["manifest"]).read_text(encoding="utf-8"))
    control_quarantine = _records(control_root / control_manifest["quarantine_file"])
    t.check(any(row["source_path"] == "docs/esy-00.md" and row["reason"] == "control_token_collision" for row in control_quarantine),
            "special control-token collisions are retained as explicit quarantine records")
    config_value = json.loads(control_config.read_text(encoding="utf-8"))
    config_value["tokenizer_manifest_sha256"] = "0" * 64
    altered = _write(t.temporary / "chunk-stale-config.json", config_value)
    _run_chunks(t, control_root, altered, "chunks-stale", expected=2)


def _repin_split(t, root, config_path, mutate):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest_path = root / config["split_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    group_path = root / manifest["group_file"]
    groups = _records(group_path)
    mutate(groups)
    for group in groups:
        group["record_sha256"] = hashlib.sha256(_canonical({key: value for key, value in group.items() if key != "record_sha256"})).hexdigest()
    raw = b"".join(_canonical(row) + b"\n" for row in groups)
    group_path.write_bytes(raw)
    manifest["group_file_sha256"] = hashlib.sha256(raw).hexdigest()
    _write(manifest_path, manifest)
    config["split_manifest_sha256"] = _sha(manifest_path)
    return _write(t.temporary / "mutated-chunk-config.json", config)


def test_chunk_rejects_rehashed_split_semantic_conflicts(t):
    root, config, _rows = _stage(t, "bad-member")
    def wrong_member(groups):
        member = groups[0]["members"][0]
        member["candidate_id"] = "invented-candidate"
        groups[0]["member_candidate_ids"][0] = "invented-candidate"
    bad_member_config = _repin_split(t, root, config, wrong_member)
    _run_chunks(t, root, bad_member_config, "chunks-bad-member", expected=2)

    root2, config2, _rows2 = _stage(t, "bad-split")
    def contradict(groups):
        eligible_group = next(group for group in groups if group["split"] in {"train", "valid"})
        eligible_group["split"] = "valid" if eligible_group["split"] == "train" else "train"
    bad_split_config = _repin_split(t, root2, config2, contradict)
    _run_chunks(t, root2, bad_split_config, "chunks-bad-split", expected=2)

    root3, config3, _ = _stage(t, "excluded-assigned")
    def assign_excluded(groups):
        group = next(g for g in groups if g["split"] in {"train", "valid"} and
                     any(not m["eligible"] for m in g["members"]))
        next(m for m in group["members"] if not m["eligible"])["split"] = group["split"]
    bad_excluded_config = _repin_split(t, root3, config3, assign_excluded)
    _run_chunks(t, root3, bad_excluded_config, "chunks-excluded-assigned", expected=2)


SCENARIOS = {"chunks": test_chunks,
             "chunk-boundaries": test_chunk_boundaries_and_oversized_structure,
             "chunk-integrity": test_chunk_control_collision_and_stale_inputs,
             "chunk-split-semantics": test_chunk_rejects_rehashed_split_semantic_conflicts}
