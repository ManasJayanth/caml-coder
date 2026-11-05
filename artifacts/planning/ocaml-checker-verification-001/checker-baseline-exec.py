#!/usr/bin/env python3
"""Run a generated OCaml smoke candidate inside a pinned, isolated container.

This check is a narrow compile-and-examples probe. It is not benchmark evidence
or a substitute for trusted grading or model acceptance.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tarfile
import tempfile
import time


IMAGE_ID = "sha256:52ae74f2f384d509b9c001aaec682ad390202836b5c655358290f49d97934a9a"
COMPILER = "/home/opam/.opam/5.5/bin/ocamlc"
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_CANDIDATE_BYTES = 64 * 1024
MAX_LOG_BYTES = 128 * 1024
SYSTEM_PROMPT = "You are a concise OCaml coding assistant. Output source code only."
USER_PROMPT = "Write one OCaml function named sum_squares that returns the sum of the squares of an int list. Use List.fold_left. Output only OCaml source code, with no explanation."
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _result_candidate(result_path):
    raw = result_path.read_bytes()
    if len(raw) > MAX_RESULT_BYTES:
        raise ValueError("probe manifest exceeds 16 MiB")
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant {value}")))
    if not isinstance(result, dict) or result.get("schema_version") != 1 or result.get("status") != "PASSED":
        raise ValueError("input must be a committed PASSED model-probe manifest")
    readiness = result.get("readiness")
    if (not isinstance(readiness, dict) or readiness.get("scope") != "runtime_probe_only" or
            readiness.get("generation_allowed") is not False or readiness.get("benchmark") is not False or
            readiness.get("code_executed") is not False):
        raise ValueError("probe readiness must state runtime-only, generation-forbidden, non-benchmark, unexecuted status")
    runtime = result.get("runtime")
    prompt = runtime.get("prompt") if isinstance(runtime, dict) else None
    messages = prompt.get("messages") if isinstance(prompt, dict) else None
    if (not isinstance(messages, list) or len(messages) != 2 or
            messages[0] != {"role": "system", "content": SYSTEM_PROMPT} or
            messages[1] != {"role": "user", "content": USER_PROMPT} or
            prompt.get("enable_thinking") is not False):
        raise ValueError("probe manifest does not bind the fixed sum_squares prompt")
    generation = runtime.get("generation") if isinstance(runtime, dict) else None
    if not isinstance(generation, dict) or not isinstance(generation.get("text"), str):
        raise ValueError("probe manifest is missing raw runtime generation text")
    candidate = result.get("output_text")
    if not isinstance(candidate, str) or candidate != generation["text"]:
        raise ValueError("top-level output_text differs from raw runtime generation text")
    token_ids = result.get("output_token_ids")
    if (not isinstance(token_ids, list) or any(type(value) is not int or value < 0 for value in token_ids) or
            token_ids != generation.get("token_ids")):
        raise ValueError("output token IDs do not match the raw generation record")
    candidate_bytes = candidate.encode("utf-8")
    if not candidate_bytes or len(candidate_bytes) > MAX_CANDIDATE_BYTES or b"\x00" in candidate_bytes:
        raise ValueError("raw candidate must be nonempty UTF-8 source no larger than 64 KiB")
    candidate_hash = _sha(candidate_bytes)
    if result.get("output_text_sha256") != candidate_hash or not SHA256.fullmatch(candidate_hash):
        raise ValueError("raw candidate SHA256 mismatch")
    return raw, candidate_bytes, result, candidate_hash


def _tar(candidate, checker):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in (("Candidate.ml", candidate), ("checker.ml", checker)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            info.uid = info.gid = 1000
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def _container_script(marker):
    return """set -eu
cd /work
export TMPDIR=/work
tar -xf - --no-same-owner -C /work
test -f Candidate.ml && test -f checker.ml
""" + f"set +e\n{COMPILER} -w +a -o probe Candidate.ml checker.ml >compile.stdout 2>compile.stderr\ncompile_status=$?\nset -e\nprintf 'SFT_COMPILE_STATUS:%s\\n' \"$compile_status\"\ncat compile.stdout compile.stderr\nif [ \"$compile_status\" -ne 0 ]; then exit \"$compile_status\"; fi\n" + """# Limit candidate stdout/stderr files to 64 KiB without raising the hard
# file-size limit inherited by the unprivileged process.
ulimit -f 128
set +e
./probe >candidate.stdout 2>candidate.stderr
candidate_status=$?
set -e
printf 'SFT_CANDIDATE_STATUS:%s\\n' "$candidate_status"
cat candidate.stdout candidate.stderr
""" + f"printf '%s\\n' '{marker}'\n" + """test "$candidate_status" -eq 0
"""


def _checker(marker):
    source = f'''module Candidate = Candidate
let sum_squares : int list -> int = Candidate.sum_squares
let fail label = failwith ("case failed: " ^ label)
let check label input expected =
  if sum_squares input <> expected then fail label
let () =
  check "empty" [] 0;
  check "negative" [-3; 2] 13;
  check "zeros" [0; 0; 0] 0;
  check "single" [7] 49;
  check "multiple" [1; -2; 3; 4] 30;
  print_endline "{marker}"
'''
    return source.encode("utf-8")


def _docker_command(name):
    script = _container_script("__MARKER__")
    return ["docker", "run", "--rm", "-i", "--name", name, "--platform", "linux/amd64",
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--pids-limit", "128",
            "--memory", "1g", "--cpus", "1",
            "--tmpfs", "/work:rw,nosuid,nodev,exec,size=64m,uid=1000,gid=1000,mode=700",
            "--user", "1000:1000", "--workdir", "/work", "--entrypoint", "/bin/sh",
            IMAGE_ID, "-c", script]


def _write_report(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(value) + b"\n"
    path.parent.resolve(strict=True)
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise FileExistsError(f"immutable report already exists: {path}")
    fd, temporary = tempfile.mkstemp(prefix=".ocaml-probe-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        os.unlink(temporary)


def _remove_container(name):
    try:
        subprocess.run(["docker", "rm", "-f", name], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True, help="PASSED model-probe manifest.json")
    parser.add_argument("--run-id", required=True, help="unique immutable checker report ID")
    args = parser.parse_args(argv)
    if not RUN_ID.fullmatch(args.run_id):
        parser.error("invalid run ID")
    result_path = args.result.resolve()
    report_path = result_path.parent / "ocaml-checks" / f"{args.run_id}.json"
    started = time.time()
    name = f"sft-ocaml-probe-{args.run_id}-{secrets.token_hex(4)}".lower()[:63]
    report = {"schema_version": 1, "id": args.run_id, "kind": "ocaml_probe_check",
              "status": "FAILED", "scope": "compile-and-fixed-example-smoke-only",
              "benchmark": False, "robustness_claim": False, "image_id": IMAGE_ID,
              "platform": "linux/amd64", "result_manifest": str(result_path),
              "container_name": name, "command": None, "probe_manifest_sha256": None,
              "candidate_sha256": None, "candidate_bytes": None, "exit_code": None,
              "timed_out": False, "sentinel_seen": False, "stdout": "", "stderr": "",
              "error": None, "started_unix": started, "finished_unix": None}
    try:
        raw, candidate, result, candidate_hash = _result_candidate(result_path)
        report["probe_manifest_sha256"] = _sha(raw)
        report["candidate_sha256"] = candidate_hash
        report["candidate_bytes"] = len(candidate)
        nonce = secrets.token_hex(16)
        marker = f"SFT_PROBE_COMPLETE_{nonce}"
        tar_input = _tar(candidate, _checker(marker))
        command = _docker_command(name)
        command[-1] = _container_script(marker)
        report["command"] = command
        try:
            completed = subprocess.run(command, input=tar_input, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=30, check=False)
            report["exit_code"] = completed.returncode
            stdout = completed.stdout[-MAX_LOG_BYTES:]
            stderr = completed.stderr[-MAX_LOG_BYTES:]
            report["stdout"] = stdout.decode("utf-8", errors="replace")
            report["stderr"] = stderr.decode("utf-8", errors="replace")
            lines = report["stdout"].splitlines()
            report["sentinel_seen"] = bool(lines and lines[-1] == marker)
            if completed.returncode == 0 and report["sentinel_seen"]:
                report["status"] = "PASSED"
            else:
                report["error"] = "container compile/assertion failed or completion sentinel missing"
        except subprocess.TimeoutExpired as error:
            report["timed_out"] = True
            report["stdout"] = (error.stdout or b"")[-MAX_LOG_BYTES:].decode("utf-8", errors="replace")
            report["stderr"] = (error.stderr or b"")[-MAX_LOG_BYTES:].decode("utf-8", errors="replace")
            report["error"] = "container exceeded 30-second smoke timeout"
            _remove_container(name)
        except OSError as error:
            report["error"] = f"cannot start isolated Docker probe: {error}"
        finally:
            _remove_container(name)
    except Exception as error:
        report["error"] = f"invalid probe input: {type(error).__name__}: {error}"
    report["finished_unix"] = time.time()
    _write_report(report_path, report)
    sys.stdout.buffer.write(_canonical({"status": report["status"], "report": str(report_path), "error": report["error"]}) + b"\n")
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
