"""Hash-bound duplicate/family grouping and deterministic pending splits."""
import hashlib
import math
import re
import unicodedata
from pathlib import Path

from .artifacts import Invalid, atomic_bytes, atomic_json, canonical, digest, fields, file_hash, identifier, implementation_hash, loads, read_json, safe_path


HASH = re.compile(r"^[0-9a-f]{64}$")
SPLIT_KINDS = {"translation", "task_family", "variant"}
ALGORITHM = "t09-v1-nfkc-5gram-jaccard-0.90"
MAX_DOCUMENTS = 2000
MAX_RECORD_BYTES = 256 * 1024 * 1024
MAX_INPUT_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ANNOTATION_BYTES = 16 * 1024 * 1024
MAX_ANNOTATIONS = 20_000
MAX_PAIR_COMPARISONS = MAX_DOCUMENTS * (MAX_DOCUMENTS - 1) // 2
MAX_TOTAL_SHINGLES = 2_000_000
NEAR_MIN_TOKENS = 20
NEAR_SHINGLE_SIZE = 5
NEAR_THRESHOLD = 0.90


class InsufficientGroups(Exception):
    pass


def _sha(value, label):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise Invalid(f"invalid SHA256 in {label}")


def _relative_file(root, value, label):
    if not isinstance(value, str) or not value:
        raise Invalid(f"{label} must be a root-relative file path")
    path = safe_path(root, value)
    if not path.is_file():
        raise Invalid(f"{label} missing or not a regular file: {value}")
    return path


def _split_lines(text):
    # Only LF is a Markdown physical line boundary. Keep U+2028/U+2029 as text.
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _normalized(text):
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = _split_lines(text)
    if lines and re.fullmatch(r"---[ \t]*(?:\n)?", lines[0]):
        end = next((i for i, line in enumerate(lines[1:], 1) if re.fullmatch(r"(?:---|\.\.\.)[ \t]*(?:\n)?", line)), None)
        if end is not None:
            lines = lines[end + 1:]
    kept = []
    for line in lines:
        if re.match(r"^ {0,3}#{1,6}[ \t]+", line):
            line = re.sub(r"^ {0,3}#{1,6}[ \t]+", "", line)
        if re.match(r"^ {0,3}(?:`{3,}|~{3,})[^\r\n]*(?:\r?\n)?$", line):
            continue
        kept.append(line)
    return " ".join(unicodedata.normalize("NFKC", "".join(kept)).casefold().split())


def _tokens(normalized):
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", normalized, flags=re.UNICODE)


def _shingles(tokens):
    if len(tokens) < NEAR_SHINGLE_SIZE:
        return set()
    values = set()
    for start in range(len(tokens) - NEAR_SHINGLE_SIZE + 1):
        raw = "\x00".join(tokens[start:start + NEAR_SHINGLE_SIZE]).encode("utf-8")
        values.add(int.from_bytes(hashlib.sha256(raw).digest()[:8], "big"))
    return values


def _read_inputs(root, config):
    fields(config, ["schema_version", "stage", "extraction_manifest", "extraction_manifest_sha256", "annotations_file", "annotations_sha256"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["stage"] != "splits":
        raise Invalid("unsupported split config")
    _sha(config["extraction_manifest_sha256"], "extraction_manifest_sha256")
    _sha(config["annotations_sha256"], "annotations_sha256")
    extraction_path = _relative_file(root, config["extraction_manifest"], "extraction manifest")
    if extraction_path.stat().st_size > MAX_INPUT_MANIFEST_BYTES:
        raise Invalid("extraction manifest exceeds split safety limit")
    if file_hash(extraction_path) != config["extraction_manifest_sha256"]:
        raise Invalid("extraction manifest hash mismatch")
    extraction = read_json(extraction_path)
    fields(extraction, ["schema_version", "id", "kind", "status", "stage", "eligibility_manifest", "eligibility_manifest_sha256",
                        "snapshot_id", "snapshot_manifest_sha256", "config_sha256", "effective_config", "implementation_sha256",
                        "record_file", "record_file_sha256", "record_count", "source_candidate_count", "counts", "review_status", "generation_allowed"])
    if (type(extraction["schema_version"]) is not int or extraction["schema_version"] != 1 or extraction["kind"] != "extraction" or
            extraction["stage"] != "extraction" or extraction["status"] not in {"PASSED", "QUARANTINED"} or
            extraction["review_status"] != "PENDING" or extraction["generation_allowed"] is not False or
            extraction["config_sha256"] != digest(extraction["effective_config"])):
        raise Invalid("extraction artifact has invalid identity, provenance, or readiness state")
    if not isinstance(extraction["effective_config"], dict):
        raise Invalid("extraction effective config must be an object")
    # Validate the complete T07 -> pinned snapshot lineage, including source
    # file bytes, and compare the exact upstream candidate set below.
    from .extract import _validate_input as validate_t07_lineage
    t07_manifest, _source_manifest, t07_candidates = validate_t07_lineage(root, extraction["effective_config"])
    if (extraction["snapshot_id"] != t07_manifest["snapshot_id"] or
            extraction["snapshot_manifest_sha256"] != t07_manifest["snapshot_manifest_sha256"]):
        raise Invalid("extraction identity does not match its T07 eligibility lineage")
    candidates_by_id = {row["id"]: row for row in t07_candidates}
    _sha(extraction["snapshot_manifest_sha256"], "snapshot_manifest_sha256")
    _sha(extraction["record_file_sha256"], "record_file_sha256")
    record_path = _relative_file(root, extraction["record_file"], "extraction record file")
    if record_path.stat().st_size > MAX_RECORD_BYTES:
        raise Invalid("extraction record file exceeds split safety limit")
    record_raw = record_path.read_bytes()
    if hashlib.sha256(record_raw).hexdigest() != extraction["record_file_sha256"]:
        raise Invalid("extraction record file hash mismatch")
    annotation_path = _relative_file(root, config["annotations_file"], "link annotation file")
    if annotation_path.stat().st_size > MAX_ANNOTATION_BYTES:
        raise Invalid("link annotation file exceeds split safety limit")
    if file_hash(annotation_path) != config["annotations_sha256"]:
        raise Invalid("link annotation hash mismatch")
    annotations = read_json(annotation_path)
    fields(annotations, ["schema_version", "links"])
    if (type(annotations["schema_version"]) is not int or annotations["schema_version"] != 1 or
            not isinstance(annotations["links"], list) or len(annotations["links"]) > MAX_ANNOTATIONS):
        raise Invalid("unsupported link annotation file")
    rows = []
    seen_row_ids = set()
    decoded = record_raw.decode("utf-8")
    physical_lines = decoded.split("\n")
    if physical_lines and physical_lines[-1] == "":
        physical_lines.pop()
    for number, line in enumerate(physical_lines, 1):
        if not line:
            raise Invalid(f"blank extraction JSONL row at line {number}")
        row = loads(line)
        if not isinstance(row, dict):
            raise Invalid(f"extraction row {number} must be an object")
        fields(row, ["schema_version", "id", "kind", "candidate_id", "candidate_status", "source_domain", "repository", "revision",
                     "source_path", "artifact_path", "source_file_sha256", "section_ordinal", "heading", "heading_ancestry", "source_span",
                     "source_text", "expanded_text", "include_dependencies", "syntax_metadata", "extraction_status", "reason_codes",
                     "version_compatibility", "review_status", "generation_allowed", "record_sha256"])
        if row["record_sha256"] != digest({key: value for key, value in row.items() if key != "record_sha256"}):
            raise Invalid(f"extraction row hash mismatch at line {number}")
        if row["id"] in seen_row_ids:
            raise Invalid("duplicate extraction record id")
        seen_row_ids.add(row["id"])
        if (row["kind"] != "extraction" or row["review_status"] != "PENDING" or row["generation_allowed"] is not False or
                row["candidate_status"] not in {"candidate_include", "candidate_exclude", "quarantine"} or
                row["extraction_status"] not in {"extracted", "quarantined", "candidate_exclude", "candidate_quarantine"}):
            raise Invalid("extraction row has unsupported state")
        if not isinstance(row["source_text"], str) or not isinstance(row["expanded_text"], str):
            raise Invalid("extraction source and expanded text must be strings")
        _sha(row["source_file_sha256"], "source_file_sha256")
        rows.append(row)
    if len(rows) != extraction["record_count"] or not rows:
        raise Invalid("extraction record count mismatch or empty extraction")
    seen_candidates = {row["candidate_id"] for row in rows}
    if seen_candidates != set(candidates_by_id):
        raise Invalid("extraction candidate coverage does not match T07 eligibility rows")
    for row in rows:
        candidate = candidates_by_id[row["candidate_id"]]
        if (row["source_domain"] != candidate["source_domain"] or row["repository"] != candidate["repository"] or
                row["revision"] != candidate["revision"] or row["source_path"] != candidate["source_path"] or
                row["artifact_path"] != candidate["artifact_path"] or row["source_file_sha256"] != candidate["source_file_sha256"] or
                row["candidate_status"] != candidate["candidate_status"]):
            raise Invalid("extraction candidate provenance differs from T07 eligibility record")
    return extraction, rows, annotations


def _documents(extraction, rows):
    if len(rows) > 200_000:
        raise Invalid("extraction section count exceeds split safety limit")
    docs = {}
    for row in rows:
        cid = row["candidate_id"]
        if not isinstance(cid, str) or not cid:
            raise Invalid("candidate_id must be nonempty")
        doc = docs.setdefault(cid, {"candidate_id": cid, "sections": [], "identity": None})
        identity = {key: row[key] for key in ("candidate_status", "source_domain", "repository", "revision", "source_path", "artifact_path", "source_file_sha256")}
        if doc["identity"] is None:
            doc["identity"] = identity
        elif doc["identity"] != identity:
            raise Invalid(f"candidate identity changes between sections: {cid}")
        doc["sections"].append(row)
    if len(docs) != extraction["source_candidate_count"] or len(docs) > MAX_DOCUMENTS:
        raise Invalid("source candidate coverage mismatch or document-count safety limit exceeded")
    for cid, doc in docs.items():
        sections = sorted(doc["sections"], key=lambda item: item["section_ordinal"])
        if not sections or [row["section_ordinal"] for row in sections] != list(range(len(sections))):
            raise Invalid(f"missing, duplicate, or unordered section ordinals for {cid}")
        position = 0
        source = []
        for section in sections:
            span = section["source_span"]
            if not isinstance(span, dict):
                raise Invalid("source span must be an object")
            fields(span, ["start_line", "end_line", "start_byte", "end_byte"])
            raw = section["source_text"].encode("utf-8")
            if type(span["start_byte"]) is not int or type(span["end_byte"]) is not int or span["start_byte"] != position or span["end_byte"] - span["start_byte"] != len(raw):
                raise Invalid(f"section source byte spans are incomplete or overlapping for {cid}")
            position = span["end_byte"]
            source.append(section["source_text"])
        full_text = "".join(source)
        if hashlib.sha256(full_text.encode("utf-8")).hexdigest() != doc["identity"]["source_file_sha256"]:
            raise Invalid(f"section text does not reconstruct the pinned source hash for {cid}")
        doc["sections"] = sections
        doc["source_text"] = full_text
        normalized = _normalized(full_text)
        doc["normalized_text_sha256"] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        doc["tokens"] = _tokens(normalized)
        doc["status"] = "eligible" if (doc["identity"]["candidate_status"] == "candidate_include" and all(s["extraction_status"] == "extracted" for s in sections)) else "unassigned"
        doc["eligible"] = doc["status"] == "eligible"
        statuses = sorted({section["extraction_status"] for section in sections})
        doc["extraction_status"] = statuses[0] if len(statuses) == 1 else "mixed"
        doc["split_group"] = None
        doc["split"] = None
    return docs


class _UnionFind:
    def __init__(self, values):
        self.parent = {value: value for value in values}

    def find(self, value):
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left, right):
        a, b = self.find(left), self.find(right)
        if a == b:
            return False
        low, high = sorted((a, b))
        self.parent[high] = low
        return True


def _group_docs(docs, annotations):
    union = _UnionFind(docs)
    relations = {}
    counts = {key: 0 for key in ("include", "exact", "near_duplicate", "translation", "task_family", "variant")}

    def connect(left, right, kind):
        if left == right:
            return
        union.union(left, right)
        relations.setdefault((min(left, right), max(left, right)), set()).add(kind)
        counts[kind] += 1

    for cid, doc in docs.items():
        for row in doc["sections"]:
            dependencies = row["include_dependencies"]
            if not isinstance(dependencies, list):
                raise Invalid("include_dependencies must be a list")
            for dependency in dependencies:
                if not isinstance(dependency, dict):
                    raise Invalid("include dependency must be an object")
                fields(dependency, ["candidate_id", "source_path", "source_file_sha256", "include_line"], ["included_from_path"])
                target = dependency["candidate_id"]
                if target not in docs:
                    raise Invalid(f"unknown include dependency candidate: {target}")
                target_doc = docs[target]
                target_identity = target_doc["identity"]
                owner_path = dependency.get("included_from_path", doc["identity"]["source_path"])
                owner_docs = [owner for owner in docs.values() if owner["identity"]["source_domain"] == doc["identity"]["source_domain"] and
                              owner["identity"]["source_path"] == owner_path]
                if (dependency["source_path"] != target_identity["source_path"] or dependency["source_file_sha256"] != target_identity["source_file_sha256"] or
                        not owner_docs):
                    raise Invalid("include dependency identity conflicts with extraction records")
                owner_has_edge = any(dep.get("candidate_id") == target for section in owner_docs[0]["sections"]
                                     for dep in section["include_dependencies"] if isinstance(dep, dict))
                if not owner_has_edge:
                    raise Invalid("transitive include dependency has no matching owner edge")
                connect(cid, target, "include")
    exact = {}
    for cid, doc in docs.items():
        exact.setdefault(doc["normalized_text_sha256"], []).append(cid)
    for members in exact.values():
        members.sort()
        for member in members[1:]:
            connect(members[0], member, "exact")

    shingle_sets = {}
    total_shingles = 0
    for cid in sorted(docs):
        tokens = docs[cid]["tokens"]
        if len(tokens) >= NEAR_MIN_TOKENS:
            shingle_sets[cid] = _shingles(tokens)
            total_shingles += len(shingle_sets[cid])
            if total_shingles > MAX_TOTAL_SHINGLES:
                raise Invalid("near-duplicate shingle inventory exceeds safety limit")
    ids = sorted(shingle_sets)
    comparisons = 0
    for index, left in enumerate(ids):
        left_set = shingle_sets[left]
        for right in ids[index + 1:]:
            comparisons += 1
            if comparisons > MAX_PAIR_COMPARISONS:
                raise Invalid("near-duplicate comparison limit exceeded")
            right_set = shingle_sets[right]
            union_size = len(left_set | right_set)
            if not union_size:
                continue
            similarity = len(left_set & right_set) / union_size
            if similarity >= NEAR_THRESHOLD:
                connect(left, right, "near_duplicate")

    links = annotations["links"]
    seen_link_ids = set()
    for link in links:
        fields(link, ["id", "kind", "source_ids"])
        identifier(link["id"])
        if link["id"] in seen_link_ids:
            raise Invalid("duplicate link annotation id")
        seen_link_ids.add(link["id"])
        kind = link["kind"]
        if kind not in SPLIT_KINDS:
            raise Invalid("unknown split link annotation kind")
        source_ids = link["source_ids"]
        if not isinstance(source_ids, list) or len(source_ids) < 2 or any(not isinstance(item, str) or item not in docs for item in source_ids):
            raise Invalid(f"annotation {link['id']} references unknown or too few source IDs")
        if len(set(source_ids)) != len(source_ids):
            raise Invalid(f"annotation {link['id']} repeats a source ID")
        for member in sorted(source_ids)[1:]:
            connect(sorted(source_ids)[0], member, kind)
    components = {}
    for cid in docs:
        components.setdefault(union.find(cid), []).append(cid)
    component_relations = {}
    for (left, right), kinds in relations.items():
        root = union.find(left)
        component_relations.setdefault(root, set()).update(kinds)
    link_ids_by_component = {}
    for link in links:
        root = union.find(link["source_ids"][0])
        link_ids_by_component.setdefault(root, []).append(link["id"])
    return components, component_relations, link_ids_by_component, counts


def _assign(components, docs, group_ids):
    eligible_by_domain = {domain: [] for domain in ("esy", "ocaml", "melange", "reason")}
    for root, members in components.items():
        for cid in members:
            doc = docs[cid]
            if doc["eligible"]:
                domain = doc["identity"]["source_domain"]
                if domain not in eligible_by_domain:
                    raise Invalid(f"unknown source domain: {domain}")
                eligible_by_domain[domain].append(root)
    eligible_by_domain = {domain: sorted(set(groups)) for domain, groups in eligible_by_domain.items()}
    too_few = {domain: len(groups) for domain, groups in eligible_by_domain.items() if len(groups) < 2}
    if too_few:
        raise InsufficientGroups("insufficient independent eligible groups per domain: " + ", ".join(f"{domain}={count}" for domain, count in sorted(too_few.items())))
    valid_roots = set()
    targets = {}
    for domain, groups in eligible_by_domain.items():
        target = min(len(groups) - 1, max(1, math.ceil(len(groups) * 0.10)))
        targets[domain] = target
        ordered = sorted(groups, key=lambda root: (hashlib.sha256(f"t09-v1|{domain}|{group_ids[root]}".encode()).hexdigest(), group_ids[root]))
        valid_roots.update(ordered[:target])
    assignments = {root: "valid" if root in valid_roots else "train" for root in components}
    actual = {}
    for domain, roots in eligible_by_domain.items():
        valid_count = sum(root in valid_roots for root in roots)
        train_count = len(roots) - valid_count
        actual[domain] = {"eligible_groups": len(roots), "target_valid_groups": targets[domain], "valid_groups": valid_count, "train_groups": train_count}
        if valid_count < 1 or train_count < 1:
            raise InsufficientGroups(f"cross-domain union leaves domain {domain} without both train and valid groups (train={train_count}, valid={valid_count})")
    return assignments, actual


def prepare(root, config, run_id):
    """Build deterministic leakage components and pending train/valid assignments."""
    root = Path(root).resolve()
    identifier(run_id)
    extraction, rows, annotations = _read_inputs(root, config)
    docs = _documents(extraction, rows)
    components, component_relations, link_ids, relation_counts = _group_docs(docs, annotations)
    group_ids = {root_id: hashlib.sha256(canonical({"algorithm": ALGORITHM, "member_candidate_ids": sorted(members)})).hexdigest()
                 for root_id, members in components.items()}
    try:
        assignments, domain_counts = _assign(components, docs, group_ids)
    except InsufficientGroups as error:
        return {"schema_version": 1, "id": run_id, "kind": "splits", "stage": "splits", "status": "BLOCKED",
                "reason": str(error), "extraction_manifest_sha256": config["extraction_manifest_sha256"], "generation_allowed": False}, 3

    groups = []
    for root_id, members in components.items():
        members.sort()
        group_id = group_ids[root_id]
        split = assignments[root_id] if any(docs[cid]["eligible"] for cid in members) else None
        member_records = []
        for cid in members:
            doc = docs[cid]
            identity = doc["identity"]
            member_records.append({"candidate_id": cid, "source_domain": identity["source_domain"], "repository": identity["repository"],
                                  "revision": identity["revision"], "source_path": identity["source_path"], "source_file_sha256": identity["source_file_sha256"],
                                  "candidate_status": identity["candidate_status"], "extraction_status": doc["extraction_status"],
                                  "eligible": doc["eligible"], "section_ids": [section["id"] for section in doc["sections"]],
                                  "normalized_text_sha256": doc["normalized_text_sha256"], "split_group": group_id,
                                  "split": split if doc["eligible"] else None})
            doc["split_group"] = group_id
            doc["split"] = split if doc["eligible"] else None
        group = {"schema_version": 1, "id": group_id, "kind": "split_group", "split_group": group_id,
                 "member_candidate_ids": members, "members": member_records, "split": split,
                 "relation_types": sorted(component_relations.get(root_id, set())),
                 "annotation_ids": sorted(link_ids.get(root_id, [])),
                 "eligible_domains": sorted({docs[cid]["identity"]["source_domain"] for cid in members if docs[cid]["eligible"]}),
                 "review_status": "PENDING", "group_review_status": "PENDING", "generation_allowed": False}
        group["record_sha256"] = digest(group)
        groups.append(group)
    groups.sort(key=lambda item: item["split_group"])
    group_bytes = b"".join(canonical(group) + b"\n" for group in groups)
    outdir = safe_path(root, f"artifacts/splits/{run_id}")
    groups_path = outdir / "groups.jsonl"
    manifest_path = outdir / "manifest.json"
    summary = {"components": len(groups), "assigned_train": sum(group["split"] == "train" for group in groups),
               "assigned_valid": sum(group["split"] == "valid" for group in groups),
               "unassigned": sum(group["split"] is None for group in groups), "domains": domain_counts}
    result_manifest = {"schema_version": 1, "id": run_id, "kind": "splits", "stage": "splits", "status": "PASSED",
                       "extraction_manifest": config["extraction_manifest"], "extraction_manifest_sha256": config["extraction_manifest_sha256"],
                       "extraction_id": extraction["id"], "snapshot_id": extraction["snapshot_id"],
                       "snapshot_manifest_sha256": extraction["snapshot_manifest_sha256"],
                       "config_sha256": digest(config), "effective_config": config, "implementation_sha256": implementation_hash(root),
                       "algorithm": ALGORITHM, "near_duplicate": {"tokenizer": "unicode-word-regex", "shingle_size": NEAR_SHINGLE_SIZE,
                                             "minimum_tokens": NEAR_MIN_TOKENS, "jaccard_threshold": NEAR_THRESHOLD},
                       "annotation_file_sha256": config["annotations_sha256"], "group_file": f"artifacts/splits/{run_id}/groups.jsonl",
                       "group_file_sha256": hashlib.sha256(group_bytes).hexdigest(), "group_count": len(groups),
                       "source_document_count": len(docs), "section_count": len(rows), "relation_counts": relation_counts,
                       "summary": summary, "review_status": "PENDING", "generation_allowed": False}
    atomic_bytes(groups_path, group_bytes)
    atomic_json(manifest_path, result_manifest)
    return {**result_manifest, "manifest": str(manifest_path), "groups": str(groups_path)}, 0
