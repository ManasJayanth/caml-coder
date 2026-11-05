"""Small, fenced SQLite ledger for one-shot stochastic attempts."""
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from .artifacts import Invalid, canonical, fields, identifier, loads, safe_path


MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_ATTEMPTS = 100_000
DEFAULT_LEASE_SECONDS = 300


class Conflict(Invalid):
    """An operation conflicts with the current immutable or fenced state."""


def _hash(value, name):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise Invalid(f"{name} must be a lowercase SHA256")


def _identity(value):
    fields(value, ("input_hashes", "generator_hash", "config_hash", "seed"))
    if not isinstance(value["input_hashes"], dict) or not 1 <= len(value["input_hashes"]) <= 10_000:
        raise Invalid("input_hashes must be a nonempty object with at most 10000 entries")
    for name, value_hash in value["input_hashes"].items():
        if not isinstance(name, str) or not name or len(name) > 512:
            raise Invalid("invalid input hash key")
        _hash(value_hash, f"input_hashes[{name}]")
    _hash(value["generator_hash"], "generator_hash")
    _hash(value["config_hash"], "config_hash")
    if type(value["seed"]) is not int or value["seed"] < 0 or value["seed"] > 2**63 - 1:
        raise Invalid("seed must be a nonnegative 63-bit integer")
    return canonical(value).decode("utf-8")


def _root_paths(root):
    root = Path(root).absolute()
    directory = safe_path(root, "artifacts/attempt-ledger")
    directory.mkdir(parents=True, exist_ok=True)
    database = safe_path(directory, "ledger.sqlite3")
    records = safe_path(directory, "records")
    records.mkdir(exist_ok=True)
    return database, records


def _connect(database):
    connection = sqlite3.connect(database, timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("""CREATE TABLE IF NOT EXISTS attempts (
        attempt_id TEXT PRIMARY KEY,
        identity_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('claimed','committed','failed')),
        fence INTEGER NOT NULL,
        lease_token TEXT,
        lease_expires REAL,
        record_name TEXT,
        record_hash TEXT
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS attempts_state_idx ON attempts(state)")
    connection.execute("""CREATE TABLE IF NOT EXISTS events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('claim','commit','fail')),
        identity_hash TEXT NOT NULL,
        fence INTEGER NOT NULL,
        happened_at REAL NOT NULL,
        record_hash TEXT
    )""")
    connection.execute("CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append-only events'); END")
    connection.execute("CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append-only events'); END")
    return connection


def _result(row, records):
    value = {"schema_version": 1, "attempt_id": row["attempt_id"], "state": row["state"],
             "fencing_token": row["fence"]}
    if row["state"] == "claimed":
        value["lease_expires_at"] = row["lease_expires"]
    if row["state"] in ("committed", "failed"):
        kind = "result" if row["state"] == "committed" else "failure"
        expected_name = f"{row['attempt_id']}.{kind}.{row['record_hash']}.json"
        if row["record_name"] != expected_name or re.fullmatch(r"[0-9a-f]{64}", row["record_hash"] or "") is None:
            raise Invalid("invalid stored ledger record path or hash")
        path = safe_path(records, row["record_name"])
        raw = path.read_bytes()
        if len(raw) > MAX_RECORD_BYTES + 1:
            raise Invalid("ledger record exceeds size limit")
        if hashlib.sha256(raw).hexdigest() != row["record_hash"]:
            raise Invalid("ledger record integrity failure")
        value["record"] = loads(raw)
        value["record_hash"] = row["record_hash"]
    return value


def _write_record(records, attempt_id, kind, payload):
    raw = canonical(payload) + b"\n"
    if len(raw) > MAX_RECORD_BYTES:
        raise Invalid("record exceeds 1 MiB")
    record_hash = hashlib.sha256(raw).hexdigest()
    name = f"{attempt_id}.{kind}.{record_hash}.json"
    path = safe_path(records, name)
    # Link provides no-overwrite installation on the same filesystem and keeps
    # an orphan harmless if a process dies before its SQLite transaction.
    if not path.exists():
        temporary = safe_path(records, f".pending-{secrets.token_hex(12)}")
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
        finally:
            temporary.unlink(missing_ok=True)
        fd = os.open(records, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    if path.read_bytes() != raw:
        raise Conflict("immutable record path contains different bytes")
    return name, record_hash


def dispatch(root, config, run_id):
    """Apply a strict v1 request and return ``(JSON result, exit code)``.

    Actions are claim, commit, fail, and status. Identity is required for every
    action. Commit/fail require the current integer fencing_token and the
    canonical payload under result/failure respectively.
    """
    try:
        run_id = identifier(run_id)
        if not isinstance(config, dict) or len(canonical(config)) > MAX_CONFIG_BYTES:
            raise Invalid("config must be an object no larger than 2 MiB")
        action = config.get("action")
        if action == "claim":
            fields(config, ("schema_version", "action", "attempt_id", "identity"), ("lease_seconds",))
        elif action == "commit":
            fields(config, ("schema_version", "action", "attempt_id", "identity", "fencing_token", "lease_token", "result"))
        elif action == "fail":
            fields(config, ("schema_version", "action", "attempt_id", "identity", "fencing_token", "lease_token", "failure"))
        elif action == "status":
            fields(config, ("schema_version", "action", "attempt_id"), ("identity",))
        else:
            raise Invalid("action must be claim, commit, fail, or status")
        if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
            raise Invalid("unsupported schema_version")
        attempt_id = identifier(config["attempt_id"])
        if action != "status" or "identity" in config:
            identity = _identity(config["identity"])
        if action in ("commit", "fail") and (type(config["fencing_token"]) is not int or config["fencing_token"] < 1):
            raise Invalid("fencing_token must be a positive integer")
        if action in ("commit", "fail") and (not isinstance(config["lease_token"], str) or not config["lease_token"]):
            raise Invalid("lease_token must be a nonempty string")
        if action == "commit" and not isinstance(config["result"], dict):
            raise Invalid("result must be an object")
        if action == "fail" and not isinstance(config["failure"], dict):
            raise Invalid("failure must be an object")
        if action == "claim":
            lease = config.get("lease_seconds", DEFAULT_LEASE_SECONDS)
            if type(lease) is not int or not 1 <= lease <= 86_400:
                raise Invalid("lease_seconds must be an integer from 1 to 86400")

        database, records = _root_paths(root)
        connection = _connect(database)
        try:
            identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest() if action != "status" or "identity" in config else None
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            now = time.time()
            if action == "claim":
                if row is not None and row["identity_json"] != identity:
                    raise Conflict("attempt identity mismatch")
                if row is None:
                    count = connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
                    if count >= MAX_ATTEMPTS:
                        raise Invalid("ledger capacity reached")
                    fence = 1
                    token = secrets.token_urlsafe(32)
                    expires = now + lease
                    connection.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,NULL,NULL)",
                                       (attempt_id, identity, "claimed", fence, token, expires))
                elif row["state"] != "claimed":
                    connection.commit()
                    return _result(row, records), 0
                elif row["lease_expires"] > now:
                    raise Conflict("attempt already has an active lease")
                else:
                    fence = row["fence"] + 1
                    token = secrets.token_urlsafe(32)
                    expires = now + lease
                    connection.execute("UPDATE attempts SET fence=?,lease_token=?,lease_expires=? WHERE attempt_id=?",
                                       (fence, token, expires, attempt_id))
                connection.execute("INSERT INTO events(attempt_id,run_id,action,identity_hash,fence,happened_at) VALUES (?,?,?,?,?,?)",
                                   (attempt_id, run_id, "claim", identity_hash, fence, now))
                row = connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
                value = _result(row, records)
                value["lease_token"] = token
                connection.commit()
                return value, 0

            if row is None:
                raise Conflict("unknown attempt")
            if "identity" in config and row["identity_json"] != identity:
                raise Conflict("attempt identity mismatch")
            if action == "status":
                connection.commit()
                return _result(row, records), 0
            if row["state"] == "committed" and action == "commit":
                record = config["result"]
                record_hash = hashlib.sha256(canonical(record) + b"\n").hexdigest()
                if row["record_hash"] == record_hash:
                    connection.commit()
                    return _result(row, records), 0
                raise Conflict("attempt already has a different committed result")
            if row["state"] == "failed":
                raise Conflict("failed attempts are terminal and retained")
            if row["state"] == "committed":
                raise Conflict("committed attempts are terminal")
            if row["fence"] != config["fencing_token"] or row["lease_token"] != config["lease_token"]:
                raise Conflict("stale fencing token")
            if row["lease_expires"] <= now:
                raise Conflict("lease expired")
            payload_key = "result" if action == "commit" else "failure"
            name, record_hash = _write_record(records, attempt_id, payload_key, config[payload_key])
            connection.execute("UPDATE attempts SET state=?,lease_token=NULL,lease_expires=NULL,record_name=?,record_hash=? WHERE attempt_id=?",
                               ("committed" if action == "commit" else "failed", name, record_hash, attempt_id))
            connection.execute("INSERT INTO events(attempt_id,run_id,action,identity_hash,fence,happened_at,record_hash) VALUES (?,?,?,?,?,?,?)",
                               (attempt_id, run_id, action, identity_hash, row["fence"], now, record_hash))
            row = connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            value = _result(row, records)
            connection.commit()
            return value, 0
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
    except Conflict as error:
        return {"schema_version": 1, "status": "CONFLICT", "error": str(error)}, 3
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        return {"schema_version": 1, "status": "INVALID", "error": str(error)}, 2
