#!/usr/bin/env python3
"""Fail-closed supervisor for the esy repair cards (stdlib only)."""
import argparse
import fcntl
import hashlib
import json
import os
import stat
import sys
import time
import uuid
from pathlib import Path

STATES = ("BOOTSTRAP", "PLAN_REQUIRED", "CODE_READY", "CODE_RUNNING",
          "DIFF_REVIEW_REQUIRED", "TEST_READY", "ACCEPTANCE_REQUIRED",
          "IMPORT_READY", "COMPLETE", "INCOMPLETE")
POLICY = {"schema_version": 1, "runnable": {"code": "gpt-6-luna",
          "plan": "gpt-6-astra", "review": "gpt-6-astra"},
          "limits": {"rounds": 12, "active_seconds": 21600,
          "additional_launches": 10, "output_bytes": 2097152,
          "file_bytes": 2097152, "growth_bytes": 16777216,
          "growth_files": 1000, "cleanup_seconds": 10},
          "timeouts": {"smoke": 120, "code": 1200, "plan": 600, "review": 600},
          "dispatch": "supervisor-only; C01 lifecycle and independent review required"}
POLICY_HASH = hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Incomplete(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    dfd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(dfd)
    finally: os.close(dfd)


def strict_json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise ValueError("duplicate JSON object key")
            out[k] = v
        return out
    return json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("invalid constant")))


def authority_layout():
    here = Path(__file__).resolve()
    # The installed executable lives in <root>/controller-authority; candidate
    # code is writable and is never accepted as the authority executable.
    if here.parent.name != "controller-authority":
        raise Incomplete("authoritative supervisor snapshot is absent; run only the supervisor-installed copy outside candidate")
    root = here.parent.parent
    candidate = root / "candidate"
    if not candidate.is_dir(): raise Incomplete("candidate directory is absent")
    return root, candidate, here.parent


def file_manifest(root, *, permit_links=False):
    result = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        bp = Path(base)
        for name in list(dirs):
            p = bp / name
            if p.is_symlink(): raise Incomplete(f"symlink forbidden: {p.relative_to(root)}")
        for name in files:
            p = bp / name; rel = p.relative_to(root).as_posix(); st = p.lstat()
            if not stat.S_ISREG(st.st_mode): raise Incomplete(f"special file forbidden: {rel}")
            if st.st_nlink > 1 and not permit_links: raise Incomplete(f"hardlinked file forbidden: {rel}")
            if st.st_size > POLICY["limits"]["file_bytes"]: raise Incomplete(f"file exceeds 2 MiB: {rel}")
            data = p.read_bytes()
            result[rel] = {"path": rel, "type": "file", "mode": stat.S_IMODE(st.st_mode),
                           "size": len(data), "sha256": digest(data)}
    return result


def verify_baseline(candidate, state):
    original_manifest = candidate.parent / "baseline-manifest.json"
    adopted_manifest = candidate.parent / "bootstrap" / "pre-C01-manifest.json"
    if not original_manifest.is_file() or digest(original_manifest.read_bytes()) != state.get("baseline_sha256"):
        raise Incomplete("frozen repository baseline manifest changed")
    if not adopted_manifest.is_file() or digest(adopted_manifest.read_bytes()) != state.get("adopted_candidate_manifest_sha256"):
        raise Incomplete("adopted pre-C01 candidate manifest changed")
    historical = candidate.parent / "events.jsonl"
    evidence_hash = digest(historical.read_bytes()) if historical.is_file() else None
    if evidence_hash != state.get("evidence_sha256"):
        raise Incomplete("historical evidence changed after adoption")
    baseline = state.get("baseline", {})
    for rel, old in baseline.items():
        p = candidate / rel
        try:
            if p.is_symlink() or not p.is_file(): raise Incomplete(f"baseline input missing or unsafe: {rel}")
            data = p.read_bytes(); st = p.stat()
        except OSError as e: raise Incomplete(f"cannot read baseline input {rel}: {e}")
        if digest(data) != old["sha256"] or len(data) != old["size"] or stat.S_IMODE(st.st_mode) != old["mode"]:
            raise Incomplete(f"original baseline bytes changed: {rel}")


def load_history(auth):
    events = auth / "events"
    rows = sorted(events.glob("*.json")) if events.exists() else []
    prev = "0" * 64; parsed = []
    for i, path in enumerate(rows):
        try: ev = strict_json(path.read_bytes())
        except Exception as e: raise Incomplete(f"corrupt event {path.name}: {e}")
        if ev.get("seq") != i + 1 or ev.get("previous") != prev or ev.get("policy_sha256") != POLICY_HASH:
            raise Incomplete(f"corrupt or incompatible event chain at {path.name}")
        body = dict(ev); claimed = body.pop("event_sha256", None)
        actual = digest(canonical(body))
        if claimed != actual: raise Incomplete(f"event hash mismatch: {path.name}")
        prev = claimed; parsed.append(ev)
    return parsed


def current_state(auth):
    events = load_history(auth)
    if not events: raise Incomplete("controller is not initialized; run init")
    return events[-1]["state"], events


def record(auth, kind, state, detail):
    events = load_history(auth)
    previous = events[-1]["event_sha256"] if events else "0" * 64
    body = {"seq": len(events) + 1, "previous": previous, "policy_sha256": POLICY_HASH,
            "kind": kind, "state": state, "at_epoch": time.time(), "detail": detail}
    body["event_sha256"] = digest(canonical(body))
    write_new(auth / "events" / f"{body['seq']:06d}.json", canonical(body))
    tmp = auth / "state.tmp"
    tmp.write_bytes(canonical({"state": state, "seq": body["seq"], "event_sha256": body["event_sha256"], "policy_sha256": POLICY_HASH}))
    os.replace(tmp, auth / "state.json")


def locked(auth):
    auth.mkdir(parents=True, exist_ok=True)
    f = open(auth / "controller.lock", "a+b")
    try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: f.close(); raise Incomplete("another controller mutation holds the exclusive lock")
    return f


def initialize(root, candidate, auth):
    if (auth / "events").exists() and any((auth / "events").iterdir()):
        raise Incomplete("already initialized; use resume")
    # Preserve the repository baseline and adopt the separately frozen current
    # candidate manifest, which includes its inherited dirty/untracked inputs.
    source = root / "baseline-manifest.json"
    adopted = root / "bootstrap" / "pre-C01-manifest.json"
    if not source.is_file(): raise Incomplete("baseline manifest unavailable beside candidate")
    if not adopted.is_file(): raise Incomplete("pre-C01 candidate manifest unavailable")
    baseline_raw = source.read_bytes(); raw = adopted.read_bytes()
    try:
        strict_json(baseline_raw)
        rows = strict_json(raw)
    except Exception as e: raise Incomplete(f"invalid frozen manifest: {e}")
    candidate_before = file_manifest(candidate)
    baseline = {}
    frozen = auth / "frozen-inputs"
    for row in rows:
        rel = row.get("path", "")
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts: raise Incomplete("baseline manifest has unsafe path")
        p = candidate / rel
        if p.is_symlink() or not p.is_file(): raise Incomplete(f"baseline input missing or unsafe: {rel}")
        data = p.read_bytes(); st = p.stat()
        expected_size = row.get("bytes", row.get("size", len(data)))
        if digest(data) != row.get("sha256") or len(data) != expected_size or stat.S_IMODE(st.st_mode) != row.get("mode"):
            raise Incomplete(f"candidate differs from frozen baseline: {rel}")
        mode = stat.S_IMODE(st.st_mode)
        dst = frozen / rel
        write_new(dst, data)
        os.chmod(dst, mode)
        baseline[rel] = {"path": rel, "type": "file", "sha256": digest(data), "size": len(data), "mode": mode}
    if set(candidate_before) != set(baseline): raise Incomplete("candidate has files outside the adopted baseline manifest")
    active = 482.411
    history = root / "events.jsonl"
    if history.exists():
        try:
            for line in history.read_bytes().splitlines():
                item = strict_json(line)
                if item.get("event") == "resume-bootstrap":
                    active = max(active, float(item.get("base_active_seconds", 0)))
        except Exception as e: raise Incomplete(f"cannot account for historical active time: {e}")
    prior_launches = 0
    jobs = root / "jobs"
    if jobs.exists():
        for receipt in jobs.glob("*/receipt.json"):
            try:
                if strict_json(receipt.read_bytes()).get("role") == "code": prior_launches += 1
            except Exception as e: raise Incomplete(f"cannot account for prior coding launch {receipt}: {e}")
    # This card's supervisor started record is outside candidate and provides
    # elapsed active time since resume; past receipts are already in base.
    started = root / "jobs" / "C01-core-001" / "started.json"
    if started.exists():
        try:
            start = strict_json(started.read_bytes())
            if start.get("role") == "code" and not (started.parent / "receipt.json").exists(): prior_launches += 1
            active += max(0.0, time.time() - float(start["wall_started"]))
        except Exception as e: raise Incomplete(f"cannot account for supervised coding elapsed time: {e}")
    state = "BOOTSTRAP"
    detail = {"baseline_sha256": digest(baseline_raw), "adopted_candidate_manifest_sha256": digest(raw),
              "baseline": baseline, "candidate_sha256": digest(canonical(file_manifest(candidate))),
              "evidence_sha256": digest((root / "events.jsonl").read_bytes()) if (root / "events.jsonl").exists() else None,
              "active_seconds": active, "coding_rounds": prior_launches, "launches_remaining": max(0, 12 - prior_launches),
              "global_round_limit": 12, "global_active_limit": 21600, "additional_launch_limit": 10,
              "plan_launches_remaining": min(10, max(0, 12 - prior_launches)), "implementation_rounds": max(0, prior_launches - 6), "unattended_dispatch": False}
    record(auth, "init", state, detail)
    raise Incomplete("initialized at BOOTSTRAP; lifecycle gates, plan and independent C01 review are still missing")


def manifest_delta(base, now):
    changed = {k: v for k, v in now.items() if k not in base or base[k] != v}
    added = [k for k in now if k not in base]
    allowed = {"scripts/esy-repair/controller.py", "scripts/esy-repair/codex-worker.sh",
               "tests/e2e/test_esy_repair_controller.py"}
    forbidden = sorted(set(changed) - allowed)
    if forbidden: raise Incomplete("out-of-card candidate modifications: " + ", ".join(forbidden))
    nbytes = sum(now[k]["size"] for k in changed)
    if len(added) > POLICY["limits"]["growth_files"] or nbytes > POLICY["limits"]["growth_bytes"]:
        raise Incomplete("candidate growth exceeds 1000 files or 16 MiB")
    return changed, added, nbytes


def verify_candidate(candidate, state):
    manifest_delta(state["baseline"], file_manifest(candidate))


def parse_provider(raw, run_id, role, revision, evidence):
    if not raw or not raw.endswith(b"\n"): raise Incomplete("truncated provider JSONL (missing final newline)")
    try: lines = [strict_json(line) for line in raw[:-1].split(b"\n")]
    except Exception as e: raise Incomplete(f"invalid provider JSONL: {e}")
    if not lines: raise Incomplete("provider emitted no events")
    known = {"thread.started", "turn.started", "item.completed", "turn.completed", "turn.failed", "error"}
    msgs = []; finals = []; kinds = [x.get("type") if isinstance(x, dict) else None for x in lines]
    if len(kinds) != 4 or kinds != ["thread.started", "turn.started", "item.completed", "turn.completed"]:
        raise Incomplete("provider event sequence differs from pinned Codex smoke protocol")
    for ev in lines:
        if not isinstance(ev, dict) or ev.get("type") not in known: raise Incomplete("unknown provider event variant")
        typ = ev["type"]
        if typ in ("error", "turn.failed"): raise Incomplete("provider reported an error")
        if typ == "thread.started" and (set(ev) != {"type", "thread_id"} or not isinstance(ev.get("thread_id"), str) or not ev["thread_id"]): raise Incomplete("malformed thread.started")
        if typ == "turn.started" and set(ev) != {"type"}: raise Incomplete("malformed turn.started")
        if typ == "item.completed":
            item = ev.get("item")
            if set(ev) != {"type", "item"} or not isinstance(item, dict) or set(item) != {"id", "type", "text"} or not isinstance(item.get("id"), str) or item.get("type") != "agent_message" or not isinstance(item.get("text"), str):
                raise Incomplete("unsupported item.completed payload")
            msgs.append(item["text"])
        if typ == "turn.completed":
            usage = ev.get("usage")
            fields = {"input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens"}
            if set(ev) != {"type", "usage"} or not isinstance(usage, dict) or set(usage) != fields or any(type(v) is not int or v < 0 for v in usage.values()): raise Incomplete("malformed turn.completed")
            finals.append(ev)
    if len(finals) != 1: raise Incomplete("provider must emit exactly one terminal turn.completed")
    if len(msgs) != 1: raise Incomplete("provider must emit exactly one final answer")
    try: obj = strict_json(msgs[0].encode("utf-8"))
    except Exception as e: raise Incomplete(f"final answer is not one strict JSON object: {e}")
    common = {"schema_version", "run_id", "role", "revision_sha256", "evidence_sha256"}
    extra = {"code": {"status", "summary", "changed_paths"}, "plan": {"cards"},
             "review": {"verdict", "findings", "missing_evidence"}}[role]
    if not isinstance(obj, dict) or set(obj) != common | extra: raise Incomplete("final answer has missing or extra fields")
    if any(k in obj for k in ("command", "commands", "argv", "executable")): raise Incomplete("executable command fields forbidden")
    if obj["schema_version"] != 1 or obj["run_id"] != run_id or obj["role"] != role or obj["revision_sha256"] != revision or obj["evidence_sha256"] != evidence:
        raise Incomplete("stale or misbound provider response")
    if role == "code":
        if obj["status"] not in ("complete", "incomplete") or not isinstance(obj["summary"], str) or not isinstance(obj["changed_paths"], list): raise Incomplete("invalid code response")
        if any(not isinstance(x, str) or Path(x).is_absolute() or ".." in Path(x).parts for x in obj["changed_paths"]): raise Incomplete("invalid code changed_paths")
    if role == "plan" and not isinstance(obj["cards"], list): raise Incomplete("invalid planner cards")
    if role == "review":
        if obj["verdict"] not in ("PASS", "FAIL") or not isinstance(obj["findings"], list) or not isinstance(obj["missing_evidence"], list): raise Incomplete("invalid review response")
        if any(not isinstance(x, str) for x in obj["findings"] + obj["missing_evidence"]): raise Incomplete("invalid review findings")
        if obj["verdict"] == "PASS" and (obj["findings"] or obj["missing_evidence"]): raise Incomplete("PASS requires empty findings and missing_evidence")
    return obj


def launch(root, candidate, auth, role, card):
    state, events = current_state(auth); verify_baseline(candidate, events[0]["detail"]); verify_candidate(candidate, events[0]["detail"])
    if role not in POLICY["runnable"]: raise Incomplete("role is not runnable")
    if state == "BOOTSTRAP" and role != "plan": raise Incomplete("BOOTSTRAP permits only planning; C01 lifecycle gates still block launch")
    if state != "BOOTSTRAP": raise Incomplete(f"launch prerequisite not satisfied in {state}")
    raise Incomplete("C01 lifecycle gate has no independently verified complete worker lifecycle; provider dispatch disabled")


def main():
    p = argparse.ArgumentParser(prog="controller.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init"); sub.add_parser("advance"); sub.add_parser("collect")
    sub.add_parser("resume"); sub.add_parser("print-handoff")
    l = sub.add_parser("launch"); l.add_argument("--role", choices=tuple(POLICY["runnable"]), required=True); l.add_argument("--card", default="C01-core")
    a = p.parse_args()
    try:
        root, candidate, auth = authority_layout()
        if a.cmd == "print-handoff":
            state, ev = current_state(auth); d = ev[0]["detail"]
            print(json.dumps({"state": state, "unfinished_obligations": ["C01 lifecycle gates", "independent C01 review", "plan", "implementation", "diff review", "tests", "acceptance", "import"],
              "baseline_sha256": d.get("baseline_sha256"), "candidate_sha256": digest(canonical(file_manifest(candidate))), "policy_sha256": POLICY_HASH,
              "evidence_sha256": d.get("evidence_sha256"), "consumed": {"coding_rounds": d.get("coding_rounds"), "active_seconds": d.get("active_seconds")},
              "active_processes": [], "cleanup_uncertainty": [], "next_command": "resume"}, sort_keys=True, indent=2)); return 0
        if a.cmd == "resume":
            state, ev = current_state(auth); verify_baseline(candidate, ev[0]["detail"]); verify_candidate(candidate, ev[0]["detail"])
            raise Incomplete(f"resumed state {state}; outstanding lifecycle and review evidence prevents dispatch")
        lock = locked(auth)
        try:
            if a.cmd == "init": initialize(root, candidate, auth)
            state, ev = current_state(auth); verify_baseline(candidate, ev[0]["detail"]); verify_candidate(candidate, ev[0]["detail"])
            if a.cmd == "collect":
                now = file_manifest(candidate); changed, added, size = manifest_delta(ev[0]["detail"]["baseline"], now)
                if not changed: raise Incomplete("no candidate work or evidence to collect")
                rid = str(uuid.uuid4()); report = {"run_id": rid, "changed": changed, "added": added, "changed_bytes": size, "candidate_sha256": digest(canonical(now))}
                write_new(auth / "reports" / f"collect-{rid}.json", canonical(report))
                record(auth, "collect", state, {"report": f"collect-{rid}.json", "sha256": digest(canonical(report))})
                print(json.dumps(report, sort_keys=True))
                if not any(e["kind"] == "launch" for e in ev):
                    print("INCOMPLETE: filesystem changes recorded, but no supervised provider run evidence exists", file=sys.stderr)
                    return 2
                return 0
            if a.cmd == "launch": launch(root, candidate, auth, a.role, a.card)
            if a.cmd == "advance": raise Incomplete(f"cannot advance from {state}: plan, supervised work, independent review and C01 lifecycle evidence are prerequisites")
        finally: lock.close()
    except Incomplete as e:
        print(f"INCOMPLETE: {e}", file=sys.stderr); return 2
    except Exception as e:
        print(f"INCOMPLETE: controller integrity failure: {e}", file=sys.stderr); return 3
    return 0


if __name__ == "__main__": raise SystemExit(main())
