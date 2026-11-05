# caml-coder

[Project dashboard](https://manasjayanth.github.io/caml-coder/) · [Latest local repair handoff](artifacts/planning/esy-repair-implementation-001/continuation-011/HANDOFF-011.md)

The dashboard is a dated status report; consult the saved handoffs for later work. Experimental repair candidates remain under artifacts/planning and are not imported into the application source. No trained-model or deployment acceptance is implied by publication.

# Local Qwen3.5-9B SFT experiment

The user selected **Qwen/Qwen3.5-9B** as the fixed student. Its pinned revision is `c202236235762e1c871ad0ccb60c8ee5ba337b9a`; tokenizer, chat-template and architecture/config hashes are frozen in `config/execution-policy.json`. Qwen3-8B is an optional historical comparator only and cannot gate or change the student choice. SELECTED-MODEL-SMOKE is a bounded local load/generation check with the native nonthinking template; it is not training, benchmark, or deployment evidence. MODEL-COMPARE records the selected model's development baseline and architecture readiness. Bonito generates documentation examples; Qwen3-Coder-30B-A3B-Instruct generates executed Pi trajectories. T12B pins raw inventories for Qwen3.5-9B, the optional comparator and these generators; T12C converts Bonito safely; T12 aggregates the evidence. Neither generator is the student.

The repository is under construction. Training is planned for an M4 Max with 128 GB unified memory; the quantized deployment target is an M1 with 16 GB. Commands must fail closed for unimplemented stages; a CLI entry point is not evidence that a stage works. Only end-to-end tests are used.

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --frozen
npm ci --ignore-scripts --cache "$PWD/.cache/npm"
./scripts/sft --help
./scripts/sft work next
./scripts/sft e2e --suite control --run-id control-check-001
```

Read [the execution contract](docs/PLAN.md) and [task cards](config/cards.json). Every passing card needs current E2E evidence. Real inference, tool isolation, dataset reviews, training, and deployment each require separate evidence. Fixture tests cannot establish real-model readiness.

Generated artifacts live under `artifacts/`, mutable workflow state under `state/`, and weights under `weights/`. Do not commit personal data, credentials, weight binaries, or generated private datasets. Pilot and final dataset approvals belong to the user. No promotion is authorized before frontier review.

The current extension adds sticky workflow gates, evidence-content verification, source candidate triage (`prepare` with `config/eligibility.json`), and a fenced attempt ledger (`attempts`). Candidate triage is not corpus approval: every row is generation-forbidden until reviewed source spans and compatible locked toolchains are proven. The task registry includes explicit prerequisite repairs, tokenizer acquisition before chunking, a catalogue runner, and one bounded card per task family. Most later stages remain unimplemented. MODEL-COMPARE uses only the 20-task development set to record baseline and selected-architecture readiness for the already selected Qwen3.5-9B; final holdout scores cannot change the student identity. Selection does not establish training readiness, and no M1 deployment result is established yet.

Use `./scripts/sft handoff --config config/handoff-progress.json --run-id <new-id>` to print a complete frontier-review prompt and build its checksummed evidence bundle. A progress handoff documents incomplete work; it does not certify a trained model.
