"""Strict JSON, content identities, and immutable atomic artifacts."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


class Invalid(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Invalid(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(data):
    def bad_constant(value):
        raise Invalid(f"non-finite JSON number: {value}")
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=bad_constant)


def read_json(path):
    return loads(Path(path).read_text(encoding="utf-8"))


def fields(value, required, optional=()):
    if not isinstance(value, dict):
        raise Invalid("expected object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise Invalid(f"missing fields={sorted(missing)}, unknown fields={sorted(unknown)}")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        raise Invalid("invalid identifier")
    return value


def safe_path(root, relative):
    root = Path(root).absolute()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise Invalid("path must be a nonempty relative path without traversal")
    cursor = root
    # Reject symlinked ancestors too: resolving first would hide the link.
    for ancestor in [root, *root.parents]:
        if ancestor.is_symlink():
            raise Invalid(f"symlinked root: {ancestor}")
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise Invalid(f"symlink forbidden: {cursor}")
    return cursor


def atomic_json(path, value):
    """No-overwrite commit; identical retry is idempotent. fsync file and parent."""
    return atomic_bytes(path, canonical(value) + b"\n")


def atomic_bytes(path, content):
    path = Path(path)
    safe_path(path.parent, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise Invalid(f"immutable artifact conflict: {path}")
        return path
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise Invalid(f"concurrent artifact conflict: {path}")
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)
    return path


def implementation_inventory(root):
    root = Path(root)
    paths = []
    for directory in ("src", "pi", "tests", "scripts", "config", "schemas", "docs"):
        paths.extend(p for p in (root / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    paths.extend(root / p for p in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json", "tsconfig.json", ".python-version") if (root / p).exists())
    if any(p.is_symlink() for p in paths):
        raise Invalid("implementation files must not be symlinks")
    return {str(p.relative_to(root)): file_hash(p) for p in sorted(paths)}


def implementation_hash(root):
    return digest(implementation_inventory(root))


def validate_record(record, contract):
    fields(record, contract["required"], contract.get("optional", []))
    if record.get("schema_version") != 1:
        raise Invalid("unsupported schema_version")
    identifier(record["id"])
    for field, choices in contract.get("enums", {}).items():
        if record.get(field) not in choices:
            raise Invalid(f"invalid {field}")
    for field, kind in contract.get("types", {}).items():
        types = {"string": str, "integer": int, "object": dict, "array": list, "boolean": bool}
        if field in record and type(record[field]) is not types[kind]:
            raise Invalid(f"wrong type for {field}")
    for field in contract.get("hashes", []):
        if not isinstance(record.get(field), str) or not re.fullmatch("[0-9a-f]{64}", record[field]):
            raise Invalid(f"invalid SHA256 in {field}")
    return record


def validate_jsonl(path, contract):
    records, seen = [], set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise Invalid(f"blank JSONL record at line {number}")
        try:
            record = validate_record(loads(line), contract)
        except (ValueError, KeyError) as error:
            raise Invalid(f"line {number}: {error}") from error
        if record["id"] in seen:
            raise Invalid(f"duplicate id: {record['id']}")
        seen.add(record["id"])
        records.append(record)
    if not records:
        raise Invalid("empty JSONL")
    return records
