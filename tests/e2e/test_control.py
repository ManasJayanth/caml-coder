"""No unit tests: every behavior is exercised through a public subprocess."""
import hashlib
import ast
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import sys


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")
    return path


def test_bootstrap(t):
    t.cli("--version")
    result = t.cli("--help")
    t.check("generate-traces" in result["stdout"] and "work" in result["stdout"], "public CLI stages exposed")
    result = t.command(["npm", "run", "check"])
    t.check(result["exit_code"] == 0, "TypeScript typecheck passes")
    result = t.command(["npm", "run", "probe"], timeout=60)
    t.check(result["exit_code"] == 0 and '"status":"PASSED"' in result["stdout"], "pinned Pi SDK entrypoints import without creating a session")
    clone = t.temporary / "missing-runtime"
    (clone / "scripts").mkdir(parents=True)
    shutil.copy2(t.root / "scripts/sft", clone / "scripts/sft")
    result = t.command([str(clone / "scripts/sft"), "--version"])
    t.check(result["exit_code"] == 3 and "environment missing" in result["stderr"], "missing runtime is a concrete blocker")
    t.cli("train", "--run-id", "unimplemented", "--config", "unused.json", expected=3)
    clean = t.temporary / "fresh-install"
    clean.mkdir()
    for name in ("pyproject.toml", "uv.lock", ".python-version", "package.json", "package-lock.json"):
        shutil.copy2(t.root / name, clean / name)
    shutil.copytree(t.root / "src", clean / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(t.root / "pi", clean / "pi")
    env = {**os.environ, "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(t.root / ".cache/uv"))}
    result = t.command(["uv", "sync", "--frozen", "--offline"], cwd=clean, env=env, timeout=60)
    t.check(result["exit_code"] == 0, "fresh Python environment installs from lock and local cache")
    result = t.command([str(clean / ".venv/bin/sft"), "--version"], cwd=clean)
    t.check(result["exit_code"] == 0, "fresh installed console entrypoint runs")
    result = t.command(["npm", "ci", "--ignore-scripts", "--offline", "--cache", os.environ.get("npm_config_cache", str(t.root / ".cache/npm"))], cwd=clean, timeout=60)
    t.check(result["exit_code"] == 0, "fresh npm environment installs exact dependency lock offline")
    result = t.command(["npm", "run", "probe"], cwd=clean, timeout=60)
    t.check(result["exit_code"] == 0, "fresh Pi dependency installation loads")


def fixture_root(t, name="project"):
    root = t.temporary / name
    root.mkdir()
    for name in ("config", "schemas"):
        shutil.copytree(t.root / name, root / name)
    catalogue = json.loads((root / "config/cards.json").read_text())
    cards = [next(card for card in catalogue if card["id"] == key) for key in ("T01", "T02")]
    cards[1]["dependencies"] = [cards[0]["id"]]
    write(root / "config/cards.json", cards)
    return root


def fixture_report(root, *, scenarios=None, status="PASSED"):
    # External evidence document fixture. No internal workflow functions imported.
    inventory = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and p.parts[len(root.parts)] in ("config", "schemas")}
    sha = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {"schema_version":1,"id":"fixture-evidence","kind":"e2e","tier":"deterministic","status":status,"implementation_hash":sha,"inventory":inventory,"started_at":"2026-01-01T00:00:00+00:00","finished_at":"2026-01-01T00:00:01+00:00","command":["fixture"],"scenarios":scenarios if scenarios is not None else [{"id":"bootstrap","status":"PASSED","assertions":[{"description":"fixture assertion","passed":True}],"commands":[{"argv":["fixture"],"exit_code":0}]}]}


def test_workflow(t):
    root = fixture_root(t)
    t.cli("work", "record", "T02", "RUNNING", "--reason", "test", root=root, expected=2)
    first = t.cli("work", "next", root=root)
    t.check(json.loads(first["stdout"])["card"]["id"] == "T01", "first ready card selected")
    good = write(t.temporary / "good.json", fixture_report(root))
    for variant, report in [
        ("empty", fixture_report(root, scenarios=[])),
        ("skip", fixture_report(root, scenarios=[{"id":"bootstrap","status":"SKIPPED","assertions":[True],"commands":["test"]}])),
        ("missing", fixture_report(root, scenarios=[{"id":"other","status":"PASSED","assertions":[True],"commands":["test"]}])),
        ("failed", fixture_report(root, status="FAILED")),
        ("false-assertion", fixture_report(root, scenarios=[{"id":"bootstrap","status":"PASSED","assertions":[{"description":"false", "passed":False}],"commands":[{"argv":["test"]}]}])),
    ]:
        path = write(t.temporary / f"{variant}.json", report)
        t.cli("work", "record", "T01", "PASSED", "--evidence", path, root=root, expected=2)
    t.cli("work", "record", "T01", "PASSED", "--evidence", good, root=root)
    second = t.cli("work", "next", root=root)
    t.check(json.loads(second["stdout"])["card"]["id"] == "T02", "valid prerequisite unlocks next card")
    with (root / "config/cards.json").open("a") as f:
        f.write("\n")
    stale = t.cli("work", "status", root=root)
    t.check(json.loads(stale["stdout"])["T01"]["status"] == "STALE", "modified code/config invalidates evidence")
    t.cli("work", "record", "T02", "RUNNING", "--reason", "test", root=root, expected=2)
    for i in range(3):
        t.cli("work", "record", "T01", "FAILED", "--reason", f"repair {i+1}", root=root)
    t.cli("work", "record", "T01", "RUNNING", "--reason", "fourth repair", root=root, expected=2)
    t.cli("work", "record", "T01", "NEEDS_REPLAN", "--reason", "three repairs exhausted", root=root)
    t.check(json.loads(t.cli("work", "status", root=root)["stdout"])["T01"]["status"] == "NEEDS_REPLAN", "three failures preserve the replan gate")


def _e2e_suite_map(path):
    tree = ast.parse(path.read_text())
    execute = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute")
    assignment = next(node for node in ast.walk(execute)
                      if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "allowed" for target in node.targets))
    return ast.literal_eval(assignment.value)


def _scenario_ids(path):
    tree = ast.parse(path.read_text())
    assignment = next(node for node in tree.body
                      if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SCENARIOS" for target in node.targets))
    return {ast.literal_eval(key) for key in assignment.value.keys}


def test_card_interfaces(t):
    cards = json.loads((t.root / "config/cards.json").read_text())
    suite_map = _e2e_suite_map(t.root / "src/sft/e2e.py")
    registered = set(suite_map)
    by_id = {card["id"]: card for card in cards}
    for card in cards:
        card_id = card["id"]
        command = shlex.split(card["commands"][0])
        suite = command[command.index("--suite") + 1]
        allowed = set(card["allowed_files"])
        unresolved = set(re.findall(r"<[^>]+>", " ".join(card["commands"]))) - {"<unique-run-id>", "<report-path>"}
        t.check(not unresolved, f"{card_id} command templates contain no unsupported placeholders")
        if card_id.startswith("TASK-"):
            task_id = card_id[5:]
            t.check(suite == "catalogue-task" and command[command.index("--task") + 1] == task_id,
                    f"{card_id} invokes the shared suite with its concrete task ID")
            t.check(card["required_scenarios"] == [f"catalogue-{task_id}"],
                    f"{card_id} requires its task-specific evidence scenario")
            def depends_on_runner(candidate, visited=None):
                visited = visited or set()
                if candidate in visited:
                    return False
                visited.add(candidate)
                return any(parent == "CATALOGUE-RUNNER" or depends_on_runner(parent, visited)
                           for parent in by_id[candidate]["dependencies"])
            t.check(depends_on_runner(card_id), f"{card_id} transitively depends on catalogue runner")
            continue
        if card_id == "CATALOGUE-RUNNER":
            t.check(suite == "catalogue-runner" and "--task" not in command,
                    "catalogue runner uses a dedicated bootstrap suite without a task placeholder")
            t.check(card["required_scenarios"] == ["catalogue-runner"],
                    "catalogue runner requires its exact bootstrap evidence scenario")
            t.check({"src/sft/e2e.py", "src/sft/cli.py", "tests/e2e/test_catalogue_runner.py", "fixtures/catalogue-runner/**"} <= allowed,
                    "catalogue runner owns suite wiring, selector, scenario and synthetic fixture")
            if suite in registered:
                test_path = "tests/e2e/" + suite_map[suite]
                t.check(test_path in allowed and set(card["required_scenarios"]) <= _scenario_ids(t.root / test_path),
                        "registered catalogue bootstrap suite implements its required scenario")
            else:
                t.check(suite not in registered, "catalogue bootstrap suite remains pending until registered")
            continue
        if suite in registered:
            test_path = "tests/e2e/" + suite_map[suite]
            scenario_ids = _scenario_ids(t.root / test_path)
            t.check(test_path in allowed and set(card["required_scenarios"]) <= scenario_ids,
                    f"{card_id} authorizes registered suite {suite} and its required scenarios")
        else:
            test_path = f"tests/e2e/test_{suite.replace('-', '_')}.py"
            t.check({"src/sft/e2e.py", "src/sft/cli.py", test_path} <= allowed,
                    f"{card_id} owns pending suite {suite} registration, CLI wiring and scenario file")
            t.check(suite not in registered, f"pending suite {suite} is not reported as implemented")

    runner = by_id["CATALOGUE-RUNNER"]
    t.check("src/sft/e2e.py" in runner["allowed_files"] and "src/sft/cli.py" in runner["allowed_files"],
            "catalogue-task family suite and selector have an explicit predecessor owner")

    root = fixture_root(t, "card-interface-project")
    evidence_path = write(t.temporary / "interface-bootstrap.json", fixture_report(root))
    t.cli("work", "record", "T01", "PASSED", "--evidence", evidence_path, root=root)
    packet = json.loads(t.cli("work", "next", root=root)["stdout"])
    t.check(packet["card"]["id"] == "T02", "public work next selects a card with passed prerequisites")
    commands = packet["card"]["commands"]
    t.check(all("<" not in command and "work-T02-" in command for command in commands),
            "work next emits concrete run IDs and evidence paths for every card command")

    def ready_packet(target_id, name, prerequisite_scenario="bootstrap"):
        fixture = fixture_root(t, name)
        actual = {card["id"]:card for card in cards}
        target = dict(actual[target_id])
        target["dependencies"] = ["T01"]
        write(fixture / "config/cards.json", [actual["T01"], target])
        evidence = write(t.temporary / f"{name}-prerequisite.json",
                         fixture_report(fixture, scenarios=[{"id":prerequisite_scenario,"status":"PASSED",
                             "assertions":[{"description":"fixture prerequisite","passed":True}],
                             "commands":[{"argv":["fixture"],"exit_code":0}]}]))
        t.cli("work", "record", "T01", "PASSED", "--evidence", evidence, root=fixture)
        return json.loads(t.cli("work", "next", root=fixture)["stdout"])

    runner_packet = ready_packet("CATALOGUE-RUNNER", "runner-ready")
    runner_commands = runner_packet["card"]["commands"]
    t.check(runner_packet["card"]["id"] == "CATALOGUE-RUNNER" and
            "--suite catalogue-runner" in runner_commands[0] and "--task" not in runner_commands[0] and
            all("<" not in command for command in runner_commands),
            "work next emits the concrete dedicated catalogue bootstrap command")

    family_packet = ready_packet("TASK-esy-practical-01", "family-ready")
    family_commands = family_packet["card"]["commands"]
    t.check(family_packet["card"]["id"] == "TASK-esy-practical-01" and
            "--suite catalogue-task" in family_commands[0] and "--task esy-practical-01" in family_commands[0] and
            all("<" not in command for command in family_commands),
            "work next emits the concrete selected-family task command")

    pending_packet = ready_packet("T12", "pending-suite-ready")
    t.check(pending_packet["card"]["id"] == "T12" and pending_packet["current"]["status"] == "PENDING" and
            "--suite models" in pending_packet["card"]["commands"][0] and
            all("<" not in command for command in pending_packet["card"]["commands"]),
            "pending but unregistered model suite still receives concrete work-next commands")


def test_workflow_gates(t):
    root = fixture_root(t)
    for gate in ("WAITING_APPROVAL", "NEEDS_REPLAN"):
        state = t.temporary / f"gate-{gate}"
        t.cli("work", "record", "T01", gate, "--reason", "human decision required", root=root, state=state)
        script = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); blocked=[]\nfor sql in (\"UPDATE events SET status='BLOCKED' WHERE card='T01'\", \"DELETE FROM events WHERE card='T01'\"):\n try: c.execute(sql); blocked.append(False)\n except sqlite3.IntegrityError: blocked.append(True)\nprint(blocked); sys.exit(0 if all(blocked) else 1)"
        protected = t.command([sys.executable, "-c", script, str(state / "workflow.sqlite")])
        t.check(protected["exit_code"] == 0, f"{gate} event UPDATE and DELETE are rejected by SQLite triggers")
        for attempted in ("BLOCKED", "FAILED", "RUNNING", "PASSED"):
            t.cli("work", "record", "T01", attempted, "--reason", "attempted transition", root=root, state=state, expected=2)
            snapshot = json.loads(t.cli("work", "status", root=root, state=state)["stdout"])
            t.check(snapshot["T01"]["status"] == gate, f"{gate} remains visible after rejected {attempted} transition")
        script = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.executemany('INSERT INTO events(card,status,payload) VALUES(?,?,?)', [('T01','BLOCKED','{\"reason\":\"legacy bypass hop 1\"}'),('T01','FAILED','{\"reason\":\"legacy bypass hop 2\"}')]); c.commit()"
        raw = t.command([sys.executable, "-c", script, str(state / "workflow.sqlite")])
        t.check(raw["exit_code"] == 0, f"{gate} history includes simulated legacy multi-hop bypass")
        snapshot = json.loads(t.cli("work", "status", root=root, state=state)["stdout"])
        t.check(snapshot["T01"]["status"] == gate, f"historical {gate} gate survives later BLOCKED and FAILED events")


def test_workflow_evidence_integrity(t):
    for mutation in ("commands", "stdout", "assertions", "missing-hash", "malformed-hash"):
        root = fixture_root(t, f"project-{mutation}")
        state = t.temporary / f"integrity-{mutation}"
        report = fixture_report(root)
        source = write(t.temporary / f"evidence-{mutation}.json", report)
        recorded = t.cli("work", "record", "T01", "PASSED", "--evidence", source, root=root, state=state)
        saved = Path(json.loads(recorded["stdout"])["evidence"])
        dependent = fixture_report(root, scenarios=[{"id":"workflow","status":"PASSED","assertions":[{"description":"dependent assertion","passed":True}],"commands":[{"argv":["fixture-dependent"],"exit_code":0}]}])
        dependent_source = write(t.temporary / f"dependent-{mutation}.json", dependent)
        t.cli("work", "record", "T02", "PASSED", "--evidence", dependent_source, root=root, state=state)
        unchanged = json.loads(t.cli("work", "status", root=root, state=state)["stdout"])
        t.check(unchanged["T01"]["status"] == "PASSED" and unchanged["T02"]["status"] == "PASSED", "untampered evidence keeps prerequisite and dependent passed")
        if mutation in {"commands", "assertions"}:
            committed = json.loads(saved.read_text())
            if mutation == "commands":
                committed["scenarios"][0]["commands"][0]["argv"].append("tampered")
            else:
                committed["scenarios"][0]["assertions"][0]["description"] = "tampered assertion"
            saved.write_text(json.dumps(committed) + "\n")
        elif mutation == "stdout":
            committed = json.loads(saved.read_text())
            committed["scenarios"][0]["commands"][0]["stdout"] = "tampered output only"
            saved.write_text(json.dumps(committed) + "\n")
        else:
            database = state / "workflow.sqlite"
            # Deliberately simulate an old/corrupted DB in this temporary E2E
            # state, where append-only triggers did not yet exist.
            script = "import json,sqlite3,sys; p=sys.argv[1]; c=sqlite3.connect(p); c.execute('DROP TRIGGER IF EXISTS events_no_update'); c.execute('DROP TRIGGER IF EXISTS events_no_delete'); row=c.execute(\"SELECT seq,payload FROM events WHERE card='T01' ORDER BY seq DESC LIMIT 1\").fetchone(); d=json.loads(row[1]); d.pop('evidence_hash',None) if sys.argv[2]=='missing-hash' else d.update(evidence_hash='not-a-digest'); c.execute('UPDATE events SET payload=? WHERE seq=?',(json.dumps(d),row[0])); c.commit()"
            result = t.command([sys.executable, "-c", script, str(database), mutation])
            t.check(result["exit_code"] == 0, f"{mutation} fixture modifies the persisted event log")
        snapshot = json.loads(t.cli("work", "status", root=root, state=state)["stdout"])
        t.check(snapshot["T01"]["status"] == "STALE", f"{mutation} invalidates passing evidence")
        t.check(snapshot["T02"]["status"] == "STALE", f"{mutation} propagates stale status to dependent evidence")
        t.cli("work", "record", "T02", "RUNNING", "--reason", "try to use stale prerequisite", root=root, state=state, expected=2)


def test_artifacts(t):
    root = fixture_root(t)
    record = {"id":"r1","schema_version":1,"artifact_hash":"a"*64,"reviewer":"reviewer","rubric":"v1","verdict":"accepted","reasons":[],"approved_targets":[]}
    data = write(t.temporary / "valid.jsonl", record)
    t.cli("validate", "--input", data, "--schema", "review", "--run-id", "valid", root=root)
    for name, content in [
        ("unknown", json.dumps({**record,"surprise":True})),
        ("schema", json.dumps({**record,"schema_version":2})),
        ("bad-hash", json.dumps({**record,"artifact_hash":"oops"})),
        ("duplicate-id", json.dumps(record)+"\n"+json.dumps(record)),
        ("duplicate-key", '{"id":"one","id":"two"}'),
        ("broken", '{"id":'), ("empty", ''),
        ("nan", '{"id":NaN}'),
        ("type", json.dumps({**record,"approved_targets":"all"})),
    ]:
        path = t.temporary / f"{name}.jsonl"
        path.write_text(content)
        t.cli("validate", "--input", path, "--schema", "review", "--run-id", name, root=root, expected=2)
    value = write(t.temporary / "object.json", {"hello":"κόσμε"})
    t.cli("artifact-commit", "--input", value, "--run-id", "object", root=root)
    committed = root / "artifacts/objects/object.json"
    before = committed.read_bytes()
    t.cli("artifact-commit", "--input", value, "--run-id", "object", root=root)
    t.check(committed.read_bytes() == before, "identical commit is idempotent")
    write(value, {"changed": True})
    t.cli("artifact-commit", "--input", value, "--run-id", "object", root=root, expected=2)
    t.check(committed.read_bytes() == before, "conflicting commit preserves original")
    (root / "artifacts/objects/.pending-interrupted").write_text('{"broken":')
    t.cli("artifact-commit", "--input", value, "--run-id", "fresh", root=root)
    t.check(json.loads((root / "artifacts/objects/fresh.json").read_text()) == {"changed": True}, "partial temp file never masquerades as committed artifact")
    t.cli("artifact-commit", "--input", value, "--run-id", "../escape", root=root, expected=2)
    (root / "artifacts/objects/linked.json").symlink_to(value)
    t.cli("artifact-commit", "--input", value, "--run-id", "linked", root=root, expected=2)


def test_harness(t):
    result = t.command([sys.executable, "-c", "print('hello')"])
    t.check(result["exit_code"] == 0 and result["stdout"].strip() == "hello", "subprocess output captured")
    result = t.command([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)
    t.check(result["timeout"] and result["exit_code"] != 0, "timeout classified and child killed")
    result = t.command([sys.executable, "-c", "import os; os._exit(7)"])
    t.check(not result["timeout"] and result["exit_code"] == 7, "crash distinct from timeout")
    result = t.command([sys.executable, "-c", "print('x'*300000)"])
    t.check(result["output_truncated"], "verbose process memory capture bounded")
    t.cli("e2e", "--suite", "nonexistent", "--run-id", "missing", expected=2)


SCENARIOS = {"bootstrap": test_bootstrap, "workflow": test_workflow, "workflow-gates": test_workflow_gates,
             "workflow-evidence": test_workflow_evidence_integrity, "card-interfaces": test_card_interfaces,
             "artifacts": test_artifacts, "harness": test_harness}
