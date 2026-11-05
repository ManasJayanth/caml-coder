#!/usr/bin/env python3
"""Probe fixed esy-managed OCaml compiler references in a pinned offline image."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[3]
PROPOSAL = Path(__file__).resolve().parent
SOURCE_PATH = PROPOSAL / "main.ml"
RESULTS = PROPOSAL / "esy-results"
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_INPUT = 128 * 1024
MAX_SOURCE = 32 * 1024
MAX_LOG = 8 * 1024
MAX_EXCERPT = MAX_LOG
TIMEOUT = 120


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def source_bundle():
    if SOURCE_PATH.is_symlink():
        raise ValueError("main.ml symlink forbidden")
    main = SOURCE_PATH.read_bytes()
    if not 0 < len(main) <= MAX_SOURCE:
        raise ValueError("main.ml is empty or exceeds the size bound")
    anchor = '  let expected = [ 1; 4; 9; 16 ] in\n  if actual <> expected then failwith "List.map assertion failed";'
    if anchor not in main.decode("utf-8"):
        raise ValueError("reviewed main.ml no longer matches the fixed wrong-result derivation")
    wrong = main.decode("utf-8").replace(anchor,
        '  let expected = [ 0 ] in\n  assert (actual = expected);').encode("utf-8")
    invalid_anchor = '  let actual = List.map square [ 1; 2; 3; 4 ] in'
    if invalid_anchor not in main.decode("utf-8"):
        raise ValueError("reviewed main.ml no longer matches the fixed malformed-source derivation")
    malformed = main.decode("utf-8").replace(invalid_anchor,
        '  let actual = List.map square [ 1; 2; 3; 4 ] in +').encode("utf-8")
    files = {"main.ml": main, "wrong_result.ml": wrong, "malformed.ml": malformed}
    archive = io.BytesIO()
    rows, total = [], 0
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, raw in files.items():
            total += len(raw)
            if len(raw) > MAX_SOURCE or total > MAX_INPUT:
                raise ValueError("fixed source bundle exceeds size limit")
            rows.append({"path": name, "bytes": len(raw), "sha256": sha(raw)})
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.uid, info.gid = len(raw), 0o644, 1000, 1000
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(raw))
    return archive.getvalue(), rows, total


def container_script(nonce: str) -> str:
    tag = f"ESYREF_{nonce}_"
    return f'''#!/bin/sh
set -eu
umask 077
export HOME=/home/opam
export TMPDIR=/work/tmp
export PATH=/home/opam/esy/bin:/home/opam/node/bin:/home/opam/.opam/5.5/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
mkdir -p /work/tmp/home /work/logs
tar -xf - --no-same-owner -C /work
cd /home/opam/esy-reference
capture() {{
  name="$1"; shift
  out="/work/logs/$name.out"; err="/work/logs/$name.err"
  set +e
  "$@" >"$out" 2>"$err"
  rc=$?
  set -e
  ob=$(wc -c <"$out" | tr -d ' '); eb=$(wc -c <"$err" | tr -d ' ')
  oh=$(sha256sum "$out" | awk '{{print $1}}'); eh=$(sha256sum "$err" | awk '{{print $1}}')
  ot=0; et=0; [ "$ob" -le {MAX_LOG} ] || ot=1; [ "$eb" -le {MAX_LOG} ] || et=1
  printf '{tag}CMD %s %s %s %s %s %s %s %s ' "$name" "$rc" "$ob" "$oh" "$ot" "$eb" "$eh" "$et"
  head -c {MAX_LOG} "$out" | base64 | tr -d '\\n'; printf ' '
  head -c {MAX_LOG} "$err" | base64 | tr -d '\\n'; printf '\\n'
}}

if [ -f package.json ]; then
  package_bytes=$(wc -c <package.json | tr -d ' '); package_sha=$(sha256sum package.json | awk '{{print $1}}')
  printf '{tag}PACKAGE %s %s\\n' "$package_bytes" "$package_sha"
else
  printf '{tag}PACKAGE 0 missing\\n'
fi
if [ -f esy.lock ]; then
  lock_bytes=$(wc -c <esy.lock | tr -d ' '); lock_sha=$(sha256sum esy.lock | awk '{{print $1}}')
  printf '{tag}LOCK esy.lock %s %s\\n' "$lock_bytes" "$lock_sha"
elif [ -d esy.lock ]; then
  find esy.lock -type f -print | LC_ALL=C sort | while IFS= read -r f; do
    lock_bytes=$(wc -c <"$f" | tr -d ' '); lock_sha=$(sha256sum "$f" | awk '{{print $1}}')
    printf '{tag}LOCK %s %s %s\\n' "$f" "$lock_bytes" "$lock_sha"
  done
else
  printf '{tag}LOCK missing 0 missing\\n'
fi
capture project-install esy install
capture compiler-path esy sh -c 'command -v ocamlopt'
capture compiler-version esy ocamlopt -version
capture compile-positive esy ocamlopt -o /work/reference.exe /work/main.ml
capture run-positive /work/reference.exe
capture compile-wrong-result esy ocamlopt -o /work/wrong.exe /work/wrong_result.ml
capture run-wrong-result /work/wrong.exe
capture compile-malformed esy ocamlopt -o /work/malformed.exe /work/malformed.ml
printf '{tag}END\\n'
'''


def parse(stdout: bytes, nonce: str):
    tag, commands, locks, package, ended = f"ESYREF_{nonce}_", {}, [], None, False
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith(tag + "CMD "):
            f = line[len(tag + "CMD "):].split(" ", 9)
            if len(f) != 10:
                raise ValueError("malformed esy command record")
            name, rc, ob, oh, ot, eb, eh, et, out64, err64 = f
            if name in commands:
                raise ValueError(f"duplicate command record: {name}")
            out, err = base64.b64decode(out64, validate=True), base64.b64decode(err64, validate=True)
            if len(out) != min(int(ob), MAX_LOG) or len(err) != min(int(eb), MAX_LOG):
                raise ValueError(f"bounded log length mismatch: {name}")
            if ((ot == "0" and (len(out) != int(ob) or sha(out) != oh)) or
                    (et == "0" and (len(err) != int(eb) or sha(err) != eh))):
                raise ValueError(f"command log hash mismatch: {name}")
            commands[name] = {"exit_code": int(rc), "stdout_bytes": int(ob), "stdout_sha256": oh,
                              "stdout": out[:MAX_EXCERPT].decode("utf-8", errors="replace"),
                              "stdout_truncated": int(ob) > MAX_EXCERPT or ot == "1",
                              "stderr_bytes": int(eb), "stderr_sha256": eh,
                              "stderr": err[:MAX_EXCERPT].decode("utf-8", errors="replace"),
                              "stderr_truncated": int(eb) > MAX_EXCERPT or et == "1"}
        elif line.startswith(tag + "PACKAGE "):
            if package is not None:
                raise ValueError("duplicate project package record")
            _, size, digest = line.split(" ")
            package = {"bytes": int(size), "sha256": digest if digest != "missing" else None}
        elif line.startswith(tag + "LOCK "):
            _, path, size, digest = line.split(" ")
            locks.append({"path": path, "bytes": int(size), "sha256": digest if digest != "missing" else None})
        elif line == tag + "END":
            ended = True
    if not ended:
        raise ValueError("container completion marker missing")
    return commands, package, locks


def evaluate(commands, package, locks, expected_package_sha):
    checks = []
    def add(name, passed, detail):
        checks.append({"id": name, "passed": bool(passed), "detail": detail})
    package_input = json.loads((PROPOSAL / "package.json").read_text(encoding="utf-8"))
    add("package-identity", package is not None and package.get("sha256") == expected_package_sha and
        package_input.get("dependencies", {}).get("ocaml") == "5.5.1000",
        "image project package.json matches the locally hash-bound exact compiler package pin")
    add("lock-present", bool(locks) and all(row["bytes"] > 0 and re.fullmatch(r"[0-9a-f]{64}", row["sha256"] or "") for row in locks),
        "image project has nonempty esy.lock file contents with exact SHA256 records")
    add("project-install", commands.get("project-install", {}).get("exit_code") == 0,
        "esy install succeeds offline against the pinned image lock in disposable project cache")
    path = commands.get("compiler-path", {})
    compiler_path = path.get("stdout", "").strip()
    add("esy-store-compiler", path.get("exit_code") == 0 and "/.esy/" in compiler_path and "/.opam/" not in compiler_path,
        "esy resolves ocamlopt from its own store, outside the opam switch")
    version = commands.get("compiler-version", {})
    add("compiler-version", version.get("exit_code") == 0 and version.get("stdout", "").strip() == "5.5.1",
        "esy-managed ocamlopt reports exact expected compiler version 5.5.1")
    add("compile-positive", commands.get("compile-positive", {}).get("exit_code") == 0,
        "fixed positive source compiles through esy ocamlopt")
    positive = commands.get("run-positive", {})
    add("run-positive", positive.get("exit_code") == 0 and positive.get("stdout") == "esy-ocaml-reference:passed\n",
        "fixed native reference prints exact success output")
    add("compile-wrong-result", commands.get("compile-wrong-result", {}).get("exit_code") == 0,
        "wrong-result control compiles successfully before runtime test")
    wrong = commands.get("run-wrong-result", {})
    add("run-wrong-result", wrong.get("exit_code", 0) != 0 and
        "Assert_failure" in (wrong.get("stderr", "") + wrong.get("stdout", "")),
        "wrong-result control exits nonzero with OCaml Assert_failure")
    malformed = commands.get("compile-malformed", {})
    diagnostic = (malformed.get("stderr", "") + malformed.get("stdout", "")).lower()
    add("compile-malformed", malformed.get("exit_code", 0) != 0 and "syntax error" in diagnostic,
        "malformed-source control fails with a syntax diagnostic")
    add("bounded-logs", all(c.get("stdout_bytes", 0) <= MAX_LOG and c.get("stderr_bytes", 0) <= MAX_LOG and
                             not c.get("stdout_truncated") and not c.get("stderr_truncated") for c in commands.values()),
        f"command logs are fully captured within {MAX_LOG} bytes per stream")
    add("command-completeness", set(commands) == {"project-install", "compiler-path", "compiler-version", "compile-positive", "run-positive",
                                                  "compile-wrong-result", "run-wrong-result", "compile-malformed"},
        "all fixed commands returned exactly once")
    return checks


def write_report(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value) + b"\n"
    if path.exists():
        raise FileExistsError(f"immutable report exists: {path}")
    fd, tmp = tempfile.mkstemp(prefix=".esy-reference-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.link(tmp, path)
        folder = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(folder)
        finally: os.close(folder)
    finally:
        os.unlink(tmp)
    return sha(data)


def run(image: str, run_id: str):
    if not IMAGE_RE.fullmatch(image):
        raise ValueError("--image must be sha256:<64 lowercase hex>")
    if not RUN_RE.fullmatch(run_id):
        raise ValueError("invalid run ID")
    report_path = RESULTS / f"{run_id}.json"
    if report_path.exists():
        raise FileExistsError(f"immutable report exists: {report_path}")
    archive, sources, source_bytes = source_bundle()
    package_path = PROPOSAL / "package.json"
    package_sha = sha(package_path.read_bytes())
    nonce = secrets.token_hex(16)
    name = f"sft-esyref-{run_id[:18]}-{secrets.token_hex(8)}".lower()[:63]
    docker = ["docker", "run", "--rm", "-i", "--name", name, "--platform", "linux/amd64",
              "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt",
              "no-new-privileges:true", "--pids-limit", "128", "--memory", "2g", "--cpus", "2",
              "--tmpfs", "/work:rw,nosuid,nodev,exec,size=128m,uid=1000,gid=1000,mode=700",
              "--tmpfs", "/home/opam/esy-reference/_esy:rw,nosuid,nodev,exec,size=128m,uid=1000,gid=1000,mode=700",
              "--user", "1000:1000", "--workdir", "/work", "--entrypoint", "/bin/sh",
              image, "-c", container_script(nonce)]
    source = Path(__file__).resolve()
    runner_sha = sha(source.read_bytes())
    report = {"schema_version": 1, "id": run_id, "kind": "esy_managed_ocaml_reference_probe",
              "status": "FAILED", "scope": "fixed-native-reference-only",
              "claim_limit": "Does not establish esy project build readiness or validate arbitrary model output.",
              "image": image, "runner": {"path": str(source.relative_to(ROOT)), "sha256": runner_sha},
              "project_package": {"path": str(package_path.relative_to(ROOT)), "sha256": package_sha},
              "source_files": sources, "source_total_bytes": source_bytes,
              "commands": ["esy install", "esy sh -c 'command -v ocamlopt'", "esy ocamlopt -version",
                           "esy ocamlopt -o /work/reference.exe /work/main.ml", "/work/reference.exe",
                           "esy ocamlopt -o /work/wrong.exe /work/wrong_result.ml", "/work/wrong.exe",
                           "esy ocamlopt -o /work/malformed.exe /work/malformed.ml"],
              "docker_argv": docker, "timeout_seconds": TIMEOUT, "container_name": name,
              "results": {}, "esy_lock_files": [], "checks": [], "timed_out": False,
              "stdout": "", "stderr": "", "started_unix": time.time()}
    proc = None
    started = time.monotonic()
    try:
        proc = subprocess.Popen(docker, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = proc.communicate(archive, timeout=TIMEOUT)
            report["exit_code"] = proc.returncode
        except subprocess.TimeoutExpired:
            report["timed_out"] = True
            try:
                subprocess.run(["docker", "rm", "-f", name], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if proc.poll() is None: proc.kill()
            stdout, stderr = proc.communicate()
            report["exit_code"] = proc.returncode
        report["stdout_bytes"], report["stderr_bytes"] = len(stdout), len(stderr)
        report["stdout_sha256"], report["stderr_sha256"] = sha(stdout), sha(stderr)
        report["stdout"] = stdout[:4096].decode("utf-8", errors="replace")
        report["stderr"] = stderr[:4096].decode("utf-8", errors="replace")
        if not report["timed_out"] and proc.returncode == 0 and len(stdout) + len(stderr) <= 128 * 1024:
            commands, package, locks = parse(stdout, nonce)
            report["results"], report["esy_lock_files"] = commands, locks
            report["checks"] = evaluate(commands, package, locks, package_sha)
            if all(row["passed"] for row in report["checks"]): report["status"] = "PASSED"
        else:
            report["checks"] = [{"id": "container-run", "passed": False,
                                 "detail": "timeout, Docker failure, or bounded output limit exceeded"}]
    except (OSError, ValueError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if proc is not None and proc.poll() is None: proc.kill(); proc.wait()
        try:
            cleanup = subprocess.run(["docker", "rm", "-f", name], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
            report["cleanup_exit_code"] = cleanup.returncode
        except (OSError, subprocess.TimeoutExpired):
            report["cleanup_exit_code"] = None
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if sha(source.read_bytes()) != runner_sha:
        report["status"] = "FAILED"
        report["checks"].append({"id": "runner-integrity", "passed": False, "detail": "runner changed during execution"})
    report["finished_unix"] = time.time()
    report_sha = write_report(report_path, report)
    return report, report_path, report_sha


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="exact sha256:<64 lowercase hex> image digest")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        report, path, report_sha = run(args.image, args.run_id)
        print(json.dumps({"status": report["status"], "report": str(path), "report_sha256": report_sha}, sort_keys=True))
        return 0 if report["status"] == "PASSED" else 1
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
