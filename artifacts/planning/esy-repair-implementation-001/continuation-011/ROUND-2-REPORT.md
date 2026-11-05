# ROUND 3 ADDENDUM (2026-10-23, later)

- Fable retry: `CLAUDE_REAL_CONFIG=1` mode added to `loop.py` (no `CLAUDE_CONFIG_DIR` override; review profile UNCHANGED —
  a widening to `~/.claude` was proposed and refused by the Claude Code permission classifier; it turned out unnecessary).
- Suite 43/43 at `frozen/orch-004` (hash `8bab0af6dcea6af8abb345810ea397ed0ead5813adaa3d278af03955fc864239`); `state.orch_hash` == orch-004.
- Smoke `review-004` (fable, real config, strict profile): **SMOKE_OK**, model `claude-fable-5-1`, 12.2 s, cleanup field `MODEL=claude-fable-5-1`.
- Source review `review-005` (fable, subject `frozen/orch-004`, packet 87423 B, 293.4 s of the 300 s cap): verdict **INCOMPLETE** —
  findings F1–F10 (1 high, 4 medium, 5 low) + 3 missing-evidence items. `state.pending_findings` = F1..F10, M0..M2.
  Key findings: F1 card acceptance can discard a sibling card's accepted edits (no base-hash gate); F2 e2e may mutate the
  tree after `tree_hash`; F3 milestone flag not revision-bound; F4 RESERVED dead-end after reserve; F5 card `e2e.argv`
  runs unsandboxed; F6 packet hash taken after the run; F7 stale comment vs profile; F8 dirs invisible to inventory;
  F9 `ORCH_ENV_PASSTHROUGH` unconditional; F10 hardcoded accounting defaults. Missing: codex-worker.sh/pi profile not in
  subject; no E2E summary artifact in packet; review-launch cap policy unstated.
- Loop rule: replan must run on the OTHER backend (codex) → blocked by OpenAI usage limit until 2026-10-29 22:41.
  Same-backend replan requires explicit user approval recorded in state (plan §8). Awaiting that decision.
- Note: 293 s review time is at the 300 s cap; larger packets will need indexed parts or a reviewed cap change.

# ROUND 2 REPORT — continuation-011 (2026-10-23)

VERDICT: **INCOMPLETE / BLOCKED_PROVIDER_UNAVAILABLE** (both review backends). Nothing accepted. No coding slot used.

## Orchestration snapshot in force
- `frozen/orch-003` — inventory hash `c8ad96ff8c1969fc4d18c0ce78fd8d8510d731acc612cb7d0c4a290788e776ac` (10 files; manifest `frozen/orch-003.manifest.json`).
  Supersedes orch-002 (`cd9fb556…`) and orch-001 (`87ad277a…`), both retained. `state.orch_hash` == orch-003.
- `source_reviews` = {} → `loop.py handoff` correctly refuses (`HANDOFF_BLOCKED no accepted source review`).
- E2E-ORCH suite: **43/43 PASS** (`e2e/run_e2e.py`; O01–O45 incl. credential lifecycle O42, provider-error classification O45, rebind/interval gates O41/O44).

## Provider smokes (real transports, through `orch/worker-claude.sh review`)
| label | backend | result | evidence |
|---|---|---|---|
| review-001 | codex (strict profile, no private CODEX_HOME) | exit 1 — `failed to initialize in-process app-server client: Operation not permitted` | `orch/evidence/review-001/run/receipt.json{,.err}` |
| review-002 | codex (proven layout: private `CODEX_HOME`/`TMPDIR`, auth symlink) | transport OK (thread+turn started) → `turn.failed: You've hit your usage limit … try again at Oct 29th, 2026 10:41 PM` | `review-002/run/receipt.json.out` sha256 `d049a946…bf71f5f23` |
| review-003 | fable (private `CLAUDE_CONFIG_DIR`, proven smoke env) | `is_error: Not logged in · Please run /login` (same as bootstrap/claude-smoke-002) | `review-003/run/receipt.json.out` sha256 `7d2b43f6…21b4dab9` |

Credential checks after the smokes: `~/.codex/auth.json` mtime unchanged (1792077133); no `auth.json` symlink residue under `orch/evidence/*/runtime/codex`; `continuation-008/pi-runtime-v2/private-pi/` empty; ledger has `credential_lifecycle removed=true` for review-002/003 (review-001 predates that code).

## Changes made this round (all root-authored, no slot)
1. `orch/env.sh` (resolved non-symlink binaries; `codex-worker.sh` sha `e036f5ce…`; `pi-nofork-v3.sb` sha `6f5bd2ea…`).
2. `review-readonly.sb` (proven pattern; writes only under `continuation-011/orch/evidence` and `continuation-011/tmp`).
3. `loop.py`: `review --subject/--name/--smoke`, `rebind-orch`, `note-interval`; `run_model` now mirrors `bootstrap/launch_worker.py` (fixed env allowlist, private runtime, auth **symlink** created/unlinked with residue check); provider error classification (`provider_error` → exit 75 unavailable / 74 other).
4. Fakes + 6 new E2E scenarios.

## Accounting
- Launches 36/48 (unchanged). Active **26566.515 s** of 32400 → remaining **5833.485 s**.
- `time-reconciliation.json`: checkpoint 24923.746 + round-1 (261 measured + 300 allowance) + round-2 planning (360 allowance) + execution-to-init (measured) + post-init root interval 450.3 s (ledger `root_interval`, launch elapsed deliberately not subtracted). Idle gap 15:27→19:21 documented, not counted.

## Open blockers (ordered)
1. **Astra (Codex) unavailable until 2026-10-29 22:41** — OpenAI usage limit. No fallback permitted.
2. **Fable (Claude) not logged in under the private config dir.** Operator option: run interactively
   `CLAUDE_CONFIG_DIR=<continuation-011>/tmp/claude-login claude /login`, then point `run_model`'s claude runtime at a copy of that dir (needs a small reviewed change) — or accept Fable as unavailable.
3. Guardian route still `GUARDIAN_PATH_NOT_IMPLEMENTED` → no coding launch possible yet (next card after a source review).
4. `PI_BIN` deviation (resolved Cellar path vs proven `/opt/homebrew/bin/pi`) unverified against `pi-nofork-v3.sb`.
5. Indexed multi-part review packets not implemented (`PACKET_TOO_LARGE` > 400 KB; orch-003 packet ≈ 85 KB, fits).

## Next bound step when a backend is available
`python3 -B orch/loop.py review --subject "$PWD/frozen/orch-003" --name orch-003 --backend codex` (or `fable`), then `replan` on the other backend for any findings, re-freeze as orch-004, re-review; only then cards A1+ and slot 37.
