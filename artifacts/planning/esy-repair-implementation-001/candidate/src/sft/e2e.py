"""E2E harness: scenarios exercise only public subprocess interfaces."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import traceback
from .artifacts import Invalid, atomic_json, digest, implementation_inventory
from .process import run
from .workflow import now


class Scenario:
    def __init__(self, root, temporary):
        self.root, self.temporary = Path(root), Path(temporary)
        self.commands, self.assertions = [], []

    def command(self, argv, *, timeout=30, cwd=None, env=None):
        result = run(argv, timeout=timeout, cwd=cwd or self.root, env=env)
        self.commands.append(result)
        return result

    def cli(self, *args, expected=0, state=None, root=None):
        env = {**os.environ, "PYTHONPATH": str(self.root / "src")}
        result = self.command([sys.executable, "-m", "sft", "--root", str(root or self.root), "--state", str(state or self.temporary / "state"), *map(str, args)], env=env)
        self.check(result["exit_code"] == expected and not result["timeout"], f"CLI {args[:2]} exits {expected}")
        return result

    def check(self, condition, description):
        self.assertions.append({"description": description, "passed": bool(condition)})
        if not condition:
            raise AssertionError(description)


def execute(root, suite, run_id, output=None):
    allowed = {"control": "test_control.py", "fetch":"test_sources.py", "preflight":"test_preflight.py", "handoff":"test_handoff.py", "eligibility":"test_eligibility.py", "ledger":"test_ledger.py", "extraction":"test_extraction.py", "tokenizer":"test_tokenizer.py", "splits":"test_splits.py", "models":"test_models.py", "chunks":"test_chunks.py", "bonito-conversion":"test_bonito_conversion.py", "qwen35-probe":"test_qwen35_probe.py", "ocaml-checker":"test_ocaml_checker.py"}
    if suite not in allowed:
        raise Invalid(f"unimplemented E2E suite {suite}; no tests skipped or marked passing")
    inventory = implementation_inventory(root)
    tier = "real-model" if suite == "qwen35-probe" else "deterministic"
    report = {"schema_version": 1, "id": run_id, "kind": "e2e", "tier": tier, "status": "FAILED", "implementation_hash": digest(inventory), "inventory": inventory, "started_at": now(), "finished_at": None,
              "command": ["sft", "e2e", "--suite", suite, "--run-id", run_id], "scenarios": []}
    spec = importlib.util.spec_from_file_location("sft_e2e_scenarios", root / "tests/e2e" / allowed[suite])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not module.SCENARIOS:
        raise Invalid("empty E2E suite")
    for name, function in module.SCENARIOS.items():
        with tempfile.TemporaryDirectory(prefix="sft-e2e-") as temporary:
            scenario = Scenario(root, Path(temporary).resolve())
            error = None
            try:
                function(scenario)
                if not scenario.commands or not scenario.assertions:
                    raise Invalid("scenario executed no commands or assertions")
            except Exception:
                error = traceback.format_exc()
            report["scenarios"].append({"id": name, "status": "FAILED" if error else "PASSED", "assertions": scenario.assertions, "commands": scenario.commands, "error": error})
    if implementation_inventory(root) != inventory:
        raise Invalid("implementation changed while E2Es were running; rerun")
    report["finished_at"] = now()
    if all(s["status"] == "PASSED" for s in report["scenarios"]):
        report["status"] = "PASSED"
    output = Path(output) if output else root / "artifacts/e2e" / f"{run_id}.json"
    atomic_json(output, report)
    return report, output
