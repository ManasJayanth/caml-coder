"""Bounded subprocess execution for trusted pipeline commands, never agent tools."""
import os
import signal
import subprocess
import tempfile
import time


def run(argv, *, timeout=30, cwd=None, env=None, output_limit=262144):
    started = time.monotonic()
    # Files avoid pipe deadlocks and memory growth from verbose subprocesses.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        timed_out = False
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(output_limit + 1), err.read(output_limit + 1)
    return {"argv": list(map(str, argv)), "exit_code": child.returncode, "timeout": timed_out,
            "duration_seconds": round(time.monotonic() - started, 6),
            "stdout": stdout[:output_limit].decode("utf-8", errors="replace"),
            "stderr": stderr[:output_limit].decode("utf-8", errors="replace"),
            "output_truncated": len(stdout) > output_limit or len(stderr) > output_limit}
