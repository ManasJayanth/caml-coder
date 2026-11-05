"""Public subprocess E2Es for pinned source acquisition and snapshot reuse."""
import hashlib
import json
import os
from pathlib import Path
import shutil


DOMAINS = ("esy", "ocaml", "melange", "reason")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob(raw):
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")
    return path


def source_fixture(t):
    sources = []
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    for domain in DOMAINS:
        repository = t.temporary / "repositories" / domain
        (repository / "docs").mkdir(parents=True)
        (repository / "docs/guide.md").write_text(f"# {domain} guide\n\nA pinned documentation example.\n")
        (repository / "LICENSE").write_text(f"Synthetic test fixture license for {domain}.\n")
        for args in (["init"], ["add", "."], ["-c", "user.name=E2E Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "fixture"]):
            result = t.command(["git", "-C", str(repository), *args], env=env)
            t.check(result["exit_code"] == 0, f"local {domain} source fixture repository initialized")
        result = t.command(["git", "-C", str(repository), "rev-parse", "HEAD"], env=env)
        revision = result["stdout"].strip()
        sources.append({"domain": domain, "repository": str(repository), "revision": revision, "prefixes": ["docs"]})
    config = {"schema_version": 1, "kind": "fixture", "sources": sources}
    return write(t.temporary / "sources.json", config), config


def _clone_snapshot(template_root, target_root):
    source = template_root / "artifacts/sources/snapshot"
    target = target_root / "artifacts/sources/snapshot"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return target


def _rewrite_manifest(snapshot_dir, mutate=None, *, rebind=False):
    manifest_path = snapshot_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if mutate:
        mutate(manifest, snapshot_dir)
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    if rebind:
        receipt_path = snapshot_dir / "manifest.receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["manifest_sha256"] = _hash(manifest_path)
        receipt_path.write_bytes(_canonical(receipt) + b"\n")
    return manifest_path


def _bad_case(t, template_root, config_path, name, mutate, *, rebind=True):
    root = t.temporary / f"project-{name}"
    snapshot_dir = _clone_snapshot(template_root, root)
    _rewrite_manifest(snapshot_dir, mutate, rebind=rebind)
    t.cli("fetch", "--config", config_path, "--run-id", "snapshot", root=root, expected=2)
    return root


def _seed_snapshot(t, label):
    path, config = source_fixture(t)
    root = t.temporary / f"project-{label}"
    root.mkdir()
    t.cli("fetch", "--config", path, "--run-id", "snapshot", root=root)
    manifest = root / "artifacts/sources/snapshot/manifest.json"
    return path, config, root, manifest


def test_fetch(t):
    path, config, root, manifest = _seed_snapshot(t, "fetch")
    content = manifest.read_bytes()
    parsed = json.loads(content)
    t.check(len(parsed["files"]) == 8 and parsed["kind"] == "fixture", "four-domain fixture snapshot records every documentation and license file")
    receipt = root / "artifacts/sources/snapshot/manifest.receipt.json"
    t.check(receipt.exists() and json.loads(receipt.read_text())["manifest_sha256"] == _hash(manifest), "separate commitment binds the exact initial manifest")
    t.cli("fetch", "--config", path, "--run-id", "snapshot", root=root)
    t.check(manifest.read_bytes() == content, "repeat fetch preserves the immutable snapshot byte-for-byte")

    # Existing bytes without either commit record are ambiguous even if they
    # happen to match the upstream source exactly.
    matching_root = t.temporary / "project-matching-partial"
    matching_target = matching_root / "artifacts/sources/matching-partial/files/ocaml/docs/guide.md"
    matching_target.parent.mkdir(parents=True)
    ocaml_repository = Path(next(s["repository"] for s in config["sources"] if s["domain"] == "ocaml"))
    shutil.copyfile(ocaml_repository / "docs/guide.md", matching_target)
    t.cli("fetch", "--config", path, "--run-id", "matching-partial", root=matching_root, expected=2)
    t.check(not (matching_root / "artifacts/sources/matching-partial/manifest.json").exists() and
            not (matching_root / "artifacts/sources/matching-partial/manifest.receipt.json").exists(),
            "matching-byte partial output without a commitment is rejected without creating commit records")

    partial = root / "artifacts/sources/partial/files/ocaml/docs"
    partial.mkdir(parents=True)
    (partial / "guide.md").write_text("interrupted content")
    t.cli("fetch", "--config", path, "--run-id", "partial", root=root, expected=2)
    t.check(not (root / "artifacts/sources/partial/manifest.json").exists(), "partial conflicting snapshot never receives a commit marker")

    # A run ID cannot be rebound to a different acquisition config.
    altered = json.loads(json.dumps(config))
    altered["sources"][0]["revision"] = "0" * 40
    bad = write(t.temporary / "changed.json", altered)
    t.cli("fetch", "--config", bad, "--run-id", "snapshot", root=root, expected=2)

    # Invalid revisions, floating refs, and traversal fail before a snapshot is committed.
    t.cli("fetch", "--config", bad, "--run-id", "missing-commit", root=root, expected=2)
    t.check(not (root / "artifacts/sources/missing-commit/manifest.json").exists(), "failed fetch never commits a snapshot manifest")
    altered["sources"][0]["revision"] = "HEAD"
    write(bad, altered)
    t.cli("fetch", "--config", bad, "--run-id", "floating", root=root, expected=2)
    altered["sources"][0]["revision"] = config["sources"][0]["revision"]
    altered["sources"][0]["prefixes"] = ["../escape"]
    write(bad, altered)
    t.cli("fetch", "--config", bad, "--run-id", "traversal", root=root, expected=2)


def test_fetch_integrity(t):
    path, config, root, manifest_path = _seed_snapshot(t, "integrity")
    content = manifest_path.read_bytes()

    # Recompute the local receipt after mutations so each case exercises the
    # manifest validator itself, while still modeling immutable local files.
    def empty(m, _): m["files"] = []
    _bad_case(t, root, path, "empty", empty)
    def omitted_record(m, _): m["files"].pop(0)
    _bad_case(t, root, path, "omitted-record", omitted_record)
    def removed_domain(m, snapshot):
        m["files"] = [record for record in m["files"] if record["domain"] != "reason"]
        shutil.rmtree(snapshot / "files/reason")
    _bad_case(t, root, path, "removed-domain", removed_domain)
    def wrong_revision(m, _): m["files"][0]["revision"] = "f" * 40
    _bad_case(t, root, path, "wrong-revision", wrong_revision)
    def wrong_repository(m, _): m["files"][0]["repository"] = "https://wrong.invalid/source.git"
    _bad_case(t, root, path, "wrong-repository", wrong_repository)
    def duplicate(m, _): m["files"].append(dict(m["files"][0]))
    _bad_case(t, root, path, "duplicate-record", duplicate)
    def wrong_bytes(m, _): m["files"][0]["bytes"] += 1
    _bad_case(t, root, path, "wrong-bytes", wrong_bytes)
    def wrong_blob(m, _): m["files"][0]["git_blob"] = "0" * 40
    _bad_case(t, root, path, "wrong-blob", wrong_blob)
    def wrong_license_marker(m, _):
        record = next(row for row in m["files"] if row["license_file"])
        record["license_file"] = False
    _bad_case(t, root, path, "wrong-license-marker", wrong_license_marker)

    # Removing both a file and record is caught by the original independent
    # commitment even when the remaining local manifest looks self-consistent.
    def remove_record_and_bytes(m, snapshot):
        record = m["files"].pop()
        (snapshot / record["artifact"]).unlink()
    _bad_case(t, root, path, "removed-file-and-record", remove_record_and_bytes, rebind=False)

    altered_root = t.temporary / "project-integrity-altered-content"
    altered_snapshot = _clone_snapshot(root, altered_root)
    (altered_snapshot / "files/esy/docs/guide.md").write_text("changed bytes\n")
    t.cli("fetch", "--config", path, "--run-id", "snapshot", root=altered_root, expected=2)
    t.check((altered_snapshot / "manifest.json").read_bytes() == content, "content tamper is rejected without rewriting the original manifest")

    symlink_root = t.temporary / "project-integrity-symlink"
    symlink_snapshot = _clone_snapshot(root, symlink_root)
    linked = symlink_snapshot / "files/esy/docs/guide.md"
    linked.unlink()
    external = t.temporary / "external-guide.md"
    external.write_text("# esy guide\n\nA pinned documentation example.\n")
    linked.symlink_to(external)
    t.cli("fetch", "--config", path, "--run-id", "snapshot", root=symlink_root, expected=2)
    t.check((symlink_snapshot / "manifest.json").read_bytes() == content, "source symlink is rejected without rewriting the manifest")

    # Control paths themselves are checked before reading, including symlinks.
    for name in ("manifest-control-symlink", "receipt-control-symlink"):
        control_root = t.temporary / f"project-{name}"
        control_snapshot = _clone_snapshot(root, control_root)
        target = control_snapshot / ("manifest.json" if name.startswith("manifest") else "manifest.receipt.json")
        saved = t.temporary / f"saved-{name}.json"
        shutil.copyfile(target, saved)
        target.unlink()
        target.symlink_to(saved)
        t.cli("fetch", "--config", path, "--run-id", "snapshot", root=control_root, expected=2)

    # A malformed JSON value is rejected as an object-shape error, not an
    # uncaught attribute access.
    malformed_root = t.temporary / "project-malformed"
    malformed_snapshot = _clone_snapshot(root, malformed_root)
    (malformed_snapshot / "manifest.json").write_text("[]\n")
    t.cli("fetch", "--config", path, "--run-id", "snapshot", root=malformed_root, expected=2)

    # A legacy manifest has no commitment receipt. It is accepted only when
    # the caller supplies the exact external hash; all supplied pins are honored.
    legacy_root = t.temporary / "project-legacy"
    legacy_snapshot = _clone_snapshot(root, legacy_root)
    (legacy_snapshot / "manifest.receipt.json").unlink()
    t.cli("fetch", "--config", path, "--run-id", "snapshot", root=legacy_root, expected=2)
    pinned_config = dict(config, expected_manifest_sha256=_hash(legacy_snapshot / "manifest.json"))
    pinned_path = write(t.temporary / "sources-pinned.json", pinned_config)
    t.cli("fetch", "--config", pinned_path, "--run-id", "snapshot", root=legacy_root)
    t.check((legacy_snapshot / "manifest.json").read_bytes() == content, "legacy reuse succeeds with exact independent manifest pin")
    wrong_pin = dict(config, expected_manifest_sha256="0" * 64)
    wrong_pin_path = write(t.temporary / "sources-wrong-pin.json", wrong_pin)
    t.cli("fetch", "--config", wrong_pin_path, "--run-id", "snapshot", root=root, expected=2)

    interrupted_root = t.temporary / "project-interrupted"
    interrupted_snapshot = _clone_snapshot(root, interrupted_root)
    (interrupted_snapshot / "manifest.json").unlink()
    t.cli("fetch", "--config", path, "--run-id", "snapshot", root=interrupted_root, expected=2)


SCENARIOS = {"fetch": test_fetch, "fetch-integrity": test_fetch_integrity}
