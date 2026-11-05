"""Lossless, hash-bound Markdown extraction from T07 candidate artifacts.

The producer preserves source text verbatim and annotates structure. It does
not approve content for training; every emitted row remains pending and
generation-forbidden.
"""
import hashlib
import re
from pathlib import Path, PurePosixPath

from .artifacts import Invalid, atomic_bytes, atomic_json, canonical, digest, fields, file_hash, identifier, implementation_hash, read_json, safe_path, loads


HASH = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA1 = re.compile(r"^[0-9a-f]{40}$")
MAX_CANDIDATE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 128 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
FENCE_OPEN = re.compile(r"^( {0,3})(`{3,}|~{3,})([^\r\n]*)(?:\r?\n)?$")
ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n)?$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*(?:\r?\n)?$")
INCLUDE = re.compile(r"^ {0,3}!include[ \t]+([^\s]+)[ \t]*(?:\r?\n)?$")
FRONTMATTER_OPEN = re.compile(r"^---[ \t]*(?:\r?\n)?$")
FRONTMATTER_CLOSE = re.compile(r"^(?:---|\.\.\.)[ \t]*(?:\r?\n)?$")


def _hash(value, label):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise Invalid(f"invalid SHA256 in {label}")


def _file(root, relative, label):
    if not isinstance(relative, str) or not relative:
        raise Invalid(f"{label} must be a root-relative path")
    path = safe_path(root, relative)
    if not path.is_file():
        raise Invalid(f"{label} missing or not a regular file: {relative}")
    return path


def _validate_input(root, config):
    fields(config, ["schema_version", "stage", "eligibility_manifest", "eligibility_manifest_sha256"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["stage"] != "extraction":
        raise Invalid("unsupported extraction config")
    _hash(config["eligibility_manifest_sha256"], "eligibility_manifest_sha256")
    manifest_path = _file(root, config["eligibility_manifest"], "eligibility_manifest")
    if file_hash(manifest_path) != config["eligibility_manifest_sha256"]:
        raise Invalid("eligibility manifest hash mismatch")
    manifest = read_json(manifest_path)
    fields(manifest, ["schema_version", "id", "kind", "status", "stage", "snapshot_id", "snapshot_manifest_sha256",
                      "config_sha256", "effective_config", "implementation_sha256", "candidate_file",
                      "candidate_file_sha256", "record_count", "counts", "license_evidence_index",
                      "review_status", "generation_allowed"])
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or
            manifest["stage"] != "eligibility" or manifest["status"] != "PASSED" or
            manifest["kind"] not in {"official", "fixture"} or manifest["review_status"] != "PENDING" or
            manifest["generation_allowed"] is not False):
        raise Invalid("eligibility artifact is not a passing, pending T07 result")
    identifier(manifest["id"])
    _hash(manifest["snapshot_manifest_sha256"], "snapshot_manifest_sha256")
    if not isinstance(manifest["effective_config"], dict) or manifest["config_sha256"] != digest(manifest["effective_config"]):
        raise Invalid("eligibility effective config hash mismatch")
    source_config = manifest["effective_config"]
    fields(source_config, ["schema_version", "stage", "snapshot_manifest", "snapshot_sha256", "domains"])
    if source_config["stage"] != "eligibility" or source_config["snapshot_sha256"] != manifest["snapshot_manifest_sha256"]:
        raise Invalid("eligibility config does not bind its snapshot")
    source_manifest_path = _file(root, source_config["snapshot_manifest"], "snapshot manifest")
    if file_hash(source_manifest_path) != manifest["snapshot_manifest_sha256"]:
        raise Invalid("source snapshot manifest hash mismatch")
    source_manifest = read_json(source_manifest_path)
    fields(source_manifest, ["schema_version", "id", "kind", "config_hash", "effective_config", "files"])
    if (source_manifest["id"] != manifest["snapshot_id"] or source_manifest["kind"] != manifest["kind"] or
            source_manifest["config_hash"] != digest(source_manifest["effective_config"]) or
            not isinstance(source_manifest["files"], list)):
        raise Invalid("source snapshot identity or config hash mismatch")
    if not isinstance(source_manifest["effective_config"], dict):
        raise Invalid("source snapshot effective config must be an object")
    fields(source_manifest["effective_config"], ["schema_version", "kind", "sources"])
    sources = source_manifest["effective_config"]["sources"]
    if not isinstance(sources, list):
        raise Invalid("source snapshot sources must be a list")
    source_domains = {}
    for source in sources:
        fields(source, ["domain", "repository", "revision", "prefixes"])
        if source["domain"] in source_domains:
            raise Invalid("duplicate source domain")
        source_domains[source["domain"]] = source
    configured_domains = {}
    if not isinstance(source_config["domains"], list):
        raise Invalid("eligibility config domains must be a list")
    for entry in source_config["domains"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("domain"), str) or entry["domain"] in configured_domains:
            raise Invalid("invalid or duplicate eligibility domain")
        configured_domains[entry["domain"]] = entry
    if not configured_domains or set(configured_domains) != set(source_domains):
        raise Invalid("eligibility and source snapshot domain coverage differs")

    candidate_path = _file(root, manifest["candidate_file"], "candidate file")
    if candidate_path.stat().st_size > MAX_CANDIDATE_BYTES:
        raise Invalid("candidate file exceeds extraction safety limit; no truncation performed")
    candidate_raw = candidate_path.read_bytes()
    if hashlib.sha256(candidate_raw).hexdigest() != manifest["candidate_file_sha256"]:
        raise Invalid("candidate file hash mismatch")
    rows = []
    seen_ids = set()
    seen_sources = set()
    candidate_text = candidate_raw.decode("utf-8")
    candidate_lines = candidate_text.split("\n")
    if candidate_lines and candidate_lines[-1] == "":
        candidate_lines.pop()
    for number, line in enumerate(candidate_lines, 1):
        if not line:
            raise Invalid(f"blank candidate row at line {number}")
        row = loads(line)
        if not isinstance(row, dict):
            raise Invalid(f"candidate row {number} is not an object")
        fields(row, ["schema_version", "snapshot_id", "snapshot_manifest_sha256", "source_domain", "repository", "revision",
                     "source_path", "artifact_path", "source_file_sha256", "license_evidence", "candidate_status", "reason_codes",
                     "content_flags", "planned_profile_id", "version_compatibility", "review_status", "generation_allowed", "id", "record_sha256"])
        if row["record_sha256"] != digest({key: value for key, value in row.items() if key != "record_sha256"}):
            raise Invalid(f"candidate row hash mismatch at line {number}")
        if row["id"] in seen_ids:
            raise Invalid("duplicate candidate id")
        seen_ids.add(row["id"])
        pair = (row["source_domain"], row["source_path"])
        if pair in seen_sources:
            raise Invalid("duplicate candidate source domain/path")
        seen_sources.add(pair)
        if (row["snapshot_id"] != manifest["snapshot_id"] or row["snapshot_manifest_sha256"] != manifest["snapshot_manifest_sha256"] or
                row["review_status"] != "PENDING" or row["generation_allowed"] is not False or
                row["candidate_status"] not in {"candidate_include", "candidate_exclude", "quarantine"}):
            raise Invalid("candidate row has invalid lineage or readiness state")
        _hash(row["source_file_sha256"], "source_file_sha256")
        rows.append(row)
    if len(rows) != manifest["record_count"] or not rows:
        raise Invalid("candidate record count mismatch or empty candidate file")
    expected_counts = {state: sum(row["candidate_status"] == state for row in rows) for state in ("candidate_include", "candidate_exclude", "quarantine")}
    if manifest["counts"] != expected_counts:
        raise Invalid("candidate status counts mismatch")

    files = {}
    for item in source_manifest["files"]:
        if not isinstance(item, dict):
            raise Invalid("source snapshot file record must be an object")
        fields(item, ["domain", "path", "artifact", "revision", "repository", "hash", "git_blob", "bytes", "license_file"])
        key = (item["domain"], item["path"])
        if key in files:
            raise Invalid("duplicate snapshot domain/path")
        files[key] = item
    total_source_bytes = 0
    for row in rows:
        key = (row["source_domain"], row["source_path"])
        item = files.get(key)
        if item is None:
            raise Invalid("candidate references a missing snapshot source")
        source = source_domains.get(row["source_domain"])
        if (source is None or row["revision"] != source["revision"] or row["repository"] != source["repository"] or
                item["revision"] != row["revision"] or item["repository"] != row["repository"] or
                item["artifact"] != row["artifact_path"] or item["hash"] != row["source_file_sha256"] or item["license_file"]):
            raise Invalid("candidate provenance does not match pinned snapshot")
        artifact = _file(source_manifest_path.parent, item["artifact"], "snapshot source file")
        if type(item["bytes"]) is not int or item["bytes"] < 0 or item["bytes"] > MAX_SOURCE_FILE_BYTES:
            raise Invalid("source file exceeds extraction safety limit; no truncation performed")
        total_source_bytes += item["bytes"]
        if total_source_bytes > MAX_TOTAL_SOURCE_BYTES:
            raise Invalid("candidate corpus exceeds extraction safety limit; no truncation performed")
        if artifact.stat().st_size != item["bytes"] or file_hash(artifact) != item["hash"]:
            raise Invalid("snapshot source bytes do not match manifest")
        raw = artifact.read_bytes()
        expected_blob = hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()
        if not isinstance(item["git_blob"], str) or not GIT_SHA1.fullmatch(item["git_blob"]) or item["git_blob"] != expected_blob:
            raise Invalid("snapshot source Git blob identity mismatch")
        row["_path"] = artifact
    return manifest, source_manifest, rows


def _text(path):
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Invalid(f"source is not UTF-8: {path}") from exc


def _lines(text):
    # Markdown is line-oriented on LF. Unicode line/paragraph separators are
    # legal content and must remain inside their original physical line.
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _fence_events(lines, skip=()):
    """Return fence ranges and fail on an unclosed fence; line numbers 1-based."""
    events = []
    opener = None
    for i, line in enumerate(lines):
        if i in skip and opener is None:
            continue
        if opener is None:
            match = FENCE_OPEN.match(line)
            if match:
                opener = (i, match.group(2)[0], len(match.group(2)), match.group(3).strip())
        else:
            indent, marker, length, info = opener
            close = re.match(r"^ {0,3}" + re.escape(marker) + r"{" + str(length) + r",}[ \t]*(?:\r?\n)?$", line)
            if close:
                events.append({"start": indent, "end": i + 1, "marker": marker * length, "info": info})
                opener = None
    if opener is not None:
        return events, "malformed_fence"
    return events, None


def _frontmatter(lines):
    if not lines or not FRONTMATTER_OPEN.fullmatch(lines[0]):
        return None, None
    for index in range(1, len(lines)):
        if FRONTMATTER_CLOSE.fullmatch(lines[index]):
            return (0, index + 1), None
    return None, "malformed_frontmatter"


def _sections(text):
    lines = _lines(text)
    front, error = _frontmatter(lines)
    if error:
        return [], [], [], error
    fences, error = _fence_events(lines, set(range(*front)) if front else ())
    if error:
        return [], [], [], error
    fenced_lines = set()
    for fence in fences:
        fenced_lines.update(range(fence["start"], fence["end"]))
    front_lines = set(range(*front)) if front else set()
    # Keep an HTML div container whole. The source set uses div wrappers for
    # admonitions and language-specific examples; a heading inside one must
    # not split away its closing tag or wrapper context.
    wrapper_lines = set()
    div_depth = 0
    admonition_depth = 0
    for i, line in enumerate(lines):
        if i in fenced_lines or i in front_lines:
            continue
        opens = len(re.findall(r"<div\b[^>]*>", line, re.I))
        closes = len(re.findall(r"</div\s*>", line, re.I))
        if div_depth or opens or admonition_depth or re.match(r"^ {0,3}:::", line):
            wrapper_lines.add(i)
        div_depth += opens - closes
        if div_depth < 0:
            return [], [], [], "unbalanced_html_wrapper"
        if re.match(r"^ {0,3}:::[^:]*\S", line):
            admonition_depth += 1
        elif re.match(r"^ {0,3}:::[ \t]*(?:\r?\n)?$", line) and admonition_depth:
            admonition_depth -= 1
    if div_depth:
        return [], [], [], "unbalanced_html_wrapper"
    if admonition_depth:
        return [], [], [], "unclosed_admonition"
    headings = []
    index = 0
    while index < len(lines):
        if index in fenced_lines or index in front_lines or index in wrapper_lines:
            index += 1
            continue
        match = ATX.match(lines[index])
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip(), "atx"))
            index += 1
            continue
        if index + 1 < len(lines) and index not in fenced_lines and index + 1 not in fenced_lines and index not in front_lines and index not in wrapper_lines and index + 1 not in wrapper_lines:
            under = SETEXT.match(lines[index + 1])
            if under and lines[index].strip() and not ATX.match(lines[index]):
                headings.append((index, 1 if under.group(1)[0] == "=" else 2, lines[index].strip(), "setext"))
                index += 2
                continue
        index += 1
    starts = [row[0] for row in headings]
    boundaries = [0] + starts[1:] if starts else [0]
    sections = []
    ancestry = []
    stack = []
    for n, (line_index, level, title, style) in enumerate(headings):
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        item = {"level": level, "title": title, "style": style, "line": line_index + 1}
        stack.append(item)
        ancestry.append([dict(x) for x in stack])
    # Keep any pre-heading content in its own section; it may hold frontmatter.
    if starts and starts[0] > 0:
        sections.append({"start": 0, "end": starts[0], "heading": None, "ancestry": []})
    for n, heading in enumerate(headings):
        end = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        sections.append({"start": heading[0], "end": end,
                         "heading": {"level": heading[1], "title": heading[2], "style": heading[3], "line": heading[0] + 1},
                         "ancestry": ancestry[n]})
    if not sections:
        sections = [{"start": 0, "end": len(lines), "heading": None, "ancestry": []}]
    # If frontmatter is present, annotate the section that owns it, without
    # changing any bytes or treating YAML separators as Markdown headings.
    for section in sections:
        section["text"] = "".join(lines[section["start"]:section["end"]])
        section["source_span"] = {"start_line": section["start"] + 1, "end_line": section["end"],
                                  "start_byte": len("".join(lines[:section["start"]]).encode("utf-8")),
                                  "end_byte": len("".join(lines[:section["end"]]).encode("utf-8"))}
    refs = []
    for i, line in enumerate(lines):
        definition = re.match(r"^ {0,3}\[(?!\^)([^\]]+)\]:[ \t]*(\S+)", line)
        footnote = re.match(r"^ {0,3}\[\^([^\]]+)\]:", line)
        if definition:
            refs.append({"kind": "reference_definition", "label": definition.group(1), "line": i + 1})
        elif footnote:
            refs.append({"kind": "footnote_definition", "label": footnote.group(1), "line": i + 1})
    metadata = {"frontmatter_span": {"start_line": 1, "end_line": front[1]} if front else None,
                "fences": [{"start_line": f["start"] + 1, "end_line": f["end"], "marker": f["marker"], "info_string": f["info"]} for f in fences],
                "document_reference_context": {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "definitions": refs}}
    return sections, fences, metadata, None


def _include_target(current_path, target):
    if not isinstance(target, str) or not target or target.startswith(("/", "\\")) or "://" in target:
        raise Invalid("include path must be relative to its source document")
    parts = list(PurePosixPath(current_path).parent.parts)
    for part in target.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise Invalid("include traversal escapes source domain")
            parts.pop()
        else:
            parts.append(part)
    result = PurePosixPath(*parts).as_posix()
    if result.startswith("../") or result == "..":
        raise Invalid("include traversal escapes source domain")
    return result


def _include_expansion(row, row_by_path, text, chain=(), state=None, base_line=1):
    state = state if state is not None else {"documents": 0, "bytes": 0}
    if len(chain) >= 12:
        raise Invalid("include depth limit exceeded")
    state["bytes"] += len(text.encode("utf-8"))
    if state["documents"] > 64 or state["bytes"] > 1_000_000:
        raise Invalid("include expansion resource limit exceeded")
    dependencies = []
    output = []
    lines = _lines(text)
    front, front_error = _frontmatter(lines)
    if front_error:
        raise Invalid("included document has malformed frontmatter")
    front_lines = set(range(*front)) if front else set()
    fences, fence_error = _fence_events(lines, front_lines)
    if fence_error:
        raise Invalid("included document has malformed fence")
    fenced = set()
    for fence in fences:
        fenced.update(range(fence["start"], fence["end"]))
    for index, line in enumerate(lines):
        number = index + 1
        match = None if index in fenced or index in front_lines else INCLUDE.match(line)
        if not match:
            output.append(line)
            continue
        target = _include_target(row["source_path"], match.group(1))
        key = (row["source_domain"], target)
        if key in chain or key == (row["source_domain"], row["source_path"]):
            raise Invalid("include cycle")
        dependency_row = row_by_path.get(key)
        if dependency_row is None or dependency_row["candidate_status"] != "candidate_include":
            raise Invalid(f"include target is missing or not a candidate: {target}")
        state["documents"] += 1
        if state["documents"] > 64:
            raise Invalid("include expansion document-count limit exceeded")
        included_text = _text(dependency_row["_path"])
        _, _, _, parse_error = _sections(included_text)
        if parse_error:
            raise Invalid("included document has malformed structure")
        nested, nested_deps = _include_expansion(dependency_row, row_by_path, included_text, chain + ((row["source_domain"], row["source_path"]),), state)
        dependencies.append({"candidate_id": dependency_row["id"], "source_path": target,
                             "included_from_path": row["source_path"],
                             "source_file_sha256": dependency_row["source_file_sha256"], "include_line": base_line + number - 1})
        dependencies.extend(nested_deps)
        output.append(nested)
    return "".join(output), dependencies


def _syntax_metadata(text, fences):
    lines = _lines(text)
    groups = []
    for i in range(len(fences) - 1):
        left, right = fences[i], fences[i + 1]
        between = "".join(lines[left["end"]:right["start"]])
        if between.strip() == "":
            lang1 = left["info"].split()[0].lower() if left["info"] else ""
            lang2 = right["info"].split()[0].lower() if right["info"] else ""
            if {lang1, lang2} == {"ocaml", "reasonml"}:
                groups.append({"fence_lines": [left["start"] + 1, right["start"] + 1], "languages": [lang1, lang2], "kind": "paired_language_examples"})
    associations = []
    for i, line in enumerate(lines):
        if "<!--#prelude#" in line or "$MDX skip" in line:
            kind = "melange_prelude" if "<!--#prelude#" in line else "mdx_skip"
            following = next((f for f in fences if f["start"] >= i), None)
            associations.append({"kind": kind, "line": i + 1, "associated_fence_line": following["start"] + 1 if following else None})
    wrappers = []
    for i, line in enumerate(lines):
        match = re.search(r"<div\b[^>]*class=[\"']([^\"']+)[\"'][^>]*>", line, re.I)
        if match:
            classes = match.group(1).split()
            wrappers.append({"line": i + 1, "classes": classes, "kind": "html_wrapper"})
    return {"paired_language_examples": groups, "example_directives": associations, "html_wrappers": wrappers}


def prepare(root, config, run_id):
    """Extract candidate sections; return `(result, exitcode)`."""
    root = Path(root).resolve()
    identifier(run_id)
    eligibility, source_manifest, rows = _validate_input(root, config)
    by_path = {(row["source_domain"], row["source_path"]): row for row in rows}
    extracted = []
    status_counts = {"extracted": 0, "candidate_exclude": 0, "candidate_quarantine": 0, "quarantined": 0}
    for row in sorted(rows, key=lambda item: (item["source_domain"], item["source_path"])):
        text = _text(row["_path"])
        if row["candidate_status"] != "candidate_include":
            status = "candidate_exclude" if row["candidate_status"] == "candidate_exclude" else "candidate_quarantine"
            status_counts[status] += 1
            sections = [{"text": text, "heading": None, "ancestry": [], "source_span": {"start_line": 1, "end_line": len(_lines(text)), "start_byte": 0, "end_byte": len(text.encode("utf-8"))}}]
            fences, syntax, reason_codes = [], {}, list(row["reason_codes"])
            section_expansions = [section["text"] for section in sections]
            section_dependencies = [[] for _ in sections]
        else:
            sections, fences, syntax_base, parse_error = _sections(text)
            reason_codes = []
            include_state = {"documents": 0, "bytes": 0}
            dependencies = []
            if parse_error:
                status = "quarantined"
                reason_codes = [parse_error]
                sections = [{"text": text, "heading": None, "ancestry": [], "source_span": {"start_line": 1, "end_line": len(_lines(text)), "start_byte": 0, "end_byte": len(text.encode("utf-8"))}}]
                syntax = {"frontmatter_span": None, "fences": []}
                section_expansions = [section["text"] for section in sections]
                section_dependencies = [[] for _ in sections]
            else:
                try:
                    section_expansions = []
                    section_dependencies = []
                    for section in sections:
                        expanded_section, deps = _include_expansion(row, by_path, section["text"], state=include_state,
                                                                     base_line=section["source_span"]["start_line"])
                        section_expansions.append(expanded_section)
                        section_dependencies.append(deps)
                    status = "extracted"
                except Invalid as exc:
                    status = "quarantined"
                    reason_codes = ["include_resolution_failed"]
                    section_expansions = [section["text"] for section in sections]
                    section_dependencies = [[] for _ in sections]
                if re.search(r"<\|[^|\r\n]{1,80}\|>", text):
                    status = "quarantined"
                    reason_codes = sorted(set(reason_codes + ["control_token_collision"]))
                    section_expansions = [section["text"] for section in sections]
                    section_dependencies = [[] for _ in sections]
                syntax = {**syntax_base, **_syntax_metadata(text, fences)}
            status_counts[status] += 1
        for ordinal, section in enumerate(sections):
            payload = {
                "schema_version": 1,
                "id": digest({"eligibility_manifest_sha256": config["eligibility_manifest_sha256"], "candidate_id": row["id"], "section": ordinal}),
                "kind": "extraction",
                "candidate_id": row["id"],
                "candidate_status": row["candidate_status"],
                "source_domain": row["source_domain"],
                "repository": row["repository"],
                "revision": row["revision"],
                "source_path": row["source_path"],
                "artifact_path": row["artifact_path"],
                "source_file_sha256": row["source_file_sha256"],
                "section_ordinal": ordinal,
                "heading": section["heading"],
                "heading_ancestry": section["ancestry"],
                "source_span": section["source_span"],
                "source_text": section["text"],
                "expanded_text": section_expansions[ordinal],
                "include_dependencies": section_dependencies[ordinal],
                "syntax_metadata": syntax,
                "extraction_status": status,
                "reason_codes": reason_codes,
                "version_compatibility": row["version_compatibility"],
                "review_status": "PENDING",
                "generation_allowed": False,
            }
            payload["record_sha256"] = digest(payload)
            extracted.append(payload)
    extracted.sort(key=lambda item: (item["source_domain"], item["source_path"], item["section_ordinal"]))
    output_bytes = b"".join(canonical(row) + b"\n" for row in extracted)
    if len(output_bytes) > MAX_OUTPUT_BYTES:
        raise Invalid("extraction output exceeds safety limit; no truncation performed")
    outdir = safe_path(root, f"artifacts/extract/{run_id}")
    records_path = outdir / "records.jsonl"
    manifest_path = outdir / "manifest.json"
    result_manifest = {
        "schema_version": 1,
        "id": run_id,
        "kind": "extraction",
        "status": "PASSED" if status_counts["quarantined"] == 0 else "QUARANTINED",
        "stage": "extraction",
        "eligibility_manifest": config["eligibility_manifest"],
        "eligibility_manifest_sha256": config["eligibility_manifest_sha256"],
        "snapshot_id": source_manifest["id"],
        "snapshot_manifest_sha256": eligibility["snapshot_manifest_sha256"],
        "config_sha256": digest(config),
        "effective_config": config,
        "implementation_sha256": implementation_hash(root),
        "record_file": f"artifacts/extract/{run_id}/records.jsonl",
        "record_file_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "record_count": len(extracted),
        "source_candidate_count": len(rows),
        "counts": status_counts,
        "review_status": "PENDING",
        "generation_allowed": False,
    }
    atomic_bytes(records_path, output_bytes)
    atomic_json(manifest_path, result_manifest)
    return {**result_manifest, "manifest": str(manifest_path), "records": str(records_path)}, 0
