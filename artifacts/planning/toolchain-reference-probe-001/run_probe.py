#!/usr/bin/env python3
"""Run fixed offline compiler reference fixtures in a digest-pinned Docker image."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "artifacts/planning/toolchain-reference-probe-001"
RESULT_ROOT = ROOT / "artifacts/planning/toolchain-reference-results"
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_FILE = 64 * 1024
MAX_INPUT = 512 * 1024
MAX_TRANSPORT_LOG = 8 * 1024
MAX_COMMAND_LOG = MAX_TRANSPORT_LOG
MAX_REPORTED_LOG = 1024
MAX_RESULT_LOG = 128 * 1024
MAX_RESULT_EXCERPT = 4 * 1024
TIMEOUT_SECONDS = 120

FIXTURES = (
    "ocaml-native/dune-project",
    "ocaml-native/dune",
    "ocaml-native/main.ml",
    "ocaml-native/wrong_result.ml",
    "ocaml-native/negative-invalid-source/dune-project",
    "ocaml-native/negative-invalid-source/dune",
    "ocaml-native/negative-invalid-source/invalid.ml",
    "reason-native/dune-project",
    "reason-native/dune",
    "reason-native/main.re",
    "reason-native/wrong_result.re",
    "reason-native/negative-invalid-source/dune-project",
    "reason-native/negative-invalid-source/dune",
    "reason-native/negative-invalid-source/invalid.re",
    "melange-emission/dune-project",
    "melange-emission/dune",
    "melange-emission/app.ml",
    "melange-emission/lib/dune",
    "melange-emission/lib/reference_lib.ml",
)

CASES = [
    {"id": "dune-version", "argv": ["dune", "--version"], "cwd": "/work"},
    {"id": "ocaml-version", "argv": ["ocamlc", "-version"], "cwd": "/work"},
    {"id": "refmt-version", "argv": ["refmt", "--version"], "cwd": "/work"},
    {"id": "melc-version", "argv": ["melc", "--version"], "cwd": "/work"},
    {"id": "ocaml-positive", "argv": ["dune", "exec", "./main.exe"], "cwd": "/work/ocaml-native"},
    {"id": "ocaml-wrong-build", "argv": ["dune", "build", "./wrong_result.exe"], "cwd": "/work/ocaml-native"},
    {"id": "ocaml-wrong-run", "argv": ["dune", "exec", "./wrong_result.exe"], "cwd": "/work/ocaml-native"},
    {"id": "ocaml-invalid-build", "argv": ["dune", "build"], "cwd": "/work/ocaml-native/negative-invalid-source"},
    {"id": "reason-positive", "argv": ["dune", "exec", "./main.exe"], "cwd": "/work/reason-native"},
    {"id": "reason-wrong-build", "argv": ["dune", "build", "./wrong_result.exe"], "cwd": "/work/reason-native"},
    {"id": "reason-wrong-run", "argv": ["dune", "exec", "./wrong_result.exe"], "cwd": "/work/reason-native"},
    {"id": "reason-invalid-build", "argv": ["dune", "build"], "cwd": "/work/reason-native/negative-invalid-source"},
    {"id": "melange-build", "argv": ["dune", "build"], "cwd": "/work/melange-emission"},
]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _safe_root_path(path: Path) -> Path:
    path = path.absolute()
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError(f"symlinked path forbidden: {ancestor}")
    return path


def _collect_fixtures():
    records = []
    total = 0
    tar_data = io.BytesIO()
    with tarfile.open(fileobj=tar_data, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for relative in FIXTURES:
            safe = PurePosixPath(relative)
            if safe.is_absolute() or any(part in {"", ".", ".."} for part in safe.parts):
                raise ValueError(f"unsafe fixture path: {relative}")
            source = _safe_root_path(FIXTURE_ROOT / Path(*safe.parts))
            if not source.is_file():
                raise ValueError(f"missing fixed fixture file: {relative}")
            size = source.stat().st_size
            if size <= 0 or size > MAX_FILE:
                raise ValueError(f"fixture file size outside bound: {relative}")
            raw = source.read_bytes()
            total += len(raw)
            if total > MAX_INPUT:
                raise ValueError("fixed fixture archive exceeds input size bound")
            records.append({"path": relative, "bytes": len(raw), "sha256": _sha(raw)})
            info = tarfile.TarInfo(relative)
            info.size = len(raw)
            info.mode = 0o644
            info.uid = info.gid = 1000
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(raw))
    return tar_data.getvalue(), records, total


def _shell(nonce: str) -> str:
    marker = f"SFTREF_{nonce}_"
    return f'''#!/bin/sh
set -eu
umask 077
export HOME=/work/tmp/home
export TMPDIR=/work/tmp
export PATH=/home/opam/.opam/5.5/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export OPAMROOT=/home/opam/.opam
export OPAMSWITCH=5.5
export OPAM_SWITCH_PREFIX=/home/opam/.opam/5.5
export CAML_LD_LIBRARY_PATH=/home/opam/.opam/5.5/lib/stublibs:/home/opam/.opam/5.5/lib/ocaml/stublibs
mkdir -p /work/tmp/home /work/logs
tar -xf - --no-same-owner -C /work

capture() {{
  name="$1"; workdir="$2"; shift 2
  out="/work/logs/$name.out"; err="/work/logs/$name.err"
  set +e
  (cd "$workdir" && "$@") >"$out" 2>"$err"
  rc=$?
  set -e
  out_bytes=$(wc -c <"$out" | tr -d ' ')
  err_bytes=$(wc -c <"$err" | tr -d ' ')
  out_sha=$(sha256sum "$out" | awk '{{print $1}}')
  err_sha=$(sha256sum "$err" | awk '{{print $1}}')
  out_truncated=0; err_truncated=0
  [ "$out_bytes" -le {MAX_TRANSPORT_LOG} ] || out_truncated=1
  [ "$err_bytes" -le {MAX_TRANSPORT_LOG} ] || err_truncated=1
  printf '{marker}CMD %s %s %s %s %s %s %s %s ' "$name" "$rc" "$out_bytes" "$out_sha" "$out_truncated" "$err_bytes" "$err_sha" "$err_truncated"
  head -c {MAX_TRANSPORT_LOG} "$out" | base64 | tr -d '\\n'
  printf ' '
  head -c {MAX_TRANSPORT_LOG} "$err" | base64 | tr -d '\\n'
  printf '\\n'
}}

capture dune-version /work dune --version
capture ocaml-version /work ocamlc -version
capture refmt-version /work refmt --version
capture melc-version /work melc --version
capture ocaml-positive /work/ocaml-native dune exec ./main.exe
capture ocaml-wrong-build /work/ocaml-native dune build ./wrong_result.exe
capture ocaml-wrong-run /work/ocaml-native dune exec ./wrong_result.exe
capture ocaml-invalid-build /work/ocaml-native/negative-invalid-source dune build
capture reason-positive /work/reason-native dune exec ./main.exe
capture reason-wrong-build /work/reason-native dune build ./wrong_result.exe
capture reason-wrong-run /work/reason-native dune exec ./wrong_result.exe
capture reason-invalid-build /work/reason-native/negative-invalid-source dune build
capture melange-build /work/melange-emission dune build

app=$(find /work/melange-emission/_build -type f -name app.js -size +0c -print -quit 2>/dev/null || true)
if [ -n "$app" ]; then
  app_bytes=$(wc -c <"$app" | tr -d ' ')
  app_sha=$(sha256sum "$app" | awk '{{print $1}}')
  printf '{marker}MELANGE %s %s\\n' "$app_bytes" "$app_sha"
else
  printf '{marker}MELANGE 0 missing\\n'
fi
printf '{marker}END\\n'
'''


def _decode(value: str) -> bytes:
    if not value:
        return b""
    return base64.b64decode(value.encode("ascii"), validate=True)


def _parse_container(stdout: bytes, nonce: str):
    text = stdout.decode("utf-8", errors="replace")
    marker = f"SFTREF_{nonce}_"
    results = {}
    melange = None
    ended = False
    for line in text.splitlines():
        if line.startswith(marker + "CMD "):
            fields = line[len(marker + "CMD "):].split(" ", 9)
            if len(fields) != 10:
                raise ValueError("malformed container command record")
            name, rc, out_size, out_sha, out_truncated, err_size, err_sha, err_truncated, out_encoded, err_encoded = fields
            if name in results:
                raise ValueError("duplicate container command record")
            out, err = _decode(out_encoded), _decode(err_encoded)
            if ((out_truncated == "0" and len(out) != int(out_size)) or
                    (err_truncated == "0" and len(err) != int(err_size)) or
                    len(out) != min(int(out_size), MAX_TRANSPORT_LOG) or
                    len(err) != min(int(err_size), MAX_TRANSPORT_LOG) or
                    not re.fullmatch(r"[0-9a-f]{64}", out_sha) or not re.fullmatch(r"[0-9a-f]{64}", err_sha) or
                    (out_truncated == "0" and _sha(out) != out_sha) or
                    (err_truncated == "0" and _sha(err) != err_sha)):
                raise ValueError(f"invalid bounded command record: {name}")
            results[name] = {"exit_code": int(rc), "stdout_bytes": int(out_size), "stderr_bytes": int(err_size),
                             "stdout_sha256": out_sha, "stderr_sha256": err_sha,
                             "stdout": out[:MAX_REPORTED_LOG].decode("utf-8", errors="replace"),
                             "stderr": err[:MAX_REPORTED_LOG].decode("utf-8", errors="replace"),
                             "stdout_truncated_for_transport": out_truncated == "1",
                             "stderr_truncated_for_transport": err_truncated == "1",
                             "stdout_truncated_in_report": int(out_size) > MAX_REPORTED_LOG,
                             "stderr_truncated_in_report": int(err_size) > MAX_REPORTED_LOG}
        elif line.startswith(marker + "MELANGE "):
            fields = line[len(marker + "MELANGE "):].split(" ")
            if len(fields) != 2:
                raise ValueError("malformed Melange output record")
            melange = {"bytes": int(fields[0]), "sha256": fields[1] if fields[1] != "missing" else None}
        elif line == marker + "END":
            ended = True
    if not ended:
        raise ValueError("container did not emit its completion marker")
    return results, melange


def _passed_checks(results, melange):
    checks = []

    def check(name, condition, detail):
        checks.append({"id": name, "passed": bool(condition), "detail": detail})

    for name in ("dune-version", "ocaml-version", "refmt-version", "melc-version"):
        item = results.get(name, {})
        check(name, item.get("exit_code") == 0 and bool(item.get("stdout", "").strip()),
              "version command exits successfully and reports a version")
    check("bounded-command-logs", all(result.get("stdout_bytes", 0) <= MAX_COMMAND_LOG and
                                       result.get("stderr_bytes", 0) <= MAX_COMMAND_LOG and
                                       not result.get("stdout_truncated_for_transport") and
                                       not result.get("stderr_truncated_for_transport")
                                       for result in results.values()),
          f"all fixed command logs stay within {MAX_COMMAND_LOG} bytes per stream")
    check("ocaml-positive", results.get("ocaml-positive", {}).get("exit_code") == 0 and
          results.get("ocaml-positive", {}).get("stdout") == "ocaml-reference:passed\n",
          "native OCaml positive fixture compiles and prints exact expected stdout")
    check("reason-positive", results.get("reason-positive", {}).get("exit_code") == 0 and
          results.get("reason-positive", {}).get("stdout") == "reason-reference:passed\n",
          "native Reason positive fixture compiles and prints exact expected stdout")
    for language in ("ocaml", "reason"):
        build = results.get(f"{language}-wrong-build", {})
        run = results.get(f"{language}-wrong-run", {})
        diagnostic = (run.get("stderr", "") + run.get("stdout", "")).lower()
        assertion = "assert_failure" in diagnostic or "assertion failed" in diagnostic
        check(f"{language}-wrong-result", build.get("exit_code") == 0 and run.get("exit_code", 0) != 0 and assertion,
              "wrong-result control builds successfully, then exits nonzero with runtime assertion diagnostic")
    for language in ("ocaml", "reason"):
        item = results.get(f"{language}-invalid-build", {})
        diagnostic = (item.get("stderr", "") + item.get("stdout", "")).lower()
        parser_error = "syntax error" in diagnostic or "syntax error" in diagnostic.replace("_", " ")
        check(f"{language}-invalid-source", item.get("exit_code", 0) != 0 and parser_error,
              "invalid-source fixture fails build with parser syntax diagnostics")
    check("melange-emission", results.get("melange-build", {}).get("exit_code") == 0 and
          isinstance(melange, dict) and melange.get("bytes", 0) > 0 and
          isinstance(melange.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", melange["sha256"]) is not None,
          "Melange build emits a nonempty hashed app.js without executing it")
    return checks


def _write_immutable(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(value) + b"\n"
    if path.exists():
        raise FileExistsError(f"immutable report already exists: {path}")
    fd, temporary = tempfile.mkstemp(prefix=".reference-probe-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise FileExistsError(f"immutable report already exists: {path}")
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.unlink(temporary)
    return _sha(raw)


def run(image: str, run_id: str):
    if not IMAGE.fullmatch(image):
        raise ValueError("--image must be an exact sha256:<64 lowercase hex> digest, not a tag")
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run ID")
    output = _safe_root_path(RESULT_ROOT / f"{run_id}.json")
    if output.exists():
        raise FileExistsError(f"immutable report already exists: {output}")
    tar_bytes, fixture_records, input_bytes = _collect_fixtures()
    nonce = secrets.token_hex(16)
    # Keep the random suffix intact when run IDs are long; Docker names are limited to 63 chars.
    name = f"sft-ref-{run_id[:20]}-{secrets.token_hex(8)}".lower()[:63]
    script = _shell(nonce)
    command = ["docker", "run", "--rm", "-i", "--name", name, "--platform", "linux/amd64",
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges:true", "--pids-limit", "128",
               "--memory", "2g", "--cpus", "2",
               "--tmpfs", "/work:rw,nosuid,nodev,exec,size=128m,uid=1000,gid=1000,mode=700",
               "--user", "1000:1000", "--workdir", "/work", "--entrypoint", "/bin/sh",
               image, "-c", script]
    source_path = Path(__file__).resolve()
    source_hash_before = _sha(source_path.read_bytes())
    report = {"schema_version": 1, "id": run_id, "kind": "offline_toolchain_reference_probe",
              "status": "FAILED", "scope": "fixed-trusted-fixtures-only",
              "claim_limit": "No model-output validation, benchmark, compatibility guarantee, or T15 pass.",
              "image": image, "platform": "linux/amd64", "container_name": name,
              "runner": {"path": str(source_path.relative_to(ROOT)), "sha256": source_hash_before},
              "command": command, "stdin_tar_bytes": len(tar_bytes), "fixture_total_bytes": input_bytes,
              "fixtures": fixture_records, "case_commands": CASES,
              "timeout_seconds": TIMEOUT_SECONDS, "container_results": {}, "melange_output": None,
              "checks": [], "timed_out": False, "stdout": "", "stderr": "", "output_truncated": False,
              "started_unix": time.time(), "finished_unix": None}
    proc = None
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = proc.communicate(tar_bytes, timeout=TIMEOUT_SECONDS)
            report["exit_code"] = proc.returncode
        except subprocess.TimeoutExpired:
            report["timed_out"] = True
            try:
                subprocess.run(["docker", "rm", "-f", name], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if proc.poll() is None:
                proc.kill()
            stdout, stderr = proc.communicate()
            report["exit_code"] = proc.returncode
        # Retain bounded diagnostic excerpts and hashes/sizes for the complete logs.
        report["stdout_bytes"] = len(stdout)
        report["stderr_bytes"] = len(stderr)
        report["stdout_sha256"] = _sha(stdout)
        report["stderr_sha256"] = _sha(stderr)
        report["stdout"] = stdout[:MAX_RESULT_EXCERPT].decode("utf-8", errors="replace")
        report["stderr"] = stderr[:MAX_RESULT_EXCERPT].decode("utf-8", errors="replace")
        report["output_truncated"] = len(stdout) + len(stderr) > MAX_RESULT_LOG
        if not report["timed_out"] and proc.returncode == 0 and not report["output_truncated"]:
            results, melange = _parse_container(stdout, nonce)
            report["container_results"] = results
            report["melange_output"] = melange
            report["checks"] = _passed_checks(results, melange)
            expected = {case["id"] for case in CASES}
            if set(results) != expected:
                report["checks"].append({"id": "command-completeness", "passed": False,
                                         "detail": "container result set differs from fixed command inventory"})
            else:
                report["checks"].append({"id": "command-completeness", "passed": True,
                                         "detail": "all fixed commands emitted exactly one result"})
            if all(check["passed"] for check in report["checks"]):
                report["status"] = "PASSED"
        elif report["timed_out"]:
            report["checks"] = [{"id": "container-timeout", "passed": False,
                                 "detail": f"container exceeded {TIMEOUT_SECONDS}s and was killed"}]
        else:
            report["checks"] = [{"id": "container-run", "passed": False,
                                 "detail": "Docker invocation failed, output exceeded bound, or completion failed"}]
    except (OSError, ValueError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        # Kill the named container too: killing the Docker client alone may leave it running.
        try:
            cleanup = subprocess.run(["docker", "rm", "-f", name], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     timeout=10, check=False)
            report["cleanup_exit_code"] = cleanup.returncode
        except (OSError, subprocess.TimeoutExpired):
            report["cleanup_exit_code"] = None
    if _sha(source_path.read_bytes()) != source_hash_before:
        report["status"] = "FAILED"
        report["checks"].append({"id": "runner-integrity", "passed": False,
                                 "detail": "runner source changed during execution"})
    report["finished_unix"] = time.time()
    report_sha256 = _write_immutable(output, report)
    return report, output, report_sha256


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="exact pinned sha256:<64 lowercase hex> Docker image digest")
    parser.add_argument("--run-id", required=True, help="new immutable report ID")
    args = parser.parse_args(argv)
    try:
        report, path, report_sha256 = run(args.image, args.run_id)
        print(json.dumps({"status": report["status"], "report": str(path),
                          "report_sha256": report_sha256}, sort_keys=True))
        return 0 if report["status"] == "PASSED" else 1
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
