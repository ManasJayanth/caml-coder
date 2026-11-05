"""Public checker CLI E2Es using synthetic candidates in real Docker containers."""
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor


GOOD = "let sum_squares xs = List.fold_left (fun acc x -> acc + x * x) 0 xs\n"


def _fixture(t, label, candidate):
    # Reuse only the fixed prompt/readiness schema, never claim model generation.
    original = json.loads((t.root / "artifacts/models/probes/qwen35-runtime-001/manifest.json").read_text())
    result = {"schema_version": 1, "status": "PASSED", "fixture_only": True,
              "readiness": original["readiness"],
              "runtime": {"prompt": original["runtime"]["prompt"],
                          "generation": {"text": candidate, "token_ids": []}},
              "output_text": candidate, "output_token_ids": [],
              "output_text_sha256": hashlib.sha256(candidate.encode()).hexdigest()}
    path = t.temporary / label / "manifest.json"
    path.parent.mkdir()
    path.write_text(json.dumps(result) + "\n")
    return path


def _invoke(t, path, run_id):
    result = t.command([sys.executable, "scripts/check_ocaml_probe.py", "--result", str(path),
                        "--run-id", run_id], timeout=45)
    report = json.loads((path.parent / "ocaml-checks" / f"{run_id}.json").read_text())
    # Preserve actual container observations after the temporary fixture is removed.
    result["checker_report"] = report
    t.check(not result["timeout"] and not report["timed_out"], "checker completed without timeout")
    return result, report


def test_checker_controls(t):
    cases = [("valid", GOOD, True),
             ("early-exit", "let sum_squares _ = 0\nlet () = exit 0\n", False),
             ("wrong-result", "let sum_squares _ = 0\n", False),
             ("syntax-error", "let sum_squares =\n", False)]
    for label, candidate, accepted in cases:
        result, report = _invoke(t, _fixture(t, label, candidate), label)
        t.check(result["exit_code"] == (0 if accepted else 1) and
                report["status"] == ("PASSED" if accepted else "FAILED"),
                f"{label}: public command returns the expected verdict")
        if label == "early-exit":
            t.check(report["exit_code"] == 0 and not report["sentinel_seen"] and
                    "SFT_CANDIDATE_STATUS:0" in report["stdout"],
                    "early exit executed successfully but cannot skip the checker and pass")
        if label == "wrong-result":
            t.check("case failed:" in report["stdout"] and not report["sentinel_seen"],
                    "wrong result fails an actual OCaml assertion")
        if label == "syntax-error":
            t.check("Syntax error" in report["stdout"], "invalid source fails at the real compiler")
        t.check(report["benchmark"] is False and report["robustness_claim"] is False,
                "fixture evidence remains a narrow smoke check")


def test_long_run_id_concurrency(t):
    run_id = "x" * 96
    paths = [_fixture(t, f"concurrent-{i}", GOOD) for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda path: _invoke(t, path, run_id), paths))
    names = [report["container_name"] for _, report in results]
    t.check(all(result["exit_code"] == 0 and report["status"] == "PASSED"
                for result, report in results), "same maximum-length run IDs succeed concurrently in distinct output directories")
    t.check(len(set(names)) == 2 and all(len(name) <= 63 and
                re.fullmatch(r"sft-ocaml-probe-x{38}-[0-9a-f]{8}", name) for name in names),
            "maximum run IDs retain independent random container suffixes")


SCENARIOS = {"checker-controls": test_checker_controls,
             "checker-container-names": test_long_run_id_concurrency}
