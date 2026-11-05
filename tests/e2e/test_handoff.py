import json
import os
import shutil
import sys
import tarfile


def test_handoff(t):
    root = t.temporary / "project"
    root.mkdir()
    for directory in ("src","config","docs","scripts","schemas","tests","pi"):
        shutil.copytree(t.root / directory, root / directory, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml","uv.lock","package.json","package-lock.json","README.md",".python-version","tsconfig.json"):
        shutil.copy2(t.root / name, root / name)
    config = {"schema_version":1,"mode":"progress","artifact_roots":[],"known_issues":["All experiment stages are unexecuted in this fixture."]}
    path = t.temporary / "handoff.json"
    path.write_text(json.dumps(config))
    result = t.cli("handoff","--config",path,"--run-id","progress",root=root)
    output = root / "artifacts/handoff/progress"
    t.check(not result["output_truncated"] and len(result["stdout"].encode()) < 262144, "handoff response fits the subprocess capture limit")
    t.check(result["stdout"] == (output / "REVIEW_PROMPT.txt").read_text(), "CLI prints the complete saved review prompt byte-for-byte")
    t.check("INCOMPLETE_BLOCKED" in result["stdout"] and "REQUIRED REVIEW" in result["stdout"], "handoff prints populated prompt with incomplete state")
    t.check("Return PASS, CHANGES_REQUIRED or BLOCKED" in result["stdout"] and result["stdout"].rstrip().endswith("must produce a new complete handoff."), "handoff includes the complete response contract and final sentence")
    t.check('"id":"TASK-javascript-holdout-10"' in result["stdout"] and "config/cards.json" in result["stdout"], "compact map reaches final child and points to full bundled cards")
    t.check("<unique-run-id>" not in result["stdout"] and "<report-path>" not in result["stdout"], "review commands have concrete run IDs and evidence paths")
    manifest = json.loads((output / "manifest.json").read_text())
    extracted = t.temporary / "extracted"
    extracted.mkdir()
    with tarfile.open(output / "bundle.tar.gz") as archive:
        archive.extractall(extracted, filter="data")
    index = extracted / "bundle/index.json"
    env = {**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONPATH":str(extracted / "bundle/src")}
    command = [sys.executable,"-m","sft","verify","--index",str(index),"--expected-index-hash",manifest["index_hash"]]
    result = t.command(command,cwd=extracted,env=env)
    t.check(result["exit_code"] == 0 and json.loads(result["stdout"])["scope"].startswith("bundle-integrity-only"), "fresh extraction verifies without implying experiment acceptance")
    alias = t.temporary / "bundle-root-alias"
    alias.symlink_to(extracted / "bundle", target_is_directory=True)
    alias_command = [sys.executable,"-m","sft","verify","--index",str(alias / "index.json"),"--expected-index-hash",manifest["index_hash"]]
    result = t.command(alias_command,cwd=extracted,env=env)
    t.check(result["exit_code"] == 0, "caller-selected bundle root may use an OS path alias")
    linked = extracted / "bundle/internal-link"
    linked.symlink_to(t.temporary, target_is_directory=True)
    result = t.command(command,cwd=extracted,env=env)
    t.check(result["exit_code"] == 2, "symlinks inside the bundle remain forbidden")
    linked.unlink()
    changed = extracted / "bundle/docs/PLAN.md"
    original = changed.read_bytes()
    changed.write_bytes(original+b"tamper")
    result = t.command(command,cwd=extracted,env=env)
    t.check(result["exit_code"] == 2, "changed artifact fails integrity verification")
    changed.write_bytes(original)
    changed.unlink()
    result = t.command(command,cwd=extracted,env=env)
    t.check(result["exit_code"] == 2, "missing artifact fails integrity verification")
    changed.write_bytes(original)
    (extracted / "bundle/unindexed.txt").write_text("unexpected")
    result = t.command(command,cwd=extracted,env=env)
    t.check(result["exit_code"] == 2, "unindexed artifacts are rejected")
    path.write_text(json.dumps({**config,"mode":"final"}))
    t.cli("handoff","--config",path,"--run-id","premature-final",root=root,expected=2)
    t.check(not (root / "artifacts/handoff/premature-final").exists(), "unexecuted gates cannot produce final handoff")
    path.write_text(json.dumps({**config,"artifact_roots":["artifacts/missing.json"]}))
    t.cli("handoff","--config",path,"--run-id","missing",root=root,expected=2)
    secret = root / "artifacts/secret.txt"
    secret.write_text("-----BEGIN " + "PRIVATE KEY-----\nsynthetic fixture\n")
    path.write_text(json.dumps({**config,"artifact_roots":["artifacts/secret.txt"]}))
    t.cli("handoff","--config",path,"--run-id","secret",root=root,expected=2)
    t.check(not (root / "artifacts/handoff/secret").exists(), "possible credential prevents committing a bundle")


SCENARIOS={"handoff":test_handoff}
