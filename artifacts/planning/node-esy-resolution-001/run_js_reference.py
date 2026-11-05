#!/usr/bin/env python3
"""Run a fixed Melange-to-Node reference probe in a pinned offline image."""

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
FIXTURE_ROOT = ROOT / "artifacts/planning/toolchain-reference-probe-001/melange-emission"
RESULT_ROOT = Path(__file__).resolve().parent / "js-results"
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_FILE = 64 * 1024
MAX_INPUT = 256 * 1024
MAX_LOG = 8 * 1024
MAX_EXCERPT = MAX_LOG
TIMEOUT = 120
FILES = ("dune-project", "dune", "app.ml", "lib/dune", "lib/reference_lib.ml")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def fixtures():
    archive_bytes = io.BytesIO()
    hashes = []
    total = 0
    with tarfile.open(fileobj=archive_bytes, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in FILES:
            path = FIXTURE_ROOT / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"missing or unsafe fixture: {name}")
            raw = path.read_bytes()
            if not 0 < len(raw) <= MAX_FILE:
                raise ValueError(f"fixture size outside bound: {name}")
            total += len(raw)
            if total > MAX_INPUT:
                raise ValueError("fixture archive exceeds size bound")
            hashes.append({"path": name, "bytes": len(raw), "sha256": sha(raw)})
            info = tarfile.TarInfo(f"project/{name}")
            info.size, info.mode, info.uid, info.gid = len(raw), 0o644, 1000, 1000
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(raw))
    return archive_bytes.getvalue(), hashes, total


def container_script(nonce: str) -> str:
    tag = f"JSREF_{nonce}_"
    return f'''#!/bin/sh
set -eu
umask 077
export HOME=/work/tmp/home
export TMPDIR=/work/tmp
export PATH=/home/opam/node/bin:/home/opam/esy/bin:/home/opam/.opam/5.5/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export OPAMROOT=/home/opam/.opam
export OPAMSWITCH=5.5
export OPAM_SWITCH_PREFIX=/home/opam/.opam/5.5
mkdir -p /work/tmp/home /work/logs
tar -xf - --no-same-owner -C /work
capture() {{
  name="$1"; cwd="$2"; shift 2
  out="/work/logs/$name.out"; err="/work/logs/$name.err"
  set +e
  (cd "$cwd" && "$@") >"$out" 2>"$err"
  rc=$?
  set -e
  out_bytes=$(wc -c <"$out" | tr -d ' '); err_bytes=$(wc -c <"$err" | tr -d ' ')
  out_sha=$(sha256sum "$out" | awk '{{print $1}}'); err_sha=$(sha256sum "$err" | awk '{{print $1}}')
  out_truncated=0; err_truncated=0
  [ "$out_bytes" -le {MAX_LOG} ] || out_truncated=1
  [ "$err_bytes" -le {MAX_LOG} ] || err_truncated=1
  printf '{tag}CMD %s %s %s %s %s %s %s %s ' "$name" "$rc" "$out_bytes" "$out_sha" "$out_truncated" "$err_bytes" "$err_sha" "$err_truncated"
  head -c {MAX_LOG} "$out" | base64 | tr -d '\\n'; printf ' '
  head -c {MAX_LOG} "$err" | base64 | tr -d '\\n'; printf '\\n'
}}
capture node-version /work node --version
capture esy-version /work esy --version
capture dune-version /work dune --version
capture melange-build /work/project dune build
apps=$(find /work/project/_build -type f -name app.js -size +0c -print 2>/dev/null || true)
app_count=$(printf '%s\\n' "$apps" | sed '/^$/d' | wc -l | tr -d ' ')
if [ "$app_count" -eq 1 ]; then
  app="$apps"
  app_bytes=$(wc -c <"$app" | tr -d ' '); app_sha=$(sha256sum "$app" | awk '{{print $1}}')
  printf '{tag}APP %s %s %s %s\\n' "$app_count" "$app" "$app_bytes" "$app_sha"
  capture node-generated-app "$(dirname "$app")" node "$app"
else
  app_path=missing
  [ "$app_count" -le 1 ] || app_path=duplicate
  printf '{tag}APP %s %s 0 missing\\n' "$app_count" "$app_path"
  capture node-generated-app /work/project node -e 'process.exit(2)'
fi
capture node-assertion-control /work node -e 'require("node:assert/strict").equal(1, 2)'
printf '{tag}END\\n'
'''


def parse(stdout: bytes, nonce: str):
    marker = f"JSREF_{nonce}_"
    rows, app, ended = {}, None, False
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith(marker + "CMD "):
            fields = line[len(marker + "CMD "):].split(" ", 9)
            if len(fields) != 10:
                raise ValueError("malformed command record")
            name, rc, ob, oh, ot, eb, eh, et, out64, err64 = fields
            if name in rows:
                raise ValueError(f"duplicate command record: {name}")
            out, err = base64.b64decode(out64, validate=True), base64.b64decode(err64, validate=True)
            if len(out) != min(int(ob), MAX_LOG) or len(err) != min(int(eb), MAX_LOG):
                raise ValueError(f"truncated transport for {name}")
            if ((ot == "0" and (len(out) != int(ob) or sha(out) != oh)) or
                    (et == "0" and (len(err) != int(eb) or sha(err) != eh))):
                raise ValueError(f"command log hash mismatch: {name}")
            rows[name] = {"exit_code": int(rc), "stdout_bytes": int(ob), "stdout_sha256": oh,
                          "stdout": out[:MAX_EXCERPT].decode("utf-8", errors="replace"),
                          "stdout_truncated": int(ob) > MAX_EXCERPT or ot == "1",
                          "stderr_bytes": int(eb), "stderr_sha256": eh,
                          "stderr": err[:MAX_EXCERPT].decode("utf-8", errors="replace"),
                          "stderr_truncated": int(eb) > MAX_EXCERPT or et == "1"}
        elif line.startswith(marker + "APP "):
            if app is not None:
                raise ValueError("duplicate app.js inventory record")
            # The count precedes the path so duplicate outputs fail closed.
            _, count, path, size, digest = line.split(" ")
            app = {"count": int(count), "path": path, "bytes": int(size),
                   "sha256": digest if digest != "missing" else None}
        elif line == marker + "END":
            ended = True
    if not ended:
        raise ValueError("container completion marker missing")
    return rows, app


def checks(rows, app):
    out = []
    def add(name, ok, detail):
        out.append({"id": name, "passed": bool(ok), "detail": detail})
    for name in ("node-version", "esy-version", "dune-version"):
        value = rows.get(name, {})
        add(name, value.get("exit_code") == 0 and bool(value.get("stdout", "").strip()),
            "installed tool version was observed")
    add("log-bounds", all(r.get("stdout_bytes", 0) <= MAX_LOG and r.get("stderr_bytes", 0) <= MAX_LOG and
                           not r.get("stdout_truncated") and not r.get("stderr_truncated") for r in rows.values()),
        f"each command log is at most {MAX_LOG} bytes and fully transported")
    add("melange-build", rows.get("melange-build", {}).get("exit_code") == 0 and
        isinstance(app, dict) and app.get("count") == 1 and app.get("path", "") not in {"", "missing", "duplicate"} and
        app.get("bytes", 0) > 0 and re.fullmatch(r"[0-9a-f]{64}", app.get("sha256", "")) is not None,
        "fixed fixture builds and emits nonempty app.js")
    app_result = rows.get("node-generated-app", {})
    add("node-generated-app", app_result.get("exit_code") == 0 and app_result.get("stdout") == "42\n",
        "Node executes the emitted fixture and prints exactly 42")
    control = rows.get("node-assertion-control", {})
    diag = (control.get("stderr", "") + control.get("stdout", ""))
    add("node-assertion-control", control.get("exit_code", 0) != 0 and "AssertionError" in diag,
        "fixed Node assertion control exits nonzero with AssertionError")
    return out


def write_immutable(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value) + b"\n"
    if path.exists():
        raise FileExistsError(f"immutable report exists: {path}")
    fd, tmp = tempfile.mkstemp(prefix=".js-reference-", dir=path.parent)
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
        raise ValueError("image must be sha256:<64 lowercase hex>")
    if not RUN_RE.fullmatch(run_id):
        raise ValueError("invalid run ID")
    report_path = RESULT_ROOT / f"{run_id}.json"
    if report_path.exists():
        raise FileExistsError(f"immutable report exists: {report_path}")
    tar_bytes, input_hashes, input_total = fixtures()
    nonce = secrets.token_hex(16)
    name = f"sft-jsref-{run_id[:18]}-{secrets.token_hex(8)}".lower()[:63]
    docker = ["docker", "run", "--rm", "-i", "--name", name, "--platform", "linux/amd64",
              "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt",
              "no-new-privileges:true", "--pids-limit", "128", "--memory", "2g", "--cpus", "2",
              "--tmpfs", "/work:rw,nosuid,nodev,exec,size=128m,uid=1000,gid=1000,mode=700",
              "--user", "1000:1000", "--workdir", "/work", "--entrypoint", "/bin/sh",
              image, "-c", container_script(nonce)]
    source = Path(__file__).resolve()
    source_hash = sha(source.read_bytes())
    run_started = time.monotonic()
    report = {"schema_version": 1, "id": run_id, "kind": "offline_melange_node_reference_probe",
              "status": "FAILED", "scope": "fixed-melange-reference-fixture-only",
              "claim_limit": "Does not establish esy project build readiness or validate arbitrary model output.",
              "image": image, "runner": {"path": str(source.relative_to(ROOT)), "sha256": source_hash},
              "fixtures": input_hashes, "fixture_total_bytes": input_total,
              "commands": [{"id": "node-version", "argv": ["node", "--version"]},
                           {"id": "esy-version", "argv": ["esy", "--version"]},
                           {"id": "dune-version", "argv": ["dune", "--version"]},
                           {"id": "melange-build", "argv": ["dune", "build"], "cwd": "project"},
                           {"id": "node-generated-app", "argv": ["node", "<emitted-app.js>"]},
                           {"id": "node-assertion-control", "argv": ["node", "-e", 'require("node:assert/strict").equal(1, 2)']}],
              "docker_argv": docker, "timeout_seconds": TIMEOUT, "container_name": name,
              "results": {}, "emitted_app": None, "checks": [], "timed_out": False,
              "stdout": "", "stderr": "", "started_unix": time.time()}
    proc = None
    try:
        proc = subprocess.Popen(docker, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = proc.communicate(tar_bytes, timeout=TIMEOUT)
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
        report["container_output_truncated"] = len(stdout) + len(stderr) > 128 * 1024
        if not report["timed_out"] and proc.returncode == 0 and not report["container_output_truncated"]:
            rows, app = parse(stdout, nonce)
            report["results"], report["emitted_app"] = rows, app
            report["checks"] = checks(rows, app)
            expected = {c["id"] for c in report["commands"]}
            report["checks"].append({"id": "command-completeness", "passed": set(rows) == expected,
                                     "detail": "each fixed command emitted one result"})
            if all(check["passed"] for check in report["checks"]): report["status"] = "PASSED"
        else:
            report["checks"] = [{"id": "container-run", "passed": False,
                                 "detail": "timeout, Docker failure, or output bound exceeded"}]
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
    report["elapsed_seconds"] = round(time.monotonic() - run_started, 3)
    if sha(source.read_bytes()) != source_hash:
        report["status"] = "FAILED"
        report["checks"].append({"id": "runner-integrity", "passed": False, "detail": "runner changed during execution"})
    report["finished_unix"] = time.time()
    report_sha = write_immutable(report_path, report)
    return report, report_path, report_sha


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="exact sha256:<64 lowercase hex> Docker image digest")
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
