"""Portable, checksummed progress/final review packets; no success inference."""
from pathlib import Path
import hashlib
import re
import shutil
import tarfile
import tempfile
from .artifacts import Invalid, atomic_bytes, atomic_json, canonical, digest, fields, file_hash, implementation_inventory, read_json, safe_path
from .workflow import cards, history, now, snapshot


def verify(index_path, expected_hash):
    index_path = Path(index_path)
    if index_path.is_symlink():
        raise Invalid("bundle index must not be a symlink")
    # The caller chooses the bundle root; macOS commonly spells /private/var as
    # /var. Resolve that root, but still reject symlinks inside the bundle.
    index_path = index_path.parent.resolve() / index_path.name
    if not re.fullmatch("[0-9a-f]{64}", expected_hash):
        raise Invalid("expected index SHA256 must be provided")
    if file_hash(index_path) != expected_hash:
        raise Invalid("bundle index hash mismatch")
    index = read_json(index_path)
    fields(index, ["schema_version", "files"])
    if index["schema_version"] != 1 or not isinstance(index["files"], dict) or not index["files"]:
        raise Invalid("empty or unsupported bundle index")
    for relative, expected in index["files"].items():
        path = safe_path(index_path.parent, relative)
        if not path.is_file() or file_hash(path) != expected:
            raise Invalid(f"missing or changed bundle artifact: {relative}")
    entries = list(index_path.parent.rglob("*"))
    if any(p.is_symlink() for p in entries):
        raise Invalid("bundle contains symlinks")
    actual = {str(p.relative_to(index_path.parent)) for p in entries if p.is_file() and p != index_path}
    if actual != set(index["files"]):
        raise Invalid("bundle contains unindexed files")
    return {"status":"PASSED", "scope":"bundle-integrity-only; not experimental acceptance", "files":len(index["files"]), "index_hash":expected_hash}


def _check_shareable(relative, content):
    parts = Path(relative).parts
    if any(part in {".env", ".git", ".pi", "node_modules", ".venv", "credentials", "auth.json"} for part in parts):
        raise Invalid(f"private or irrelevant path excluded: {relative}")
    if Path(relative).suffix in {".safetensors", ".gguf", ".bin", ".sqlite", ".pem"}:
        raise Invalid(f"binary weights/state/keys excluded: {relative}")
    # Deliberately limited detection, not a promise to detect every possible secret.
    if re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bhf_[A-Za-z0-9]{25,}\b|\bsk-[A-Za-z0-9_-]{30,}\b", content):
        raise Invalid(f"possible credential in artifact: {relative}")


def build(root, state, config, run_id):
    fields(config, ["schema_version", "mode", "artifact_roots", "known_issues"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["mode"] not in {"progress", "final"}:
        raise Invalid("unsupported handoff configuration")
    if not isinstance(config["artifact_roots"], list) or not isinstance(config["known_issues"], list):
        raise Invalid("artifact_roots and known_issues must be lists")
    inventory = implementation_inventory(root)
    code_hash = digest(inventory)
    current = snapshot(root, state)
    pending = [key for key, value in current.items() if value["status"] != "PASSED" and key != "T42"]
    if config["mode"] == "final" and pending:
        raise Invalid(f"final handoff blocked: required cards not currently passed: {', '.join(pending)}")
    output = safe_path(root, f"artifacts/handoff/{run_id}")
    if output.exists():
        raise Invalid("handoff run ID already exists; use a new run ID")
    # Stage outside final directory; a failed build never looks complete.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".handoff-", dir=output.parent) as temporary:
        bundle = Path(temporary) / "bundle"
        bundle.mkdir()
        selected = {relative: root / relative for relative in inventory}
        for name in ("README.md", ".gitignore"):
            if (root / name).exists():
                selected[name] = root / name
        for path in (Path(state) / "evidence").glob("*.json"):
            selected[f"state/evidence/{path.name}"] = path
        for relative in config["artifact_roots"]:
            path = safe_path(root, relative)
            if "handoff" in Path(relative).parts or Path(relative).parts[0] != "artifacts":
                raise Invalid("handoff inputs must be explicit artifact paths outside handoff outputs")
            if not path.exists():
                raise Invalid(f"required handoff artifact missing: {relative}")
            entries = [path] if path.is_file() else path.rglob("*")
            for entry in entries:
                if entry.is_symlink():
                    raise Invalid("symlink in handoff inputs")
                if entry.is_file():
                    selected[str(entry.relative_to(root))] = entry
        for relative, source in sorted(selected.items()):
            content = source.read_bytes()
            _check_shareable(relative, content)
            target = safe_path(bundle, relative)
            atomic_bytes(target, content)
            target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        audit = {"created_at":now(), "mode":config["mode"], "implementation_hash":code_hash, "work_state":current,
                 "completion":"INCOMPLETE_BLOCKED" if pending else "AWAITING_FRONTIER_REVIEW", "known_issues":config["known_issues"],
                 "model_state":"No model weights, generation, datasets, approvals, training or deployment are implied by this handoff. Inspect actual evidence below."}
        atomic_json(bundle / "review-state.json", audit)
        atomic_json(bundle / "work-history.json", history(state))
        reports = []
        for relative in sorted(selected):
            if relative.startswith("artifacts/e2e/") and relative.endswith(".json"):
                report = read_json(bundle / relative)
                reports.append({"path":relative, "tier":report.get("tier"), "status":report.get("status"),
                                "fresh":report.get("implementation_hash") == code_hash, "tested_hash":report.get("implementation_hash"),
                                "started_at":report.get("started_at"), "finished_at":report.get("finished_at"),
                                "scenarios":[{"id":s.get("id"),"status":s.get("status"),
                                              "assertion_count":len(s.get("assertions",[])),
                                              "command_count":len(s.get("commands",[]))}
                                             for s in report.get("scenarios",[])]})
        # Full commands, stdout/stderr, assertions and timings stay in the
        # indexed bundle reports. The prompt carries compact pointers only.
        card_map = [{"id":card["id"], "goal":card["goal"], "dependencies":card["dependencies"],
                     "required_scenarios":card["required_scenarios"], "tier":card["tier"]}
                    for card in cards(root).values()]
        state_map = {key:{"status":value["status"], **({"repair_count":value["repair_count"]} if "repair_count" in value else {})}
                     for key,value in current.items()}
        plan = (root / "docs/PLAN.md").read_text()
        prompt = f'''You are the independent frontier-model reviewer of this local SFT implementation. Review correctness, reproducibility, experimental validity, safety and completeness. Do not trust completion claims. Review only: do not publish, promote, run bulk generation or start training.

PROJECT
Original workspace: {root}
Tested implementation inventory hash: {code_hash}
Progress state: {audit['completion']}
This is a {config['mode']} handoff. Missing implementation or required evidence means BLOCKED or CHANGES_REQUIRED, never PASS. No chat history is needed. Read all bundle files before concluding.

USER OBJECTIVE AND APPROVED EXECUTION CONTRACT
{plan}

IMPLEMENTATION STATE (computed from actual evidence)
{canonical(state_map).decode()}

EXACT WORK CARD MAP
The following exact IDs, goals, dependencies, required scenarios and evidence tiers summarize the work catalogue. The bundled config/cards.json is authoritative for each card's full contract, allowed files, exclusions and commands. Do not infer completion from the map.
{canonical(card_map).decode()}

REPRODUCIBILITY
Python runtime is pinned in .python-version, Python packages in uv.lock, Pi/TypeScript dependencies in package-lock.json. Use uv sync --frozen and npm ci --ignore-scripts in an isolated checkout. Execute public ./scripts/sft commands. config/sources.json contains immutable source revisions. Each included snapshot manifest records original file hashes, Git blob hashes, domain and source revision; verify before use. Read actual config files for all settings. No model revision/checkpoint/dataset identity may be inferred from its planned name. Missing model/data/review/schedule/conversion manifests are missing evidence. Weight binaries are intentionally excluded; a completed implementation must provide pinned acquisition and restoration manifests. All current evidence commands and their test-source hashes are below and in the bundle. Fixture inputs are regenerated by versioned E2E scenarios; original temporary directories may no longer exist.

EXECUTED EVIDENCE
Each report path below points to a bundled artifacts/e2e/*.json file containing full argv, stdout/stderr, assertions, timings and tested source inventory. The map lists report tier/status/hash freshness and scenario assertion/command counts without copying logs into this prompt. Fresh=false means historical evidence, not a current pass. Missing suites and real-model/acceptance runs are not executed.
{canonical(reports).decode()}

EXPERIMENT RESULTS
Do not invent pilot yields, dataset counts, training steps, memory peaks, acceptance scores, model revisions or user approvals. Consult included artifacts; absent reports mean NOT RUN. Source file counts are not training-example counts. Host-only doctor success does not establish real-model readiness. Deterministic fixtures do not establish Pi tool isolation or real inference correctness.

KNOWN LIMITATIONS AND OPEN ISSUES
{canonical(config['known_issues']).decode()}
Secret scanning covers only known credential patterns; inspect all bundle contents for omissions and sensitive data before sharing further. No external sharing was performed.

REQUIRED REVIEW
1. Independently verify inventory checksums and detect missing/unindexed artifacts.
2. Trace source, chunk, attempt, review, target, schedule, checkpoint and deployment ancestry; missing stages are blockers.
3. Audit duplicate/translated/task-family splits, leakage and holdout reuse.
4. Audit all four tools, container isolation, trusted grading, request/tool/token/time limits and actual observations.
5. Audit teacher normalization, exact prompt prefixes, first-target/EOS/padding masks and whole-episode limits.
6. Verify actual sampling counts, optimizer steps, adapter-only changes and restart behavior.
7. Separate deterministic fixtures, actual models and acceptance evidence.
8. Find stale/empty/fabricated logs, false-green assertions, weakened thresholds and skipped requirements.
9. Verify exact-hash user pilot/dataset approvals and independent reviews.
10. Recompute matched-runtime baseline gains and lost previously passing general tasks.
11. Rerun bounded E2Es where feasible and explicitly report unrun checks. Do not start expensive stages or modify the experiment during review.
12. Audit this handoff for missing context and misleading claims.

RESPONSE CONTRACT
Return PASS, CHANGES_REQUIRED or BLOCKED. Give prioritized findings with exact file/artifact references, expected versus observed behavior, evidence and impact. Supply small repair cards with scoped files and E2E acceptance. Identify invalidated approvals, runs and benchmarks. List residual uncertainty and unexecuted checks. Never PASS missing, stale or blocked required evidence. Repairs return to the same work loop and must produce a new complete handoff.
'''
        atomic_bytes(bundle / "REVIEW_PROMPT.txt", prompt.encode())
        index = {"schema_version":1,"files":{str(p.relative_to(bundle)):file_hash(p) for p in sorted(bundle.rglob("*")) if p.is_file()}}
        atomic_json(bundle / "index.json", index)
        index_hash = file_hash(bundle / "index.json")
        verify(bundle / "index.json", index_hash)
        output.mkdir()
        shutil.copytree(bundle, output / "bundle")
        with tarfile.open(output / "bundle.tar.gz", "w:gz") as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    archive.add(path, arcname=f"bundle/{path.relative_to(bundle)}", recursive=False)
        wrapper = f"BUNDLE LOCATION AND INTEGRITY\nBundle: {output / 'bundle.tar.gz'}\nIndex: {output / 'bundle/index.json'}\nExpected index SHA256: {index_hash}\nVerify after extracting to any directory: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=bundle/src python3.12 -m sft verify --index bundle/index.json --expected-index-hash {index_hash}\nVerification proves file integrity only, not that experimental gates passed.\n\n" + prompt
        atomic_bytes(output / "REVIEW_PROMPT.txt", wrapper.encode())
        atomic_json(output / "manifest.json", {"schema_version":1,"id":run_id,"mode":config["mode"],"implementation_hash":code_hash,"index_hash":index_hash,"archive_hash":file_hash(output / "bundle.tar.gz"),"prompt_hash":file_hash(output / "REVIEW_PROMPT.txt"),"state":audit["completion"]})
    return wrapper, output
