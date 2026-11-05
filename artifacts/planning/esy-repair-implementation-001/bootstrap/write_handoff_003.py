"""Supervisor evidence packet writer; not an accepted workflow controller."""
from pathlib import Path
import datetime
import difflib
import hashlib
import json
import stat
import time

S = Path(__file__).resolve().parents[1]
ROOT = S.parents[2]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

def record(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}

baseline = json.loads((S / "baseline-manifest.json").read_text())
starting = json.loads((S / "bootstrap.json").read_text())
changed_originals = []
for item in baseline:
    path = ROOT / item["path"]
    if (not path.is_file() or path.is_symlink()
            or sha(path.read_bytes()) != item["sha256"]
            or stat.S_IMODE(path.stat().st_mode) != item["mode"]):
        changed_originals.append(item["path"])

manifest = []
for path in sorted((S / "candidate").rglob("*")):
    if path.is_symlink():
        raise RuntimeError(f"Unexpected candidate symlink: {path}")
    if path.is_file():
        manifest.append({"path": str(path.relative_to(S / "candidate")),
                         "mode": stat.S_IMODE(path.stat().st_mode),
                         "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())})
(S / "candidate-manifest-003.json").write_text(json.dumps(manifest, indent=2) + "\n")
revision = sha(canon(manifest))

result = json.loads((S / "RESULT-003.json").read_text())
result.update(candidate_sha256=revision, original_files_verified=len(baseline),
              original_files_changed=changed_originals,
              finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              active_seconds_consumed=round(482.411 + time.time() - 1792651436.0642276, 3))
(S / "RESULT-003.json").write_text(json.dumps(result, indent=2) + "\n")

packet = S / "frontier-packet-003"
packet.mkdir(exist_ok=False)
baseline_by_path = {r["path"]: r for r in baseline}
parts = []
for i, item in enumerate(manifest):
    rel = item["path"]
    before_path = S / "baseline" / rel
    before = before_path.read_text() if before_path.is_file() else ""
    after = (S / "candidate" / rel).read_text()
    if rel in baseline_by_path and baseline_by_path[rel]["sha256"] == item["sha256"]:
        continue
    diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                 fromfile="baseline/" + rel, tofile="candidate/" + rel))
    path = packet / f"source-{i:03d}.txt"
    path.write_text("FILE " + rel + "\nMANIFEST " + json.dumps(item)
                    + "\nCOMPLETE FINAL SOURCE\n" + after + "\nEXACT DIFF\n" + diff)
    parts.append(record(path))

files = [S / "bootstrap.json", S / "baseline-manifest.json", S / "candidate-manifest-003.json",
         S / "RESULT-003.json", S / "events.jsonl", S / "base-image-inspect-001.json",
         S / "base-readonly-probe-001.txt", S / "C01-deferred-cards.json",
         S / "required-esy-scenario-status-003.json", S / "FOLLOWUP_PLAN_NOTES-003.json"]
files += sorted(S.glob("budget-*.json"))
files += sorted(S.glob("original-preservation-*.json"))
for directory in sorted((S / "jobs").iterdir()):
    if directory.is_dir():
        for name in ("prompt.txt", "final.txt", "receipt.json", "started.json", "stdout", "stderr", "worker.sh", "sandbox.sb"):
            path = directory / name
            if path.is_file():
                files.append(path)
for path in sorted((S / "reviews").rglob("*")):
    if path.is_file():
        files.append(path)
files += [S / "bootstrap" / name for name in (
    "launch_worker.py", "trusted-codex-worker-003.sh", "containment-002.json",
    "kqueue-probe-001.json", "codex-astra-smoke-002.json", "C01-worker-claim-rejection.json")]
index = [record(path) for path in sorted(set(files)) if path.is_file()]
index += parts
evidence = sha(canon(index))
(S / "artifact-index-003.json").write_text(json.dumps({"evidence_sha256": evidence, "files": index}, indent=2) + "\n")

reviews = []
for job in ("C01-supervised-review-001", "R1-review-001", "R2-review-001",
            "seed-image-build-review-001", "R3-final-review-001", "remaining-work-plan-001"):
    path = S / "jobs" / job / "final.txt"
    if path.is_file():
        reviews.append("\n" + job + "\n" + path.read_text())
history = packet / "review-history.txt"
history.write_text("\n".join(reviews))

text = """You are the independent frontier reviewer of an INCOMPLETE esy reference-runner repair.
Review all indexed source/diff and review-history parts before issuing any verdict. This is an explicit multi-part packet; no source has been silently truncated. It was produced by a supervising evidence writer because the workflow controller remains unaccepted. It is not evidence that controller print-handoff works.

OBJECTIVE AND SCOPE
Repair offline esy compilation with disposable caches, exact compiler/package/lock identities, bounded output, reliable failure reports and owned-resource cleanup. No dataset generation, adapter experiments, model training or promotion. macOS only; uv package management; preserve original dirty/untracked files and lockfile.

CURRENT POLICY
The user explicitly replaced Claude Fable with fresh Codex gpt-6-astra review. Separate fresh Astra planning; gpt-6-luna coding. Historical Fable artifacts are superseded, never current requirements. No silent model substitutions. Twelve coding launches and six active hours maximum; never reset consumed budgets. Unattended execution remains disabled. Native worker containment is required; coding has no Docker socket access. All host tests/builds require independent pre-execution safety review.

RUNTIME INVARIANTS
Pinned base sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267; esy0.9.2, npm compiler5.5.1000, compiler output5.5.1. Readonly root/compiler/dependencies, network none, uid:gid1000:1000, capdropALL/no-new-privileges, pids128/cpus2/memory2GiB, deadline120s maximum; /work128MiB executable and two32MiB cache tmpfs mounts at original project paths. Never esy install at runtime. Verify complete inventories before candidate and immutable inventories afterward. Remove only exact proven-owned containers; query errors are not absence.

FINAL STATUS
""" + json.dumps(result, indent=2) + "\nSTARTING STATE\n" + json.dumps(starting, indent=2)
text += "\nREVIEW IDENTITIES\n" + json.dumps({"revision_sha256": revision, "evidence_sha256": evidence})
text += "\nREQUIRED E2E OUTCOMES\n" + (S / "required-esy-scenario-status-003.json").read_text()
text += "\nFOLLOW-UP PLAN QUALIFICATIONS\n" + (S / "FOLLOWUP_PLAN_NOTES-003.json").read_text()
text += "\nSOURCE AND DIFF PARTS\n" + json.dumps(parts, indent=2)
text += "\nREVIEW HISTORY PART\n" + json.dumps(record(history), indent=2)
text += "\nCOMPLETE ARTIFACT INDEX\n" + str(S / "artifact-index-003.json")
text += """\nVERIFICATION LIMITS
Read RESULT-003 for exact completed and missing evidence. Provider exit zero is not acceptance. The controller public E2E failed at PLAN_RUNNING replay. Earlier coding-worker claims of review approval were rejected. Real esy acceptance scenarios cannot be credited from static review, mocks, or named checks alone. No guarded import is authorized without passing complete evidence and final review. Original files have not been replaced.

REVIEW INSTRUCTIONS
Check every approved requirement; exact source/evidence identities; missing scenarios and false positives; unsafe cleanup; scope changes; concurrent-change/import handling. Read every listed source part and review-history part. If context is insufficient, report missing context, not PASS. Inspect raw evidence from the index where needed. Return strict JSON with revision_sha256, evidence_sha256, verdict(PASS|CHANGES_REQUIRED|BLOCKED), findings[{id,severity,location,problem,required_change,required_e2e}], missing_evidence. PASS requires zero findings AND zero missing evidence.
Every finding must be planned by a fresh separate Codex Astra process as small bounded cards. Coding remains smaller-model work, but exhausted coding budgets prohibit further launches until the user explicitly authorizes a new allocation; do not reset this run. Reviews must use fresh Codex Astra. Preserve failed attempts and all user edits. Do not broaden into model training or waive any gate.
"""
(S / "FRONTIER_HANDOFF-003.txt").write_text(text)
print(json.dumps({"status": result["status"], "handoff": str(S / "FRONTIER_HANDOFF-003.txt"),
                  "revision_sha256": revision, "evidence_sha256": evidence,
                  "source_parts": len(parts), "original_changes": changed_originals}))
