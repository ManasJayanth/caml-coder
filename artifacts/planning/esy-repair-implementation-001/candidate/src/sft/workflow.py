"""Append-only task history; current evidence is checked on every transition."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid
from .artifacts import Invalid, atomic_json, canonical, digest, fields, implementation_hash, read_json, safe_path


STATES = {"PENDING", "RUNNING", "PASSED", "FAILED", "BLOCKED", "WAITING_APPROVAL", "NEEDS_REPLAN"}


def now():
    return datetime.now(timezone.utc).isoformat()


def connect(state):
    path = safe_path(state, "workflow.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, card TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)")
    # Prevent accidental rewrites through ordinary SQLite statements. This is
    # defense in depth for the local workflow, not a security boundary against
    # an owner who can alter the database or drop its triggers.
    db.execute("CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append-only events'); END")
    db.execute("CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append-only events'); END")
    return db


def cards(root):
    result = read_json(Path(root) / "config/cards.json")
    if len({c["id"] for c in result}) != len(result):
        raise Invalid("duplicate work card")
    known = set()
    for card in result:
        fields(card, ["id", "goal", "dependencies", "allowed_files", "exclusions", "contract", "acceptance", "commands", "required_scenarios", "tier"])
        if not set(card["dependencies"]) <= known:
            raise Invalid("cards must be topologically ordered")
        if not card["required_scenarios"]:
            raise Invalid("card lacks required evidence scenarios")
        known.add(card["id"])
    return {c["id"]: c for c in result}


def evidence(root, path, card):
    report = read_json(path)
    fields(report, ["schema_version", "id", "kind", "tier", "status", "implementation_hash", "inventory", "started_at", "finished_at", "command", "scenarios"])
    if report["schema_version"] != 1 or report["kind"] != "e2e" or report["status"] != "PASSED":
        raise Invalid("evidence is not a passing E2E report")
    if report["implementation_hash"] != implementation_hash(root) or digest(report["inventory"]) != report["implementation_hash"]:
        raise Invalid("stale or invalid implementation evidence")
    if report["tier"] != card["tier"]:
        raise Invalid("wrong evidence tier")
    scenarios = report["scenarios"]
    if not scenarios or len({s["id"] for s in scenarios}) != len(scenarios):
        raise Invalid("empty or duplicate evidence scenarios")
    for scenario in scenarios:
        if scenario.get("status") != "PASSED" or not scenario.get("assertions") or not scenario.get("commands"):
            raise Invalid("scenario skipped, failed, missing assertions, or missing commands")
        if any(not isinstance(a, dict) or a.get("passed") is not True or not a.get("description") for a in scenario["assertions"]):
            raise Invalid("scenario has failed or malformed assertions")
        if any(not isinstance(c, dict) or not c.get("argv") for c in scenario["commands"]):
            raise Invalid("scenario has malformed command evidence")
    if not set(card["required_scenarios"]) <= {s["id"] for s in scenarios}:
        raise Invalid("required scenarios missing")
    return report


def snapshot(root, state):
    catalogue = cards(root)
    with connect(state) as db:
        events = db.execute("SELECT card,status,payload FROM events ORDER BY seq").fetchall()
    from .artifacts import loads
    current = {key: {"status": "PENDING", "repair_count": 0} for key in catalogue}
    gated = set()
    for key, status, payload in events:
        if key in current and key not in gated:
            current[key] = {**loads(payload), "status": status}
            if status in {"WAITING_APPROVAL", "NEEDS_REPLAN"}:
                # A gate is an append-only hold. No later ordinary event can
                # hide it until a separately authorized resolution exists.
                gated.add(key)
    for key, item in current.items():
        if item["status"] == "PASSED":
            try:
                report = evidence(root, item["evidence"], catalogue[key])
                recorded_hash = item.get("evidence_hash")
                if not isinstance(recorded_hash, str) or recorded_hash != digest(report):
                    raise Invalid("missing, malformed, or mismatched recorded evidence hash")
                if any(current[dep]["status"] != "PASSED" for dep in catalogue[key]["dependencies"]):
                    raise Invalid("prerequisite evidence is stale")
            except (Invalid, OSError, ValueError, KeyError) as error:
                item["status"] = "STALE"
                item["reason"] = str(error)
    return current


def history(state):
    from .artifacts import loads
    with connect(state) as db:
        return [{"sequence":seq,"card":card,"status":status,"payload":loads(payload)}
                for seq,card,status,payload in db.execute("SELECT seq,card,status,payload FROM events ORDER BY seq")]


def next_card(root, state):
    catalogue, current = cards(root), snapshot(root, state)
    for key, card in catalogue.items():
        status = current[key]["status"]
        if status in {"PENDING", "STALE", "FAILED", "RUNNING"} and current[key].get("repair_count", 0) < 3:
            if all(current[dep]["status"] == "PASSED" for dep in card["dependencies"]):
                run_id = f"work-{key}-{uuid.uuid4().hex[:12]}"
                card = resolved_card(root, card, run_id)
                packet = {"card": card, "current": current[key], "implementation_hash": implementation_hash(root),
                          "prerequisites": {dep: current[dep] for dep in card["dependencies"]},
                          "execution_policy": read_json(Path(root) / "config/execution-policy.json"),
                          "full_contract": str(Path(root) / "docs/PLAN.md"),
                          "workflow": "Run current E2E; edit only allowed files; run affected E2Es; inspect artifacts; record evidence. Maximum 3 failed repairs. No weakened tests, limits, stubs, or unapproved stage advances."}
                # UTF-8 bytes is a conservative upper bound on tokenizer token count.
                if len(canonical(packet)) > 12000:
                    raise Invalid("context packet exceeds conservative 12000-token bound")
                return packet
    return {"status": "BLOCKED", "reason": "No dependency-ready card; inspect work status for approval, blockers, or exhausted repairs.", "cards": current}


def resolved_card(root, card, run_id):
    return {**card, "commands":[command.replace("<unique-run-id>", run_id).replace("<report-path>", str(Path(root) / f"artifacts/e2e/{run_id}.json")) for command in card["commands"]]}


def record(root, state, card_id, status, report_path=None, reason=None):
    catalogue = cards(root)
    if card_id not in catalogue or status not in STATES - {"PENDING"}:
        raise Invalid("unknown card or invalid requested state")
    card = catalogue[card_id]
    db = connect(state)
    try:
        db.execute("BEGIN IMMEDIATE")
        current = snapshot(root, state)
        old = current[card_id]
        if old.get("repair_count", 0) >= 3 and status != "NEEDS_REPLAN":
            raise Invalid("three failed repairs: NEEDS_REPLAN; preserve evidence and escalate")
        if status in {"RUNNING", "PASSED", "WAITING_APPROVAL"} and any(current[dep]["status"] != "PASSED" for dep in card["dependencies"]):
            raise Invalid("prerequisites not currently passed")
        if old["status"] in {"WAITING_APPROVAL", "NEEDS_REPLAN"}:
            raise Invalid("approval/replan gate is immutable pending separately authorized resolution")
        payload = {"at": now(), "repair_count": old.get("repair_count", 0) + int(status == "FAILED"), "reason": reason}
        if status == "PASSED":
            if not report_path:
                raise Invalid("passing state requires E2E evidence")
            report = evidence(root, report_path, card)
            copied = safe_path(state, f"evidence/{digest(report)}.json")
            atomic_json(copied, report)
            payload["evidence"] = str(copied.absolute())
            payload["evidence_hash"] = digest(report)
        elif not reason:
            raise Invalid("non-passing states require a reason")
        db.execute("INSERT INTO events(card,status,payload) VALUES(?,?,?)", (card_id, status, canonical(payload).decode()))
        db.commit()
        return {"card": card_id, "status": status, **payload}
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
