"""Deterministic, token-aware Bonito passage chunking.

This stage only prepares pending inputs. It never generates or marks a passage
ready for generation.
"""
import hashlib
import json
from pathlib import Path
import re

from .artifacts import Invalid, atomic_bytes, atomic_json, canonical, digest, fields, file_hash, identifier, implementation_hash, loads, read_json, safe_path


HASH = re.compile(r"^[0-9a-f]{64}$")
BONITO_REPOSITORY = "BatsResearch/bonito-v1"
BONITO_REVISION = "0b70064ffa8956ab6bec867b87fc85762dd26d81"
TASKS = ("question answering without choices", "extractive question answering", "summarization")
BONITO_SPECIAL_TOKENS = {"<unk>": 0, "<s>": 1, "</s>": 2}
BONITO_PROTOCOL_TOKENS = {
    "<|tasktype|>": [523, 28766, 5553, 1123, 28766, 28767],
    "<|context|>": [523, 28766, 2714, 28766, 28767],
    "<|task|>": [523, 28766, 5553, 28766, 28767],
    "<|pipe|>": [523, 28766, 12911, 28766, 28767],
}
SOURCE_LIMIT = 1536
PROMPT_LIMIT = 2048
GENERATION_RESERVE = 1024
TOTAL_LIMIT = 4096
MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
CONTROL_TOKEN = re.compile(r"<\|[^|\r\n]{1,80}\|>")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)(?:\r?\n)?$")
DIV_OPEN = re.compile(r"<div\b[^>]*>", re.I)
DIV_CLOSE = re.compile(r"</div\s*>", re.I)
ADMONITION_OPEN = re.compile(r"^ {0,3}:::[^:\r\n]*\S")
ADMONITION_CLOSE = re.compile(r"^ {0,3}:::[ \t]*(?:\r?\n)?$")


def _sha(value, label):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise Invalid(f"invalid SHA256 in {label}")


def _relative_file(root, value, label):
    if not isinstance(value, str) or not value:
        raise Invalid(f"{label} must be a root-relative path")
    path = safe_path(root, value)
    if not path.is_file():
        raise Invalid(f"{label} is missing or not a regular file")
    return path


def _read_jsonl(path, maximum):
    if path.stat().st_size > maximum:
        raise Invalid("chunk input JSONL exceeds safety limit")
    rows = []
    seen = set()
    raw = path.read_bytes()
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line:
            raise Invalid(f"blank JSONL row at line {number}")
        row = loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in seen:
            raise Invalid(f"malformed or duplicate JSONL row at line {number}")
        seen.add(row["id"])
        rows.append(row)
    return raw, rows


def _tokenizer(root, path, expected_sha):
    _sha(expected_sha, "tokenizer_manifest_sha256")
    if file_hash(path) != expected_sha:
        raise Invalid("tokenizer manifest hash mismatch")
    manifest = read_json(path)
    fields(manifest, ["schema_version", "id", "kind", "config_hash", "repo_id", "revision", "files", "special_tokens", "protocol_tokens", "probes", "tokenizers_version", "implementation_hash"])
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or
            manifest["repo_id"] != BONITO_REPOSITORY or manifest["revision"] != BONITO_REVISION or
            not isinstance(manifest["files"], list) or manifest["special_tokens"] != BONITO_SPECIAL_TOKENS or
            manifest["protocol_tokens"] != BONITO_PROTOCOL_TOKENS):
        raise Invalid("tokenizer receipt is not the pinned Bonito identity")
    manifest_dir = path.parent
    file_records = {}
    for record in manifest["files"]:
        fields(record, ["path", "sha256", "bytes", "max_bytes"])
        rel = record["path"]
        _sha(record["sha256"], "tokenizer file sha256")
        if not isinstance(rel, str) or rel in file_records or type(record["bytes"]) is not int or record["bytes"] < 0 or record["bytes"] > record["max_bytes"]:
            raise Invalid("invalid tokenizer asset record")
        asset = safe_path(manifest_dir, f"files/{rel}")
        if not asset.is_file() or asset.stat().st_size != record["bytes"] or file_hash(asset) != record["sha256"]:
            raise Invalid(f"pinned tokenizer asset is missing or corrupt: {rel}")
        file_records[rel] = asset
    if "tokenizer.json" not in file_records:
        raise Invalid("pinned Bonito tokenizer.json is absent")
    try:
        from tokenizers import Tokenizer, __version__ as tokenizers_version
        tokenizer = Tokenizer.from_file(str(file_records["tokenizer.json"]))
    except Exception as error:
        raise Invalid(f"cannot load actual pinned Bonito tokenizer: {error}") from error
    if manifest["tokenizers_version"] != tokenizers_version:
        raise Invalid("tokenizers runtime version differs from the verified receipt")
    tokenizer_json = read_json(file_records["tokenizer.json"])
    added_rows = tokenizer_json.get("added_tokens") if isinstance(tokenizer_json, dict) else None
    if not isinstance(added_rows, list):
        raise Invalid("tokenizer.json has no added-token inventory")
    added = {}
    for row in added_rows:
        if not isinstance(row, dict) or not isinstance(row.get("content"), str) or type(row.get("id")) is not int or type(row.get("special")) is not bool or row["content"] in added:
            raise Invalid("malformed or duplicate tokenizer added token")
        added[row["content"]] = row
    for token, token_id in manifest["special_tokens"].items():
        if type(token_id) is not int or not isinstance(added.get(token), dict) or added[token]["id"] != token_id or added[token]["special"] is not True or tokenizer.token_to_id(token) != token_id:
            raise Invalid(f"Bonito special-token identity mismatch: {token}")
    for token, expected in manifest["protocol_tokens"].items():
        if tokenizer.encode(token, add_special_tokens=False).ids != expected:
            raise Invalid(f"Bonito protocol-token identity mismatch: {token}")
    return tokenizer, {"manifest_sha256": expected_sha, "repo_id": manifest["repo_id"], "revision": manifest["revision"],
                       "tokenizers_version": tokenizers_version,
                       "tokenizer_sha256": next(row["sha256"] for row in manifest["files"] if row["path"] == "tokenizer.json")}


def _line_records(text):
    records = []
    byte = 0
    line_no = 1
    pieces = [part + "\n" for part in text.split("\n")[:-1]]
    if text.split("\n")[-1]:
        pieces.append(text.split("\n")[-1])
    for piece in pieces:
        raw = piece.encode("utf-8")
        records.append({"text": piece, "start_byte": byte, "end_byte": byte + len(raw), "start_line": line_no,
                        "end_line": line_no + piece.count("\n") - (1 if piece.endswith("\n") else 0)})
        byte += len(raw)
        line_no += piece.count("\n")
    if not records and text == "":
        return []
    if records and not text.endswith(("\n", "\r")):
        pass
    return records


def _atoms(text):
    """Partition text into exact ordered blocks, keeping syntax containers whole."""
    lines = _line_records(text)
    atoms = []
    i = 0
    while i < len(lines):
        start = i
        line = lines[i]["text"]
        fm_open = i == 0 and re.fullmatch(r"---[ \t]*(?:\r?\n)?", line)
        if fm_open:
            i += 1
            while i < len(lines) and not re.fullmatch(r"(?:---|\.\.\.)[ \t]*(?:\r?\n)?", lines[i]["text"]):
                i += 1
            if i >= len(lines):
                raise Invalid("malformed frontmatter cannot be chunked")
            i += 1
        else:
            fence = FENCE_OPEN.match(line)
            if fence:
                marker = fence.group(1)[0]
                size = len(fence.group(1))
                i += 1
                close = re.compile(r"^ {0,3}" + re.escape(marker) + r"{" + str(size) + r",}[ \t]*(?:\r?\n)?$")
                while i < len(lines) and not close.fullmatch(lines[i]["text"]):
                    i += 1
                if i >= len(lines):
                    raise Invalid("unclosed fence cannot be chunked")
                i += 1
            elif DIV_OPEN.search(line) or ADMONITION_OPEN.match(line):
                div_depth = 0
                admonition_depth = 0
                while i < len(lines):
                    current = lines[i]["text"]
                    if FENCE_OPEN.match(current):
                        fence_match = FENCE_OPEN.match(current)
                        marker, size = fence_match.group(1)[0], len(fence_match.group(1))
                        i += 1
                        close = re.compile(r"^ {0,3}" + re.escape(marker) + r"{" + str(size) + r",}[ \t]*(?:\r?\n)?$")
                        while i < len(lines) and not close.fullmatch(lines[i]["text"]):
                            i += 1
                        if i >= len(lines):
                            raise Invalid("unclosed fence cannot be chunked")
                        i += 1
                        continue
                    div_depth += len(DIV_OPEN.findall(current)) - len(DIV_CLOSE.findall(current))
                    if ADMONITION_OPEN.match(current):
                        admonition_depth += 1
                    elif ADMONITION_CLOSE.match(current) and admonition_depth:
                        admonition_depth -= 1
                    i += 1
                    if div_depth <= 0 and admonition_depth <= 0:
                        break
                if div_depth or admonition_depth:
                    raise Invalid("unbalanced wrapper cannot be chunked")
            else:
                # Ordinary prose can split only at physical line or blank-line
                # boundaries; list/table lines are grouped as one block.
                listish = bool(re.match(r"^\s*(?:[-+*]|\d+[.)]|\|)", line))
                if listish:
                    i += 1
                    while i < len(lines) and (lines[i]["text"].strip() and re.match(r"^\s*(?:[-+*]|\d+[.)]|\||  )", lines[i]["text"])):
                        i += 1
                    while i < len(lines) and not lines[i]["text"].strip():
                        i += 1
                else:
                    i += 1
                    while i < len(lines) and lines[i]["text"].strip() and not FENCE_OPEN.match(lines[i]["text"]) and not DIV_OPEN.search(lines[i]["text"]) and not ADMONITION_OPEN.match(lines[i]["text"]):
                        if re.match(r"^\s*(?:[-+*]|\d+[.)]|\|)", lines[i]["text"]):
                            break
                        i += 1
                    while i < len(lines) and not lines[i]["text"].strip():
                        i += 1
        if i == start:
            i += 1
        atoms.append({"text": "".join(row["text"] for row in lines[start:i]),
                      "start_byte": lines[start]["start_byte"], "end_byte": lines[i - 1]["end_byte"],
                      "start_line": lines[start]["start_line"], "end_line": lines[i - 1]["end_line"]})
    if "".join(atom["text"] for atom in atoms) != text:
        raise Invalid("chunk atomization failed exact reconstruction")
    return atoms


def _heading_context(ancestry):
    if not isinstance(ancestry, list):
        raise Invalid("heading ancestry must be an array")
    rows = []
    for item in ancestry:
        if not isinstance(item, dict) or type(item.get("level")) is not int or not 1 <= item["level"] <= 6 or not isinstance(item.get("title"), str):
            raise Invalid("malformed heading ancestry")
        rows.append("#" * item["level"] + " " + item["title"])
    return "\n".join(rows)


def _prompt(task, passage):
    return f"<|tasktype|>\n{task}\n<|context|>\n{passage}\n<|task|>\n"


def _measure(tokenizer, ancestry, content):
    context = _heading_context(ancestry)
    stripped = content.strip()
    passage = f"{context}\n\n{stripped}" if context and stripped else context or stripped
    passage_tokens = len(tokenizer.encode(passage, add_special_tokens=False).ids)
    task_records = []
    for task in TASKS:
        prompt = _prompt(task, passage)
        ids = tokenizer.encode(prompt, add_special_tokens=True).ids
        prompt_tokens = len(ids)
        task_records.append({"task": task, "prompt_tokens": prompt_tokens,
                             "input_ids_sha256": hashlib.sha256(canonical(ids)).hexdigest(),
                             "within_bounds": passage_tokens <= SOURCE_LIMIT and prompt_tokens <= PROMPT_LIMIT and
                                             prompt_tokens + GENERATION_RESERVE <= TOTAL_LIMIT})
    return passage, passage_tokens, task_records


def _fits(tokenizer, ancestry, content):
    _passage, source_tokens, tasks = _measure(tokenizer, ancestry, content)
    return source_tokens <= SOURCE_LIMIT and all(item["within_bounds"] for item in tasks)


def _chunk_section(tokenizer, row):
    source = row["source_text"]
    has_includes = bool(row["include_dependencies"])
    text = row["expanded_text"] if has_includes else source
    if not has_includes and text != source:
        raise Invalid("expanded text differs from source without include dependencies")
    ancestry = row["heading_ancestry"]
    if CONTROL_TOKEN.search(text):
        return [], "control_token_collision"
    if has_includes:
        if _fits(tokenizer, ancestry, text):
            return [{"text": text, "root_source_text": source, "source_span": row["source_span"], "source_kind": "whole_root_section_with_whole_source_dependencies"}], None
        return [], "oversized_indivisible_included_section"
    syntax = row.get("syntax_metadata", {})
    if (isinstance(syntax, dict) and syntax.get("paired_language_examples")) or re.search(r"^ {0,3}===\s+[\"']", text, re.M):
        if _fits(tokenizer, ancestry, text):
            return [{"text": text, "root_source_text": source, "source_span": row["source_span"], "source_kind": "whole_root_section_for_paired_examples_or_tabs"}], None
        return [], "oversized_indivisible_paired_examples_or_tabs"
    try:
        atoms = _atoms(text)
    except Invalid:
        return [], "malformed_structure"
    if not atoms:
        return [], "empty_section"
    packed = []
    current = []
    for atom in atoms:
        if not _fits(tokenizer, ancestry, atom["text"]):
            return [], "oversized_indivisible_block"
        candidate = current + [atom]
        if current and not _fits(tokenizer, ancestry, "".join(part["text"] for part in candidate)):
            packed.append(current)
            current = [atom]
        else:
            current = candidate
    if current:
        packed.append(current)
    result = []
    for group in packed:
        first, last = group[0], group[-1]
        result.append({"text": "".join(atom["text"] for atom in group),
                       "root_source_text": "".join(atom["text"] for atom in group),
                       "source_span": {"start_byte": row["source_span"]["start_byte"] + first["start_byte"],
                                       "end_byte": row["source_span"]["start_byte"] + last["end_byte"],
                                       "start_line": row["source_span"]["start_line"] + first["start_line"] - 1,
                                       "end_line": row["source_span"]["start_line"] + last["end_line"] - 1},
                       "source_kind": "exact_root_source_span"})
    if "".join(item["text"] for item in result) != source:
        return [], "source_reconstruction_failed"
    return result, None


def _inputs(root, config):
    fields(config, ["schema_version", "stage", "extraction_manifest", "extraction_manifest_sha256", "split_manifest", "split_manifest_sha256", "tokenizer_manifest", "tokenizer_manifest_sha256"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["stage"] != "chunks":
        raise Invalid("unsupported chunk config")
    for key in ("extraction_manifest_sha256", "split_manifest_sha256", "tokenizer_manifest_sha256"):
        _sha(config[key], key)
    extraction_path = _relative_file(root, config["extraction_manifest"], "extraction manifest")
    split_path = _relative_file(root, config["split_manifest"], "split manifest")
    tokenizer_path = _relative_file(root, config["tokenizer_manifest"], "tokenizer manifest")
    if file_hash(extraction_path) != config["extraction_manifest_sha256"] or file_hash(split_path) != config["split_manifest_sha256"]:
        raise Invalid("upstream manifest hash mismatch")
    extraction, split = read_json(extraction_path), read_json(split_path)
    fields(extraction, ["schema_version", "id", "kind", "status", "stage", "eligibility_manifest", "eligibility_manifest_sha256", "snapshot_id", "snapshot_manifest_sha256", "config_sha256", "effective_config", "implementation_sha256", "record_file", "record_file_sha256", "record_count", "source_candidate_count", "counts", "review_status", "generation_allowed"])
    fields(split, ["schema_version", "id", "kind", "stage", "status", "extraction_manifest", "extraction_manifest_sha256", "extraction_id", "snapshot_id", "snapshot_manifest_sha256", "config_sha256", "effective_config", "implementation_sha256", "algorithm", "near_duplicate", "annotation_file_sha256", "group_file", "group_file_sha256", "group_count", "source_document_count", "section_count", "relation_counts", "summary", "review_status", "generation_allowed"])
    if (extraction["kind"] != "extraction" or extraction["stage"] != "extraction" or extraction["status"] not in {"PASSED", "QUARANTINED"} or extraction["review_status"] != "PENDING" or extraction["generation_allowed"] is not False or
            split["kind"] != "splits" or split["stage"] != "splits" or split["status"] != "PASSED" or split["review_status"] != "PENDING" or split["generation_allowed"] is not False or
            split["extraction_manifest_sha256"] != config["extraction_manifest_sha256"] or split["extraction_id"] != extraction["id"] or
            extraction["config_sha256"] != digest(extraction["effective_config"]) or split["config_sha256"] != digest(split["effective_config"])):
        raise Invalid("extraction/split lineage or pending state is invalid")
    records_path = _relative_file(root, extraction["record_file"], "extraction records")
    record_raw, rows = _read_jsonl(records_path, MAX_INPUT_BYTES)
    if hashlib.sha256(record_raw).hexdigest() != extraction["record_file_sha256"] or len(rows) != extraction["record_count"]:
        raise Invalid("extraction records do not match manifest")
    for row in rows:
        fields(row, ["schema_version", "id", "kind", "candidate_id", "candidate_status", "source_domain", "repository", "revision", "source_path", "artifact_path", "source_file_sha256", "section_ordinal", "heading", "heading_ancestry", "source_span", "source_text", "expanded_text", "include_dependencies", "syntax_metadata", "extraction_status", "reason_codes", "version_compatibility", "review_status", "generation_allowed", "record_sha256"])
        if row["record_sha256"] != digest({key: value for key, value in row.items() if key != "record_sha256"}) or row["review_status"] != "PENDING" or row["generation_allowed"] is not False:
            raise Invalid("extraction row hash or state invalid")
    if split["extraction_manifest"] != config["extraction_manifest"]:
        raise Invalid("split manifest points to another extraction manifest")
    group_path = _relative_file(root, split["group_file"], "split group records")
    group_raw, groups = _read_jsonl(group_path, MAX_INPUT_BYTES)
    if hashlib.sha256(group_raw).hexdigest() != split["group_file_sha256"] or len(groups) != split["group_count"]:
        raise Invalid("split group records do not match manifest")
    section_ids = {row["id"] for row in rows}
    memberships = {}
    for group in groups:
        if group.get("record_sha256") != digest({key: value for key, value in group.items() if key != "record_sha256"}) or group.get("generation_allowed") is not False or group.get("review_status") != "PENDING":
            raise Invalid("split group hash or state invalid")
        for member in group.get("members", []):
            cid = member.get("candidate_id")
            for sid in member.get("section_ids", []):
                if sid not in section_ids or sid in memberships:
                    raise Invalid("split group section coverage is missing or duplicated")
                memberships[sid] = {"split_group": group["split_group"], "split": member.get("split"), "eligible": member.get("eligible"), "candidate_id": cid,
                                    "dependencies": group.get("relation_types", [])}
    if set(memberships) != section_ids:
        raise Invalid("split groups do not cover every extraction section")
    tokenizer, tokenizer_identity = _tokenizer(root, tokenizer_path, config["tokenizer_manifest_sha256"])
    from .splits import _documents, _read_inputs as read_split_inputs
    validated_extraction, validated_rows, _annotations = read_split_inputs(root, split["effective_config"])
    if (validated_extraction["id"] != extraction["id"] or
            [row["id"] for row in validated_rows] != [row["id"] for row in rows]):
        raise Invalid("split effective input does not validate to this extraction inventory")
    documents = _documents(extraction, rows)
    seen_candidates = set()
    for group in groups:
        if group.get("id") != group.get("split_group") or not isinstance(group.get("members"), list):
            raise Invalid("split group identity is inconsistent")
        member_ids = [member.get("candidate_id") for member in group["members"]]
        if member_ids != group.get("member_candidate_ids") or len(set(member_ids)) != len(member_ids):
            raise Invalid("split group candidate inventory is inconsistent")
        for member in group["members"]:
            cid = member["candidate_id"]
            if cid not in documents or cid in seen_candidates:
                raise Invalid("split candidate is unknown or assigned to multiple groups")
            seen_candidates.add(cid)
            doc = documents[cid]
            section_ids_for_candidate = [section["id"] for section in doc["sections"]]
            eligible = doc["eligible"]
            if (member.get("section_ids") != section_ids_for_candidate or member.get("eligible") is not eligible or
                    member.get("source_domain") != doc["identity"]["source_domain"] or
                    member.get("repository") != doc["identity"]["repository"] or member.get("revision") != doc["identity"]["revision"] or
                    member.get("source_path") != doc["identity"]["source_path"] or
                    member.get("source_file_sha256") != doc["identity"]["source_file_sha256"] or
                    member.get("extraction_status") != doc["extraction_status"] or
                    member.get("normalized_text_sha256") != doc["normalized_text_sha256"] or
                    member.get("split_group") != group["split_group"] or
                    member.get("split") != (group.get("split") if eligible else None) or
                    (eligible and group.get("split") not in {"train", "valid"})):
                raise Invalid("split member does not match validated source identity, eligibility, or group assignment")
    if seen_candidates != set(documents):
        raise Invalid("split groups omit or add source candidates")
    return extraction, split, rows, memberships, tokenizer, tokenizer_identity


def _verify(root, output, config, effective, tokenizer_identity):
    manifest_path = safe_path(output, "manifest.json")
    manifest = read_json(manifest_path)
    fields(manifest, ["schema_version", "id", "kind", "stage", "status", "config_hash", "implementation_hash", "extraction_manifest_sha256", "split_manifest_sha256", "tokenizer", "chunk_file", "chunk_file_sha256", "chunk_count", "quarantine_file", "quarantine_file_sha256", "quarantined_section_count", "source_section_count", "review_status", "generation_allowed"])
    if manifest["id"] != output.name or manifest["kind"] != "chunks" or manifest["stage"] != "chunks" or manifest["config_hash"] != digest(effective) or manifest["extraction_manifest_sha256"] != config["extraction_manifest_sha256"] or manifest["split_manifest_sha256"] != config["split_manifest_sha256"] or manifest["tokenizer"] != tokenizer_identity or manifest["review_status"] != "PENDING" or manifest["generation_allowed"] is not False:
        raise Invalid("chunk run ID is bound to a different config or upstream identity")
    if manifest["implementation_hash"] != implementation_hash(Path(__file__).resolve().parents[2]):
        raise Invalid("chunk implementation changed since manifest creation")
    chunks_path = _relative_file(root, manifest["chunk_file"], "chunk records")
    raw, chunks = _read_jsonl(chunks_path, MAX_OUTPUT_BYTES)
    if hashlib.sha256(raw).hexdigest() != manifest["chunk_file_sha256"] or len(chunks) != manifest["chunk_count"]:
        raise Invalid("chunk output records do not match manifest")
    for row in chunks:
        if row.get("record_sha256") != digest({key: value for key, value in row.items() if key != "record_sha256"}) or row.get("review_status") != "PENDING" or row.get("generation_allowed") is not False:
            raise Invalid("chunk record hash or state invalid")
    quarantine_path = _relative_file(root, manifest["quarantine_file"], "chunk quarantine records")
    quarantine_raw, quarantine = _read_jsonl(quarantine_path, MAX_OUTPUT_BYTES)
    if hashlib.sha256(quarantine_raw).hexdigest() != manifest["quarantine_file_sha256"] or len(quarantine) != manifest["quarantined_section_count"]:
        raise Invalid("chunk quarantine records do not match manifest")
    return manifest


def prepare(root, config, run_id):
    """Build an immutable token-aware chunk artifact from pending T09 groups."""
    root = Path(root).resolve()
    identifier(run_id)
    effective = dict(config)
    extraction, split, rows, memberships, tokenizer, tokenizer_identity = _inputs(root, config)
    output = safe_path(root, f"artifacts/chunks/{run_id}")
    if output.exists():
        if not output.is_dir() or not safe_path(output, "manifest.json").is_file():
            raise Invalid("uncommitted chunk output already exists")
        manifest = _verify(root, output, config, effective, tokenizer_identity)
        return {"status": manifest["status"], "id": run_id, "manifest": str(output / "manifest.json"), "chunks": manifest["chunk_count"]}, 0
    chunks = []
    quarantines = []
    eligible_sections = 0
    for row in rows:
        membership = memberships[row["id"]]
        if not membership["eligible"] or membership["split"] not in {"train", "valid"}:
            continue
        eligible_sections += 1
        pieces, failure = _chunk_section(tokenizer, row)
        if failure:
            quarantine = {"schema_version": 1, "id": digest({"section_id": row["id"], "config_hash": digest(effective)}),
                          "kind": "chunk_quarantine", "candidate_id": row["candidate_id"], "section_id": row["id"],
                          "source_path": row["source_path"], "reason": failure, "review_status": "PENDING", "generation_allowed": False}
            quarantine["record_sha256"] = digest(quarantine)
            quarantines.append(quarantine)
            continue
        for ordinal, piece in enumerate(pieces):
            passage, source_tokens, task_counts = _measure(tokenizer, row["heading_ancestry"], piece["text"])
            if source_tokens > SOURCE_LIMIT or any(not task["within_bounds"] for task in task_counts):
                quarantine = {"schema_version": 1, "id": digest({"section_id": row["id"], "config_hash": digest(effective)}),
                              "kind": "chunk_quarantine", "candidate_id": row["candidate_id"], "section_id": row["id"],
                              "source_path": row["source_path"], "reason": "token_budget_exceeded", "review_status": "PENDING", "generation_allowed": False}
                quarantine["record_sha256"] = digest(quarantine)
                quarantines.append(quarantine)
                chunks = [chunk for chunk in chunks if chunk["section_id"] != row["id"]]
                break
            dependencies = row["include_dependencies"] if row["include_dependencies"] else []
            chunk = {"schema_version": 1,
                     "id": digest({"config_hash": digest(effective), "section_id": row["id"], "chunk_ordinal": ordinal,
                                   "tokenizer_sha256": tokenizer_identity["tokenizer_sha256"], "passage": passage}),
                     "kind": "chunk", "candidate_id": row["candidate_id"], "section_id": row["id"],
                     "section_ordinal": row["section_ordinal"], "chunk_ordinal": ordinal,
                     "source_domain": row["source_domain"], "repository": row["repository"], "revision": row["revision"],
                     "source_path": row["source_path"], "source_file_sha256": row["source_file_sha256"],
                     "split_group": membership["split_group"], "split": membership["split"],
                     "heading_ancestry": row["heading_ancestry"], "passage": passage,
                     "passage_sha256": hashlib.sha256(passage.encode("utf-8")).hexdigest(),
                     "source_text": piece["root_source_text"], "source_span": piece["source_span"],
                     "source_kind": piece["source_kind"], "source_dependencies": dependencies,
                     "tokenizer_sha256": tokenizer_identity["tokenizer_sha256"], "source_token_count": source_tokens,
                     "task_prompt_counts": task_counts, "generation_reserve": GENERATION_RESERVE,
                     "review_status": "PENDING", "generation_allowed": False}
            chunk["record_sha256"] = digest(chunk)
            chunks.append(chunk)
    chunks.sort(key=lambda row: (row["source_domain"], row["source_path"], row["section_ordinal"], row["chunk_ordinal"]))
    raw = b"".join(canonical(row) + b"\n" for row in chunks)
    if len(raw) > MAX_OUTPUT_BYTES:
        raise Invalid("chunk output exceeds safety limit; no truncation performed")
    chunk_file = f"artifacts/chunks/{run_id}/chunks.jsonl"
    quarantine_raw = b"".join(canonical(row) + b"\n" for row in quarantines)
    quarantine_file = f"artifacts/chunks/{run_id}/quarantine.jsonl"
    manifest = {"schema_version": 1, "id": run_id, "kind": "chunks", "stage": "chunks",
                "status": "QUARANTINED" if quarantines else "PASSED", "config_hash": digest(effective),
                "implementation_hash": implementation_hash(Path(__file__).resolve().parents[2]),
                "extraction_manifest_sha256": config["extraction_manifest_sha256"],
                "split_manifest_sha256": config["split_manifest_sha256"], "tokenizer": tokenizer_identity,
                "chunk_file": chunk_file, "chunk_file_sha256": hashlib.sha256(raw).hexdigest(),
                "chunk_count": len(chunks), "source_section_count": eligible_sections,
                "quarantine_file": quarantine_file, "quarantine_file_sha256": hashlib.sha256(quarantine_raw).hexdigest(),
                "quarantined_section_count": len(quarantines), "review_status": "PENDING", "generation_allowed": False}
    atomic_bytes(safe_path(root, chunk_file), raw)
    atomic_bytes(safe_path(root, quarantine_file), quarantine_raw)
    manifest_path = safe_path(root, f"artifacts/chunks/{run_id}/manifest.json")
    atomic_json(manifest_path, manifest)
    manifest = _verify(root, safe_path(root, f"artifacts/chunks/{run_id}"), config, effective, tokenizer_identity)
    return {"status": manifest["status"], "id": run_id, "manifest": str(manifest_path), "chunks": manifest["chunk_count"]}, 0
