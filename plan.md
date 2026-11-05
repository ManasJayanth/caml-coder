# PLAN 012 — Portable, small-model-friendly review-worker acceptance loop

## ROUND 4 (current) — address the five blockers from HANDOFF-011-DRAFT

### Context
Rounds 2–3 produced a working, E2E-tested orchestration (`continuation-011/orch`, snapshot `orch-007`, 45/45), a live Fable
transport, one Fable source review (orch-004 → 10 findings) and an approved Fable re-plan into cards C1–C4. Nothing can be
coded yet because the real-credential Pi route is not wired, two cards reference E2E ids that already exist, and orch-005..007
are unreviewed. Budget: **36/48 launches, ≈3883 s active time left** — enough for one source review, one re-plan and at most
ONE 600 s coding card with its review; the plan below is ordered so the run stops honestly wherever the time gate fails.
Codex/Astra stays unavailable until 2026-10-29 22:41; all planning/review uses Fable under the recorded approval.

### Facts that shape the fix (read-only, verified)
- `continuation-008/pi-nofork-v3.sb`: `deny process-fork`; writes only under `continuation-008/pi-runtime-v2`; **reads denied
  under `/Users/psac` except `pi-runtime-v2`**; `~/.codex` read-denied; `private-pi` write-denied (auth is provisioned by the
  guardian outside the sandbox). ⇒ job tree + prompt must live under `pi-runtime-v2/jobs/<card>-<n>/`, not `orch/jobs/`.
- `continuation-008/guardian-v2.py`: argv = one spec path; keys `argv env cwd output timeout cap auth_source`; `output` must not
  pre-exist; **stdin must be an open pipe** (EOF before spawn ⇒ `launcher absent before spawn`); writes `output/{auth-ready.json,
  ready.json,stdout,stderr,receipt.json}`; receipt keys `status(TERMINATED|CLEANUP_UNVERIFIED) worker_pid worker_reaped exit_code
  reason elapsed_seconds credential_removed`. Credential: `~/.codex/auth.json` → `private-pi/auth.json` (0600), unlinked in `finally`.
- Proven env (bootstrap/launch-correction.py): allowlist `PATH LANG SSL_CERT_FILE NODE_EXTRA_CA_CERTS` + `HOME=runtime/home`,
  `PI_CODING_AGENT_DIR=runtime/private-pi`, `PI_CODING_AGENT_SESSION_DIR=runtime/sessions`, `PI_TELEMETRY=0`, `TMPDIR=runtime`.
- Proven argv used `/opt/homebrew/bin/pi` (symlink). `worker-pi.sh` rejects symlinks; the resolved Cellar path is used and the
  profile does not path-match the binary, so this is a provenance note, not a functional change.

### B1 — Guardian route (root-authored, no slot; files: `orch/loop.py`, `orch/run_bounded.py`, `e2e/fake_guardian.py`, `e2e/run_e2e.py`)
1. `run_bounded.py`: new option `--stdin-pipe` — create `os.pipe()`, give the read end to the child as stdin, keep the write end
   open in the launcher until the child is reaped, then close. Receipt gains `stdin_mode`.
2. `loop.py` env: `PI_RUNTIME` (= `continuation-008/pi-runtime-v2`), `PI_GUARDIAN`, `BOOT_PYTHON`; `AUTH_DIR` stays `PI_RUNTIME/private-pi`.
3. `cmd_run_card` when `PI_GUARDIAN` is set (replaces today's `GUARDIAN_PATH_NOT_IMPLEMENTED` exit):
   - job dir `PI_RUNTIME/jobs/<card>-<n>/` (0700, must not exist) with `tree/` (copy of parent) and `prompt.txt`;
   - `spec.json` built by `coding_spec()` = exact `worker-pi.sh` vector (`SANDBOX_EXEC -f PI_PROFILE PI_BIN --print --mode json
     --provider --model --thinking high --no-session --no-extensions --no-mcp --no-skills --no-prompt-templates --no-context-files
     --no-themes --no-approve --offline --tools read,edit,write @prompt`), env = proven allowlist above, `cwd=tree`,
     `output=job/guardian`, `timeout=min(card.timeout,600)`, `cap=2097152`, `auth_source='real'`; serialized only to `job/spec.json`;
   - launch `[BOOT_PYTHON, '-B', PI_GUARDIAN, spec]` through `run_bounded.py --stdin-pipe` with timeout `card.timeout+30`, cap 1 MiB;
   - gate: run_bounded receipt `ok`+`reaped`; `job/guardian/receipt.json` read with `read_bounded_json` (16 KiB): `status=='TERMINATED'`,
     `worker_reaped is True`, `credential_removed is True`, `exit_code==0`; any other value or missing receipt ⇒
     `uncertain_stop` (lock kept). `CARD_DONE` is read from `job/guardian/stdout` (bounded). `check_auth_clean` re-run after.
   - ledger events `guardian_spec` (spec sha), `guardian_receipt` (fields).
4. E2E (fake guardian honouring the contract above, run as a real process via `BOOT_PYTHON`): O48 happy path (receipt fields,
   CARD_DONE from guardian stdout, job under `PI_RUNTIME/jobs`, prompt/tree under `PI_RUNTIME`); O49 `credential_removed:false`
   ⇒ BLOCKED_CLEANUP_UNCERTAIN + lock; O50 `CLEANUP_UNVERIFIED` ⇒ uncertain; O51 pre-existing output dir ⇒ guardian dies without
   receipt ⇒ uncertain (never "zero children"); O52 fake guardian asserts stdin is open at start (fails loudly with DEVNULL);
   O53 spec.json argv equals the `worker-pi.sh` vector and env has no `LEAK_CANARY`; O29 extended for the guardian path.
5. Fix the wrong `CLAUDE_REAL_CONFIG` comment in `run_model` (F7; profile is authoritative) — ledger note in the orch-008 manifest.

### B2 — Scenario-id collision for C3/C4 (root-authored, then one Fable re-plan)
1. `loop.py`: `retire-card ID --reason TEXT` → status `NEEDS_REPLAN` (ledgered; refused if RESERVED/E2E_PASS). E2E O54.
2. Planner prompt gains `EXISTING_E2E_IDS:` (ids parsed from the parent tree's `e2e/run_e2e.py`, `^def O\d+`) and the rule
   "new scenario ids must not be in EXISTING_E2E_IDS". `validate_card` is not changed (ids are inside argv, not statically knowable).
3. Execution: `retire-card C3`, `retire-card C4` → `replan --backend fable --same-backend-approved …` (dispositions required only
   for pending findings; none pending → the planner must still `replaces` both). Expect C3'/C4' with free ids (O55+).

### B3 — Review the unreviewed mechanics
Freeze `frozen/orch-008` (after B1+B2), `rebind-orch`, `set-parent`, then
`review --subject frozen/orch-008 --name orch-008 --backend fable` (≤300 s; packet ≈95 KB — if `PACKET_TOO_LARGE` or the 300 s
cap is hit, stop and report; do not raise caps unreviewed). Findings ⇒ dispositions via the B2 re-plan path.

### B4 — First coding launch, only if the time gate passes
`run-card C1` (slot 37; needs ≥840 s available) → guardian route → scope verify → card E2E (`O32`) → `review --card C1`
(Fable, ≤300 s). Accepted ⇒ copy only `loop.py` and `e2e/run_e2e.py` from the accepted tree into `orch/` (ledgered root copy,
re-freeze orch-009, rebind, source review). If the gate fails at any point: stop, keep evidence, write the handoff.

### B5 — Handoff
Update `HANDOFF-011-DRAFT.md` → final; `loop.py handoff` once gates allow; print in full. Remaining dispositions (F5, F6, F8–F10,
M0, M1) stay deferred with reasons; Codex/Astra re-check after 2026-10-29 is the first item of the next continuation.

### Verification
- `python3 -B e2e/run_e2e.py` ⇒ `TOTAL 52 FAILED 0` (45 + O48–O54).
- Real guardian path proven only by the first actual card run (B4); no uncounted coding smoke (Plan 011 §3).
- After any real launch: `private-pi/` empty, `~/.codex/auth.json` unchanged by us, lock free, ledger complete.

### Out of scope this round
Sandboxing card `e2e.argv` (F5), directory-aware inventory (F8), indexed multi-part packets, Astra transport, cards C2–C4 execution.

---

## ROUND 2 (done) — bind real tools, smoke the providers, get the Astra review of `orch/`

Status of round 1 (done, no slots used): `continuation-011/orch/{run_bounded.py,loop.py,worker-*.sh,env.sh.example}`
and `continuation-011/e2e/{fake_engine.py,run_e2e.py}` exist; 37/37 fake-backed E2E scenarios pass; mutation check
confirmed the suite fails when scope checking is disabled. Nothing real has been launched. §§0–11 below are unchanged.

### Verified bindings (read-only, 2026-10-23)
| key | value | note |
|---|---|---|
| CODEX_BIN | `/opt/homebrew/Caskroom/codex/0.163.0/bin/codex` | `/opt/homebrew/bin/codex` is a symlink; frozen `codex-worker.sh` rejects symlinks |
| CLAUDE_BIN | `/opt/homebrew/Caskroom/claude-code@latest/2.1.308/claude` | symlink resolved for the same reason (Fable backend) |
| PI_BIN | `/opt/homebrew/Cellar/pi-coding-agent/1.3.0/bin/pi` | **deviation**: Plan 011's proven argv used `/opt/homebrew/bin/pi` (a symlink). Recorded; not exercised this round (no coding launch). First coding card must confirm `pi-nofork-v3.sb` does not path-match the symlink. |
| CODEX_WORKER | `candidate/scripts/esy-repair/codex-worker.sh` (absolute) | frozen, hash recorded at P0 |
| PI_PROFILE | `continuation-008/pi-nofork-v3.sb` | existing |
| REVIEW_PROFILE | **new** `continuation-011/review-readonly.sb` | modeled on proven `jobs/A9-B1a-source-review-001/sandbox.sb`: `(allow default)`, `(deny file-write*)`, writes allowed only under `continuation-011/orch/evidence` and `continuation-011/tmp`, mDNS sockets allowed, `(deny signal)` except self/children |
| AUTH_DIR | `continuation-008/pi-runtime-v2/private-pi` | currently empty (verified) |
| PI_GUARDIAN | empty | guardian route stays `GUARDIAN_PATH_NOT_IMPLEMENTED`; coding launches remain blocked until a reviewed guardian card |
| Codex auth | `~/.codex/auth.json` present | never copied into packets/evidence |

### Steps (serial; each produces evidence under `continuation-011/`)
1. **`orch/env.sh`** from the table above (no secrets). **`review-readonly.sb`** written as described.
2. **`loop.py` addition — `review --subject DIR [--name N] [--smoke]`**: packet = inline inventory+contents of DIR,
   `revision = inv_hash(DIR)`, scope `source:N` (or `smoke:N`). Acceptance writes `state.source_reviews[N] = hash`;
   `--smoke` never changes acceptance state, exits 0 iff transport ok and `parse_verdict` succeeds, and records
   backend/exit/elapsed/out-hash in `state.smokes`. Final milestone packet must include `source_reviews`.
   `handoff` refuses if `source_reviews` lacks an entry for the frozen orch snapshot in use.
3. **New E2E scenarios** (fake-backed, same suite): O39 subject review accepted/findings/malformed; O40 smoke records
   transport and leaves cards/milestone untouched; O41 handoff refuses without the orch source review. Full suite must
   stay green (now 40 scenarios).
4. **Freeze** `continuation-011/frozen/orch-001/` = copy of `orch/*.py`, `orch/*.sh`, `env.sh.example`, `e2e/*.py`,
   `review-readonly.sb`; write `frozen/orch-001.manifest.json` (inventory + hash).
5. **Time reconciliation** (`continuation-011/time-reconciliation.json`): root-authored round-1 interval measured
   conservatively from file mtimes (first orch file created → last E2E summary written), added to the 24923.746 s
   checkpoint; `loop.py init --active-seconds <sum> --launches-used 36 --parent frozen/orch-001`. No idle subtracted.
6. **Provider smokes** (real, no coding slot, ≤300 s each, time ledgered): `review --subject frozen/smoke-subject
   --smoke --backend codex` then `--backend fable`. Smoke subject = one 20-line file. A smoke failure is diagnosed
   from retained stderr; the only permitted profile adjustment is adding a write-allow for a Codex/Claude log or
   session subpath under `$HOME/.codex` or `$HOME/.claude` (never `auth.json`, never broader) — re-run suite + smoke.
   Fable unavailable ⇒ `BLOCKED_PROVIDER_UNAVAILABLE` recorded; Astra alone may still review, but re-planning then
   requires the explicit user approval noted in §8.
7. **Astra source review of orch**: `review --subject frozen/orch-001 --name orch-001 --backend codex`.
   Findings ⇒ dispositions via `replan` on the other backend (Fable) per §8, fix, re-freeze as `orch-002`, re-review.
8. **Stop and report**: print smoke results, review verdict/findings, ledger, remaining time. Do **not** write cards
   A1+ or reserve slot 37 in this round; the guardian integration card is the next item after acceptance.

### Verification for this round
- `python3 -B e2e/run_e2e.py` ⇒ `TOTAL 40 FAILED 0`.
- Both smokes present in `state.smokes` with real transport evidence (`evidence/*/run/receipt.json{,.out,.err}`).
- `state.source_reviews['orch-00N']` equals the frozen manifest hash, or an honest INCOMPLETE with listed findings.
- `continuation-008/pi-runtime-v2/private-pi/` still empty; `~/.codex/auth.json` untouched (mtime unchanged).

Status: PLAN ONLY. Approving this plan creates no reservation, launch, or budget entry.
Supersedes the *packaging* of EXECUTION PLAN 011 (same milestone, same budgets, same stop rules).
Goal stated by user: small-coding-model-friendly, zero gaps, correct, safe; E2E tests only (no unit tests);
final step prints a full frontier-review handoff prompt; review and re-plan are done by DIFFERENT frontier
models; the loop repeats until a review returns nothing to address; orchestration scripts are inlined here
so the plan is portable (Claude, Pi, Codex workers).

---------------------------------------------------------------------------------------------------
## 0. Context and verified facts (read from the repo, not assumed)

Workers found at `artifacts/planning/esy-repair-implementation-001/candidate/scripts/esy-repair/`:

| script | verified behavior | consequence for this plan |
|---|---|---|
| `claude-worker.sh` | roles `code`/`review`; **`review` here exits 64** ("use codex-worker.sh") — Plan 011 says it execs sibling codex-worker. These disagree. Uses `CLAUDE_BIN`, `CLAUDE_CODING_MODEL`, flags `--print --output-format json --no-session-persistence --restricted --setting-sources "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --permission-mode --tools` | Step 1 of execution must hash the file and confirm which variant is live. New `worker-claude.sh` below defines `review` explicitly so the ambiguity cannot matter. |
| `codex-worker.sh` | exactly 5 args `ROLE WORKSPACE PROMPT PROFILE CODEX_EXE`; `plan`/`review` = `gpt-6-astra`, read-only, shell disabled, ephemeral, ignores user config; validates absolute, non-symlink inputs | Reused UNCHANGED as the Codex worker. Never override model. |
| `pi-worker.sh` | 4 args, env `PI_BIN PI_PROVIDER PI_CODING_MODEL`; **lacks `--thinking high`, `--offline`, `--no-themes`, `--no-prompt-templates` parity with the proven invocation** | NOT used for coding. `worker-pi.sh` below carries the full proven flag set. |
| `continuation-008/guardian-v2.py` | single arg = spec JSON path; keys `argv env cwd output timeout cap auth_source`; stdin must stay an open liveness pipe; `output` must not pre-exist; provisions/removes `auth.json` in `pi-runtime-v2/private-pi`; self-described "experimental" | Used only for Pi coding with `auth_source=real`. Treated as untrusted-until-verified (see C0). |

Budgets (carried over, unchanged): 36 launches consumed, cap 48, slots 37–48; active-time ceiling 32400 s,
checkpoint 24923.746 s; cleanup reserve ≥180 s; a 600 s coding job needs ≥840 s available. Failed launch consumes a slot.
Only Astra (gpt-6-astra via Codex) or Fable (via Claude) may plan/review; coding = gpt-6-luna/high through Pi.
Claude/Fable status is "unavailable" in Plan 011; this plan keeps Fable as an OPTIONAL backend that is
used only if a smoke proves it available — otherwise `BLOCKED_PROVIDER_UNAVAILABLE`, never silent substitution.

Out of scope (unchanged): LoRA/training, dataset generation, wider esy fault matrix, general controller repair,
import into original source. Even ACCEPTED does not authorize any of these.

---------------------------------------------------------------------------------------------------
## 1. Rules every small coding model must follow (put verbatim at top of every card prompt)

1. One objective per card. Edit ONLY files listed in `ALLOWED_PATHS`. Create nothing else.
2. You may use only read/edit/write tools. Do not run, import, compile, test, or call providers.
3. Each single edit < 3000 characters. If larger, split across several edits to the same file.
4. Do not touch history, `config/`, `uv.lock`, adapters, or any file not in `ALLOWED_PATHS`.
5. Finish by printing exactly one line: `CARD_DONE <card-id>`; if blocked print `CARD_BLOCKED <card-id>: <reason>` and stop.
6. If any instruction conflicts with another, stop with `CARD_BLOCKED`. Never guess.
7. Never print or write credentials, tokens, or paths under `private-pi`.

Each card prompt is machine-assembled from a fixed template (§4) so a small model never sees prose planning.

---------------------------------------------------------------------------------------------------
## 2. Layout (all paths relative to `$ORCH_ROOT`, the directory containing this plan's `orch/`)

```
orch/
  env.sh               # operator-filled, sourced by scripts; see env.sh.example (no secrets)
  run_bounded.py       # the ONLY process launcher (deadline, caps, process-group ownership, receipt)
  worker-claude.sh     # roles: code | plan | review   (Claude CLI / Fable; review may delegate to codex)
  worker-codex.sh      # thin wrapper over frozen codex-worker.sh (plan | review | code)
  worker-pi.sh         # role: code (full proven Pi flag set, high reasoning)
  loop.py              # state machine driver: init|run-card|verify|e2e|review|replan|handoff|status
  cards/               # one JSON per card (schema §4)
  state.json           # durable state (atomic replace + fsync)
  ledger.jsonl         # append-only launch/time ledger (fsync per line)
  lock                 # O_EXCL lock; kept on uncertainty
  evidence/<card>/<attempt>/...   # manifests, diffs, receipts, raw streams
e2e/
  fakes/{claude,codex,pi}.sh      # fake CLIs run as real processes (deterministic scenarios)
  run_e2e.py           # runs scenarios as subprocesses against the REAL orch/ scripts
```

No absolute machine path appears in any script. `ORCH_ROOT` is derived from the script location; every tool
binary comes from `env.sh` and is validated absolute, executable, non-symlink before use.

---------------------------------------------------------------------------------------------------
## 3. Inline orchestration scripts (materialize exactly; do not improvise)

### 3.0 `orch/env.sh.example` → copy to `orch/env.sh`, fill, never commit secrets
```bash
# All values absolute. Validated by every worker; missing => exit 64.
export CLAUDE_BIN=/absolute/path/to/claude          # optional (Fable backend)
export CLAUDE_FABLE_MODEL=claude-fable-5-1          # review/plan model when REVIEW_BACKEND=fable
export CLAUDE_CODING_MODEL=                         # empty unless Claude coding is explicitly approved
export CODEX_BIN=/absolute/path/to/codex            # real, non-symlink
export CODEX_WORKER=/absolute/path/to/codex-worker.sh   # the frozen existing script
export PI_BIN=/opt/homebrew/bin/pi
export PI_PROVIDER=openai-codex
export PI_CODING_MODEL=gpt-6-luna
export SANDBOX_EXEC=/usr/bin/sandbox-exec
export PI_PROFILE=/absolute/path/to/pi-nofork-v3.sb       # coding sandbox
export REVIEW_PROFILE=/absolute/path/to/review-readonly.sb
export PI_GUARDIAN=/absolute/path/to/guardian-v2.py        # optional; required when auth_source=real
export BOOT_PYTHON=/absolute/path/to/python3               # verified interpreter
```

### 3.1 `orch/run_bounded.py` — sole launcher (stdlib only)
Contract: `run_bounded.py RECEIPT_JSON TIMEOUT_S CAP_BYTES CWD -- argv...` (stdin = /dev/null unless
`--stdin FILE`). Writes `RECEIPT_JSON` (≤16 KiB), `RECEIPT.out`, `RECEIPT.err` (each ≤ CAP_BYTES). Exit code 0 if
receipt published (even if child failed); 70 if the launcher itself failed; 71 if ownership/reap is uncertain.
```python
#!/usr/bin/env python3
import json, os, selectors, signal, subprocess, sys, time

def main():
    a = sys.argv[1:]
    sep = a.index('--')
    receipt, timeout, cap, cwd = a[0], float(a[1]), int(a[2]), a[3]
    stdin_path = None
    opts = a[4:sep]
    if opts[:1] == ['--stdin']:
        stdin_path = opts[1]
    argv = a[sep + 1:]
    start_wall, start = time.time(), time.monotonic()
    rec = {'schema': 1, 'argv_len': len(argv), 'start_wall': start_wall, 'status': 'launcher-error',
           'reaped': False, 'signal': None, 'overflow': {'out': False, 'err': False}, 'ownership_uncertain': False}
    out_p, err_p = receipt + '.out', receipt + '.err'
    for p in (receipt, out_p, err_p):
        if os.path.lexists(p):
            print('refusing to overwrite ' + p, file=sys.stderr); return 70
    child = None
    bufs = {'out': bytearray(), 'err': bytearray()}
    try:
        stdin = open(stdin_path, 'rb') if stdin_path else subprocess.DEVNULL
        child = subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, close_fds=True)
        rec['pid'] = child.pid
        sel = selectors.DefaultSelector()
        for name, pipe in (('out', child.stdout), ('err', child.stderr)):
            os.set_blocking(pipe.fileno(), False); sel.register(pipe, selectors.EVENT_READ, name)
        deadline = start + timeout; term_at = None; reaped = False
        while True:
            if not reaped:
                rec['reap_pending'] = True          # set BEFORE waitpid; never signal after this point
                pid, st = os.waitpid(child.pid, os.WNOHANG)
                if pid:
                    reaped = True; rec['reaped'] = True; rec['exit'] = os.waitstatus_to_exitcode(st)
                rec['reap_pending'] = False
            if reaped and not sel.get_map():
                break
            now = time.monotonic()
            if not reaped and now >= deadline and rec['signal'] is None:
                rec['signal'] = 'TERM'; term_at = now
                try: os.killpg(child.pid, signal.SIGTERM)       # owned, unreaped direct leader
                except ProcessLookupError: pass
            if not reaped and term_at and now >= term_at + 3 and rec['signal'] == 'TERM':
                rec['signal'] = 'KILL'
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            if reaped and now > deadline + 10:               # pipes held by descendants => uncertain
                rec['ownership_uncertain'] = True; break
            for key, _ in sel.select(0.05):
                data = os.read(key.fileobj.fileno(), 16384)
                if not data:
                    sel.unregister(key.fileobj); continue
                b = bufs[key.data]; room = cap - len(b); b.extend(data[:max(0, room)])
                if len(data) > room: rec['overflow'][key.data] = True
            if any(rec['overflow'].values()) and not reaped and rec['signal'] is None:
                rec['signal'] = 'TERM'; term_at = time.monotonic()
                try: os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        rec['status'] = ('uncertain' if rec['ownership_uncertain'] else
                         'timeout' if rec['signal'] and rec.get('exit', 0) != 0 and time.monotonic() >= deadline else
                         'overflow' if any(rec['overflow'].values()) else
                         'ok' if rec.get('exit') == 0 else 'child-failed')
    except BaseException as e:                                   # protect acquisition + interrupts
        rec['error'] = type(e).__name__
        if child is not None and not rec['reaped']:
            rec['ownership_uncertain'] = True; rec['status'] = 'uncertain'
    finally:
        rec['elapsed'] = round(time.monotonic() - start, 3)
        for p, b in ((out_p, bufs['out']), (err_p, bufs['err'])):
            with open(p, 'xb') as f: f.write(bytes(b)); f.flush(); os.fsync(f.fileno())
        tmp = receipt + '.tmp'
        with open(tmp, 'x') as f: json.dump(rec, f, sort_keys=True); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, receipt)
    return 71 if rec['ownership_uncertain'] else 0

if __name__ == '__main__':
    sys.exit(main())
```

### 3.2 `orch/worker-common.sh` (sourced)
```bash
die(){ echo "worker: $*" >&2; exit 64; }
abs_file(){ [[ "$1" = /* && -f "$1" && ! -L "$1" ]] || die "absolute regular non-symlink file required: $2"; }
abs_dir(){  [[ "$1" = /* && -d "$1" && ! -L "$1" ]] || die "absolute non-symlink dir required: $2"; }
abs_exe(){  [[ "$1" = /* && -x "$1" && ! -L "$1" ]] || die "absolute executable non-symlink required: $2"; }
```

### 3.3 `orch/worker-codex.sh` — `ROLE WORKSPACE PROMPT PROFILE` (roles plan|review|code)
```bash
#!/bin/bash
set -euo pipefail
. "$(dirname "$0")/worker-common.sh"; . "$(dirname "$0")/env.sh"
[[ $# -eq 4 ]] || die "usage: ROLE WORKSPACE PROMPT PROFILE"
abs_exe "$CODEX_BIN" CODEX_BIN; abs_file "$CODEX_WORKER" CODEX_WORKER
exec /bin/bash "$CODEX_WORKER" "$1" "$2" "$3" "$4" "$CODEX_BIN"   # model/sandbox fixed inside frozen script
```

### 3.4 `orch/worker-claude.sh` — `ROLE WORKSPACE PROMPT PROFILE` (roles code|plan|review)
```bash
#!/bin/bash
set -euo pipefail
. "$(dirname "$0")/worker-common.sh"; . "$(dirname "$0")/env.sh"
[[ $# -eq 4 ]] || die "usage: ROLE WORKSPACE PROMPT PROFILE"
role=$1; ws=$2; prompt=$3; profile=$4
abs_dir "$ws" workspace; abs_file "$prompt" prompt; abs_file "$profile" profile
case "$role" in
  review|plan)
    # Backend is explicit. Default codex (Astra). fable requires a proven-available Claude CLI.
    case "${REVIEW_BACKEND:-codex}" in
      codex) exec /bin/bash "$(dirname "$0")/worker-codex.sh" "$role" "$ws" "$prompt" "$profile" ;;
      fable) : "${CLAUDE_BIN:?}"; : "${CLAUDE_FABLE_MODEL:?}"; abs_exe "$CLAUDE_BIN" CLAUDE_BIN
             cd "$ws"
             # No tools at all: the packet is inline. Same hardening flags as the proven coding path.
             exec "$SANDBOX_EXEC" -f "$profile" "$CLAUDE_BIN" --print --model "$CLAUDE_FABLE_MODEL" \
               --output-format json --no-session-persistence --restricted --setting-sources "" \
               --strict-mcp-config --mcp-config '{"mcpServers":{}}' --permission-mode default \
               --tools "" < "$prompt" ;;
      *) die "REVIEW_BACKEND must be codex|fable" ;;
    esac ;;
  code)
    : "${CLAUDE_CODING_MODEL:?coding via Claude not approved}"; : "${CLAUDE_BIN:?}"; abs_exe "$CLAUDE_BIN" CLAUDE_BIN
    cd "$ws"
    exec "$SANDBOX_EXEC" -f "$profile" "$CLAUDE_BIN" --print --model "$CLAUDE_CODING_MODEL" --output-format json \
      --no-session-persistence --restricted --setting-sources "" --strict-mcp-config \
      --mcp-config '{"mcpServers":{}}' --permission-mode acceptEdits --tools "Read,Edit,Write,Glob,Grep" < "$prompt" ;;
  *) die "unsupported role" ;;
esac
```

### 3.5 `orch/worker-pi.sh` — `code WORKSPACE PROMPT PROFILE` (full proven flags, high reasoning)
```bash
#!/bin/bash
set -euo pipefail
. "$(dirname "$0")/worker-common.sh"; . "$(dirname "$0")/env.sh"
[[ $# -eq 4 && "$1" = code ]] || die "usage: code WORKSPACE PROMPT PROFILE"
ws=$2; prompt=$3; profile=$4
abs_dir "$ws" workspace; abs_file "$prompt" prompt; abs_file "$profile" profile; abs_exe "$PI_BIN" PI_BIN
cd "$ws"
exec "$SANDBOX_EXEC" -f "$profile" "$PI_BIN" --print --mode json --provider "$PI_PROVIDER" --model "$PI_CODING_MODEL" \
  --thinking high --no-session --no-extensions --no-mcp --no-skills --no-prompt-templates \
  --no-context-files --no-themes --no-approve --offline --tools read,edit,write "@$prompt"
```
When `auth_source=real` the loop does NOT call this script directly; it writes a guardian spec whose `argv`
is this exact vector (§3.6 `coding_spec`) and launches `$BOOT_PYTHON -B $PI_GUARDIAN spec.json` under
`run_bounded.py` with stdin held open (guardian liveness). After exit it asserts `private-pi/auth.json` is absent.

### 3.6 `orch/loop.py` — state-machine driver (stdlib only)
Subcommands (each exits non-zero and writes `evidence/.../error.json` on any gate failure; none "continues anyway"):

| cmd | does | refuses when |
|---|---|---|
| `init` | verifies env, hashes parent manifest, writes `state.json` | any binding missing; parent inventory ≠ expected hash; tree has symlinks |
| `status` | prints cards, attempts, slots, active seconds | — |
| `run-card ID` | gates → reserve slot → fresh workspace → coding worker via `run_bounded` → freeze → scope-verify → card E2E | deps not `ACCEPTED`; attempts≥3; slots exhausted; time gate fails; lock held; receipt `uncertain` |
| `review` | builds packet, hashes it, runs review worker, strict-parses verdict | any packet file missing/hash-mismatch; transport unavailable |
| `replan` | runs plan worker with the OTHER backend, validates new cards | planner backend == reviewer backend of the same round; card schema invalid |
| `handoff` | prints final frontier prompt in full | any card not terminal |

Core gate code (the parts a small model must not rewrite):
```python
import hashlib, json, os, sys, time, pathlib, shutil, subprocess

ROOT = pathlib.Path(__file__).resolve().parent
LIMITS = {'cap_launches': 48, 'time_ceiling': 32400.0, 'reserve': 180.0, 'job_needs': 840.0, 'job_timeout': 600}

def sha(p):           return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def jwrite(p, obj):   # atomic, fsynced
    t = str(p) + '.tmp'
    with open(t, 'w') as f: json.dump(obj, f, sort_keys=True, indent=1); f.flush(); os.fsync(f.fileno())
    os.replace(t, p)
def append_ledger(rec):                       # O_APPEND + fsync, one line
    fd = os.open(ROOT / 'ledger.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try: os.write(fd, (json.dumps(rec, sort_keys=True) + '\n').encode()); os.fsync(fd)
    finally: os.close(fd)
def acquire_lock():
    try: return os.open(ROOT / 'lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError: sys.exit('LOCK_HELD: previous run uncertain or still active; inspect evidence')

def inventory(root):
    """Normalized, symlink-hostile inventory: relpath,mode,size,sha. Raises on symlink/special file."""
    out = []
    for p in sorted(pathlib.Path(root).rglob('*')):
        if p.is_symlink(): raise SystemExit('SYMLINK_IN_TREE ' + str(p))
        if p.is_dir(): continue
        if not p.is_file(): raise SystemExit('SPECIAL_FILE ' + str(p))
        out.append([str(p.relative_to(root)), oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
    return out
def inv_hash(inv): return hashlib.sha256(json.dumps(inv, sort_keys=True).encode()).hexdigest()

def time_gate(state, need):
    used = state['active_seconds']
    avail = LIMITS['time_ceiling'] - used - LIMITS['reserve']
    if avail < need: sys.exit('TIME_GATE_FAILED avail=%.1f need=%.1f' % (avail, need))

def slot_gate(state):
    if state['launches_used'] >= LIMITS['cap_launches']: sys.exit('SLOT_CAP_REACHED')

def reserve_slot(state, card, attempt):
    state['launches_used'] += 1                       # consumed BEFORE launch; never refunded
    append_ledger({'event': 'reserve', 'slot': state['launches_used'], 'card': card, 'attempt': attempt,
                   'wall': time.time()})
    jwrite(ROOT / 'state.json', state)

def scope_verify(parent_inv, new_inv, allowed):
    """Return (ok, problems). Changed/added/removed paths must be a subset of allowed; no deletions."""
    p = {r[0]: r for r in parent_inv}; n = {r[0]: r for r in new_inv}; probs = []
    for path in set(p) | set(n):
        if p.get(path) != n.get(path):
            if path not in allowed: probs.append('OUT_OF_SCOPE ' + path)
            if path not in n:       probs.append('DELETED ' + path)
    return (not probs, probs)

def parse_verdict(text):
    """Strict. Accept only a single fenced ```json block whose object has exactly the schema keys."""
    import re
    blocks = re.findall(r'```json\s*(\{.*?\})\s*```', text, re.S)
    if len(blocks) != 1: return None
    try: v = json.loads(blocks[0])
    except ValueError: return None
    need = {'revision', 'findings', 'missing_evidence', 'coverage', 'cleanup', 'verdict'}
    if set(v) != need or v['verdict'] not in ('ACCEPTED', 'INCOMPLETE', 'BLOCKED'): return None
    if v['coverage'].get('complete') is not True or v['coverage'].get('truncated') is not False:
        v['verdict'] = 'INCOMPLETE'
    if v['findings'] or v['missing_evidence']:
        v['verdict'] = 'INCOMPLETE' if v['verdict'] == 'ACCEPTED' else v['verdict']
    return v
```
The rest of `loop.py` is thin glue that calls these and `run_bounded.py`. Review worker is run with
`REVIEW_BACKEND` taken from state (`reviewer_backend`); the planner for the next round gets the OTHER backend.
Reviewer output is only ever consumed through `parse_verdict`; free text never advances state. `ACCEPTED` is
honored only if the supervisor ALSO independently confirms `findings==[] and missing_evidence==[]` itself.

---------------------------------------------------------------------------------------------------
## 4. Card schema and template (machine-checked; one file per card in `orch/cards/`)

```json
{"id":"A1","objective":"<one sentence>","depends_on":["P0"],
 "parent_manifest":"<path>","parent_hash":"<sha256 filled by loop at run time>",
 "allowed_paths":["tests/e2e/test_review_adapter_e2e.py"],
 "inputs_inline":["<path to read-only context file>"],
 "acceptance_rows":["R1: ...","R2: ..."], "stop_condition":"<when to print CARD_BLOCKED>",
 "e2e":{"argv":["<fixed command>"],"expect_status":0,"expect_files":["..."]},
 "max_edit_chars":3000,"timeout":600}
```
Validation (in `init`/`replan`): unique id; `allowed_paths` non-empty, relative, no `..`, ≤3 files; exactly one
objective; `e2e.argv` fixed (no shell, no placeholders left: any `<`…`>` or `TODO` in a card = reject);
acyclic deps; `timeout ≤ 600`.

Prompt assembly (`assemble-card-prompt`): fixed header = Rules §1; then OBJECTIVE, PARENT HASH, ALLOWED_PATHS,
INPUTS (inlined verbatim, size-capped 200 KB total), ACCEPTANCE ROWS, STOP CONDITION, closing line. No other text.

---------------------------------------------------------------------------------------------------
## 5. The workflow loop (state machine)

```
PENDING → RESERVED → CODED → FROZEN → SCOPE_OK → E2E_PASS → SOURCE_REVIEWED → ACCEPTED
   any gate failure → FAILED(attempt n)   n<3: retry same card (new slot);  n=3: → NEEDS_REPLAN
   uncertainty (lock/cleanup/reap) → BLOCKED_CLEANUP_UNCERTAIN (STOP; keep lock + evidence)
```
Per card (`loop.py run-card ID`):
1. **Gate**: deps ACCEPTED; attempts<3; `slot_gate`; `time_gate(job_needs=840)`; acquire lock; verify parent inventory hash == card.parent_hash; verify no leftover `auth.json`.
2. **Reserve** slot (ledger + state, fsync) *before* anything launches.
3. **Workspace**: fresh `pi-runtime-v2/jobs/<card>-<n>/`, mode 0700, copy of parent candidate (copy, never link), prompt file assembled, hash recorded.
4. **Launch** coding worker (Pi via guardian when `auth_source=real`) through `run_bounded.py`, timeout 600, cap 2 MiB.
5. **Receipt gate**: status must be `ok` and `reaped=true`; `uncertain` ⇒ BLOCKED_CLEANUP_UNCERTAIN. Worker stdout must contain `CARD_DONE <id>`; `CARD_BLOCKED` ⇒ attempt failed (slot spent).
6. **Freeze**: inventory of workspace; `scope_verify` vs parent; write `result-manifest.json` + diff; reject symlinks/special files/oversize.
7. **E2E** the card's fixed command via `run_bounded.py` (20 s default, 200 s matrix); compare status and expected files.
8. **Credential check**: `auth.json` absent; residual `ps` query for the job's process groups (fixed `/bin/ps -axo pid=,ppid=,pgid=`, 5 s/1 MiB bound).
9. **Source review** (`loop.py review --scope card`): separate Astra (or Fable) session; pass ⇒ ACCEPTED and the new frozen manifest becomes the parent for dependents. Time and ledger updated for EVERY step including reviews.
10. Time accounting: record monotonic elapsed + wall anchors per step into the ledger; never subtract idle by inference; interrupted intervals recovered conservatively (assume full elapsed since last anchor).

Milestone loop (after all cards ACCEPTED): `review` (final, through real adapter) → if `parse_verdict` has findings or
missing evidence → `replan` (different backend/model, fresh session) → new small cards → loop. Terminates only when
a fresh review returns ACCEPTED with zero findings and zero missing evidence, OR a stop rule fires (cap/time/
uncertainty/provider unavailable) ⇒ honest INCOMPLETE/BLOCKED handoff. Three failures on one objective ⇒ forced
replan by a fresh planner; budgets never reset.

---------------------------------------------------------------------------------------------------
## 6. Card list for this milestone (small, serial, each with an E2E)

| id | objective | allowed path | E2E that proves it (real process, no unit tests) |
|---|---|---|---|
| P0 | **Pre-flight (no coding launch)**: verify 82-entry parent manifest (size/mode/regular/no extras), the 5 plan hashes, historical preservation, env bindings, time tail, guardian/profile hashes | none | `loop.py init` exits 0 and prints bindings; negative: tamper copy ⇒ exit non-zero |
| S0 | **Schema review (no coding launch)**: Astra verdict on version-2 index+detail receipt schema incl. byte-budget table | none | `parse_verdict` of the review is ACCEPTED, else replan |
| B0 | `dispatch-coding.py`-equivalent is **this orch/** itself; run **E2E-ORCH suite (§7)** and Astra source review of `orch/` | `orch/*` (root-authored, accounted; no coding slot) | all §7 scenarios pass |
| A1 | precreate 18 matrix rows + `result.json` index writer | `tests/e2e/test_review_adapter_e2e.py` | `--scenario matrix` exits 0, `result.json` ≤65536 B, 18 rows |
| A2 | detail-file publisher (exclusive create, hash/size refs, atomic index replace) | same | `lifecycle-normal` exits 0; detail hashes verify |
| A3 | explicit not-run rows + publication-failure nonzero | same | `routing-missing` ⇒ row1 fail, rows2–18 not-run, status 1 |
| B1 | register every `bounded_run` before attempt (incl. no-child) | same | `deadline-suite-before-first` ⇒ invocation recorded, 0 children |
| B2 | record partial output/status on failure before re-raise | same | `lifecycle-stdout-overflow` ⇒ retained bytes ≤4096, overflow flag, status 1 |
| B3 | ownership facts: PID/PGID, signal intent/attempt/result, reap, EOF-vs-closed | same | `lifecycle-timeout`, `lifecycle-post-reap-*` (never signals reaped) |
| C1 | runner skeleton: fixed scenario table, argv builder `e2e_argv` | `run-review-adapter-e2e-011.py` | runner with `--list` prints 18 IDs, rejects unknown |
| C2 | runner: child ownership/finalizer, raw bounds, receipt readers (limit+1 before parse) | same | oversize/dup-key/unsupported-schema receipt fixtures rejected |
| D1 | bootstrap role: private liveness pipe, protected acquisition, independent EOF | same | kill-bootstrap control ⇒ runner exits, status recorded |
| D2 | independent descendant check (`ps` rows validated, group comparison) | same | surviving-group control ⇒ `BLOCKED_CLEANUP_UNCERTAIN` |
| E1 | provider smoke operation + final review invocation (existing review route only) | same | fake-provider matrix then real smoke if Codex available |
| X* | correction cards, one concern each | per Astra | per finding |

Each card is expected to be ≤1 coding launch; slots are consumed only by coding launches (P0, S0, B0 and reviews
use none but all consume time). Reserve slots (≈42–48) for corrections; if A/B or C/D need splitting, shrink the
reserve visibly — never bundle concerns.

---------------------------------------------------------------------------------------------------
## 7. E2E-ORCH suite — tests the orchestration itself (no unit tests; every case is a subprocess run)

`e2e/run_e2e.py` creates a temp `ORCH_ROOT` copy, writes a fake `env.sh` pointing to `e2e/fakes/*`, runs the REAL
`orch/*.sh`, `run_bounded.py`, `loop.py` as processes, and asserts exit code + receipt/ledger/state contents.
Fakes read `FAKE_SCENARIO` from their environment and exhibit deterministic behavior.

| ID | edge case | expected |
|---|---|---|
| O01 | happy path: one card, fake pi edits allowed file, fake review ACCEPTED | state ACCEPTED, ledger has reserve+done, slot=+1 |
| O02 | worker edits file outside `allowed_paths` | FAILED, `OUT_OF_SCOPE`, slot consumed, attempt+1 |
| O03 | worker deletes an allowed file / adds symlink / creates special file | rejected (`DELETED`/`SYMLINK_IN_TREE`/`SPECIAL_FILE`) |
| O04 | worker exceeds timeout, ignores SIGTERM | TERM then KILL after 3 s, receipt `timeout`, reaped, no stray proc |
| O05 | worker output > cap | killed, `overflow` flag, streams ≤cap |
| O06 | worker prints `CARD_BLOCKED` | attempt failed, slot spent, no E2E run |
| O07 | worker prints nothing / exit 0 | attempt failed (`missing CARD_DONE`) |
| O08 | child spawns a background grandchild that holds pipes | `uncertain` ⇒ exit 71, lock retained, state BLOCKED_CLEANUP_UNCERTAIN, no auto-kill of saved PIDs |
| O09 | launcher interrupted (SIGINT) mid-run | receipt published or state uncertain; lock retained; next `run-card` refuses (`LOCK_HELD`) |
| O10 | two `run-card` at once | exactly one gets lock; other exits `LOCK_HELD` |
| O11 | `state.json` torn write simulation (kill between tmp and replace) | old state intact, tmp ignored/cleaned |
| O12 | launch counter at 48 | `SLOT_CAP_REACHED`, no worker spawned |
| O13 | active time leaves <840 s | `TIME_GATE_FAILED`, no worker spawned, no slot consumed |
| O14 | failed launch then retry | slot not reused (ledger shows distinct slots) |
| O15 | 3 failures on one card | state NEEDS_REPLAN; `run-card` refuses 4th |
| O16 | parent manifest tampered after freeze | `init`/`run-card` refuse (hash mismatch) |
| O17 | env path relative / symlink / non-executable | worker exit 64 with reason |
| O18 | guardian leaves `auth.json` | step 8 fails ⇒ BLOCKED_CLEANUP_UNCERTAIN |
| O19 | review returns two JSON blocks / extra keys / prose-only / `ACCEPTED` with findings | `parse_verdict` ⇒ not accepted; state unchanged |
| O20 | review output truncated mid-JSON | no acceptance; fresh review required |
| O21 | review says `ACCEPTED` but `coverage.truncated=true` | downgraded to INCOMPLETE |
| O22 | provider unavailable (fake exits 75) | `BLOCKED_PROVIDER_UNAVAILABLE`; no fallback to another model |
| O23 | planner backend == reviewer backend | `replan` refuses |
| O24 | replan returns card with placeholder `<…>`/`TODO`, `..` path, >3 files, cyclic dep | rejected, nothing appended |
| O25 | review→replan→new card→re-review cycle (2 rounds then ACCEPTED) | terminates; ledger shows both rounds |
| O26 | prompt packet file missing or hash mismatch | `review` refuses before launch |
| O27 | oversize receipt (65537 B) / duplicate JSON keys | rejected before parse / on parse |
| O28 | `claude-worker review` with `REVIEW_BACKEND=fable` and `--tools ""` flag check | fake records argv: no tools, no MCP, restricted |
| O29 | Pi worker argv | fake records exact vector incl. `--thinking high --offline --no-themes` |
| O30 | handoff before all cards terminal | refuses; after terminal prints full prompt, byte-identical to file |

Run the whole suite for any change to `run_bounded.py`, `loop.py`, or workers. Each scenario ≤20 s; suite ≤ 5 min.
Exit status 0 only if all pass; the result is written to `evidence/e2e-orch/<run>/summary.json`.

Milestone E2Es (the 18 literal scenarios of Plan 011 §6) run unchanged through `run-review-adapter-e2e-011.py`;
their expected statuses are copied verbatim from Plan 011 (matrix 0, lifecycle-normal 0, setup-failure 1,
post-reap-exception 1, post-reap-interrupt 130, timeout 1, stdout/stderr-overflow 1, cleanup-interrupt 1,
deadline-before-first 1, deadline-before-next 1, records-exact-limit 0, records-one-over 1, routing-missing 1,
routing-duplicate 1, diagnostic-ascii 1, diagnostic-multibyte 1, diagnostic-interrupt 130). Their fixed env
(`PATH=/usr/bin:/bin`, `LANG=C`, private HOME/TMPDIR/UV_CACHE_DIR, `UV_OFFLINE=1`, `UV_PYTHON_DOWNLOADS=never`),
uv path `/opt/homebrew/Cellar/uv/0.13.5/bin/uv`, and command vector are also unchanged.

---------------------------------------------------------------------------------------------------
## 8. Review and re-plan (frontier-only, different models)

* **Review** always goes through `worker-claude.sh review` (the "claude worker script"), backend by `REVIEW_BACKEND`:
  `codex` ⇒ gpt-6-astra (read-only, shell disabled, ephemeral — via frozen codex-worker.sh), or `fable` ⇒
  claude-fable-5-1 with zero tools. Packet must contain all source, diffs, hashes, receipts INLINE (tools disabled).
  If the packet is too large: indexed parts + required synthesis step; a part-count/coverage receipt is mandatory.
* **Re-plan** for findings runs in a *separate fresh session on the other backend* (reviewer codex ⇒ planner fable;
  reviewer fable ⇒ planner codex). If the other backend is unavailable ⇒ `BLOCKED_PROVIDER_UNAVAILABLE`
  (a fresh Astra session of the same backend is permitted ONLY with explicit user approval recorded in state).
* The planner prompt contains: the review JSON, the card schema, the rules §1, the current manifest hash, remaining
  slots/time, and the instruction "emit ≤4 cards as one JSON array; one concern per card; each with fixed E2E".
* Every finding gets a recorded disposition: `card:<id>` | `rejected:<reason>` | `deferred:<reason>` — a finding
  with no disposition blocks the next review. A rejected finding is shown to the next reviewer.

---------------------------------------------------------------------------------------------------
## 9. Final step — printed frontier handoff prompt

`loop.py handoff` writes `RESULT-011.json` + `HANDOFF-011.txt` under `continuation-011/` (never replacing
RESULT-010) and **prints the entire handoff to the terminal**. Its fixed sections, each filled from files:

1. Verdict and exact revision/environment hashes (result-manifest path, bytes, SHA256; parent; inventory hash).
2. Complete card/launch ledger incl. failures; cap 48; remaining slots; time checkpoint, reconciled tail, active total vs 32400.
3. For each of the 18 scenarios: argv, expected/actual status, stream lengths+hashes, index/detail paths+hashes, `ps` result.
4. E2E-ORCH summary (O01–O30) with hashes.
5. Schema, source, and envelope reviews with their verdicts; real-provider smoke evidence or `BLOCKED_PROVIDER_UNAVAILABLE`.
6. Cleanup/lock/credential-absence/original-preservation evidence; every uncertainty.
7. **Full review prompt** (below) with ALL placeholders filled, complete source and accumulated diff inline (or
   indexed parts with coverage receipts), then each returned review and each finding's disposition.
8. Open blockers + next bound small card if incomplete.

Review prompt (filled by the script; any remaining `[` `]` placeholder ⇒ handoff refuses):
```
You are the independent final reviewer of review-worker adapter acceptance ONLY. You may not edit, execute code,
delegate, or infer runtime evidence from source closure. Read ALL inline material.
REVISION: <path, bytes, sha256>   PARENT: <path, bytes, sha256>
SOURCE INVENTORY: <paths/modes/bytes/hashes + inventory hash>
CARDS & DISPOSITIONS: <ids, scope, evidence, every prior finding + disposition>
SCHEMA APPROVAL: <v2 design + source review hashes>
ENVELOPE/BOOTSTRAP/RUNNER: <paths, hashes, reviews, tested commands, independent completion>
ENVIRONMENT: <OS/sandbox, uv, python, lock, adapters, codex/provider/model>
PUBLIC E2Es (18): <argv, expected/actual, stream hashes, index/detail hashes, row+call inventories, reap/EOF/ps>
E2E-ORCH (O01–O30): <results>
PROVIDER SMOKE: <adapter argv, identity, context, availability, hashes, cleanup>
ACCOUNTING: <launches/cap48, failed launches, intervals, remaining within 32400, reserve>
PRESERVATION: <original/historical inventory, no import, lock disposition>
COVERAGE: <files/bytes supplied, parts, truncation flags>
TASK: check correctness, regressions, provenance, process ownership, finite-failure contract, every acceptance
criterion. Distinguish expected negative controls from envelope failure. Zero findings with missing evidence is NOT
acceptance. Return exactly ONE fenced ```json block with keys: revision, findings[{id,severity,location,evidence}],
missing_evidence[], coverage{complete,truncated}, cleanup, verdict (ACCEPTED|INCOMPLETE|BLOCKED). ACCEPTED requires
zero findings, zero missing evidence, all 18 E2Es plus real smoke, independently completed envelope, preserved
accounting. Output outside the JSON block is ignored.
```

---------------------------------------------------------------------------------------------------
## 10. Zero-gap checklist (each item maps to a mechanism above)

- Smaller-model safety: one objective, fixed template, allowed paths, ≤3000-char edits, machine scope verify (§1,§3.6,§4).
- Workflow loop with attempt/slot/time gates and replan trigger (§5).
- E2E only: card E2Es (§6), orchestration E2Es O01–O30 (§7), 18 public milestone E2Es; no unit tests, no helper imports.
- Edge cases: timeout, overflow, orphans, interrupts, concurrency, torn writes, tamper, symlinks, credential residue, malformed/spoofed/truncated reviews, provider outage, planner=reviewer, bad cards (§7).
- Portable scripts for Claude, Pi, Codex inlined (§3); env-only bindings; no machine paths.
- Review via claude-worker script with Astra or Fable; planning by a different model; loop until nothing remains (§8).
- Final printed handoff with fully populated review prompt (§9).
- Disagreement flagged: live `claude-worker.sh review` exits 64 vs Plan 011 claim — resolved by hash check at P0 and by `worker-claude.sh`.
- Known risks left explicit: guardian is "experimental" (hash+behavior re-verified at P0, never trusted by receipt alone);
  Fable availability unproven (smoke before use); time may not fit all cards (stop honestly, per Plan 011).

---------------------------------------------------------------------------------------------------
## 11. Verification of THIS plan before execution (read-only checks, then user approval)

1. Confirm `ORCH_ROOT` location and fill `env.sh` with real absolute binaries (Codex path must be real and non-symlink).
2. `diff` live `claude-worker.sh`/`codex-worker.sh`/`pi-worker.sh` hashes against those recorded at P0.
3. After approval and before any coding launch: write `orch/`, `e2e/`; run `e2e/run_e2e.py` (O01–O30) — all green —
   then Astra source review of `orch/`; only then reserve slot 37.
4. Reconcile the active-time tail first; if remaining < Σ(card timeouts + reviews + 180 s), shrink scope visibly
   rather than overrun.
