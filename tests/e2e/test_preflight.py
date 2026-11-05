import json
import os
import subprocess
import sys
import selectors


def test_preflight(t):
    root = t.temporary / "project"
    root.mkdir()
    config = {"schema_version":1,"minimum_disk_gib":1,"minimum_memory_gib":1,"require_docker":False,"require_apple_silicon":True,"endpoints":[]}
    path = t.temporary / "doctor.json"
    def invoke(name, changes, expected):
        path.write_text(json.dumps({**config, **changes}))
        return t.cli("doctor","--config",path,"--run-id",name,root=root,expected=expected)
    invoke("host",{},0)
    invoke("disk",{"minimum_disk_gib":10**12},3)
    invoke("memory",{"minimum_memory_gib":10**12},3)
    invoke("wrong-type",{"minimum_disk_gib":True},2)
    invoke("unknown",{"extra":True},2)
    invoke("external",{"endpoints":[{"name":"external","url":"http://example.com"}]},2)
    path.write_text(json.dumps({**config,"require_docker":True}))
    result = t.command([sys.executable,"-m","sft","--root",str(root),"doctor","--config",str(path),"--run-id","missing-runtime"],env={**os.environ,"PATH":"/nonexistent","PYTHONPATH":str(t.root / "src")})
    t.check(result["exit_code"] == 3 and any(c["name"] == "docker_daemon" and c["status"] == "BLOCKED" for c in json.loads(result["stdout"])["checks"]), "missing Docker blocks preflight")
    binaries = t.temporary / "binaries"
    binaries.mkdir()
    node = binaries / "node"
    node.write_text("#!/bin/sh\necho v1.0.0\n")
    node.chmod(0o755)
    path.write_text(json.dumps(config))
    result = t.command([sys.executable,"-m","sft","--root",str(root),"doctor","--config",str(path),"--run-id","incompatible-node"],env={**os.environ,"PATH":str(binaries)+os.pathsep+os.environ["PATH"],"PYTHONPATH":str(t.root / "src")})
    t.check(result["exit_code"] == 3 and any(c["name"] == "node" and c["status"] == "BLOCKED" for c in json.loads(result["stdout"])["checks"]), "incompatible external runtime version blocks preflight")
    process = subprocess.Popen([sys.executable,str(t.root / "tests/e2e/scripted_provider.py"),str(t.temporary / "requests.jsonl")],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        t.check(bool(selector.select(5)), "scripted provider starts within deadline")
        port = process.stdout.readline().strip()
        selector.close()
        t.check(port.isdigit(), "scripted provider binds a local port")
        invoke("endpoint",{"endpoints":[{"name":"fixture","url":f"http://127.0.0.1:{port}/health"}]},0)
        invoke("endpoint-failure",{"endpoints":[{"name":"fixture","url":f"http://127.0.0.1:{port}/unavailable"}]},3)
    finally:
        process.terminate()
        process.wait(timeout=5)
    invoke("endpoint-offline",{"endpoints":[{"name":"fixture","url":f"http://127.0.0.1:{port}/health"}]},3)


SCENARIOS={"preflight":test_preflight}
