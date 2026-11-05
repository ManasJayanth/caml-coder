#!/usr/bin/env python3
"""Run or capture the fixed offline esy reference.

Public interface: ``--image sha256:<hex>`` and ``--run-id ID`` select a normal
run; ``--expectations FILE`` and ``--output-dir DIRECTORY`` bind it to protected
supervisor inputs and outputs. ``--capture-expectations FILE --image IMAGE``
captures validated base and derivative identities before acceptance runs and
cannot be combined with ``--run-id``. ``--case`` is one of suite (default),
positive, wrong-result, syntax, timeout, output, or resource. The fixed
negative cases are controls, never arbitrary source execution. ``--timeout``
accepts 1..120 seconds and only lowers the default. Expectations are published
immutably. The supervisor builds the Dockerfile separately with reviewed
commands; this module never builds images or installs packages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import secrets
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE_TAG = "ocaml-sft-esy-project-probe:001"
BASE_ID = "sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267"
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_OUTPUT = 128 * 1024
MAX_STREAM = 16 * 1024
MAX_CAPTURE = 4 * 1024 * 1024
DEFAULT_TIMEOUT = 120


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# This script receives only fixed mode names and the supervisor's JSON manifest.
# It never evaluates a command from the manifest.
NODE = r'''const fs=require('fs'), path=require('path'), crypto=require('crypto'), cp=require('child_process');
const mode=process.argv[2], arg=process.argv[3]||'{}';
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
function inventory(root){let rows=[]; function walk(p,rel){for(const n of fs.readdirSync(p).sort()){const q=path.join(p,n), r=rel?rel+'/'+n:n, s=fs.lstatSync(q); if(s.isSymbolicLink())throw Error('symlink forbidden: '+r); if(s.isDirectory())walk(q,r); else if(s.isFile())rows.push({path:r,bytes:s.size,mode:s.mode&0o777,sha256:hash(fs.readFileSync(q))}); else throw Error('unsafe seed type: '+r)}} walk(root,''); return rows}
function run(cmd,args,timeout=15000,max=16384){let r=cp.spawnSync(cmd,args,{encoding:'utf8',timeout,maxBuffer:max,killSignal:'SIGKILL',env:process.env}); return {status:r.status,signal:r.signal||null,error:r.error?String(r.error):null,stdout:(r.stdout||'').slice(0,8192),stderr:(r.stderr||'').slice(0,8192)}}
function immutable(){const p='/home/opam/esy-reference', q=path.join(p,'package.json'); const st=fs.lstatSync(q); if(!st.isFile()||st.isSymbolicLink())throw Error('unsafe package.json'); return {package:{path:'package.json',bytes:st.size,mode:st.mode&0o777,sha256:hash(fs.readFileSync(q))},locks:fs.existsSync(path.join(p,'esy.lock'))?inventory(path.join(p,'esy.lock')):[],projectSeed:inventory('/home/opam/esy-reference/_esy'),cacheSeed:inventory('/home/opam/esy-reference/node_modules/.cache')}}
function compiler(storeOnly=false){let p;if(storeOnly){let found=[];function walk(d){for(const n of fs.readdirSync(d)){const q=path.join(d,n),s=fs.lstatSync(q);if(s.isSymbolicLink())continue;if(s.isDirectory())walk(q);else if(s.isFile()&&n==='ocamlopt'&&(s.mode&0o111))found.push(q)}}walk('/home/opam/esy-reference/_esy');if(found.length!==1)throw Error('fixed esy store must contain exactly one executable ocamlopt');p=found[0]}else{const r=run('/home/opam/esy/bin/esy',['sh','-c','command -v ocamlopt']);p=r.stdout.trim();if(r.status!==0||!p||!p.startsWith('/'))throw Error('esy compiler path lookup failed')};const real=fs.realpathSync(p),st=fs.lstatSync(real);if(!st.isFile()||st.isSymbolicLink())throw Error('compiler path is unsafe');const version=run(real,['-version']);if(version.status!==0)throw Error('compiler version failed');return {path:real,bytes:st.size,sha256:hash(fs.readFileSync(real)),version:version.stdout.trim()}}
function main(){ if(mode==='capture-base'){const i=immutable(), c=compiler(true); return {immutable:i,compiler:c}}
 if(mode==='capture-derivative'){return {seedProject:inventory('/home/opam/esy-cache-seed/_esy'),seedCache:inventory('/home/opam/esy-cache-seed/node-cache'),immutable:immutable(),compiler:compiler(true)}}
 if(mode!=='run')throw Error('unknown fixed harness mode'); const cfg=JSON.parse(arg);
 function copyTree(src,dst){fs.mkdirSync(dst,{recursive:true});for(const n of fs.readdirSync(src)){const a=path.join(src,n),b=path.join(dst,n),s=fs.lstatSync(a);if(s.isSymbolicLink())throw Error('seed symlink forbidden: '+a);if(s.isDirectory())copyTree(a,b);else if(s.isFile()){fs.copyFileSync(a,b);fs.chmodSync(b,s.mode&0o777);fs.utimesSync(b,s.atime,s.mtime)}else throw Error('unsafe seed type: '+a)}}
 copyTree('/home/opam/esy-cache-seed/_esy','/home/opam/esy-reference/_esy'); copyTree('/home/opam/esy-cache-seed/node-cache','/home/opam/esy-reference/node_modules/.cache');
 const start=immutable(), comp=compiler(), commands={};
 for(const [n,b64] of Object.entries(cfg.fixtures||{}))fs.writeFileSync('/work/'+n,Buffer.from(b64,'base64'),{mode:0o444});
 const runCmd=(name,cmd,args,timeout=cfg.timeout)=>{let r=cp.spawnSync(cmd,args,{encoding:'utf8',timeout:timeout*1000,maxBuffer:32768,killSignal:'SIGKILL',env:process.env}); let out=Buffer.from(r.stdout||''), err=Buffer.from(r.stderr||''); commands[name]={exit_code:r.status,signal:r.signal||null,timed_out:!!(r.error&&r.error.code==='ETIMEDOUT'),error:r.error?String(r.error):null,stdout_bytes:out.length,stdout_sha256:hash(out),stdout:out.subarray(0,8192).toString('utf8'),stdout_truncated:out.length>8192,stderr_bytes:err.length,stderr_sha256:hash(err),stderr:err.subarray(0,8192).toString('utf8'),stderr_truncated:err.length>8192}; return commands[name]};
 const probe=(p,write)=>{try{if(write){let t=p+'/.probe-'+process.pid;fs.writeFileSync(t,'ok',{flag:'wx'});fs.unlinkSync(t);return {path:p,allowed:true}}let f=fs.openSync(p,'r+');fs.closeSync(f);return {path:p,allowed:true}}catch(e){return {path:p,allowed:false,code:e.code||String(e)}}};
 const results={commands,pre_immutable:start,compiler:comp,seed_checks:{project:JSON.stringify(start.projectSeed)===JSON.stringify(cfg.expected.derivative.seedProject),cache:JSON.stringify(start.cacheSeed)===JSON.stringify(cfg.expected.derivative.seedCache)},write_probes:{cache:probe('/home/opam/esy-reference/node_modules/.cache',true),package:probe('/home/opam/esy-reference/package.json',false),lock:probe('/home/opam/esy-reference/esy.lock/index.json',false),compiler:probe(comp.path,false)},timed_out:false,output_exceeded:false,resource_exceeded:false};
 const esy='/home/opam/esy/bin/esy', src='/work'; const compile=(label,file,out)=>runCmd(label,esy,['ocamlopt','-o',src+'/'+out,src+'/'+file]); const execute=(label,bin,timeout)=>runCmd(label,src+'/'+bin,[],timeout);
 if(cfg.case==='suite'||cfg.case==='positive'||cfg.case==='wrong-result'||cfg.case==='syntax'){
   let which=cfg.case==='suite'?['positive','wrong-result','syntax']:[cfg.case];
   if(which.includes('positive')){runCmd('compile-positive',esy,['ocamlopt','-o',src+'/positive.exe',src+'/main.ml']); if(commands['compile-positive'].exit_code===0)runCmd('run-positive',src+'/positive.exe',[])}
   if(which.includes('wrong-result')){runCmd('compile-wrong-result',esy,['ocamlopt','-o',src+'/wrong.exe',src+'/wrong_result.ml']); if(commands['compile-wrong-result'].exit_code===0)runCmd('run-wrong-result',src+'/wrong.exe',[])}
   if(which.includes('syntax'))runCmd('compile-syntax',esy,['ocamlopt','-o',src+'/syntax.exe',src+'/syntax.ml']);
 }
 if(cfg.case==='timeout')runCmd('timeout-loop','/bin/sh',['-c','while :; do :; done'],Math.min(cfg.timeout,2));
 if(cfg.case==='output')runCmd('output-flood','/usr/bin/yes',['esy-output-control'],2);
 if(cfg.case==='resource')runCmd('resource-pressure','/home/opam/node/bin/node',['-e','Buffer.alloc(3*1024*1024*1024)'],Math.min(cfg.timeout,5));
 results.post_immutable=immutable(); results.immutable_unchanged=JSON.stringify({package:start.package,locks:start.locks})===JSON.stringify({package:results.post_immutable.package,locks:results.post_immutable.locks}); results.post_compiler=compiler(); results.compiler_unchanged=JSON.stringify(comp)===JSON.stringify(results.post_compiler); results.compiler_matches_expectation=JSON.stringify(comp)===JSON.stringify(cfg.expected.base.compiler);
 if(cfg.case==='resource')results.resource_exceeded=!!(commands['resource-pressure']&&(commands['resource-pressure'].exit_code!==0||commands['resource-pressure'].signal));
 results.installation_matches_expectation=JSON.stringify(start.package)===JSON.stringify(cfg.expected.base.immutable.package)&&JSON.stringify(start.locks)===JSON.stringify(cfg.expected.base.immutable.locks);
 return results; }
try{process.stdout.write(JSON.stringify(main()))}catch(e){process.stderr.write(String(e&&e.stack||e));process.exitCode=2}
'''


def docker_image(image: str) -> dict:
    raw = subprocess.run(["docker", "image", "inspect", image], check=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, timeout=15).stdout
    rows = json.loads(raw)
    if len(rows) != 1:
        raise ValueError("image inspect did not return exactly one image")
    return rows[0]


def bounded_process(argv: list[str], timeout: int, cap: int = MAX_OUTPUT) -> dict:
    """Collect stdout/stderr under a hard cap and wall deadline."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            close_fds=True)
    sel = selectors.DefaultSelector()
    for stream, label in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
        os.set_blocking(stream.fileno(), False)
        sel.register(stream, selectors.EVENT_READ, label)
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    overflow = False
    deadline = time.monotonic() + timeout
    timed_out = False
    while sel.get_map():
        left = deadline - time.monotonic()
        if left <= 0:
            timed_out = True
            proc.kill()
            break
        for key, _ in sel.select(min(left, 0.2)):
            block = os.read(key.fd, 65536)
            if not block:
                sel.unregister(key.fileobj)
                continue
            dest = chunks[key.data]
            remaining = max(0, cap - sum(len(x) for x in chunks.values()))
            if len(block) > remaining:
                overflow = True
            dest.extend(block[:remaining])
            if overflow:
                proc.kill()
                break
        if overflow:
            break
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    return {"exit_code": proc.returncode, "timed_out": timed_out, "output_exceeded": overflow,
            **{k: bytes(v) for k, v in chunks.items()}}


def docker_argv(image: str, name: str, owner: str, mode: str, argument: str = "") -> list[str]:
    script64 = __import__("base64").b64encode(NODE.encode()).decode()
    args = ["docker", "run", "--name", name, "--label", "esy-reference.owner=" + owner,
            "--platform", "linux/amd64", "--pull=never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--pids-limit", "128",
            "--memory", "2g", "--cpus", "2", "--tmpfs", "/work:rw,nosuid,nodev,exec,size=128m,uid=1000,gid=1000,mode=700",
            "--user", "1000:1000", "--workdir", "/home/opam/esy-reference", "--entrypoint",
            "/home/opam/node/bin/node", image, "-e", "eval(Buffer.from(process.argv[1],'base64').toString())",
            script64, mode]
    if mode == "run":
        args[args.index("--user"):args.index("--user")] = ["--tmpfs", "/home/opam/esy-reference/_esy:rw,nosuid,nodev,exec,size=32m,uid=1000,gid=1000,mode=700",
            "--tmpfs", "/home/opam/esy-reference/node_modules/.cache:rw,nosuid,nodev,exec,size=32m,uid=1000,gid=1000,mode=700"]
    if argument:
        args.append(argument)
    return args


def docker_container_inspect(name: str) -> dict | None:
    p = subprocess.run(["docker", "container", "inspect", name], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=10)
    if p.returncode:
        return None
    rows = json.loads(p.stdout)
    return rows[0] if len(rows) == 1 else None


def cleanup_owned(name: str, owner: str) -> dict:
    obj = docker_container_inspect(name)
    if obj is None:
        return {"verified_absent": False, "reason": "inspect-unavailable"}
    if obj.get("Config", {}).get("Labels", {}).get("esy-reference.owner") != owner:
        return {"verified_absent": False, "reason": "ownership-label-mismatch"}
    rm = subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    absent = docker_container_inspect(name) is None
    return {"remove_exit_code": rm.returncode, "verified_absent": absent,
            "reason": "removed-and-absence-queried" if absent else "absence-query-failed"}


def atomic_json(path: Path, value) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value) + b"\n"
    fd, tmp = tempfile.mkstemp(prefix=".esy-ref-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.link(tmp, path)
        d = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        os.unlink(tmp)
    return digest(data)


def capture_expectations(image: str, output: Path):
    if not IMAGE_RE.fullmatch(image): raise ValueError("capture image must be immutable sha256 ID")
    local = docker_image(BASE_TAG)
    if local.get("Id") != BASE_ID:
        raise ValueError("local base tag does not resolve to the pinned base ID")
    # Capture uses read-only, offline containers and the same confined user.
    owner = secrets.token_hex(16)
    derivative_image = docker_image(image)
    if derivative_image.get("Id") != image: raise ValueError("capture derivative ID mismatch")
    vals = []
    for im, mode in ((BASE_ID, "capture-base"), (image, "capture-derivative")):
        nm = "esy-capture-" + secrets.token_hex(8)
        argv = docker_argv(im, nm, owner, mode)
        result = bounded_process(argv, 30, MAX_CAPTURE)
        obj = docker_container_inspect(nm)
        clean = cleanup_owned(nm, owner) if obj else {"verified_absent": False, "reason": "container-not-inspectable"}
        if result["exit_code"] != 0 or result["timed_out"] or result["output_exceeded"]:
            raise RuntimeError("capture container failed: " + result["stderr"].decode(errors="replace")[:512])
        vals.append(json.loads(result["stdout"]))
        if not clean["verified_absent"]:
            raise RuntimeError("capture cleanup could not verify container absence")
    base, derivative = vals
    layers = derivative_image.get("RootFS", {}).get("Layers", [])
    base_layers = local.get("RootFS", {}).get("Layers", [])
    if layers[:len(base_layers)] != base_layers:
        raise ValueError("derivative image does not preserve the pinned base layer prefix")
    if derivative.get("seedProject") != base["immutable"].get("projectSeed") or derivative.get("seedCache") != base["immutable"].get("cacheSeed"):
        raise ValueError("derivative seed inventories differ from base installation")
    if derivative.get("immutable", {}).get("package") != base["immutable"].get("package") or derivative.get("immutable", {}).get("locks") != base["immutable"].get("locks"):
        raise ValueError("derivative package or lock inventories differ from base installation")
    if derivative.get("compiler") != base.get("compiler"):
        raise ValueError("derivative compiler identity differs from base installation")
    if base.get("compiler", {}).get("version") != "5.5.1" or not base.get("immutable", {}).get("locks"):
        raise ValueError("base installation lacks the expected compiler or lock inventory")
    expectation = {"schema": 1, "base_image": BASE_ID, "image": image,
                   "base_layers": base_layers, "image_layers": layers, "base": base,
                   "derivative": derivative, "runner_sha256": digest(Path(__file__).read_bytes())}
    h = atomic_json(output, expectation)
    return {"status": "PASSED", "expectations": str(output), "sha256": h}


def source_files(case: str) -> dict[str, bytes]:
    main = (HERE / "main.ml").read_bytes()
    if case not in ("suite", "positive", "wrong-result", "syntax"):
        return {}
    files = {"main.ml": main}
    if case in ("suite", "wrong-result"):
        anchor = '  let expected = [ 1; 4; 9; 16 ] in\n  if actual <> expected then failwith "List.map assertion failed";'
        if anchor not in main.decode(): raise ValueError("main.ml fixed derivation anchor changed")
        files["wrong_result.ml"] = main.decode().replace(anchor, '  let expected = [ 0 ] in\n  assert (actual = expected);').encode()
    if case in ("suite", "syntax"):
        files["syntax.ml"] = b"let broken =\n"
    return files


def run(image: str, run_id: str, expectations: Path, output_dir: Path, case: str, timeout: int):
    if not IMAGE_RE.fullmatch(image): raise ValueError("--image must be immutable sha256 ID")
    expectations = expectations.resolve()
    output_dir = output_dir.resolve()
    if expectations.is_relative_to(ROOT) or output_dir.is_relative_to(ROOT):
        raise ValueError("expectations and output directory must be outside the candidate")
    exp_bytes = expectations.read_bytes()
    expected = json.loads(exp_bytes)
    if digest(exp_bytes.rstrip(b"\n")) != digest(canonical(expected)): raise ValueError("expectations are not canonical")
    if expected.get("image") != image or expected.get("base_image") != BASE_ID: raise ValueError("expectation/image binding mismatch")
    img = docker_image(image)
    if img.get("Id") != image: raise ValueError("requested image ID does not match daemon image")
    if img.get("RootFS", {}).get("Layers", [])[:len(expected["base_layers"])] != expected["base_layers"]: raise ValueError("base layer prefix mismatch")
    report_path = output_dir / (run_id + ".json")
    reserve = output_dir / (run_id + ".reserve")
    output_dir.mkdir(parents=True, exist_ok=True)
    if report_path.exists(): raise FileExistsError("immutable report already exists")
    fd = os.open(reserve, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    runner_path = Path(__file__).resolve(); runner_hash = digest(runner_path.read_bytes())
    if expected.get("runner_sha256") != runner_hash: raise ValueError("expectation runner hash mismatch")
    owner = secrets.token_hex(16); name = "esyref-" + secrets.token_hex(16)
    files = source_files(case)
    # Keep payload bounded and deterministic; Docker receives no host mounts.
    cfg = {"case": case, "timeout": timeout, "expected": expected,
           "fixtures": {n: __import__("base64").b64encode(b).decode() for n,b in files.items()}}
    argv = docker_argv(image, name, owner, "run", __import__("base64").b64encode(canonical(cfg)).decode())
    report = {"schema": 1, "id": run_id, "status": "FAILED", "reason": "not-completed", "case": case,
              "fixture_hashes": {n: digest(b) for n,b in files.items()}, "expectation_sha256": digest(exp_bytes),
              "runner_sha256": runner_hash, "image": image, "docker_argv": argv,
              "limits": {"timeout_seconds": timeout, "work_mib": 128, "cache_mib": 32, "memory_mib": 2048},
              "commands": {}, "started_unix": time.time()}
    try:
        streams = bounded_process(argv, timeout + 15, MAX_OUTPUT)
        report["docker_exit_code"] = streams["exit_code"]
        report["docker_stdout"] = streams["stdout"].decode(errors="replace")[:4096]
        report["docker_stderr"] = streams["stderr"].decode(errors="replace")[:4096]
        report["output_exceeded"] = streams["output_exceeded"]
        report["timed_out"] = streams["timed_out"]
        obj = docker_container_inspect(name)
        report["container_inspect"] = obj
        if obj:
            st = obj.get("State", {})
            report["oom_killed"] = bool(st.get("OOMKilled"))
            report["actual_config"] = {"image": obj.get("Image"), "user": obj.get("Config",{}).get("User"),
               "network_mode": obj.get("HostConfig",{}).get("NetworkMode"), "readonly_rootfs": obj.get("HostConfig",{}).get("ReadonlyRootfs"),
               "mounts": obj.get("Mounts",[]), "memory": obj.get("HostConfig",{}).get("Memory"),
               "nano_cpus": obj.get("HostConfig",{}).get("NanoCpus"), "pids_limit": obj.get("HostConfig",{}).get("PidsLimit"),
               "cap_drop": obj.get("HostConfig",{}).get("CapDrop"), "security_opt": obj.get("HostConfig",{}).get("SecurityOpt")}
        else: report["reason"]="container-inspect-failed"
        cleanup = cleanup_owned(name, owner); report["cleanup"] = cleanup
        if streams["timed_out"]: report["reason"]="timeout"
        elif streams["output_exceeded"]: report["reason"]="output-limit"
        elif report.get("oom_killed"): report["reason"]="resource-oom"
        elif streams["exit_code"] == 0:
            try: result=json.loads(streams["stdout"])
            except Exception: result={}
            report["results"]=result
            report["reason"], report["status"] = evaluate(case, result)
        else: report["reason"]="docker-command-failed"
        if not cleanup.get("verified_absent"): report["status"]="FAILED"; report["reason"]="cleanup-unverified"
    finally:
        # The owned container is inspected and removed in the guarded path above.
        pass
    if digest(runner_path.read_bytes()) != runner_hash: report["reason"]="runner-modified"; report["status"]="FAILED"
    report["finished_unix"] = time.time()
    report_hash = atomic_json(report_path, report)
    return report, report_path, report_hash


def evaluate(case: str, result: dict) -> tuple[str, str]:
    cmds = result.get("commands", {})
    if not result.get("immutable_unchanged"): return "immutable-inventory-changed", "FAILED"
    if not result.get("installation_matches_expectation"): return "installation-identity-mismatch", "FAILED"
    if not result.get("compiler_unchanged") or not result.get("compiler_matches_expectation"): return "compiler-identity-changed", "FAILED"
    if not all(result.get("seed_checks", {}).values()): return "seed-mismatch", "FAILED"
    if not result.get("write_probes", {}).get("cache", {}).get("allowed"): return "cache-write-probe-failed", "FAILED"
    if not all(not x.get("allowed") for k,x in result.get("write_probes",{}).items() if k!="cache"): return "readonly-probe-failed", "FAILED"
    if case in ("suite", "positive"):
        p=cmds.get("run-positive",{}); c=cmds.get("compile-positive",{})
        if c.get("exit_code")!=0 or p.get("exit_code")!=0 or p.get("stdout")!="esy-ocaml-reference:passed\n": return "positive-failed", "FAILED"
    if case in ("suite", "wrong-result"):
        if cmds.get("compile-wrong-result",{}).get("exit_code")!=0 or cmds.get("run-wrong-result",{}).get("exit_code")==0 or "Assert_failure" not in cmds.get("run-wrong-result",{}).get("stderr",""): return "wrong-result-control-invalid", "FAILED"
        if case=="wrong-result": return "wrong-result-observed", "FAILED"
    if case in ("suite", "syntax"):
        s=cmds.get("compile-syntax",{}); diag=s.get("stderr","").lower()+s.get("stdout","").lower()
        if s.get("exit_code")==0 or not ("syntax" in diag or "expected" in diag): return "syntax-control-invalid", "FAILED"
        if case=="syntax": return "syntax-failure-observed", "FAILED"
    if case=="timeout":
        if not cmds.get("timeout-loop",{}).get("timed_out"): return "timeout-control-invalid", "FAILED"
        return "timeout-observed", "FAILED"
    if case=="output":
        if not cmds.get("output-flood",{}).get("stdout_truncated"): return "output-control-invalid", "FAILED"
        return "output-limit-observed", "FAILED"
    if case=="resource":
        if not (result.get("resource_exceeded") or result.get("oom_killed")): return "resource-control-unconfirmed", "FAILED"
        return ("resource-oom-observed" if result.get("oom_killed") else "resource-pressure-observed"), "FAILED"
    return "controls-observed", "PASSED"


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", required=True); p.add_argument("--run-id")
    p.add_argument("--expectations", type=Path); p.add_argument("--output-dir", type=Path)
    p.add_argument("--capture-expectations", type=Path)
    p.add_argument("--case", choices=("suite","positive","wrong-result","syntax","timeout","output","resource"),default="suite")
    p.add_argument("--timeout", type=int, default=120)
    a=p.parse_args(argv)
    try:
        if a.timeout<1 or a.timeout>120: raise ValueError("--timeout must be 1..120")
        if a.capture_expectations:
            if a.run_id: raise ValueError("--capture-expectations is mutually exclusive with --run-id")
            if a.capture_expectations.resolve().is_relative_to(ROOT): raise ValueError("expectations must be outside the candidate")
            result=capture_expectations(a.image,a.capture_expectations)
        else:
            if not a.run_id or not RUN_RE.fullmatch(a.run_id): raise ValueError("valid --run-id required")
            if not a.expectations or not a.output_dir: raise ValueError("--expectations and --output-dir required")
            result,path,h=run(a.image,a.run_id,a.expectations,a.output_dir,a.case,a.timeout)
            result={"status":result["status"],"reason":result["reason"],"report":str(path),"report_sha256":h}
        print(json.dumps(result,sort_keys=True)); return 0 if result["status"]=="PASSED" else 1
    except Exception as e:
        print(json.dumps({"status":"FAILED","reason":"input-or-supervisor-error","error":f"{type(e).__name__}: {e}"},sort_keys=True)); return 2

if __name__=="__main__": raise SystemExit(main())
