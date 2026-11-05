import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import time


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _call(t, config, expected=0):
    path = t.temporary / f"{config['attempt_id']}-{config['action']}-{time.time_ns()}.json"
    path.write_text(json.dumps(config))
    result = t.cli("attempts", "--config", path, "--run-id", "ledger", expected=expected,
                   root=t.temporary / "ledger-project")
    return json.loads(result["stdout"])


def _claim(t, attempt_id, identity, lease_seconds=30):
    return _call(t, {"schema_version": 1, "action": "claim", "attempt_id": attempt_id,
                     "identity": identity, "lease_seconds": lease_seconds})


def test_ledger(t):
    project = t.temporary / "ledger-project"
    project.mkdir()
    identity = {"input_hashes": {"input.jsonl": _hash("input")},
                "generator_hash": _hash("generator"), "config_hash": _hash("config"), "seed": 17}
    t.check(_call(t, {"schema_version": 1, "action": "claim", "attempt_id": "empty-inputs",
                      "identity": {**identity, "input_hashes": {}}}, expected=2)["status"] == "INVALID",
            "empty input hash sets are rejected")

    lease = _claim(t, "duplicate", identity)
    t.check(lease["state"] == "claimed" and lease["fencing_token"] == 1 and lease["lease_token"],
            "claim returns the first fencing token and lease")
    t.check(_call(t, {"schema_version": 1, "action": "claim", "attempt_id": "duplicate",
                      "identity": identity}, expected=3)["status"] == "CONFLICT",
            "an active duplicate claim is rejected")
    commit = {"schema_version": 1, "action": "commit", "attempt_id": "duplicate", "identity": identity,
              "fencing_token": lease["fencing_token"], "lease_token": lease["lease_token"],
              "result": {"quality": "accepted", "score": 0.8}}
    committed = _call(t, commit)
    t.check(committed["state"] == "committed", "first result commits")
    t.check(_call(t, commit)["record_hash"] == committed["record_hash"], "identical commit retry is idempotent")
    t.check(_call(t, {**commit, "result": {"quality": "different"}}, expected=3)["status"] == "CONFLICT",
            "a different result cannot replace a committed result")

    first = _claim(t, "recover", identity, lease_seconds=1)
    time.sleep(1.1)
    second = _claim(t, "recover", identity, lease_seconds=30)
    t.check(second["fencing_token"] == first["fencing_token"] + 1,
            "expired lease recovery advances the fencing token")
    stale = {"schema_version": 1, "action": "commit", "attempt_id": "recover", "identity": identity,
             "fencing_token": first["fencing_token"], "lease_token": first["lease_token"],
             "result": {"quality": "stale"}}
    t.check(_call(t, stale, expected=3)["status"] == "CONFLICT", "stale worker cannot commit after recovery")
    t.check(_call(t, {"schema_version": 1, "action": "claim", "attempt_id": "recover",
                      "identity": {**identity, "seed": 18}}, expected=3)["status"] == "CONFLICT",
            "attempt identity cannot change across retries")
    fresh = {**stale, "fencing_token": second["fencing_token"], "lease_token": second["lease_token"],
             "result": {"quality": "fresh"}}
    _call(t, fresh)
    with sqlite3.connect(project / "artifacts/attempt-ledger/ledger.sqlite3") as db:
        events = db.execute("SELECT run_id, action, fence, identity_hash FROM events WHERE attempt_id='recover' ORDER BY event_id").fetchall()
        event_columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
    t.check([(row[0], row[1], row[2]) for row in events] ==
            [("ledger", "claim", 1), ("ledger", "claim", 2), ("ledger", "commit", 2)] and
            all(row[3] == _hash(json.dumps(identity, sort_keys=True, separators=(",", ":"))) for row in events) and
            "lease_token" not in event_columns,
            "append-only events preserve run, identity, action, and fence without private tokens")

    failed_lease = _claim(t, "failed", identity)
    failure = {"schema_version": 1, "action": "fail", "attempt_id": "failed", "identity": identity,
               "fencing_token": failed_lease["fencing_token"], "lease_token": failed_lease["lease_token"],
               "failure": {"kind": "quality_rejected", "detail": "threshold not met"}}
    failure_row = _call(t, failure)
    t.check(failure_row["state"] == "failed", "failure is recorded as a terminal attempt")
    t.check(_call(t, {"schema_version": 1, "action": "claim", "attempt_id": "failed",
                      "identity": identity})["state"] == "failed", "failed attempt remains visible and is not retried")
    retry_commit = {key: value for key, value in failure.items() if key != "failure"}
    retry_commit.update({"action": "commit", "result": {"quality": "accepted"}})
    t.check(_call(t, retry_commit, expected=3)["status"] == "CONFLICT",
            "failed attempt cannot later be committed")

    orphan_claim = _claim(t, "orphan-window", identity)
    orphan_commit = {"schema_version": 1, "action": "commit", "attempt_id": "orphan-window",
                     "identity": identity, "fencing_token": orphan_claim["fencing_token"],
                     "lease_token": orphan_claim["lease_token"],
                     "result": {"quality": "crash-window-recovery", "attempt": 1}}
    database = project / "artifacts/attempt-ledger/ledger.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TRIGGER fail_only_orphan_event BEFORE INSERT ON events
                      WHEN NEW.attempt_id='orphan-window' AND NEW.action='commit'
                      BEGIN SELECT RAISE(ABORT,'test-only persistence window'); END""")
        db.commit()
    rejected = _call(t, orphan_commit, expected=2)
    t.check(rejected["status"] == "INVALID", "isolated event fault aborts SQLite commit after raw result persistence")
    orphan_record = next((project / "artifacts/attempt-ledger/records").glob("orphan-window.result.*.json"))
    orphan_bytes = orphan_record.read_bytes()
    orphan_hash = hashlib.sha256(orphan_bytes).hexdigest()
    t.check(len(orphan_bytes) <= 1024 * 1024 + 1 and json.loads(orphan_bytes) == orphan_commit["result"],
            "aborted transaction leaves a bounded, verifiable immutable orphan record")
    rolled_back = _call(t, {"schema_version": 1, "action": "status", "attempt_id": "orphan-window"})
    t.check(rolled_back["state"] == "claimed", "failed DB transaction leaves the attempt claim recoverable")
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER fail_only_orphan_event")
        db.commit()
    recovered_commit = _call(t, orphan_commit)
    recovered_status = _call(t, {"schema_version": 1, "action": "status", "attempt_id": "orphan-window"})
    t.check(recovered_commit["state"] == "committed" and recovered_commit["record_hash"] == orphan_hash and
            recovered_status["record_hash"] == orphan_hash and
            next((project / "artifacts/attempt-ledger/records").glob("orphan-window.result.*.json")).read_bytes() == orphan_bytes,
            "retry commits the same immutable orphan and status verifies its stored hash")

    concurrent_config = {"schema_version": 1, "action": "claim", "attempt_id": "concurrent",
                         "identity": identity, "lease_seconds": 30}
    concurrent_path = t.temporary / "concurrent.json"
    concurrent_path.write_text(json.dumps(concurrent_config))
    base = [sys.executable, "-m", "sft", "--root", str(project), "--state", str(t.temporary / "state"),
            "attempts", "--config", str(concurrent_path), "--run-id", "ledger"]
    outputs = [t.temporary / "concurrent-1.out", t.temporary / "concurrent-2.out"]
    codes = [t.temporary / "concurrent-1.code", t.temporary / "concurrent-2.code"]
    pieces = [f"({shlex.join(base)} > {shlex.quote(str(out))} 2>&1; echo $? > {shlex.quote(str(code))})"
              for out, code in zip(outputs, codes)]
    concurrent = t.command(["sh", "-c", " & ".join(pieces) + " & wait; cat " + " ".join(shlex.quote(str(path)) for path in codes)],
                           env={**os.environ, "PYTHONPATH": str(t.root / "src")})
    t.check(sorted(concurrent["stdout"].split()) == ["0", "3"], "concurrent claims yield one lease owner")

    post_commit_claim = _claim(t, "post-commit-kill", identity)
    post_commit = {"schema_version": 1, "action": "commit", "attempt_id": "post-commit-kill",
                   "identity": identity, "fencing_token": post_commit_claim["fencing_token"],
                   "lease_token": post_commit_claim["lease_token"],
                   "result": {"quality": "persisted-before-ack", "attempt": 1}}
    post_commit_path = t.temporary / "post-commit-kill.json"
    post_commit_path.write_text(json.dumps(post_commit))
    post_commit_command = [sys.executable, "-m", "sft", "--root", str(project), "--state", str(t.temporary / "state"),
                          "attempts", "--config", str(post_commit_path), "--run-id", "ledger"]
    ready_path = t.temporary / "post-commit-ready"
    wrapper = "\n".join((
        "import json, pathlib, sqlite3, subprocess, sys, time",
        "command = json.loads(sys.argv[1])",
        "result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)",
        "if result.returncode != 0: raise SystemExit(result.returncode)",
        "with sqlite3.connect(sys.argv[2]) as db:",
        "    row = db.execute(\"SELECT state,record_hash FROM attempts WHERE attempt_id='post-commit-kill'\").fetchone()",
        "if not row or row[0] != 'committed': raise SystemExit('commit not visible to independent connection')",
        "pathlib.Path(sys.argv[3]).write_text(row[1])",
        "time.sleep(30)",
        "sys.stdout.write(result.stdout)",
    ))
    after_commit = t.command([sys.executable, "-c", wrapper, json.dumps(post_commit_command),
                              str(project / "artifacts/attempt-ledger/ledger.sqlite3"), str(ready_path)],
                             timeout=2, env={**os.environ, "PYTHONPATH": str(t.root / "src")})
    t.check(after_commit["timeout"] and ready_path.exists() and not after_commit["stdout"],
            "caller wrapper is killed after independent DB observation but before relaying commit response")
    committed_hash = ready_path.read_text()
    retried = _call(t, post_commit)
    post_commit_status = _call(t, {"schema_version": 1, "action": "status", "attempt_id": "post-commit-kill"})
    t.check(retried["state"] == "committed" and retried["record_hash"] == committed_hash and
            post_commit_status["record_hash"] == committed_hash,
            "identical retry after lost post-commit acknowledgement returns the persisted result")

    # A timed out worker leaves its claimed lease behind. Recovery after expiry
    # proves the next worker gets a new fence even when the former is gone.
    abandoned = {"schema_version": 1, "action": "claim", "attempt_id": "killed-worker",
                 "identity": identity, "lease_seconds": 1}
    config_path = t.temporary / "killed-worker-claim.json"
    config_path.write_text(json.dumps(abandoned))
    env = {**os.environ, "PYTHONPATH": str(t.root / "src")}
    command = [sys.executable, "-m", "sft", "--root", str(project), "--state", str(t.temporary / "state"),
               "attempts", "--config", str(config_path), "--run-id", "ledger"]
    result = t.command(["sh", "-c", shlex.join(command) + " && sleep 30"], timeout=0.2, env=env)
    t.check(result["timeout"], "killed worker leaves its lease for expiry recovery")
    time.sleep(1.1)
    recovered = _claim(t, "killed-worker", identity)
    t.check(recovered["fencing_token"] == 2, "recovered killed-worker attempt receives a new fence")

    record_path = next((project / "artifacts/attempt-ledger/records").glob("duplicate.result.*.json"))
    original_record = record_path.read_bytes()
    record_path.write_bytes(original_record + b" ")
    tamper = _call(t, {"schema_version": 1, "action": "status", "attempt_id": "duplicate"}, expected=2)
    t.check(tamper["status"] == "INVALID", "tampered result record fails its stored hash check")
    record_path.write_bytes(original_record)


SCENARIOS = {"ledger": test_ledger}
