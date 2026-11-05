# PLAN-013 REQUEST — from the pi agent (tmux pane %2) to the Claude session (pane %3)

Date: 2026-10-23 (round 4 of PLAN 012 just closed; see handoff below).
From: pi coding agent, sibling pane (`%2`), acting on an explicit operator instruction relayed verbatim below.
To: Claude Code session in pane `%3` of this repo.

## Operator instruction (verbatim intent, relayed by pi)

> send it the handoff and ask it to plan the next step and get back to you with a plan file. The plan needs to
> break down the tasks so that smaller coding models can execute it. it needs a workflow loop and e2e test. it
> needs to think through possible edge cases and have e2e tests for it too. dont bother with unit tests. only e2e
> tests. The plan must not gaps. address it should be small coding model friendly. make this your goal. small
> coding model friendly zero gaps correct safe plan. I want the final step to be a review prompt so that a
> frontier model can review all the work done. This plan must print such a handoff prompt so that the frontier
> model has all the context it needs. inline the orchestration script always. write claude, pi coding and codex
> orchestration scripts so that this plan is portable

## Your deliverable

1. Author **PLAN 013 — Round 5** for the continuation described in HANDOFF-011 (inlined below in full): the next
   bound steps, ordered, with honest stop rules. Write it to
   `artifacts/planning/esy-repair-implementation-001/continuation-011/PLAN-013-ROUND5.md`
   (adjust the path only if an established plan-file convention exists in the repo; state where you put it).
2. The plan MUST be:
   - **Small-coding-model friendly, zero gaps, correct, safe — this is the stated goal.** One objective per card;
     fixed machine-assembled card template; allowed paths (1–3, relative); each single edit < 3000 chars;
     acceptance rows that are machine-checkable; a fixed E2E command per card; stop conditions that tell the
     worker exactly when to print CARD_BLOCKED. No prose planning ever reaches a coding worker.
   - **Workflow loop**: card lifecycle PENDING → … → ACCEPTED with attempt/slot/time/uncertainty gates, review by
     a frontier model, re-plan on findings by a DIFFERENT frontier model (Codex/Astra returns 2026-10-29 22:41;
     until then Fable with recorded same-backend approval), every finding getting a disposition
     (card:/rejected:/deferred:), loop until a review returns nothing to address or a stop rule fires.
   - **E2E tests ONLY — no unit tests.** Every card's proof is a real subprocess E2E. Think through the edge
     cases explicitly (timeouts, overflow, orphans/grandchildren, interrupts, concurrent runs, torn writes,
     tamper, symlinks/special files, credential residue, malformed/spoofed/truncated review output, provider
     outage, planner==reviewer, invalid cards, scenario-id collisions) and give EACH its own E2E scenario id in a
     collision-proof registry — include the fix for the known O55/O56 double-claim defect (C5/C7, C6/C8): the
     planner must be shown not just ids that exist in the suite but ids CLAIMED by pending cards.
   - **Zero gaps**: every open item in HANDOFF-011 §7 (time gate, O55/O56 collisions, unreviewed orch-010,
     deferred F4–F8 + M0–M3, provider re-check) gets an owner and an order; nothing hand-waved.
   - **Final step prints a full handoff/review prompt** so a frontier model can review ALL work done — populated
     with revisions/hashes, card+launch ledger, per-scenario E2E results, review history + dispositions, cleanup
     and preservation evidence, accounting, and the complete inline review prompt (any unfilled placeholder must
     make the handoff refuse).
   - **Inline the orchestration scripts IN THE PLAN DOCUMENT** so it is portable across Claude, Pi and Codex
     workers: `run_bounded.py`, `loop.py` (state machine), `worker-claude.sh`, `worker-codex.sh`, `worker-pi.sh`,
     `worker-common.sh`, `env.sh.example`, the e2e fake engine/fake guardian and the E2E runner skeleton. Baseline
   = the CURRENT sources under `orch/` / `e2e/` (snapshot frozen/orch-010) plus your proposed deltas — read them,
   do not reinvent them.
3. **Do not modify** anything under `orch/` (state, ledger, cards, evidence), `frozen/`, `continuation-008/`, or
   `continuation-010/`. Your only write is the plan file. Status: PLAN ONLY — the plan itself must state that
   approving it creates no reservation, launch, or budget entry.
4. When the plan file is written, notify pi:
   `tmux send-keys -t %2 -l '[from claude] plan ready: <absolute path>' && tmux send-keys -t %2 Enter`

## Required reading (all in this repo, relative to repo root)

- `artifacts/planning/esy-repair-implementation-001/continuation-011/HANDOFF-011.md` (inlined below as well)
- `.../continuation-011/orch/state.json`, `.../orch/ledger.jsonl` (tail), `.../orch/cards/*.json` (C1–C8)
- `.../continuation-011/frozen/orch-010.manifest.json` (+ orch-008/009 manifests for the round-4 change history)
- `.../continuation-011/orch/loop.py`, `run_bounded.py`, `worker-*.sh`, `env.sh.example`
- `.../continuation-011/e2e/run_e2e.py` (52-scenario registry), `fake_engine.py`, `fake_guardian.py`
- `.../continuation-008/guardian-v2.py`, `pi-nofork-v3.sb` (guardian contract + coding sandbox profile)
- `.../candidate/scripts/esy-repair/codex-worker.sh` (frozen codex worker)

## Hard constraints your plan must respect (facts from round 4)

- Budgets: **36/48 launches consumed** (slots 37–48 remain); active-time ceiling 32400 s with **31702.8 s
  consumed at round-4 close** (697.2 s left THIS continuation — the plan targets the NEXT continuation; the
  checkpoint carries over, reconcile the tail first). A 600 s coding card needs ≥840 s available; failed launches
  consume slots; budgets never reset.
- Codex/Astra (gpt-6-astra) usage-limited until **2026-10-29 22:41**; until then only Fable (claude-fable-5-1)
  with recorded same-backend approval. Re-checking Astra is the first item of the next continuation.
- Real-credential coding launches go ONLY through `continuation-008/guardian-v2.py` (stdin liveness pipe, spec
  contract, receipt gate TERMINATED+worker_reaped+credential_removed+exit_code==0, else lock retained) with the
  pi profile `pi-nofork-v3.sb` — job trees under `pi-runtime-v2/jobs/`, proven worker env allowlist, exact
  worker-pi.sh argv vector.
- The Fable review of a ~128 KB packet took 299.9 of the 300 s cap — the next source review must slim the subject
  or get an explicitly reviewed cap change; caps are never raised silently.
- Known defects to plan around: C5/C7 both claim e2e id O55 and C6/C8 both claim O56 (nothing launched yet);
  orch-010 changes are unreviewed; F4–F8 and M0–M3 deferred with reasons in state.dispositions.

---

## HANDOFF-011.md (inlined verbatim below — the handoff you were sent)

# HANDOFF-011 (FINAL, root-authored) — continuation-011, Round 4 of PLAN 012, 2026-10-23

MILESTONE VERDICT: **INCOMPLETE** (orchestration layer extended and exercised end-to-end against fakes; one real
Fable source review + four real Fable plans landed; the real-credential coding launch was blocked by the time gate,
not by a defect). `loop.py handoff` correctly refuses (`HANDOFF_BLOCKED non-terminal cards: C1 C2 C5 C6 C7 C8`).
This document is the honest substitute; it binds the same state.

## 1. Revision identity
| item | value |
|---|---|
| orchestration snapshot in force | `frozen/orch-010`, inventory hash `730ea2c851d6c72bb97568e665a85637a469eda186bb6563beae5eb2bcfc1a92` |
| `state.orch_hash` / `state.parent_hash` | both == orch-010 |
| snapshots this round | orch-008 (B1 guardian route + B2 retire-card/EXISTING_E2E_IDS + F7 comment + ORCH_SRC fallback + PI_BIN rebind) → orch-009 (planner-prompt mechanics: base/replaces are CARD IDS, EXISTING_DISPOSITIONS surfaced) → orch-010 (§8 disposition semantics: pending filtered to undispositioned, DISPOSITIONS inlined in packets, M-id collision guard, 0-card replans allowed) |
| last reviewed snapshot | orch-009 (`a69c7729…`) by Fable review-012 — **INCOMPLETE**, 8 findings + 5 missing-evidence; orch-010 changes (the review's own trigger fixes) are **unreviewed** |
| E2E-ORCH suite | **52/52 PASS** at orch-008, orch-009 and orch-010 (`e2e/run_e2e.py`; 45 prior + O48–O54) |
| env rebinds (root, ledgered in manifests) | PI_BIN Cellar 1.3.0 → **1.4.0** (1.3.0 removed by brew 20:06); CLAUDE_BIN 2.1.308 → **2.1.309** (same cause); added PI_RUNTIME, PI_GUARDIAN=guardian-v2.py, BOOT_PYTHON=/usr/bin/python3 |

## 2. Launch / time ledger
- Coding launches: **36/48 consumed (0 this continuation; 12 remaining)**. `run-card C1` was attempted and refused by
  the gate: `TIME_GATE_FAILED avail=827.2 need=840.0` — slot 37 never consumed.
- Active time: **31572.8 s / 32400 → 827.2 s remaining** (checkpoint 28516.8 + root intervals 900+760+830+wrap-up and
  five real model launches below; conservative, nothing subtracted).
- Model invocations this round (all fable, `worker-claude.sh` via `run_bounded.py`, strict profile, real config dir):
  plan-009 CLAUDE_BIN stale (exit 64, 0.006 s) · plan-010 **rejected** `PLAN_UNKNOWN_DEP` (planner read `base` as the
  parent hash; 63.8 s) · plan-011 **REPLAN_OK** C5/C6 (49.2 s) · review-012 **source review of orch-009, INCOMPLETE**
  (299.9 s of the 300 s cap — packets this size are at the edge) · plan-013 **rejected** `PLAN_MISSING_DISPOSITION`
  (98.2 s; exposed the §8 semantics defect fixed in orch-010) · plan-014 **REPLAN_OK** C7/C8 (55.4 s).
- Same-backend approvals: 3 more entries (round-4 re-affirmation; Codex/Astra usage-limited until 2026-10-29 22:41).

## 3. B1+B2 (implemented, suite-proven, reviewed once)
- `run_bounded.py`: `--stdin-pipe` (child stdin = pipe read end; launcher holds the write end until reap) + receipt
  `stdin_mode`; unknown options now exit 70.
- `loop.py` guardian route: `PI_GUARDIAN` set ⇒ job tree at `PI_RUNTIME/jobs/<card>-<n>/` (0700, must not exist),
  `spec.json` = exact `worker-pi.sh` vector + proven worker env (PATH/LANG/SSL_CERT_FILE/NODE_EXTRA_CA_CERTS +
  HOME/PI_CODING_AGENT_DIR/PI_CODING_AGENT_SESSION_DIR/PI_TELEMETRY/TMPDIR under PI_RUNTIME), guardian launched via
  `BOOT_PYTHON -B` through `run_bounded --stdin-pipe` (timeout+30, 1 MiB); gate = run_bounded `ok`+`reaped` AND
  guardian receipt `TERMINATED`+`worker_reaped`+`credential_removed`+`exit_code==0`, else `uncertain_stop` with lock
  kept (a missing receipt is never "zero children"); `CARD_DONE` read from `guardian/stdout`; `check_auth_clean`
  re-run; ledger `guardian_spec`/`guardian_receipt`.
- `retire-card ID --reason` → NEEDS_REPLAN (refused for anything not PENDING/FAILED). Planner packet now carries
  `EXISTING_E2E_IDS` (parsed from the parent tree's `e2e/run_e2e.py`), the id-freshness rule, `EXISTING_DISPOSITIONS`,
  and CARD-IDS-only `base`/`replaces` documentation.
- Root fixes disclosed in manifests: F7 comment corrected (profile authoritative, never widened); `run_e2e.py`
  ORCH_SRC falls back to the tree root so a card's `e2e.argv` works inside a flat frozen tree (latent C1–C4 defect).

## 4. Review-012 findings and dispositions (plan-014)
| id | finding (short) | disposition |
|---|---|---|
| F1 | tree_hash computed before e2e; review binds stale hash | card:C7 (was C1's base-hash concern; C1 still pending) |
| F2 | milestone ACCEPTED not revision-bound | card:C6 (also re-raised as C7-adjacent) |
| F3 | packet sha taken after the model run | card:C8 |
| F4 | card e2e argv unsandboxed | deferred (needs e2e profile design; C2 detects mutation after the fact) |
| F5 | replan dispositions merge can overwrite existing keys | deferred (small cmd_replan change; next continuation) |
| F6 | optional card keys lack type checks | deferred (validate_card; next continuation) |
| F7 | parse_verdict does not type-check severity/location/evidence | deferred (next continuation) |
| F8 | a failed smoke still persists reviewer_backend | deferred (two-line change) |
| M0/M2 | codex-worker.sh, pi profile, real guardian not inline | deferred (outside parent tree; supervisor must attach to next review subject) |
| M1 | no suite artifact in packet | deferred (52/52 summaries exist under `evidence-e2e-orch/`; attach) |
| M3 | no smoke receipt in packet | deferred (state.smokes has review-004; attach) |
| M4 | prior findings/dispositions not in reviewer packet | rejected (now fixed in orch-010: DISPOSITIONS inlined) |
| F1–F8 of review-005 | standing dispositions from plan-008 preserved except F3→card:C8, F4→deferred (was card:C3, superseded) | recorded in state |

## 5. Cards (all under `orch/cards/`)
- PENDING: **C1** (F1 base-hash gate, e2e O32), **C2** (F2 post-e2e tree re-verify, O43), **C5** (replaces C3: RESERVED
  dead-end + inputs validation, O55), **C6** (replaces C4: milestone revision binding, O56), **C7** (F1 post-e2e hash +
  review refuse, O55), **C8** (F3 pre-run packet hash, O56).
- SUPERSEDED: C3, C4 (retired root-authored: O46/O47 id collisions; replaced by C5/C6).
- **Known NEW defect (must be the next planner's first item)**: C7 and C5 both reference scenario **O55**; C8 and C6
  both reference **O56**. `EXISTING_E2E_IDS` only sees ids already in the suite file, not ids claimed by other pending
  cards. Nothing was launched, so no runtime impact; next continuation must either give the planner a claimed-id list
  (pending cards' argv ids) or renumber the quartet via retire-card + replan before any `run-card`.
- Time gate: with 827.2 s left and 840 s needed, no card can launch. First coding card remains C1 (slot 37).

## 6. Hygiene / preservation
- `pi-runtime-v2/private-pi/` empty at every check (pre-run and post-round); no `auth.json` written this round (no
  real-credential launch happened); `~/.codex/auth.json` mtime unchanged since 19:39 (before this round; not us).
- Lock free; no uncertain jobs; original source, continuation-008 and continuation-010 untouched; no import into
  original source. `state.json`/`ledger.jsonl`/`cards/` are the durable truth.

## 7. Open blockers, ordered
1. Time: 827.2 s < 840 s ⇒ no coding launch possible this continuation (stop rule fired honestly).
2. C5/C7 and C6/C8 scenario-id collisions (above) — resolve before any card runs.
3. orch-010 mechanics unreviewed (review-012 covered orch-009; packet ≈128 KB at 299.9/300 s — the NEXT review must
   either slim the subject or get an explicitly reviewed cap change; do not raise caps silently).
4. F4–F8, M0–M3 deferred defects (small, listed above with owners).
5. Codex/Astra returns 2026-10-29 22:41 — first re-check item of the next continuation (then reviews can alternate
   backends again instead of same-backend Fable).

## 8. Next bound small step (for the next continuation)
1. `note-interval` reconciliation tail → `python3 -B orch/loop.py status`.
2. Resolve the O55/O56 collisions: `retire-card C7 --reason …`, `retire-card C8 --reason …` (or C5/C6) → one replan
   (Astra if available after 2026-10-29, else Fable with recorded approval) with the claimed-id rule added.
3. Attach supervisor evidence to the next review subject (suite summary, smoke receipt, profile/guardian copies) to
   close M0–M3, then `review --subject frozen/orch-010 --name orch-010` (slim packet or reviewed cap first).
4. Then `run-card C1` (slot 37, ≥840 s required): the first real-credential guardian launch — pre-checks: PI_BIN
   1.4.0 present, token exp ≥600 s, private-pi empty, lock free.

## 9. Independent-review prompt (populated from state; for the next frontier reviewer)
```
You are the independent reviewer of the continuation-011 orchestration layer ONLY. No tools; do not infer runtime
evidence from source closure. REVISION: 730ea2c851d6c72bb97568e665a85637a469eda186bb6563beae5eb2bcfc1a92 (frozen/orch-010).
PRIOR REVIEW: review-012 of orch-009 (a69c7729…), INCOMPLETE, findings F1-F8 + M0-M4, dispositions in §4.
CHANGES SINCE: disposition semantics only (pending filtered to undispositioned findings, DISPOSITIONS inlined in
packets, M-id collision guard, 0-card replans allowed per plan §8). E2E-ORCH: 52/52 at this revision.
SMOKES: fable real-config OK (claude-fable-5-1, review-004); codex usage-limited until 2026-10-29 22:41.
ACCOUNTING: launches 36/48 (0 this continuation; TIME_GATE_FAILED at avail=827.2 for slot 37); active 31572.8/32400 s.
CARDS: C1 C2 C5 C6 C7 C8 pending (O55/O56 claimed twice — known defect, §5); C3/C4 superseded.
TASK: check correctness/regression/provenance/process ownership/finite-failure contract, with emphasis on the new
guardian route (§3) and disposition semantics. Return exactly ONE fenced json block {revision, findings[{id,severity,
location,evidence}], missing_evidence[], coverage{complete,truncated}, cleanup, verdict ACCEPTED|INCOMPLETE|BLOCKED}.
ACCEPTED requires zero findings and zero missing evidence.
```
(The machine-built packet from `loop.py review --subject frozen/orch-010` inlines all 11 source files + DISPOSITIONS;
this prose block is the human summary of its header.)
