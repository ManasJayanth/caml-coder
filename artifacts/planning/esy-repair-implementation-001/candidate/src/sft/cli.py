import argparse
from pathlib import Path
import sys
from . import __version__
from .artifacts import Invalid, atomic_json, canonical, digest, identifier, implementation_hash, read_json, safe_path, validate_jsonl


def parser():
    p = argparse.ArgumentParser(prog="sft", description="Evidence-gated local Qwen3-8B SFT pipeline")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--state", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    work = sub.add_parser("work").add_subparsers(dest="action", required=True)
    work.add_parser("next")
    work.add_parser("status")
    record = work.add_parser("record")
    record.add_argument("card")
    record.add_argument("status")
    record.add_argument("--evidence", type=Path)
    record.add_argument("--reason")
    e2e = sub.add_parser("e2e")
    e2e.add_argument("--suite", required=True)
    e2e.add_argument("--run-id", required=True)
    e2e.add_argument("--output", type=Path)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--config", type=Path, required=True)
    doctor.add_argument("--run-id", required=True)
    val = sub.add_parser("validate")
    val.add_argument("--input", type=Path, required=True)
    val.add_argument("--schema", required=True)
    val.add_argument("--run-id", required=True)
    commit = sub.add_parser("artifact-commit", help="Commit a strict JSON object immutably")
    commit.add_argument("--input", type=Path, required=True)
    commit.add_argument("--run-id", required=True)
    verify = sub.add_parser("verify", help="Verify a review bundle against an independently supplied index hash")
    verify.add_argument("--index", type=Path, required=True)
    verify.add_argument("--expected-index-hash", required=True)
    for name in ("fetch", "prepare", "attempts", "generate-docs", "generate-traces", "export", "train", "evaluate", "package", "handoff"):
        stage = sub.add_parser(name, help="Reserved pipeline stage; fails closed until implemented")
        stage.add_argument("--run-id", required=True)
        stage.add_argument("--config", type=Path, required=True)
    review = sub.add_parser("review")
    review.add_argument("action", choices=["export", "import"])
    review.add_argument("--run-id", required=True)
    review.add_argument("--config", type=Path, required=True)
    return p


def dispatch(args):
    root = args.root.resolve()
    state = args.state.resolve() if args.state else root / "state"
    if hasattr(args, "run_id"):
        identifier(args.run_id)
    if args.command == "work":
        from . import workflow
        if args.action == "next":
            return workflow.next_card(root, state), 0
        if args.action == "status":
            return workflow.snapshot(root, state), 0
        return workflow.record(root, state, args.card, args.status, args.evidence, args.reason), 0
    if args.command == "e2e":
        from .e2e import execute
        report, path = execute(root, args.suite, args.run_id, args.output)
        return {"status": report["status"], "report": str(path)}, 0 if report["status"] == "PASSED" else 1
    if args.command == "doctor":
        from .doctor import inspect
        result = inspect(root, read_json(args.config))
        result.update(schema_version=1, id=args.run_id, config_hash=digest(result["effective_config"]), implementation_hash=implementation_hash(root))
        output = safe_path(root, f"artifacts/doctor/{args.run_id}/report.json")
        atomic_json(output, result)
        return {**result, "report": str(output)}, 0 if result["status"] == "PASSED" else 3
    if args.command == "fetch":
        from .corpus import fetch
        manifest, output = fetch(root, read_json(args.config), args.run_id)
        return {"status":"PASSED", "scope":"source-fetch-only", "kind":manifest["kind"], "manifest":str(output), "files":len(manifest["files"])}, 0
    if args.command == "prepare":
        config = read_json(args.config)
        if config.get("stage") == "extraction":
            from .extract import prepare
        elif config.get("stage") == "model_assets":
            from .model_assets import prepare
        elif config.get("stage") == "splits":
            from .splits import prepare
        elif config.get("stage") == "bonito_conversion":
            from .conversion import prepare
        elif config.get("stage") == "chunks":
            from .chunks import prepare
        elif config.get("stage") == "models":
            from .models import prepare
        else:
            from .eligibility import prepare
        return prepare(root, config, args.run_id)
    if args.command == "attempts":
        from .ledger import dispatch as ledger_dispatch
        return ledger_dispatch(root, read_json(args.config), args.run_id)
    if args.command == "verify":
        from .handoff import verify
        return verify(args.index, args.expected_index_hash), 0
    if args.command == "handoff":
        from .handoff import build
        prompt, output = build(root, state, read_json(args.config), args.run_id)
        # This command deliberately prints the actual populated reviewer prompt.
        return prompt, 0
    if args.command == "validate":
        identifier(args.schema)
        contract = read_json(safe_path(root, f"schemas/{args.schema}.json"))
        records = validate_jsonl(args.input, contract)
        result = {"schema_version": 1, "id": args.run_id, "status": "PASSED", "record_count": len(records), "input_hash": digest(records), "contract_hash": digest(contract), "implementation_hash":implementation_hash(root)}
        atomic_json(safe_path(root, f"artifacts/validation/{args.run_id}.json"), result)
        return result, 0
    if args.command == "artifact-commit":
        value = read_json(args.input)
        if not isinstance(value, dict):
            raise Invalid("artifact must be a JSON object")
        path = safe_path(root, f"artifacts/objects/{args.run_id}.json")
        atomic_json(path, value)
        return {"path": str(path), "hash": digest(value)}, 0
    return {"status": "BLOCKED", "reason": f"{args.command} has not been implemented or verified; no generation, training, or promotion performed"}, 3


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result, code = dispatch(args)
    except (Invalid, ValueError, OSError, KeyError) as error:
        result, code = {"status": "FAILED", "error": str(error)}, 2
    except KeyboardInterrupt:
        result, code = {"status": "INTERRUPTED"}, 130
    sys.stdout.buffer.write(result.encode("utf-8") if isinstance(result, str) else canonical(result) + b"\n")
    return code
