#!/usr/bin/env python3
"""Bounded, offline Docker runner for the fixed esy reference project.

Capture is performed by the supervisor before ordinary runs. Container payloads
are canonical JSON on stdin; no manifest content is placed in argv or evaluated.
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE_TAG = "ocaml-sft-esy-project-probe:001"
BASE_ID = "sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267"
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_EXPECTATIONS = 1024 * 1024
MAX_PAYLOAD = 512 * 1024
MAX_DOCKER_BYTES = 1024 * 1024
MAX_REPORT = 256 * 1024
DEFAULT_TIMEOUT = 120


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def read_bounded(path: Path, limit: int) -> bytes:
    st = path.lstat()
    if not path.is_file() or path.is_symlink() or st.st_size > limit:
        raise ValueError(f"input must be a regular file no larger than {limit} bytes")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"input exceeds {limit} byte limit")
    return data


def bounded_process(argv: list[str], timeout: float, cap: int = MAX_DOCKER_BYTES,
                    stdin: bytes | None = None) -> dict:
    """Drain both pipes and bounded stdin under one monotonic deadline."""
    if os.name != "posix":
        raise RuntimeError("runner requires POSIX process-group supervision")
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                            close_fds=True)
    sel = selectors.DefaultSelector()
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    stream_hashes = {"stdout": hashlib.sha256(), "stderr": hashlib.sha256()}
    stream_sizes = {"stdout": 0, "stderr": 0}
    total = 0
    overflow = False
    sent = 0
    if stdin is not None:
        os.set_blocking(proc.stdin.fileno(), False)
        sel.register(proc.stdin, selectors.EVENT_WRITE, "stdin")
    for label, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        os.set_blocking(pipe.fileno(), False)
        sel.register(pipe, selectors.EVENT_READ, label)
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        while sel.get_map():
            left = deadline - time.monotonic()
            if left <= 0:
                timed_out = True
                break
            for key, _ in sel.select(min(left, .1)):
                if key.data == "stdin":
                    if sent == len(stdin):
                        sel.unregister(key.fileobj); key.fileobj.close(); continue
                    try:
                        sent += os.write(key.fd, stdin[sent:sent + 65536])
                    except BrokenPipeError:
                        sel.unregister(key.fileobj); key.fileobj.close()
                else:
                    block = os.read(key.fd, 65536)
                    if not block:
                        sel.unregister(key.fileobj); continue
                    total += len(block)
                    stream_sizes[key.data] += len(block)
                    stream_hashes[key.data].update(block)
                    room = max(0, cap - sum(map(len, streams.values())))
                    streams[key.data].extend(block[:room])
                    if total > cap:
                        overflow = True
                        break
            if overflow:
                break
        if proc.poll() is None and (timed_out or overflow):
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=2)
    finally:
        if proc.poll() is None:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired: pass
        sel.close()
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                try: pipe.close()
                except OSError: pass
    return {"exit_code": proc.returncode, "timed_out": timed_out, "output_exceeded": overflow,
            "total_bytes": total, "stdout_total_bytes": stream_sizes["stdout"],
            "stderr_total_bytes": stream_sizes["stderr"],
            "stdout_full_sha256": stream_hashes["stdout"].hexdigest(),
            "stderr_full_sha256": stream_hashes["stderr"].hexdigest(),
            "stdout": bytes(streams["stdout"]), "stderr": bytes(streams["stderr"])}


# Fixed in-container program. It accepts only bounded JSON from stdin and fixed
# mode names. Filesystem identities are checked before esy/compiler execution.
NODE = r'''const fs=require('fs'),path=require('path'),crypto=require('crypto'),cp=require('child_process');
const mode=process.argv[2], hash=b=>crypto.createHash('sha256').update(b).digest('hex');
function inventory(root){let rows=[];function walk(p,rel){let s=fs.lstatSync(p);if(s.isSymbolicLink()||(!s.isDirectory()&&!s.isFile()))throw Error('unsafe inventory type: '+(rel||'.'));let row={path:rel||'.',type:s.isDirectory()?'dir':'file',mode:s.mode&0o777,uid:s.uid,gid:s.gid,mtime_ms:Math.floor(s.mtimeMs)};if(s.isFile()){row.bytes=s.size;row.sha256=hash(fs.readFileSync(p))}rows.push(row);if(s.isDirectory())for(const n of fs.readdirSync(p).sort())walk(path.join(p,n),rel?rel+'/'+n:n)}walk(root,'');return rows}
function run(cmd,args,deadline,max=32768){let left=Math.max(1,deadline-Date.now());let r=cp.spawnSync(cmd,args,{encoding:'utf8',timeout:left,maxBuffer:max,killSignal:'SIGKILL',env:process.env});return {exit_code:r.status,signal:r.signal||null,timed_out:!!(r.error&&r.error.code==='ETIMEDOUT'),error:r.error?String(r.error):null,error_code:r.error&&r.error.code||null,stdout:(r.stdout||'').slice(0,8192),stderr:(r.stderr||'').slice(0,8192),stdout_bytes:Buffer.byteLength(r.stdout||''),stderr_bytes:Buffer.byteLength(r.stderr||'')}}
function immutable(baseCapture=false){let root='/home/opam/esy-reference';let names=fs.readdirSync(root).filter(n=>n==='package.json'||n==='esy.lock'||n==='npm-shrinkwrap.json'||/(^|[-.])lock(file|b)?([-.]|$)/i.test(n)).sort();if(!names.includes('package.json')||!names.includes('esy.lock'))throw Error('required manifest/lock missing');let project=[];for(let n of names)project.push(...inventory(path.join(root,n)).map(x=>({...x,path:n+(x.path==='.'?'':'/'+x.path)})));let installation=inventory(path.join(root,'_esy')),node_cache=inventory(path.join(root,'node_modules/.cache'));return {project,installation,node_cache,seed:baseCapture?installation:inventory('/home/opam/esy-cache-seed/_esy'),node_seed:baseCapture?node_cache:inventory('/home/opam/esy-cache-seed/node-cache')}}
function findCompiler(){let root='/home/opam/.esy';let found=[];function walk(d){for(let n of fs.readdirSync(d)){let p=path.join(d,n),s=fs.lstatSync(p);if(s.isDirectory())walk(p);else if(n==='ocamlopt'&&(s.mode&0o111)){let real=fs.realpathSync(p);if(!found.includes(real))found.push(real)}}}walk(root);if(found.length!==1)throw Error('expected one canonical ocamlopt in /home/opam/.esy, got '+found.length);let p=found[0],s=fs.statSync(p);return {path:p,bytes:s.size,mode:s.mode&0o777,sha256:hash(fs.readFileSync(p))}}
function main(){if(mode.startsWith('capture-')){let i=immutable(mode==='capture-base'),c=findCompiler();if(mode==='capture-base'){let v=run(c.path,['-version'],Date.now()+5000);if(v.exit_code!==0||!v.stdout.includes('5.5.1'))throw Error('pinned compiler version mismatch');c.version=v.stdout.trim()}return {immutable:i,compiler:c}}let raw=fs.readFileSync(0);if(raw.length>524288)throw Error('payload exceeds limit');let cfg=JSON.parse(raw.toString('utf8')),deadline=Date.now()+cfg.timeout*1000;
function copy(src,dst){let rootStat=fs.statSync(src);fs.mkdirSync(dst,{recursive:true,mode:rootStat.mode&0o777});for(let n of fs.readdirSync(src)){let a=path.join(src,n),b=path.join(dst,n),s=fs.lstatSync(a);if(s.isSymbolicLink())throw Error('seed symlink forbidden');if(s.isDirectory())copy(a,b);else if(s.isFile()){fs.copyFileSync(a,b);fs.chmodSync(b,s.mode&0o777);fs.utimesSync(b,s.atime,s.mtime)}else throw Error('unsafe seed type')}fs.chmodSync(dst,rootStat.mode&0o777);fs.utimesSync(dst,rootStat.atime,rootStat.mtime)}
copy('/home/opam/esy-cache-seed/_esy','/home/opam/esy-reference/_esy');copy('/home/opam/esy-cache-seed/node-cache','/home/opam/esy-reference/node_modules/.cache');
let start=immutable(),expected=cfg.expected,commands={},compiler=findCompiler();
if(JSON.stringify(start.project)!==JSON.stringify(expected.derivative.immutable.project)||JSON.stringify(start.seed)!==JSON.stringify(expected.derivative.immutable.seed)||JSON.stringify(start.node_seed)!==JSON.stringify(expected.derivative.immutable.node_seed)||JSON.stringify(start.installation)!==JSON.stringify(expected.derivative.immutable.installation)||JSON.stringify(start.node_cache)!==JSON.stringify(expected.derivative.immutable.node_cache))throw Object.assign(Error('integrity gate: derivative inventory mismatch'),{gate:'derivative-inventory'});
if(JSON.stringify(compiler)!==JSON.stringify((( {path,bytes,mode,sha256})=>({path,bytes,mode,sha256}))(expected.base.compiler)))throw Object.assign(Error('integrity gate: compiler identity mismatch'),{gate:'compiler-static'});
let esy=run('/home/opam/esy/bin/esy',['sh','-c','command -v ocamlopt'],deadline,8192);commands.esy_lookup=esy;if(esy.exit_code!==0||esy.timed_out||esy.stdout.trim()!==compiler.path)throw Object.assign(Error('integrity gate: esy compiler path mismatch'),{gate:'esy-lookup'});
let cv=run(compiler.path,['-version'],deadline);commands.compiler_version=cv;if(cv.exit_code!==0||!cv.stdout.includes('5.5.1'))throw Object.assign(Error('compiler version failed'),{gate:'compiler-version'});
let probes={};for(let [k,p] of Object.entries({esy_cache:'/home/opam/esy-reference/_esy',node_cache:'/home/opam/esy-reference/node_modules/.cache'})){try{let f=path.join(p,'.write-probe-'+process.pid);fs.writeFileSync(f,'ok',{flag:'wx'});fs.unlinkSync(f);probes[k]={path:p,exists:true,operation:'exclusive-create-delete',allowed:true}}catch(e){probes[k]={path:p,exists:e.code!=='ENOENT',operation:'exclusive-create-delete',allowed:false,code:e.code}}}
let lockRow=start.project.find(x=>x.path.startsWith('esy.lock/')&&x.type==='file');if(!lockRow)throw Error('no inventoried existing lock target');for(let [k,p] of Object.entries({package:'/home/opam/esy-reference/package.json',lock:'/home/opam/esy-reference/'+lockRow.path,compiler:compiler.path})){try{let fd=fs.openSync(p,'r+');fs.closeSync(fd);probes[k]={path:p,exists:true,operation:'open-r+',allowed:true}}catch(e){probes[k]={path:p,exists:e.code!=='ENOENT',operation:'open-r+',allowed:false,code:e.code}}}
let files=cfg.fixtures||{};for(let [n,b64] of Object.entries(files)){if(!/^[a-z0-9_-]+\.ml$/.test(n))throw Error('bad fixture name');let b=Buffer.from(b64,'base64');if(b.toString('base64')!==b64)throw Error('bad fixture encoding');fs.writeFileSync('/work/'+n,b,{mode:0o444})}
function invoke(label,cmd,args){let r=run(cmd,args,deadline);commands[label]=r;return r}let src='/work',esybin='/home/opam/esy/bin/esy';function compile(label,file,out){return invoke(label,esybin,['ocamlopt','-o',src+'/'+out,src+'/'+file])}function exec(label,bin){return invoke(label,src+'/'+bin,[])}
let c=cfg.case;if(['suite','positive','wrong-result','syntax'].includes(c)){let kinds=c==='suite'?['positive','wrong-result','syntax']:[c];if(kinds.includes('positive')){let r=compile('compile-positive','main.ml','positive.exe');if(r.exit_code===0)exec('run-positive','positive.exe')}if(kinds.includes('wrong-result')){let r=compile('compile-wrong-result','wrong_result.ml','wrong.exe');if(r.exit_code===0)exec('run-wrong-result','wrong.exe')}if(kinds.includes('syntax'))compile('compile-syntax','syntax.ml','syntax.exe')}
if(c==='timeout'||c==='output'||c==='resource'){let file={timeout:'loop.ml',output:'output.ml',resource:'memory.ml'}[c],exe={timeout:'loop.exe',output:'output.exe',resource:'memory.exe'}[c],r=compile('compile-'+c,file,exe);if(r.exit_code===0){let x=invoke('run-'+c,src+'/'+exe,[]);if(x.timed_out)x.reason='command-timeout';if(x.error_code==='ENOBUFS'||x.stdout_bytes>32768||x.stderr_bytes>32768)x.reason='command-output-overflow';if(x.error_code==='ENOMEM'||/Out of memory/.test(x.stderr))x.reason='allocation-failure';if(x.signal==='SIGKILL'&&!x.timed_out)x.reason='unattributed-signal'}}
let end=immutable();return {stage:'completed',case:c,commands,probes,pre_inventory:start,post_inventory:end,immutable_unchanged:JSON.stringify(start.project)===JSON.stringify(end.project),compiler,compiler_unchanged:JSON.stringify(compiler)===JSON.stringify(findCompiler())}}
try{process.stdout.write(JSON.stringify(main()))}catch(e){process.stdout.write(JSON.stringify({stage:'integrity-or-harness-failure',gate:e.gate||null,error:String(e),stack:String(e.stack||'')}));process.exitCode=2}
'''


def docker_image(image: str) -> dict:
    p = bounded_process(["docker", "image", "inspect", image], 15)
    if p["exit_code"] != 0 or p["timed_out"] or p["output_exceeded"]:
        raise RuntimeError("bounded image inspection failed")
    rows = json.loads(p["stdout"])
    if len(rows) != 1 or rows[0].get("Id") != image:
        raise ValueError("image must resolve to its exact immutable ID")
    return rows[0]


def docker_container_inspect(container_id: str) -> tuple[str, dict | None]:
    p = bounded_process(["docker", "container", "inspect", container_id], 10)
    if p["timed_out"] or p["output_exceeded"]:
        return "query-failed", None
    if p["exit_code"]:
        # A successful daemon query with an exact no-such-container response is absence.
        err = p["stderr"].decode("utf-8", "replace").lower()
        return ("absent", None) if "no such container" in err else ("query-failed", None)
    try:
        rows = json.loads(p["stdout"])
        return ("present", rows[0]) if len(rows) == 1 else ("query-failed", None)
    except (ValueError, TypeError):
        return "query-failed", None


def cleanup_owned(container_id: str | None, owner: str) -> dict:
    if not container_id:
        return {"verified_absent": False, "reason": "container-id-unavailable"}
    state, obj = docker_container_inspect(container_id)
    if state == "absent": return {"verified_absent": True, "reason": "daemon-confirmed-absent"}
    if state != "present": return {"verified_absent": False, "reason": "inspect-query-failed"}
    labels = obj.get("Config", {}).get("Labels", {}) or {}
    if obj.get("Id") != container_id or labels.get("esy-reference.owner") != owner:
        return {"verified_absent": False, "reason": "ownership-mismatch"}
    rm = bounded_process(["docker", "rm", "-f", container_id], 10)
    state2, _ = docker_container_inspect(container_id)
    return {"remove_exit_code": rm["exit_code"], "verified_absent": state2 == "absent",
            "reason": "removed-and-daemon-confirmed-absent" if state2 == "absent" else "absence-unverified"}


def docker_create(image: str, name: str, owner: str, mode: str) -> list[str]:
    argv = ["docker", "create", "-i", "--name", name, "--label", "esy-reference.owner="+owner,
            "--platform", "linux/amd64", "--pull=never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--pids-limit", "128",
            "--memory", "2g", "--cpus", "2", "--tmpfs", "/work:rw,nosuid,nodev,exec,size=128m,uid=1000,gid=1000,mode=700",
            "--user", "1000:1000", "--workdir", "/home/opam/esy-reference", "--entrypoint",
            "/home/opam/node/bin/node", image, "-e", NODE, mode]
    if mode == "run":
        argv[2:2] = ["--tmpfs", "/home/opam/esy-reference/_esy:rw,nosuid,nodev,exec,size=32m,uid=1000,gid=1000,mode=700",
                     "--tmpfs", "/home/opam/esy-reference/node_modules/.cache:rw,nosuid,nodev,exec,size=32m,uid=1000,gid=1000,mode=700"]
    return argv


def validate_config(obj: dict, image: str, owner: str, mode: str) -> None:
    c, h = obj.get("Config", {}), obj.get("HostConfig", {})
    if obj.get("Image") != image or c.get("User") != "1000:1000" or c.get("WorkingDir") != "/home/opam/esy-reference":
        raise ValueError("container identity/user/workdir mismatch")
    if (c.get("Labels", {}) or {}).get("esy-reference.owner") != owner:
        raise ValueError("container ownership label mismatch")
    if h.get("NetworkMode") != "none" or h.get("ReadonlyRootfs") is not True or h.get("Memory") != 2*1024**3 or h.get("NanoCpus") != 2_000_000_000 or h.get("PidsLimit") != 128:
        raise ValueError("effective resource configuration mismatch")
    if h.get("CapDrop") != ["ALL"] or "no-new-privileges:true" not in (h.get("SecurityOpt") or []):
        raise ValueError("effective security configuration mismatch")
    if c.get("Volumes"):
        raise ValueError("image declares unexpected volumes")
    expected = {"/work":"rw,nosuid,nodev,exec,size=128m,uid=1000,gid=1000,mode=700"}
    if mode == "run": expected.update({"/home/opam/esy-reference/_esy":"rw,nosuid,nodev,exec,size=32m,uid=1000,gid=1000,mode=700",
                                        "/home/opam/esy-reference/node_modules/.cache":"rw,nosuid,nodev,exec,size=32m,uid=1000,gid=1000,mode=700"})
    if h.get("Tmpfs") != expected:
        raise ValueError("effective tmpfs destinations/options mismatch")
    mounts = obj.get("Mounts", [])
    if not isinstance(mounts, list) or {m.get("Destination") for m in mounts} != set(expected) or any(m.get("Type") != "tmpfs" or not m.get("RW") for m in mounts):
        raise ValueError("effective mount set mismatch")


def capture_expectations(image: str, output: Path) -> dict:
    if not IMAGE_RE.fullmatch(image): raise ValueError("capture image must be immutable sha256 ID")
    base = docker_image(BASE_TAG)
    if base.get("Id") != BASE_ID: raise ValueError("local base tag does not resolve to pinned ID")
    derivative = docker_image(image)
    if derivative.get("Config", {}).get("Volumes"):
        raise ValueError("derivative declares unexpected image volumes")
    base_layers = base.get("RootFS", {}).get("Layers", [])
    layers = derivative.get("RootFS", {}).get("Layers", [])
    if not base_layers or layers[:len(base_layers)] != base_layers: raise ValueError("derivative layer prefix mismatch")
    owner = secrets.token_hex(16); captures=[]
    for im, mode in ((BASE_ID,"capture-base"),(image,"capture-derivative")):
        name="esyref-cap-"+secrets.token_hex(8); cid=None; clean={"verified_absent":False,"reason":"not-started"}
        try:
            create=bounded_process(docker_create(im,name,owner,mode),15)
            if create["exit_code"] or create["timed_out"]: raise RuntimeError("container create failed")
            cid=create["stdout"].decode().strip()
            st,obj=docker_container_inspect(cid)
            if st!="present": raise RuntimeError("created container inspection failed")
            validate_config(obj,im,owner,mode)
            result=bounded_process(["docker","start","-ai",cid],30,MAX_DOCKER_BYTES)
            if result["exit_code"] or result["timed_out"] or result["output_exceeded"]: raise RuntimeError("capture execution failed")
            captures.append(json.loads(result["stdout"]))
        finally:
            clean=cleanup_owned(cid,owner)
            if not clean["verified_absent"]: raise RuntimeError("capture cleanup unverified: "+clean["reason"])
    b,d=captures
    bi,di=b.get("immutable",{}),d.get("immutable",{})
    bc,dc=b.get("compiler",{}),d.get("compiler",{})
    compiler_static=lambda c:{k:c.get(k) for k in ("path","bytes","mode","sha256")}
    if (compiler_static(bc)!=compiler_static(dc) or bc.get("version")!="5.5.1" or bi.get("project")!=di.get("project") or
        bi.get("installation")!=di.get("installation") or bi.get("node_cache")!=di.get("node_cache") or
        bi.get("installation")!=di.get("seed") or bi.get("node_cache")!=di.get("node_seed")):
        raise ValueError("derivative compiler, installation, or seed inventory differs from base")
    source={}
    for name in ("run_esy_reference.py","Dockerfile.esy-runtime","main.ml","package.json","esy.lock"):
        p=HERE/name
        if p.is_file(): source[name]=sha(read_bounded(p,1024*1024))
    value={"schema_version":1,"base_image":BASE_ID,"image":image,"base_layers":base_layers,
           "image_layers":layers,"base":b,"derivative":d,"source_sha256":source}
    if len(canonical(value))+1>MAX_EXPECTATIONS: raise ValueError("captured expectations exceed size limit")
    atomic_json(output,value)
    return {"status":"PASSED","expectations":str(output),"sha256":sha(canonical(value)+b"\n")}


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); data=canonical(value)+b"\n"
    fd,tmp=tempfile.mkstemp(prefix=".esyref-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.link(tmp,path); d=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(d)
        finally: os.close(d)
    finally: os.unlink(tmp)


def source_files(case: str) -> dict[str, bytes]:
    main=read_bounded(HERE/"main.ml",64*1024)
    result={"main.ml":main}
    if case in ("suite","wrong-result"):
        text=main.decode(); anchor='  let expected = [ 1; 4; 9; 16 ] in\n  if actual <> expected then failwith "List.map assertion failed";'
        if text.count(anchor)!=1: raise ValueError("fixed main.ml derivation anchor changed")
        result["wrong_result.ml"]=text.replace(anchor,'  let expected = [ 0 ] in\n  assert (actual = expected);').encode()
    if case in ("suite","syntax"): result["syntax.ml"]=b"let broken =\n"
    if case in ("timeout","output","resource"):
        result[{"timeout":"loop.ml","output":"output.ml","resource":"memory.ml"}[case]]={
            "timeout":b"let () = while true do () done\n",
            "output":b"let () = while true do print_endline (String.make 4096 'x'); flush stdout done\n",
            "resource":b"let () = let rec grow xs = let x=Bytes.create 65536 in Bytes.fill x 0 65536 'x'; grow (x::xs) in grow []\n"}[case]
    return result


def evaluate(case: str, result: dict) -> tuple[str,str]:
    if result.get("stage")!="completed": return "integrity-gate-failed","FAILED"
    cmds=result.get("commands",{}); probes=result.get("probes",{})
    if not result.get("immutable_unchanged") or not result.get("compiler_unchanged"): return "immutable-integrity-failed","FAILED"
    if not all(probes.get(k,{}).get("allowed") is True and probes.get(k,{}).get("exists") is True and probes.get(k,{}).get("operation")=="exclusive-create-delete" for k in ("esy_cache","node_cache")): return "cache-write-probe-failed","FAILED"
    if not all(probes.get(k,{}).get("exists") is True and probes.get(k,{}).get("operation")=="open-r+" and probes.get(k,{}).get("allowed") is False and probes.get(k,{}).get("code") in ("EROFS","EACCES") for k in ("package","lock","compiler")): return "readonly-probe-failed","FAILED"
    def normal(label,code):
        c=cmds.get(label,{})
        return c.get("exit_code")==code and c.get("signal") is None and not c.get("timed_out") and c.get("error") is None
    def failed_normally(label):
        c=cmds.get(label,{})
        return isinstance(c.get("exit_code"),int) and c.get("exit_code")!=0 and c.get("signal") is None and not c.get("timed_out") and c.get("error") is None
    if case in ("positive","suite"):
        if not normal("compile-positive",0) or not normal("run-positive",0) or cmds["run-positive"].get("stdout")!="esy-ocaml-reference:passed\n": return "positive-failed","FAILED"
    if case in ("wrong-result","suite"):
        if not normal("compile-wrong-result",0) or not failed_normally("run-wrong-result") or "Assert_failure" not in cmds["run-wrong-result"].get("stderr",""): return "wrong-result-control-invalid","FAILED"
        if case=="wrong-result": return "wrong-result-observed","FAILED"
    if case in ("syntax","suite"):
        s=cmds.get("compile-syntax",{}); diag=s.get("stderr","")
        if s.get("exit_code")==0 or s.get("signal") is not None or s.get("timed_out") or not re.search(r"(?m)^Error: Syntax error",diag): return "syntax-control-invalid","FAILED"
        if case=="syntax": return "syntax-failure-observed","FAILED"
    if case in ("timeout","output","resource"):
        c=cmds.get("run-"+case,{})
        if not normal("compile-"+case,0): return "control-fixture-did-not-compile","FAILED"
        reason=c.get("reason")
        if case=="timeout" and reason!="command-timeout": return "timeout-not-observed","FAILED"
        if case=="output" and reason!="command-output-overflow": return "output-overflow-not-observed","FAILED"
        if case=="resource" and reason!="allocation-failure": return "allocation-pressure-not-observed","FAILED"
        if case=="resource": return "resource-allocation-failure-observed","FAILED"
        return case+"-observed","FAILED"
    return "controls-passed","PASSED"


def run(image:str,run_id:str,expectations:Path,output_dir:Path,case:str,timeout:int)->tuple[dict,Path,str]:
    if not IMAGE_RE.fullmatch(image): raise ValueError("--image must be immutable sha256 ID")
    if expectations.is_symlink(): raise ValueError("expectations cannot be a symlink")
    exp_path=expectations.resolve(strict=True); out=output_dir.resolve()
    if exp_path.is_relative_to(ROOT) or out.is_relative_to(ROOT): raise ValueError("expectations/output must be outside candidate")
    raw=read_bounded(exp_path,MAX_EXPECTATIONS); expected=json.loads(raw)
    if raw.rstrip(b"\n")!=canonical(expected): raise ValueError("expectations must be canonical JSON")
    if expected.get("schema_version")!=1 or expected.get("image")!=image or expected.get("base_image")!=BASE_ID: raise ValueError("expectation identity mismatch")
    runner=Path(__file__).resolve(); runner_hash=sha(read_bounded(runner,1024*1024))
    for name in ("run_esy_reference.py", "Dockerfile.esy-runtime", "main.ml"):
        path = HERE / name
        if expected.get("source_sha256", {}).get(name) != sha(read_bounded(path, 1024*1024)):
            raise ValueError("reviewed source hash mismatch: " + name)
    img=docker_image(image)
    if img.get("Config", {}).get("Volumes"):
        raise ValueError("image declares unexpected volumes")
    layers=img.get("RootFS",{}).get("Layers",[])
    if layers!=expected.get("image_layers") or layers[:len(expected.get("base_layers",[]))]!=expected.get("base_layers"): raise ValueError("image layer identity mismatch")
    files=source_files(case)
    cfg={"case":case,"timeout":timeout,"expected":expected,"fixtures":{k:v.decode("latin1").encode("latin1").hex() for k,v in files.items()}}
    # Node decodes fixture hex; bounded payload is one JSON stdin document.
    cfg["fixtures"]={k:__import__("base64").b64encode(v).decode("ascii") for k,v in files.items()}
    payload=canonical(cfg)
    if len(payload)>MAX_PAYLOAD: raise ValueError("container payload exceeds bound")
    out.mkdir(parents=True,exist_ok=True); report_path=out/(run_id+".json"); reserve=out/(run_id+".reserve")
    if report_path.exists() or report_path.is_symlink(): raise FileExistsError("immutable report already exists")
    fd=os.open(reserve,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
    report={"schema":1,"id":run_id,"status":"FAILED","reason":"reserved-attempt-not-completed","case":case,
            "image":image,"runner_sha256":runner_hash,"source_sha256":expected["source_sha256"],"expectation_sha256":sha(raw),"fixture_hashes":{k:sha(v) for k,v in files.items()},
            "timeout_seconds":timeout,"cleanup":{"verified_absent":False,"reason":"not-started"},"stage":"reserved"}
    name="esyref-"+secrets.token_hex(12); owner=secrets.token_hex(16); cid=None
    try:
        create=bounded_process(docker_create(image,name,owner,"run"),15)
        if create["exit_code"] or create["timed_out"]: raise RuntimeError("docker create failed")
        cid=create["stdout"].decode().strip()
        if not re.fullmatch(r"[0-9a-f]{64}",cid): raise RuntimeError("docker create did not return an exact container ID")
        report["container_id"]=cid
        state,obj=docker_container_inspect(cid)
        if state!="present": raise RuntimeError("container inspect query failed")
        validate_config(obj,image,owner,"run")
        report["actual_config"]={"image":obj.get("Image"),"user":obj.get("Config",{}).get("User"),"workdir":obj.get("Config",{}).get("WorkingDir"),"host_config":obj.get("HostConfig",{}),"mounts":obj.get("Mounts",[])}
        result=bounded_process(["docker","start","-ai",cid],DEFAULT_TIMEOUT,MAX_DOCKER_BYTES,payload)
        inspect_state,inspect_obj=docker_container_inspect(cid)
        report["container_state_query"]=inspect_state
        if inspect_state=="present": report["oom_killed"]=bool(inspect_obj.get("State",{}).get("OOMKilled"))
        report.update({"stage":"container-finished","docker_exit_code":result["exit_code"],"timed_out":result["timed_out"],"output_exceeded":result["output_exceeded"],"docker_stdout_bytes":result["stdout_total_bytes"],"docker_stdout_full_sha256":result["stdout_full_sha256"],"docker_stdout_retained_sha256":sha(result["stdout"]),"docker_stderr_bytes":result["stderr_total_bytes"],"docker_stderr_full_sha256":result["stderr_full_sha256"],"docker_stderr":result["stderr"].decode("utf-8","replace")[:2048]})
        if result["timed_out"]: report["reason"]="host-deadline"
        elif result["output_exceeded"]: report["reason"]="docker-output-overflow"
        elif report.get("oom_killed") and case=="resource": report["reason"]="resource-oom-observed"
        elif result["exit_code"]==0:
            obj_result=json.loads(result["stdout"]); report["results"]=obj_result; report["reason"],report["status"]=evaluate(case,obj_result)
        else: report["reason"]="container-nonzero"
    except BaseException as exc:
        report["reason"]="supervisor-error"; report["error"]=f"{type(exc).__name__}: {exc}"
    finally:
        try: report["cleanup"]=cleanup_owned(cid,owner)
        except BaseException as exc: report["cleanup"]={"verified_absent":False,"reason":"cleanup-exception","error":f"{type(exc).__name__}: {exc}"}
        if not report["cleanup"].get("verified_absent"): report["status"]="FAILED"; report["reason"]="cleanup-unverified"
        try:
            for input_name in ("run_esy_reference.py", "Dockerfile.esy-runtime", "main.ml"):
                if sha(read_bounded(HERE/input_name,1024*1024))!=expected["source_sha256"][input_name]:
                    report["status"]="FAILED"; report["reason"]="source-modified"; report["source_mismatch"]=input_name
        except BaseException as exc: report["status"]="FAILED"; report["reason"]="source-recheck-failed"; report["source_error"]=str(exc)
        report["finished_unix"]=time.time()
        data=canonical(report)+b"\n"
        if len(data)>MAX_REPORT: report={"schema":1,"id":run_id,"status":"FAILED","reason":"report-size-bound","cleanup":report["cleanup"]}; data=canonical(report)+b"\n"
        atomic_json(report_path,report)
    return report,report_path,sha(data)


def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--image",required=True); p.add_argument("--run-id"); p.add_argument("--expectations",type=Path); p.add_argument("--output-dir",type=Path); p.add_argument("--capture-expectations",type=Path)
    p.add_argument("--case",choices=("suite","positive","wrong-result","syntax","timeout","output","resource"),default="suite"); p.add_argument("--timeout",type=int,default=120); a=p.parse_args(argv)
    try:
        if not 1<=a.timeout<=120: raise ValueError("--timeout must be 1..120")
        if a.capture_expectations:
            if a.run_id: raise ValueError("capture cannot be combined with run ID")
            if a.capture_expectations.is_symlink(): raise ValueError("capture output cannot be a symlink")
            if a.capture_expectations.resolve().is_relative_to(ROOT): raise ValueError("capture output must be outside candidate")
            result=capture_expectations(a.image,a.capture_expectations)
        else:
            if not a.run_id or not RUN_RE.fullmatch(a.run_id) or not a.expectations or not a.output_dir: raise ValueError("valid run ID, expectations and output directory required")
            result,path,h=run(a.image,a.run_id,a.expectations,a.output_dir,a.case,a.timeout); result={"status":result["status"],"reason":result["reason"],"report":str(path),"report_sha256":h}
        print(json.dumps(result,sort_keys=True)); return 0 if result["status"]=="PASSED" else 1
    except Exception as exc:
        if a.capture_expectations and not a.capture_expectations.is_symlink() and not a.capture_expectations.resolve().is_relative_to(ROOT):
            failure_path=a.capture_expectations.with_name(a.capture_expectations.name+".failure.json")
            try:
                atomic_json(failure_path,{"schema":1,"status":"FAILED","reason":"capture-failed",
                                          "error":f"{type(exc).__name__}: {exc}","finished_unix":time.time()})
            except Exception:
                pass
        print(json.dumps({"status":"FAILED","reason":"input-or-supervisor-error","error":f"{type(exc).__name__}: {exc}"},sort_keys=True)); return 2


if __name__=="__main__": raise SystemExit(main())
