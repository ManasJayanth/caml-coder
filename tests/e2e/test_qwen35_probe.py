"""Real-model E2E for the fixed Qwen3.5-9B runtime smoke."""
import hashlib
import json
from pathlib import Path
import sys
import uuid


MODEL_ID = "qwen35_9b"
REPO_ID = "Qwen/Qwen3.5-9B"
REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
TOKENIZER_SHA256 = "0756ac9b9343d39ddeda2767a3a18574f4f25cbb6281d0cf2c77572ed82ba9e9"
TEMPLATE_SHA256 = "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715"
CONFIG_SHA256 = "d0883072e01861ed0b2d47be3c16c36a8e81c224c7ffaa310c6558fb3f932b05"
OCAML_IMAGE_ID = "sha256:52ae74f2f384d509b9c001aaec682ad390202836b5c655358290f49d97934a9a"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def test_qwen35_probe(t):
    root = t.root
    probe_id = f"qwen35-probe-e2e-{uuid.uuid4().hex}"
    probe_result = t.command(
        [sys.executable, "scripts/probe_qwen35.py", "--config", "config/models.json", "--run-id", probe_id],
        timeout=300,
    )
    t.check(probe_result["exit_code"] == 0 and not probe_result["timeout"],
            "public standalone probe loads the selected model and exits successfully")
    probe_summary = json.loads(probe_result["stdout"])
    manifest_path = root / "artifacts/models/probes" / probe_id / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = _sha(manifest_bytes)
    manifest = json.loads(manifest_bytes)

    policy = json.loads((root / "config/execution-policy.json").read_text(encoding="utf-8"))
    selected = policy["student"]
    t.check(probe_summary["status"] == "PASSED" and probe_summary["manifest"] == str(manifest_path) and
            probe_summary["manifest_sha256"] == manifest_hash and manifest["id"] == probe_id and
            manifest["status"] == "PASSED" and manifest["model_id"] == MODEL_ID and
            manifest["repo_id"] == REPO_ID and manifest["revision"] == REVISION and
            selected["model_id"] == MODEL_ID and selected["revision"] == REVISION,
            "probe manifest binds the exact user-selected Qwen3.5-9B revision")
    t.check(manifest["architecture"]["config_sha256"] == CONFIG_SHA256 == selected["config_sha256"] and
            manifest["tokenizer"]["tokenizer_sha256"] == TOKENIZER_SHA256 == selected["tokenizer_sha256"] and
            manifest["tokenizer"]["chat_template_sha256"] == TEMPLATE_SHA256 == selected["template_sha256"] and
            manifest["runtime"]["prompt"]["enable_thinking"] is False and
            manifest["runtime"]["prompt"]["chat_template_sha256"] == TEMPLATE_SHA256,
            "loaded config, tokenizer, and native nonthinking template match frozen identities")

    runtime = manifest["runtime"]
    generation = runtime["generation"]
    device = runtime["device"]
    t.check(device["metal_available"] is True and "gpu" in device["default"].lower() and
            generation["method"] == "greedy" and generation["seed"] == 17 and
            generation["max_new_tokens"] == 128 and 0 < len(generation["token_ids"]) <= 128 and
            generation["eos_emitted"] is True and generation["finish_reason"] == "stop" and
            isinstance(generation["text"], str) and bool(generation["text"].strip()) and
            manifest["output_text"] == generation["text"] and
            manifest["output_token_ids"] == generation["token_ids"] and
            manifest["output_text_sha256"] == _sha(generation["text"].encode("utf-8")),
            "actual Metal GPU generation is nonempty, bounded, EOS-terminated, and hash-bound")
    t.check(manifest["readiness"] == {"scope": "runtime_probe_only", "generation_allowed": False,
                                      "benchmark": False, "code_executed": False},
            "probe explicitly limits its claim to runtime smoke evidence")

    checker_id = f"{probe_id}-ocaml-check"
    checker_result = t.command(
        [sys.executable, "scripts/check_ocaml_probe.py", "--result", str(manifest_path), "--run-id", checker_id],
        timeout=90,
    )
    t.check(checker_result["exit_code"] == 0 and not checker_result["timeout"],
            "isolated network-disabled OCaml checker compiles and executes the generated candidate")
    checker_summary = json.loads(checker_result["stdout"])
    checker_path = manifest_path.parent / "ocaml-checks" / f"{checker_id}.json"
    checker_bytes = checker_path.read_bytes()
    checker = json.loads(checker_bytes)
    t.check(checker_summary["status"] == "PASSED" and checker_summary["report"] == str(checker_path) and
            checker["status"] == "PASSED" and checker["probe_manifest_sha256"] == manifest_hash and
            checker["image_id"] == OCAML_IMAGE_ID and checker["platform"] == "linux/amd64" and
            "--network" in checker["command"] and checker["command"][checker["command"].index("--network") + 1] == "none" and
            "--read-only" in checker["command"] and "--cap-drop" in checker["command"] and
            checker["command"][checker["command"].index("--user") + 1] == "1000:1000" and
            checker["sentinel_seen"] is True and checker["exit_code"] == 0,
            "checker artifact records the exact probe and successful isolated compile/run sentinel")
    t.check(manifest_path.read_bytes() == manifest_bytes and _sha(manifest_path.read_bytes()) == manifest_hash and
            checker_path.read_bytes() == checker_bytes and
            checker["scope"] == "compile-and-fixed-example-smoke-only" and
            checker["benchmark"] is False and checker["robustness_claim"] is False,
            "probe and checker evidence remain immutable and explicitly make no benchmark claim")


SCENARIOS = {"qwen35-probe": test_qwen35_probe}
