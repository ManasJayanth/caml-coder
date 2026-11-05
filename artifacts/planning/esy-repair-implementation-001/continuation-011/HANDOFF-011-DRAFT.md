# HANDOFF-011 (DRAFT, root-authored) — continuation-011, 2026-10-23

MILESTONE VERDICT: **INCOMPLETE** (review-worker adapter acceptance not started; orchestration layer reviewed once, findings dispositioned into cards; coding launches blocked on the guardian route).
`loop.py handoff` is correctly refusing (`HANDOFF_BLOCKED`: 4 non-terminal cards; no accepted source review of orch-007). This draft is the honest substitute; it binds the same state.

## 1. Revision identity
| item | value |
|---|---|
| orchestration snapshot in force | `frozen/orch-007`, inventory hash `984ef2df1b2298cb86477e8c3aea4f41d0a35943e1754fbfc34725331cea245f` (manifest sha `ab567810…`) |
| `state.orch_hash` / `state.parent_hash` | both == orch-007 |
| last reviewed snapshot | `frozen/orch-004` (`8bab0af6dcea…`) by Fable — INCOMPLETE; orch-005/006/007 changed only loop mechanics (approval flag, review-JSON-in-planner-prompt, set-parent, backfill-review, NO-TOOLS prompt lines, narrowed placeholder validator) and are **unreviewed** |
| E2E-ORCH suite | 45/45 PASS at orch-007 (`e2e/run_e2e.py`) |
| Plan 011 inputs | RESULT-010, continuation-010 untouched; `candidate/scripts/esy-repair/codex-worker.sh` sha `e036f5ce…`; `continuation-008/pi-nofork-v3.sb` sha `6f5bd2ea…` |

## 2. Launch / time ledger
- Coding launches: **36/48 consumed, 0 this continuation**, 12 remaining. Reviews/plans/smokes consume no slot (M2 disposition: rejected as "by design", encoded by O01/O25).
- Active time: **28516.8 s / 32400 → 3883.2 s remaining** (`state.active_seconds`; `time-reconciliation.json` + ledger `root_interval` entries; every root-authored interval added, launch elapsed never subtracted; idle approval gap 15:27→19:21 documented, not counted).
- Model invocations (all through `orch/worker-claude.sh review|plan`, `run_bounded.py`, strict `review-readonly.sb`):
  review-001 codex strict-profile fail · review-002 codex **usage-limit until 2026-10-29 22:41** · review-003 fable private-config "Not logged in" · review-004 fable real-config **SMOKE_OK** (`claude-fable-5-1`, 12.2 s) · review-005 fable source review of orch-004 (293.4 s, packet 87423 B, sha `dd7a4643…`, out sha `529a9561…`) → INCOMPLETE · plan-006 fable (REVIEW_JSON null → malformed) · plan-007 fable (rejected by over-strict validator) · plan-008 fable **REPLAN_OK** (95.4 s, packet sha `0ab782be…`, out sha `8a14b462…`).
- Same-backend approvals recorded in `state.same_backend_approvals` (3 entries, one per replan attempt; user: "Approve Fable replan").

## 3. Fable review of orch-004 — findings and dispositions (plan-008)
| id | sev | finding (short) | disposition |
|---|---|---|---|
| F1 | high | card acceptance can discard a sibling card's accepted edits (no base-hash gate) | card:C1 |
| F2 | med | e2e may mutate the tree after `tree_hash`; acceptance binds stale hash | card:C2 |
| F3 | med | milestone ACCEPTED flag not revision-bound | card:C4 |
| F4 | med | prep failure after reserve leaves card RESERVED forever | card:C3 |
| F5 | med | card `e2e.argv` runs unsandboxed | deferred (needs new profile) |
| F6 | low | packet hash taken after the model run | deferred |
| F7 | low | comment vs profile on CLAUDE_REAL_CONFIG | deferred — NOTE: profile was deliberately left strict; the real-config route *did* work (review-004/005/plan-008) without widening it, so the comment is wrong, not the profile |
| F8 | low | directories invisible to inventory | deferred |
| F9 | low | ORCH_ENV_PASSTHROUGH unconditional | deferred |
| F10 | low | hardcoded accounting defaults | deferred |
| M0 | — | codex-worker.sh / pi profile not in subject | deferred (outside parent tree) |
| M1 | — | no suite-run artifact in packet | deferred (supervisor evidence) — suite result now in this handoff |
| M2 | — | launch-cap policy for reviews unstated | rejected (by design) |

## 4. Cards (orch/cards/*.json; sha C1 `243157aa…` C2 `cc5c8940…` C3 `c1221ea2…` C4 `fec7759c…`), all PENDING, timeout 480, paths `loop.py` + `e2e/run_e2e.py`, chained C1→C2→C3→C4
- **Known plan defect**: C3 and C4 name E2E scenarios `O46`/`O47`, which already exist in `run_e2e.py` (set-parent / backfill-review). Their own stop conditions would make a worker print `CARD_BLOCKED`. The planner only saw the inventory, not the file. First action for the next planner: re-issue C3/C4 with free ids (e.g. O48/O49) — or give the planner the scenario-id list. C1 (`O32`) and C2 (`O43`) are free.
- Cards cannot be dispatched yet: `run-card` refuses with `GUARDIAN_PATH_NOT_IMPLEMENTED` (real-credential Pi launch via `continuation-008/guardian-v2.py` is not wired). That integration is itself a reviewed root/bootstrap change, per Plan 011 §3.

## 5. Hygiene / preservation
- `continuation-008/pi-runtime-v2/private-pi/` empty throughout. No `auth.json` symlink residue under `orch/evidence/*/runtime/codex` (ledger `credential_lifecycle removed=true` for every codex/fable run after review-001).
- **Observation**: `~/.codex/auth.json` mtime moved 1792077133 → 1792764366 (19:39:26). No orchestration launch was running then (review-002 ended 19:34:49; review-004 began 19:45:23) and the review profile denies writes outside `orch/evidence`/`tmp`; the most plausible writer is the user's own Codex app/daemon refreshing its token. Attribution not verified by this supervisor; recorded, not hidden.
- Lock free; no uncertain jobs; original source and continuation-010 untouched; no import into original source.

## 6. Open blockers, ordered
1. Guardian/real-credential Pi route not implemented → no coding launch possible (needs a small reviewed bootstrap card + E2E).
2. C3/C4 scenario-id collision (re-plan needed; cheap).
3. orch-005..007 loop-mechanics changes unreviewed (needs a Fable source review of orch-007, ~300 s; the 300 s review cap was nearly hit at 87 KB — larger packets need indexed parts or a reviewed cap change).
4. Codex/Astra unavailable until 2026-10-29 22:41; all planning/review this continuation was Fable with recorded approval.
5. Time: 3883 s remain — enough for one source review + one replan, not for a 600 s coding card plus its review and reserve.

## 7. Next bound small step
`python3 -B orch/loop.py review --subject "$PWD/frozen/orch-007" --name orch-007 --backend fable` → if accepted, replan C3/C4 ids → implement guardian route as a reviewed card → then `run-card C1` (slot 37).

## 8. Independent-review prompt (populated from state; for the next frontier reviewer)
```
You are the independent reviewer of the continuation-011 orchestration layer ONLY. No tools; do not infer runtime
evidence from source closure. REVISION: 984ef2df1b2298cb86477e8c3aea4f41d0a35943e1754fbfc34725331cea245f (frozen/orch-007).
PRIOR REVIEW: seq 5 of orch-004 (8bab0af6dcea…), INCOMPLETE, findings F1-F10 + M0-M2 with dispositions above.
CHANGES SINCE: loop mechanics only (same-backend approval gate, REVIEW_JSON in planner prompt, set-parent,
backfill-review, NO-TOOLS prompt lines, placeholder validator limited to machine-consumed fields).
E2E-ORCH: 45/45 at this revision. SMOKES: fable real-config OK (claude-fable-5-1); codex usage-limited.
ACCOUNTING: launches 36/48; active 28516.8/32400 s. CARDS: C1-C4 pending (C3/C4 scenario ids collide).
TASK: check correctness/regression/provenance/process ownership/finite-failure contract. Return exactly ONE fenced
json block {revision, findings[{id,severity,location,evidence}], missing_evidence[], coverage{complete,truncated},
cleanup, verdict ACCEPTED|INCOMPLETE|BLOCKED}. ACCEPTED requires zero findings and zero missing evidence.
```
(The machine-built packet from `loop.py review --subject frozen/orch-007` inlines all 10 source files; this prose block is the human summary of its header.)
