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
