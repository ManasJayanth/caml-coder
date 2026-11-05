# PLAN 013 — Round 5 of the review-worker acceptance loop (continuation-011)

Target file in repo (written on approval): `artifacts/planning/esy-repair-implementation-001/continuation-011/PLAN-013-ROUND5.md`
(no other plan-file convention exists in the repo; PLAN 012 lives in the repo-root `plan.md`).

**Status: PLAN ONLY.** Approving this plan creates no reservation, launch, allocation or budget entry. Nothing under
`orch/`, `frozen/`, `continuation-008/`, `continuation-010/` is modified by this document. Every snippet below runs only
during execution of this plan, after the operator decisions in §1 are recorded.

Goal (operator, verbatim intent): small-coding-model friendly, zero gaps, correct, safe; workflow loop; E2E tests only
(no unit tests) including edge cases; review by a frontier model and re-plan by a DIFFERENT frontier model, loop until a
review returns nothing to address or a stop rule fires; final step prints a full frontier review prompt; orchestration
scripts inlined (Claude, Pi, Codex workers) so the plan is portable.

---------------------------------------------------------------------------------------------------
## 0. Verified facts that shape this round (read from the repo on 2026-10-24; nothing assumed)

| fact | value | consequence |
|---|---|---|
| state in force | `orch/state.json`: launches 36/48, `active_seconds` **31702.757** / 32400 ⇒ **697.2 s left**; `orch_hash == parent_hash ==` orch-010 `730ea2c8…`; `reviewer_backend=fable`; `pending_findings=[]`; `source_reviews={}` | **No coding card can ever launch under the current ceiling** (a card needs ≥840 s today, ≥1230 s after §5 D4). Budgets never reset and carry over. Round 5 is impossible without an explicit, recorded operator time allocation (§1 Decision 1). |
| pending cards | C1 (O32), C2 (O43), C5 (O55), C6 (O56), C7 (O55), C8 (O56); C3/C4 SUPERSEDED | O55/O56 double-claimed (known). Additionally: **C7 duplicates C2** (both = post-e2e re-hash + stale review refusal); **C5 R2 is wrong** (requires `inputs_inline` to be a dict; `assemble_prompt` iterates a list of paths; PLAN 012 §4 schema says list); **C6 R4 and C2 R1 predate the orch-011 mechanics below** (handoff gate, suite step) and would fail their own E2E. C1 is consistent and stays. |
| suite | `e2e/run_e2e.py` 52 scenarios, 37.3 s total, max 5.4 s; ids O01–O54 except O32, O43 (free, claimed by C1/C2) | A full-suite run per card is cheap (≤60 s) and closes the "card breaks another scenario" gap. |
| registry defect | a duplicate `def O55` in `run_e2e.py` is silently shadowed; `run_e2e.py O999` runs nothing and exits 0 | §5 D8 makes both fatal. |
| planner packet | `EXISTING_E2E_IDS` regex `^def (O\d+)\b` misses `O03a/O03b/O20_O21`; ids claimed by pending cards are not shown and not validated | §5 D2 shows claimed ids AND rejects collisions in `replan`, `add-card` and `init`. |
| review cap | review-012 packet 118988 B took 299.8 of 300 s; the next subject (orch-011 + attachments) is ≈160 KB | cap 300 → **600 s** must be explicitly approved (§1 Decision 2). Never raised silently. |
| bindings | `CODEX_BIN=/opt/homebrew/Caskroom/codex/0.163.0/bin/codex` **MISSING** (brew now has 0.164.0); PI_BIN 1.4.0 OK; CLAUDE_BIN 2.1.309 OK; `/usr/bin/python3` = 3.9.6; `/usr/bin/sandbox-exec` OK | root rebinds CODEX_BIN before the Astra smoke (ledgered in the orch-011 manifest note). The guardian route builds its argv from `PI_BIN` without validating it → §5 D15 validates before a slot is consumed. |
| Astra | usage-limited until 2026-10-29 22:41 | until then: Fable reviews AND Fable plans with recorded same-backend approval (precedent: 8 entries in `state.same_backend_approvals`). |
| guardian | `continuation-008/guardian-v2.py` contract; exit_code≠0 with cleanup verified is today treated as **uncertainty** (lock retained) | a provider outage on the coding model would wedge the loop; §5 D13 makes a cleanly-reaped non-zero worker an attempt failure and adds a failure-streak brake. |
| hygiene | `pi-runtime-v2/private-pi/` empty; `~/.codex/auth.json` mtime 2026-10-23 19:36 (not us); lock free | unchanged preconditions for the first real launch. |
| disposition keys | review-005 and review-012 both used ids F1–F8; plan-014 merged review-012's over review-005's (`state.dispositions.F1 = card:C7` etc.) | this is finding F5 in action. §6.4 records a provenance table so nothing is lost; C13 fixes the merge. |

---------------------------------------------------------------------------------------------------
## 1. Operator decisions required before execution (each recorded in the ledger by the command named)

1. **Active-time allocation (blocking).** Without it the only executable scope is P0 + P1 + handoff (INCOMPLETE).
   Mechanism: new `loop.py allocate-time --ceiling N --approval "<who/when/words>"` (§5 D1): ledgered, refuses to lower,
   refuses >+86400 s per call, refuses blank approval. Recommendation from the accounting in §8:
   `--ceiling 61200` (+28800 s = 8 h) covers P0–P5 with Tier-1 cards at worst-case gates (≈27500 s), typical ≈13800 s.
   Tier 2/3 need a second allocation only if the operator wants them after Tier 1 lands (§8 table).
2. **Review cap 300 → 600 s** (`LIMITS['review_timeout']`, `review_need` 480 → 780; smoke cap unchanged 120). Approving
   this plan is the explicit review of that change; it is disclosed in the orch-011 manifest note. Packets stay ≤400 KB.
3. **Same-backend approval text** (Fable plans/cards while Fable reviews) for `add-card --approval` and any
   `replan --same-backend-approved` before 2026-10-29 22:41. Suggested: `"operator approved PLAN 013 Round 5 via pi
   relay on <date>; cards authored by Fable (claude-fable-5-1), reviewer of review-012 also Fable; Astra usage-limited
   until 2026-10-29 22:41"`.
4. **CODEX_BIN rebind** to `/opt/homebrew/Caskroom/codex/0.164.0/bin/codex` (verify non-symlink, executable) — root,
   disclosed in the manifest note like the PI_BIN/CLAUDE_BIN rebinds of round 4.
5. **Accounting of planning time** (recommendation: honest file-anchored interval): `note-interval` for pi's request
   authoring (HANDOFF-011.md mtime 2026-10-23 20:46 → PLAN-013-REQUEST.md mtime 2026-10-24 08:49 is mostly idle
   overnight; count the anchored writing interval only, basis stated) and for this plan (PLAN-013-REQUEST.md mtime →
   PLAN-013-ROUND5.md mtime, no idle subtracted). Precedent: round-2 planning was noted as a 360 s allowance.

---------------------------------------------------------------------------------------------------
## 2. Rules every coding worker sees (unchanged, verbatim in every card prompt — `RULES` in loop.py)

1. One objective. Edit ONLY files listed in ALLOWED_PATHS. Create nothing else.
2. Use only read/edit/write tools. Do not run, import, compile, test, or call providers.
3. Each single edit < 3000 characters; split larger changes into several edits.
4. Do not touch history, config/, uv.lock, adapters, or any file not in ALLOWED_PATHS.
5. Finish by printing exactly one line: CARD_DONE <card-id>. If blocked print CARD_BLOCKED <card-id>: <reason> and stop.
6. If instructions conflict, stop with CARD_BLOCKED. Never guess.
7. Never print or write credentials, tokens, or paths under private-pi.

Card prompts are machine-assembled by `assemble_prompt` (RULES, CARD_ID, OBJECTIVE, PARENT_HASH, ALLOWED_PATHS,
ACCEPTANCE_ROWS, STOP_CONDITION, optional inlined inputs, closing line). No prose planning reaches a worker.

---------------------------------------------------------------------------------------------------
## 3. Who does what

| actor | does | never does |
|---|---|---|
| **root / supervisor** (pi, pane %2) | applies the inlined deltas of §5 to `orch/` + `e2e/` (orch-011), runs the suite, freezes, rebinds, runs the loop commands in §4 order, writes manifests/notes, records intervals | edits a card's output tree; edits `state.json`/`ledger.jsonl` by hand; raises any cap not listed in §1 |
| **coding worker** (gpt-6-luna via `worker-pi.sh` vector inside `guardian-v2.py`, profile `pi-nofork-v3.sb`) | one card per launch, edits only `allowed_paths` in a copy of the parent tree | runs anything; sees credentials; sees prose |
| **reviewer** (Fable via `worker-claude.sh review`; Astra via `worker-codex.sh` once the smoke passes) | reviews a packet, returns one JSON block | edits, executes |
| **planner** (the OTHER backend; until 10-29 Fable with recorded approval) | `replan` after findings: ≤4 cards + dispositions | re-dispositions standing findings (C13 enforces) |
| **frontier reviewer of the whole round** | reads the printed `HANDOFF-012.txt` prompt (§7) | — |

---------------------------------------------------------------------------------------------------
## 4. Round-5 execution order (serial; every step ledgered; stop rules in §9)

All commands run from `artifacts/planning/esy-repair-implementation-001/continuation-011/` with `python3 -B orch/loop.py …`
(`/usr/bin/python3` 3.9.6). `R` = root action, `L` = loop command (bounded, ledgered), `G` = gate that may stop the round.

### P0 — Reconcile and decide (no launches, no slots)
0.1 `L status` — confirm launches 36, active 31702.757, lock absent, `pending_findings=[]`.
0.2 `R` verify bindings read-only: PI_BIN 1.4.0, CLAUDE_BIN 2.1.309, CODEX 0.164.0 present & non-symlink; `/usr/bin/python3`;
    `private-pi/` empty; `~/.codex/auth.json` mtime unchanged (record it). Rebind `CODEX_BIN` in `orch/env.sh` (Decision 4).
0.3 `R` apply **D1 only** (ceiling + `allocate-time`, §5) to `orch/loop.py`; append scenario **O57** and the `Box.init`
    change to `e2e/run_e2e.py`; run `python3 -B e2e/run_e2e.py` ⇒ `TOTAL 53 FAILED 0`.
0.4 `L note-interval --seconds S --basis "round-5 planning: pi request authoring + Claude plan authoring, file-anchored
    (<mtimes>)" --start-wall … --end-wall …` (Decision 5). Then `note-interval` for 0.2–0.3.
0.5 **G** `L allocate-time --ceiling 61200 --approval "<Decision 1 text>"` ⇒ `ALLOCATED`. If the operator declines:
    skip to P6 with verdict INCOMPLETE; write `HANDOFF-012.md` by hand explaining the time blocker (as round 4 did).

### P1 — orch-011: root-authored mechanics (no slots; time counted by `note-interval`)
1.1 `R` apply deltas **D2–D15** (§5) to `orch/loop.py`, `e2e/run_e2e.py`, `e2e/fake_engine.py`, `e2e/fake_guardian.py`,
    `orch/env.sh.example`; add scenarios **O58–O69**; update O01/O30/O41 and `Box` as specified (§5.2).
1.2 `R` `python3 -B e2e/run_e2e.py` ⇒ **`TOTAL 65 FAILED 0`** (52 + O57–O69). A failing root scenario is fixed in the
    scenario or the delta (disclosed in the manifest note); scenarios are never deleted or renamed.
1.3 `R` attachments (closes M0–M3): create `orch/external/` with byte-identical copies:
    `pi-nofork-v3.sb` (PI_PROFILE), `guardian-v2.py` (PI_GUARDIAN), `codex-worker.sh` (CODEX_WORKER),
    `review-004-receipt.json` + `review-004-receipt.out` (Fable smoke under review-readonly.sb, `CLAUDE_REAL_CONFIG=1`;
    checked for zero secrets — it contains model usage JSON only), and `e2e-summary-orch-011.json` = the 1.2 summary.
    Record sha256 of each source → copy in the manifest note.
1.4 `R` freeze `frozen/orch-011/` = `orch/*.py`, `orch/*.sh`, `orch/env.sh.example`, `review-readonly.sb`, `e2e/*.py`,
    `external/*` (same relative layout as orch-010 + `external/`); write `frozen/orch-011.manifest.json` (inventory, hash,
    note listing D1–D15, O57–O69, CODEX_BIN rebind, attachments, review-cap change per Decision 2).
1.5 `L rebind-orch` ⇒ `ORCH_REBOUND`; `L set-parent <abs>/frozen/orch-011` ⇒ `PARENT_SET` (hash must equal the manifest
    hash and the new `orch_hash`; if not, stop: layout drift). `L note-interval` for P1.

### P2 — Provider re-check (≤120 s; no slot)
2.1 `L review --subject <abs>/frozen/smoke-subject --name astra-smoke-r5 --smoke --backend codex`.
    - `SMOKE_OK` ⇒ Astra available: from here reviews stay on **fable** (explicit `--backend fable` on every review until
      C16 lands, because the smoke flipped `reviewer_backend` to codex — finding F8) and **replans run on codex** (the
      other backend) with no same-backend approval needed.
    - exit 75 (`BLOCKED_PROVIDER_UNAVAILABLE`) ⇒ Fable-only: every `replan` passes `--backend fable
      --same-backend-approved "<Decision 3 text>"`; every review passes `--backend fable`. Record in the round report.

### P3 — Source review of the orchestration in force (≤600 s)
3.1 `L review --subject <abs>/frozen/orch-011 --name orch-011 --backend fable`.
    `REVIEW_ACCEPTED` ⇒ `state.source_reviews['orch-011'] == orch_hash`; go to P4.
    `REVIEW_NOT_ACCEPTED findings=[…]` ⇒ 3.2.
3.2 `L replan [--backend codex | --backend fable --same-backend-approved "…"]` ⇒ every finding gets a disposition
    (`card:` cards are appended to the program AFTER the Tier-1 chain by `depends_on` the planner chooses; collisions are
    now rejected by D2); then 3.1 again on the SAME snapshot only if the replan produced 0 cards (pure dispositions);
    if cards were produced, the orch source is fixed by those cards in P4 and the snapshot is re-reviewed in P5.
    **Stop rule**: two non-accepted source reviews with new undispositioned findings on root mechanics ⇒ stop, hand off.

### P4 — Card program (slots 37–48)
4.1 `R` write the card files of §6 to `continuation-011/cards-round5/C9.json … C18.json` (byte-exact).
4.2 Re-issue the quartet (all `L`, no slots):
```
retire-card C2 --reason "rows predate orch-011 (suite step, summary dir); re-issued as C9 with the same objective"
add-card cards-round5/C9.json  --reason "PLAN 013 §6 C9 replaces C2 (F2 review-005 / F1 review-012)" --approval "<Decision 3>"
retire-card C7 --reason "duplicate of C2/C9 (post-e2e re-hash + stale review refusal); O55 double-claimed with C5" --superseded-by C9
retire-card C5 --reason "R2 requires inputs_inline to be a dict; assemble_prompt and PLAN 012 §4 define a list"
add-card cards-round5/C10.json --reason "PLAN 013 §6 C10 replaces C5 (F4 review-005)" --approval "<Decision 3>"
retire-card C6 --reason "R4 handoff precondition changed by orch-011 (e2e summary gate, --seq); re-issued as C11"
add-card cards-round5/C11.json --reason "PLAN 013 §6 C11 replaces C6 (F3 review-005 / F2 review-012)" --approval "<Decision 3>"
retire-card C8 --reason "base C7 retired; O56 double-claimed with C6; re-issued as C12"
add-card cards-round5/C12.json --reason "PLAN 013 §6 C12 replaces C8 (F6 review-005 / F3 review-012)" --approval "<Decision 3>"
set-disposition F2  card:C11 --reason "C11 implements the milestone revision binding (was deferred)"
set-disposition F10 "root:orch-011 D7 removed the baked init defaults" --reason "root-authored, disclosed in manifest"
set-disposition M0  "root:orch-011 external/ carries codex-worker.sh and pi-nofork-v3.sb" --reason "attached to the review subject"
set-disposition M1  "root:orch-011 external/e2e-summary-orch-011.json; handoff also requires a live summary" --reason "attached"
set-disposition M2  "root:orch-011 external/ carries pi-nofork-v3.sb and guardian-v2.py" --reason "attached"
set-disposition M3  "root:orch-011 external/review-004-receipt.* (fable smoke, real config, strict profile)" --reason "attached"
set-disposition R005-F8 "deferred:inventory() skips directories, so an empty directory added by a worker is invisible; low, no card this round" --reason "key lost to the F-id collision of plan-014; re-recorded"
```
    (`retire-card … --superseded-by C9` redirects `F1: card:C7` → `card:C9`; `add-card C12` with `replaces: C8` redirects
    `F3: card:C8` → `card:C12`.) `L status` must now show PENDING: C1, C9, C10, C11, C12; SUPERSEDED: C2–C8.
4.3 **Per-card loop** (Tier 1 order C1 → C9 → C10 → C11 → C12; each `depends_on` the previous):
    a. `R` pre-checks (read-only): `private-pi/` empty; lock absent; `python3 -B orch/loop.py status` avail ≥ `card_need`
       (§5 D4: timeout+30+e2e+300+180); token lifetime ≥ 600 s — decode `~/.codex/auth.json` exp WITHOUT printing it:
       `python3 -I -c "import json,base64,time;t=json.load(open('$HOME/.codex/auth.json'))['tokens']['access_token'].split('.')[1];print(int(json.loads(base64.urlsafe_b64decode(t+'='*(-len(t)%4)))['exp']-time.time()))"`
       (prints seconds remaining only).
    b. **G** `L run-card <ID>` ⇒ `E2E_PASS … tree_hash=…` (slot consumed). Failure paths: `ATTEMPT_FAILED` (retry allowed
       while attempts<3 AND the slot rule in §9 holds), `BLOCKED_CLEANUP_UNCERTAIN` (exit 71: STOP; inspect; `clear-lock`
       only after manual verification; `retire-card`), `WORKER_FAILURE_STREAK` (two clean worker failures in a row: inspect
       `guardian/stdout` for a provider error before `--acknowledge-streak`).
    c. **G** `L review --card <ID> --backend fable` (≤600 s) ⇒ `REVIEW_ACCEPTED card:<ID>` (parent advances to the card tree)
       or `REVIEW_NOT_ACCEPTED findings=[…]` ⇒ `L replan …` ⇒ new card(s) replacing `<ID>` (planner must `replaces`), then
       continue with the replacement. Malformed/provider-error reviews change no state; re-run once, then stop rule.
    d. `L status`; update the round report (`ROUND-5-REPORT.md`, prose, root).
4.4 **Tier gate** after C12 is ACCEPTED: compute remaining slots and `ceiling − active`. Add Tier 2 (C13–C16) with
    `add-card` + `set-disposition F5 card:C13`, `F6 card:C14`, `F7 card:C15`, `F8 card:C16` only if slots ≥ 4+1 and
    time ≥ 4×1860 s (worst) — else record `deferred:` reasons and go to P5. Same for Tier 3 (C17, C18; `F4 card:C17`,
    `F9 card:C18`) with slots ≥ 2+1 and time ≥ 2×1860 s.

### P5 — Promote, re-freeze, final reviews
5.1 `R` copy from the last ACCEPTED tree (`state.parent_dir`) into the live tree, byte-exact, ledgered via manifest note:
    `loop.py` → `orch/loop.py`; `e2e/run_e2e.py`, `e2e/fake_engine.py`, `e2e/fake_guardian.py` → `e2e/`. Nothing else.
5.2 `R` `python3 -B e2e/run_e2e.py` ⇒ `TOTAL (65 + accepted cards' scenarios) FAILED 0`; copy summary into
    `orch/external/e2e-summary-orch-012.json`; freeze `frozen/orch-012` + manifest; `L rebind-orch`.
5.3 **G** `L review --subject <abs>/frozen/orch-012 --name orch-012 --backend fable` (≤600 s) ⇒ accepted or findings
    (findings ⇒ replan ⇒ P4 loop again if budget allows, else stop).
5.4 **G** `L review --backend fable` (scope `final`; requires every card ACCEPTED/SUPERSEDED; revision = parent_hash)
    ⇒ `REVIEW_ACCEPTED final` ⇒ `milestone=ACCEPTED` (+`milestone_revision` once C11 landed).
5.5 `L note-interval` for P5.

### P6 — Handoff (always executed, whatever the verdict)
6.1 `L handoff --seq 12` ⇒ prints the complete frontier review prompt (§7) and writes `HANDOFF-012.txt`,
    `RESULT-012.json`. It refuses (and the round reports the refusal verbatim) when: a card is non-terminal, the
    orchestration source changed since `rebind-orch`, no accepted source review of the snapshot in force, no live
    `evidence-e2e-orch/summary.json` bound to the live source hashes or with failures, an unfilled `{{placeholder}}`,
    inline size > 1 MiB, or outputs for `--seq 12` already exist.
6.2 If 6.1 refuses, `R` writes `HANDOFF-012.md` (prose, like HANDOFF-011.md) stating the exact refusal line, and the
    §7 template filled by hand from `state.json`/ledger — never claiming more than the state proves.
6.3 `R` hygiene record: `private-pi/` empty, `~/.codex/auth.json` mtime unchanged, lock free, no uncertain jobs,
    original source / continuation-008 / continuation-010 untouched.

---------------------------------------------------------------------------------------------------
## 5. orch-011 — root-authored deltas (exact; baseline = `frozen/orch-010` sources inlined verbatim in Appendix A)

Apply to `orch/loop.py` unless stated. "LOCATE" text is copied from the baseline and occurs exactly once. New code is
complete; do not improvise. After all deltas: `python3 -B e2e/run_e2e.py` ⇒ `TOTAL 65 FAILED 0`.

### D1 — ceiling in state + `allocate-time` (Decision 1)
LOCATE `TERMINAL = {'ACCEPTED', 'SUPERSEDED', 'NEEDS_REPLAN', 'BLOCKED_CLEANUP_UNCERTAIN'}` — INSERT after it:
````python


def ceiling(st):
    """Active-time ceiling in force: LIMITS default unless an operator allocation (allocate-time) raised it."""
    return float(st.get('time_ceiling', LIMITS['time_ceiling']))
````
REPLACE every `LIMITS['time_ceiling']` outside the `LIMITS` dict and `ceiling()` itself with `ceiling(st)` — five sites:
`time_gate` (`avail = ceiling(st) - st['active_seconds']`), `cmd_note_interval` print, `build_packet` ACCOUNTING line,
`cmd_replan` BUDGET line, `cmd_handoff` (rewritten in D6).
INSERT after `cmd_note_interval`:
````python


def cmd_allocate_time(a):
    """Operator-recorded raise of the active-time ceiling. Only ever raises; never silent; ledgered with the approval text."""
    if not (a.approval or '').strip():
        sys.exit('ALLOCATION_NEEDS_APPROVAL (who/when/words)')
    with Lock():
        st = load_state()
        cur = ceiling(st)
        if not (cur < a.ceiling <= cur + 86400):
            sys.exit('ALLOCATION_INVALID: ceiling must be > %.1f and at most %.1f (one step <= 86400 s)' % (cur, cur + 86400))
        st['time_ceiling'] = float(a.ceiling)
        st.setdefault('allocations', []).append({'old': cur, 'new': float(a.ceiling), 'approval': a.approval,
                                                 'active_at_allocation': st['active_seconds'], 'wall': time.time()})
        save_state(st)
        append_ledger({'event': 'allocate_time', 'old': cur, 'new': float(a.ceiling), 'approval': a.approval})
        print('ALLOCATED ceiling=%.1f active=%.3f remaining=%.3f' % (a.ceiling, st['active_seconds'],
                                                                     a.ceiling - st['active_seconds']))
````
`main()`: add `p = sub.add_parser('allocate-time'); p.add_argument('--ceiling', type=float, required=True);
p.add_argument('--approval', required=True); p.set_defaults(f=cmd_allocate_time)`.

### D2 — scenario-id registry: claimed ids shown AND enforced (O55/O56 defect)
INSERT after `check_acyclic`:
````python


ID_RE = re.compile(r'\bO\d+[a-z]?(?:_O\d+[a-z]?)*\b')     # O55, O03a, O20_O21


def ids_of(text):
    """Scenario ids mentioned in text; a joined name like O20_O21 claims both parts."""
    return {part for m in ID_RE.findall(text) for part in m.split('_')}


def suite_e2e_ids(parent_dir):
    """Ids already defined by the parent tree's suite (def names, split on '_')."""
    p = pathlib.Path(parent_dir) / 'e2e' / 'run_e2e.py'
    out = set()
    try:
        names = re.findall(r'^def (O[0-9A-Za-z_]+)\s*\(', p.read_text(), re.M) if p.is_file() else []
    except OSError:
        names = []
    for n in names:
        out.add(n)
        out.update(ids_of(n))
    return out


def claimed_e2e_ids(st, cards):
    """Ids referenced by e2e.argv of every card that is not retired/superseded -> {id: [card ids]}."""
    out = {}
    for cid, c in cards.items():
        if st['cards'].get(cid, {}).get('status') in ('SUPERSEDED', 'NEEDS_REPLAN'):
            continue
        for i in sorted(ids_of(' '.join(c['e2e']['argv']))):
            out.setdefault(i, []).append(cid)
    return out


def e2e_id_collisions(c, suite_ids, claimed):
    mine = ids_of(' '.join(c['e2e']['argv']))
    return sorted(i for i in mine if i in suite_ids or (i in claimed and claimed[i] != [c['id']]))
````
In `cmd_init`, LOCATE `    cards = load_cards()` (inside cmd_init) — INSERT after it:
````python
    claimed = claimed_e2e_ids(st, cards)
    dup = {i: v for i, v in claimed.items() if len(v) > 1}
    taken = sorted(i for i in claimed if i in suite_e2e_ids(parent))
    if dup or taken:
        sys.exit('CARD_E2E_ID_COLLISION claimed_twice=%s already_in_suite=%s' % (dup, taken))
````
In `cmd_replan`: REPLACE the block from `        e2e_src = pathlib.Path(st['parent_dir']) / 'e2e' / 'run_e2e.py'` through
`            e2e_ids = []` (5 lines) with:
````python
        suite = suite_e2e_ids(st['parent_dir'])
        e2e_ids = sorted(suite)
        claimed = claimed_e2e_ids(st, existing)
````
REPLACE the two prompt lines
`            'Any e2e scenario id a new card references (in e2e.argv or acceptance rows) must NOT be in '` /
`            'EXISTING_E2E_IDS; pick fresh ids larger than every listed id.',` with:
````python
            'CLAIMED_E2E_IDS: ' + ','.join('%s=%s' % (i, '+'.join(v)) for i, v in sorted(claimed.items())),
            'Any e2e scenario id a new card references (in e2e.argv or acceptance rows) must be in NEITHER '
            'EXISTING_E2E_IDS NOR CLAIMED_E2E_IDS (ids pending cards already own); pick fresh ids larger than every '
            'listed id. A card that replaces a retired card may NOT reuse the retired card\'s id either.',
````
LOCATE (in cmd_replan) `            new[c['id']] = c` — INSERT before it:
````python
            coll = e2e_id_collisions(c, suite, claimed)
            if coll:
                save_state(st)
                sys.exit('PLAN_E2E_ID_COLLISION %s claims %s' % (c['id'], coll))
            for i in ids_of(' '.join(c['e2e']['argv'])):
                claimed.setdefault(i, []).append(c['id'])
````

### D3 — root card management: `add-card`, `set-disposition`, `retire-card --superseded-by`
REPLACE the whole `cmd_retire_card` with:
````python
def redirect_dispositions(st, old, new):
    for k, v in list(st.get('dispositions', {}).items()):
        if v == 'card:' + old:
            st['dispositions'][k] = 'card:' + new
            append_ledger({'event': 'disposition_redirect', 'finding': k, 'old': v, 'new': 'card:' + new})


def cmd_retire_card(a):
    """Root-authored retirement: -> NEEDS_REPLAN (a replan must replace it) or, with --superseded-by, -> SUPERSEDED by an
    existing live card (dispositions card:<retired> follow)."""
    if not a.reason or not a.reason.strip():
        sys.exit('RETIRE_NEEDS_REASON')
    with Lock():
        st = load_state()
        cs = st['cards'].get(a.id)
        if not cs:
            sys.exit('UNKNOWN_CARD')
        if cs['status'] not in ('PENDING', 'FAILED', 'BLOCKED_CLEANUP_UNCERTAIN'):
            sys.exit('RETIRE_BLOCKED status=' + cs['status'])
        cs['retired_reason'] = a.reason
        if a.superseded_by:
            ts = st['cards'].get(a.superseded_by)
            if a.superseded_by == a.id or not ts or ts['status'] in ('SUPERSEDED', 'NEEDS_REPLAN', 'BLOCKED_CLEANUP_UNCERTAIN'):
                sys.exit('RETIRE_SUPERSEDER_INVALID ' + str(a.superseded_by))
            cs['status'] = 'SUPERSEDED'
            cs['superseded_by'] = [a.superseded_by]
            redirect_dispositions(st, a.id, a.superseded_by)
        else:
            cs['status'] = 'NEEDS_REPLAN'
        save_state(st)
        append_ledger({'event': 'retire_card', 'card': a.id, 'reason': a.reason, 'superseded_by': a.superseded_by})
        print('CARD_RETIRED %s -> %s' % (a.id, cs['status'] + (' by ' + a.superseded_by if a.superseded_by else
                                                                ' (replan must replace it)')))


def cmd_add_card(a):
    """Root-authored card from a frontier plan file: validated exactly like a planner card, collision-checked, ledgered."""
    if not a.reason.strip() or not a.approval.strip():
        sys.exit('ADD_CARD_NEEDS_REASON_AND_APPROVAL')
    with Lock():
        st = load_state()
        existing = load_cards()
        p = pathlib.Path(a.file)
        if not p.is_file() or p.is_symlink():
            sys.exit('ADD_CARD_FILE_INVALID')
        c = read_bounded_json(p, 256 * 1024)
        err = validate_card(c)
        if err:
            sys.exit('CARD_INVALID: ' + err)
        if c['id'] in existing or c['id'] in st['cards']:
            sys.exit('CARD_DUPLICATE ' + c['id'])
        allc = dict(existing)
        allc[c['id']] = c
        for d in c['depends_on'] + ([c['base']] if c.get('base') else []):
            if d not in allc:
                sys.exit('CARD_UNKNOWN_DEP ' + d)
        if not check_acyclic(allc):
            sys.exit('CARD_CYCLE')
        coll = e2e_id_collisions(c, suite_e2e_ids(st['parent_dir']), claimed_e2e_ids(st, existing))
        if coll:
            sys.exit('CARD_E2E_ID_COLLISION %s' % coll)
        rep = c.get('replaces')
        if rep:
            rs = st['cards'].get(rep)
            if not rs or rs['status'] != 'NEEDS_REPLAN':
                sys.exit('ADD_CARD_REPLACES_INVALID %s (subject must be a retired NEEDS_REPLAN card)' % rep)
        dest = ROOT / 'cards' / (c['id'] + '.json')
        jwrite(dest, c)
        st['cards'][c['id']] = {'status': 'PENDING', 'attempts': 0, 'root_added': True}
        if rep:
            st['cards'][rep].update(status='SUPERSEDED', superseded_by=[c['id']])
            redirect_dispositions(st, rep, c['id'])
        append_ledger({'event': 'add_card', 'card': c['id'], 'sha': sha(dest), 'reason': a.reason, 'approval': a.approval,
                       'replaces': rep})
        save_state(st)
        print('CARD_ADDED %s' % c['id'])


def cmd_set_disposition(a):
    """Root-authored disposition. Only an absent or deferred: entry may change; values card:<live id> | root:<why> |
    deferred:<why> (deferred only for an absent key). Ledgered with the reason."""
    if not a.reason.strip():
        sys.exit('SET_DISPOSITION_NEEDS_REASON')
    with Lock():
        st = load_state()
        cur = st.get('dispositions', {}).get(a.key)
        if cur is not None and not cur.startswith('deferred:'):
            sys.exit('DISPOSITION_LOCKED %s=%s (only absent or deferred: values may be changed)' % (a.key, cur))
        if not re.fullmatch(r'(card:[A-Za-z0-9_-]+|root:.+|deferred:.+)', a.value, re.S) \
                or (a.value.startswith('deferred:') and cur is not None):
            sys.exit('DISPOSITION_VALUE_INVALID (card:<id> | root:<why> | deferred:<why> for a new key)')
        if a.value.startswith('card:'):
            cs = st['cards'].get(a.value[5:])
            if not cs or cs['status'] in ('SUPERSEDED', 'NEEDS_REPLAN', 'BLOCKED_CLEANUP_UNCERTAIN'):
                sys.exit('DISPOSITION_UNKNOWN_CARD ' + a.value)
        st.setdefault('dispositions', {})[a.key] = a.value
        save_state(st)
        append_ledger({'event': 'set_disposition', 'finding': a.key, 'old': cur, 'new': a.value, 'reason': a.reason})
        print('DISPOSITION_SET %s %s -> %s' % (a.key, cur, a.value))
````
`main()`: `retire-card` gains `p.add_argument('--superseded-by')`; add
`p = sub.add_parser('add-card'); p.add_argument('file'); p.add_argument('--reason', required=True); p.add_argument('--approval', required=True); p.set_defaults(f=cmd_add_card)` and
`p = sub.add_parser('set-disposition'); p.add_argument('key'); p.add_argument('value'); p.add_argument('--reason', required=True); p.set_defaults(f=cmd_set_disposition)`.

### D4 + D10 + D13 + D15 — gates, suite step, guardian clean-failure, binding checks (`LIMITS`, `guardian_bindings`, `cmd_run_card`)
REPLACE the `LIMITS = {...}` dict with:
````python
LIMITS = {'cap_launches': 48, 'time_ceiling': 32400.0, 'reserve': 180.0,
          'review_need': 780.0, 'job_timeout': 600, 'review_timeout': 600, 'cap_bytes': 2 * 1024 * 1024,
          'max_attempts': 3, 'packet_cap': 400 * 1024, 'inputs_cap': 200 * 1024, 'receipt_cap': 16384,
          'smoke_timeout': 120, 'e2e_timeout': 120, 'e2e_cap': 200, 'suite_timeout': 300,
          'max_worker_streak': 2, 'handoff_cap': 1 << 20}
# review_timeout 300->600 and review_need 480->780: PLAN 013 Decision 2 (review-012 ran 299.8/300 s on a 119 KB packet).
````
REPLACE the whole `guardian_bindings` with:
````python
def guardian_bindings(env):
    """Validate EVERY binding the guardian spec will carry (absolute, existing, non-symlink) before a slot is consumed."""
    for key, kind in (('PI_GUARDIAN', 'file'), ('PI_RUNTIME', 'dir'), ('BOOT_PYTHON', 'exe'), ('PI_BIN', 'exe'),
                      ('SANDBOX_EXEC', 'exe'), ('PI_PROFILE', 'file')):
        p = pathlib.Path(env.get(key) or '')
        if not str(p).startswith('/') or p.is_symlink() or not p.exists():
            sys.exit('%s_INVALID (absolute existing non-symlink %s required)' % (key, kind))
        if (kind == 'file' and not p.is_file()) or (kind == 'dir' and not p.is_dir()) \
                or (kind == 'exe' and not (p.is_file() and os.access(p, os.X_OK))):
            sys.exit('%s_INVALID' % key)
````
INSERT before `def cmd_run_card(a):`:
````python
def card_need(c):
    """Worst-case active seconds one run-card may consume: coding (+30 s guardian grace) + card e2e + full suite + reserve."""
    e2e_t = min(int(c['e2e'].get('timeout', LIMITS['e2e_timeout'])), LIMITS['e2e_cap'])
    return min(c['timeout'], LIMITS['job_timeout']) + 30 + e2e_t + LIMITS['suite_timeout'] + LIMITS['reserve']


````
REPLACE the whole `cmd_run_card` with:
````python
def cmd_run_card(a):
    env = load_env()
    with Lock() as L:
        st = load_state()
        cards = load_cards()
        if a.id not in cards:
            sys.exit('UNKNOWN_CARD')
        c = cards[a.id]
        cs = st['cards'].setdefault(a.id, {'status': 'PENDING', 'attempts': 0})
        if cs['status'] not in ('PENDING', 'FAILED'):
            sys.exit('CARD_NOT_RUNNABLE status=' + cs['status'])
        if cs['attempts'] >= LIMITS['max_attempts']:
            sys.exit('ATTEMPTS_EXHAUSTED: replan required')
        for d in c['depends_on']:
            if not dep_satisfied(st, d):
                sys.exit('DEPENDENCY_NOT_ACCEPTED ' + d)
        if st.get('worker_failure_streak', 0) >= LIMITS['max_worker_streak']:
            if not (a.acknowledge_streak or '').strip():
                sys.exit('WORKER_FAILURE_STREAK %d: inspect the last guardian/stdout and receipts for a provider outage; '
                         'pass --acknowledge-streak "<what you checked>" to continue' % st['worker_failure_streak'])
            append_ledger({'event': 'streak_acknowledged', 'streak': st['worker_failure_streak'], 'note': a.acknowledge_streak})
            st['worker_failure_streak'] = 0
            save_state(st)
        if env.get('PI_GUARDIAN'):
            guardian_bindings(env)
        base_id = c.get('base')
        if base_id:
            bs = st['cards'].get(base_id, {})
            if not bs.get('tree'):
                sys.exit('BASE_TREE_MISSING ' + base_id)
            base_dir, base_hash = bs['tree'], bs['tree_hash']
        else:
            base_dir, base_hash = st['parent_dir'], st['parent_hash']
        parent_inv = inventory(base_dir)
        if inv_hash(parent_inv) != base_hash:
            sys.exit('PARENT_HASH_MISMATCH')
        if not check_auth_clean(env):
            uncertain_stop(L, st)
        slot_gate(st)
        time_gate(st, card_need(c))
        attempt = cs['attempts'] + 1
        reserve_slot(st, a.id, attempt)
        cs['attempts'] = attempt
        cs['status'] = 'RESERVED'
        save_state(st)
        job_timeout = min(c['timeout'], LIMITS['job_timeout'])
        ev = ROOT / 'evidence' / a.id / str(attempt)
        if env.get('PI_GUARDIAN'):
            # Real-credential route: the job tree MUST live under PI_RUNTIME (the pi profile denies reads/writes
            # elsewhere under /Users/psac); the worker runs via the guardian with auth_source=real.
            job = pathlib.Path(env['PI_RUNTIME']) / 'jobs' / ('%s-%d' % (a.id, attempt))
            if job.exists():
                fail_attempt(st, a.id, 'JOB_DIR_EXISTS ' + str(job))
            job.mkdir(parents=True, mode=0o700)
            tree = job / 'tree'
            shutil.copytree(base_dir, tree)
            prompt = job / 'prompt.txt'
            prompt.write_text(assemble_prompt(dict(c), dict(st, parent_hash=base_hash), base_dir))
            append_ledger({'event': 'prompt', 'card': a.id, 'attempt': attempt, 'sha': sha(prompt)})
            spec = coding_spec(env, tree, prompt, job / 'guardian', job_timeout)
            jwrite(job / 'spec.json', spec)
            append_ledger({'event': 'guardian_spec', 'card': a.id, 'attempt': attempt, 'sha': sha(job / 'spec.json'),
                           'output': str(job / 'guardian')})
            rec, _ = launch(L, st, '%s/%d/code' % (a.id, attempt),
                            [env['BOOT_PYTHON'], '-B', env['PI_GUARDIAN'], str(job / 'spec.json')],
                            job_timeout + 30, 1 << 20, str(job), stdin_pipe=True)
            if rec is None:
                uncertain_stop(L, st, a.id)
            if rec['status'] != 'ok' or not rec.get('reaped'):
                uncertain_stop(L, st, a.id)
            gp = job / 'guardian' / 'receipt.json'
            g = None
            if gp.is_file() and not gp.is_symlink():
                try:
                    g = read_bounded_json(gp, LIMITS['receipt_cap'])
                except SystemExit:
                    g = None
            append_ledger({'event': 'guardian_receipt', 'card': a.id, 'attempt': attempt,
                           'status': None if g is None else g.get('status'),
                           'worker_reaped': None if g is None else g.get('worker_reaped'),
                           'exit_code': None if g is None else g.get('exit_code'),
                           'credential_removed': None if g is None else g.get('credential_removed'),
                           'reason': None if g is None else g.get('reason')})
            if g is None or g.get('status') != 'TERMINATED' or g.get('worker_reaped') is not True \
                    or g.get('credential_removed') is not True:
                uncertain_stop(L, st, a.id)      # cleanup unverified: never interpret a missing/bad receipt as "zero children"
            gout = job / 'guardian' / 'stdout'
            out = gout.read_bytes()[:LIMITS['cap_bytes']].decode('utf-8', 'replace') if gout.is_file() else ''
            if g.get('exit_code') != 0:          # cleanup verified, worker failed: an attempt failure, not uncertainty
                st['worker_failure_streak'] = st.get('worker_failure_streak', 0) + 1
                perr = provider_error(out)
                if perr:
                    append_ledger({'event': 'provider_failed', 'label': '%s/%d/code' % (a.id, attempt), 'message': perr[:300]})
                fail_attempt(st, a.id, 'worker-exit-%s%s' % (g.get('exit_code'), (': ' + perr[:120]) if perr else ''))
        else:
            job = ROOT / 'jobs' / ('%s-%d' % (a.id, attempt))
            if job.exists():
                fail_attempt(st, a.id, 'JOB_DIR_EXISTS ' + str(job))
            job.mkdir(parents=True, mode=0o700)
            tree = job / 'tree'
            shutil.copytree(base_dir, tree)
            prompt = job / 'prompt.txt'
            prompt.write_text(assemble_prompt(dict(c), dict(st, parent_hash=base_hash), base_dir))
            append_ledger({'event': 'prompt', 'card': a.id, 'attempt': attempt, 'sha': sha(prompt)})
            rec, out = launch(L, st, '%s/%d/code' % (a.id, attempt),
                              ['/bin/bash', str(ROOT / 'worker-pi.sh'), 'code', str(tree), str(prompt), env['PI_PROFILE']],
                              job_timeout, LIMITS['cap_bytes'], str(tree))
            if rec is None:
                uncertain_stop(L, st, a.id)
            if rec['status'] == 'uncertain':
                uncertain_stop(L, st, a.id)
            if rec['status'] != 'ok':
                fail_attempt(st, a.id, 'worker-' + rec['status'])
        st['worker_failure_streak'] = 0
        if ('CARD_BLOCKED %s' % a.id) in out:
            fail_attempt(st, a.id, 'worker reported CARD_BLOCKED')
        if ('CARD_DONE %s' % a.id) not in out:
            fail_attempt(st, a.id, 'missing CARD_DONE')
        if not check_auth_clean(env):
            uncertain_stop(L, st, a.id)
        try:
            new_inv = inventory(tree)
        except SystemExit as e:
            fail_attempt(st, a.id, str(e))
        ok, probs = scope_verify(parent_inv, new_inv, set(c['allowed_paths']))
        if not ok:
            fail_attempt(st, a.id, 'scope: ' + '; '.join(probs))
        if inv_hash(new_inv) == inv_hash(parent_inv):
            fail_attempt(st, a.id, 'no change produced')
        manifest = {'card': a.id, 'attempt': attempt, 'parent_hash': base_hash, 'inventory': new_inv,
                    'tree_hash': inv_hash(new_inv)}
        jwrite(job / 'result-manifest.json', manifest)
        e = c['e2e']
        t = min(int(e.get('timeout', LIMITS['e2e_timeout'])), LIMITS['e2e_cap'])
        rec2, _ = launch(L, st, '%s/%d/e2e' % (a.id, attempt), list(e['argv']), t, 1 << 20, str(tree),
                         {'E2E_SUMMARY_DIR': str(ev / 'e2e-summary')})
        if rec2 is None or rec2['status'] == 'uncertain':
            uncertain_stop(L, st, a.id)
        if not rec2['reaped'] or rec2.get('exit') != e['expect_status'] or rec2['status'] in ('timeout', 'overflow'):
            fail_attempt(st, a.id, 'e2e status %s/%s' % (rec2['status'], rec2.get('exit')))
        for f in e.get('expect_files', []):
            if not (tree / f).is_file():
                fail_attempt(st, a.id, 'e2e missing file ' + f)
        suite = tree / 'e2e' / 'run_e2e.py'
        if suite.is_file() and not suite.is_symlink():   # the tree carries its own E2E suite: the WHOLE suite must stay green
            rec3, _ = launch(L, st, '%s/%d/suite' % (a.id, attempt), [env['BOOT_PYTHON'], '-B', 'e2e/run_e2e.py'],
                             LIMITS['suite_timeout'], 1 << 20, str(tree), {'E2E_SUMMARY_DIR': str(ev / 'suite-summary')})
            if rec3 is None or rec3['status'] == 'uncertain':
                uncertain_stop(L, st, a.id)
            if not rec3['reaped'] or rec3.get('exit') != 0 or rec3['status'] != 'ok':
                fail_attempt(st, a.id, 'suite status %s/%s' % (rec3['status'], rec3.get('exit')))
            try:
                post = inv_hash(inventory(tree))
            except SystemExit as e2:
                fail_attempt(st, a.id, str(e2))
            if post != manifest['tree_hash']:
                fail_attempt(st, a.id, 'SUITE_TREE_MUTATED')
        cs.update(status='E2E_PASS', tree=str(tree), tree_hash=manifest['tree_hash'])
        save_state(st)
        print('E2E_PASS %s attempt=%d tree_hash=%s' % (a.id, attempt, manifest['tree_hash']))
````
`main()`: `run-card` gains `p.add_argument('--acknowledge-streak')`.
Notes: `code_need` is gone (the gate is per card via `card_need`); the e2e step passes `E2E_SUMMARY_DIR` outside the tree so
`run_e2e.py` (D8) never writes into the job tree; the suite step is skipped for trees without `e2e/run_e2e.py` (E2E Box
parents) and mandatory for the orchestration tree every card edits.

### D5 — `external/` attachments are part of the orchestration source hash
In `orch_source_inventory`, LOCATE `    return sorted(rows)` — INSERT before it:
````python
    ext = ROOT / 'external'
    if ext.is_dir() and not ext.is_symlink():
        for p in sorted(ext.iterdir()):
            if p.is_symlink():
                raise SystemExit('SYMLINK_IN_TREE ' + str(p))
            if p.is_file():
                rows.append(['external/' + p.name, oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
````
Update the docstring's file list accordingly (`external/*` = byte copies of out-of-tree review material).

### D7 — F10: no baked accounting defaults
`main()`: REPLACE `p.add_argument('--active-seconds', type=float, default=24923.746)` with
`p.add_argument('--active-seconds', type=float, required=True)` and `p.add_argument('--launches-used', type=int, default=36)`
with `p.add_argument('--launches-used', type=int, required=True)`. In `cmd_init`, REPLACE
`    for k in ('PI_BIN', 'SANDBOX_EXEC', 'PI_PROFILE', 'REVIEW_PROFILE'):` with
`    for k in ('PI_BIN', 'SANDBOX_EXEC', 'PI_PROFILE', 'REVIEW_PROFILE', 'BOOT_PYTHON'):`.

### D14 — `clear-lock` (ledgered manual recovery; no automatic salvage)
INSERT after `cmd_read_receipt`:
````python


def cmd_clear_lock(a):
    """Root-authored release of a lock retained by an uncertainty stop, AFTER manual inspection. Refuses while the
    locking process is alive or a credential is still present. Cards stay BLOCKED_CLEANUP_UNCERTAIN until retired."""
    if not a.reason.strip():
        sys.exit('CLEAR_LOCK_NEEDS_REASON')
    env = load_env()
    lp = ROOT / 'lock'
    if not lp.exists():
        sys.exit('LOCK_NOT_HELD')
    if not check_auth_clean(env):
        sys.exit('CLEAR_LOCK_BLOCKED credential residue in AUTH_DIR; remove it by hand and record why')
    pid = lp.read_text().strip()
    try:
        os.kill(int(pid), 0)
        sys.exit('CLEAR_LOCK_BLOCKED process %s still alive' % pid)
    except (ProcessLookupError, ValueError):
        pass
    except PermissionError:
        sys.exit('CLEAR_LOCK_BLOCKED process %s exists (permission denied)' % pid)
    append_ledger({'event': 'clear_lock', 'reason': a.reason, 'lock_pid': pid})
    os.unlink(lp)
    print('LOCK_CLEARED (was pid %s); uncertain cards stay BLOCKED_CLEANUP_UNCERTAIN until retire-card' % pid)
````
`main()`: `p = sub.add_parser('clear-lock'); p.add_argument('--reason', required=True); p.set_defaults(f=cmd_clear_lock)`.

### D6 — handoff prints the COMPLETE frontier review prompt (sources, ledger, E2E results, preservation), refuses when unproven
REPLACE `REVIEW_TEMPLATE` and the whole `cmd_handoff` with:
````python
REVIEW_TEMPLATE = """You are the independent final reviewer of the continuation-011 orchestration layer and its card program ONLY.
You may not edit, execute code, delegate, or infer runtime evidence from source closure. Read ALL inline material.
NO TOOLS: everything you need is inline below. Do not emit tool calls.
REVISION (parent tree in force): {{revision}}
ORCH_HASH (orchestration snapshot in force, source-reviewed): {{orch_hash}}
ACCOUNTING: {{accounting}}
ALLOCATIONS (operator-recorded ceiling changes): {{allocations}}
CARD STATE: {{cards}}
CARD FILES (objective, allowed paths, acceptance rows, e2e, stop condition): {{card_files}}
DISPOSITIONS (every finding ever raised -> card:/rejected:/deferred:/root:): {{dispositions}}
REVIEW HISTORY (reviews, source_reviews, smokes, same_backend_approvals, last_review): {{reviews}}
E2E-ORCH RESULTS (per scenario; bound to the live source hashes): {{e2e_summary}}
PRESERVATION / CLEANUP:
{{preservation}}
SOURCE INVENTORY (relpath mode size sha256):
{{inventory}}
SOURCE CONTENTS (the parent tree in force, every file inline):
{{sources}}
LEDGER (append-only: every reservation, launch, interval, review, replan, allocation, retirement, disposition):
{{ledger}}
TASK: check correctness, regressions, provenance, process ownership, finite-failure contract, credential lifecycle,
every card's acceptance rows against its tree, every finding's disposition, scenario-id uniqueness, and the accounting
(no cap raised without a ledgered allocation/approval). Zero findings with missing evidence is NOT acceptance.
Return exactly ONE fenced json block with keys revision, findings[{id,severity,location,evidence}], missing_evidence[],
coverage{complete,truncated}, cleanup, verdict (ACCEPTED|INCOMPLETE|BLOCKED). ACCEPTED requires zero findings and zero
missing evidence. Output outside the block is ignored.
"""


def e2e_summary_check():
    """The live suite summary must exist, be all-pass and be bound to the live orchestration sources (run_e2e.py D8)."""
    p = ROOT.parent / 'evidence-e2e-orch' / 'summary.json'
    if not p.is_file() or p.is_symlink():
        sys.exit('HANDOFF_BLOCKED no e2e summary at %s (run e2e/run_e2e.py)' % p)
    s = read_bounded_json(p, 1 << 20)
    if not isinstance(s, dict) or not isinstance(s.get('results'), list) or not isinstance(s.get('sources'), dict):
        sys.exit('HANDOFF_BLOCKED e2e summary malformed (re-run e2e/run_e2e.py on the live source)')
    failed = [r.get('id') for r in s['results'] if not r.get('pass')]
    if not s['results'] or failed:
        sys.exit('HANDOFF_BLOCKED e2e summary has failures %s' % failed)
    live = {r[0]: r[3] for r in orch_source_inventory() if r[0].endswith(('.py', '.sh'))}
    stale = sorted(n for n, h in live.items() if s['sources'].get(n) != h)
    if stale:
        sys.exit('HANDOFF_BLOCKED e2e summary stale for %s (re-run the suite on the live source)' % stale)
    return s


def preservation_report(env, st):
    rows = []
    d = env.get('AUTH_DIR')
    if d:
        p = pathlib.Path(d)
        rows.append('AUTH_DIR %s entries=%s' % (d, sorted(x.name for x in p.iterdir()) if p.is_dir() else 'MISSING'))
    else:
        rows.append('AUTH_DIR unset')
    rt = env.get('PI_RUNTIME')
    jobs = pathlib.Path(rt) / 'jobs' if rt else None
    if jobs and jobs.is_dir():
        for j in sorted(jobs.iterdir()):
            r = j / 'guardian' / 'receipt.json'
            if r.is_file() and not r.is_symlink():
                try:
                    g = read_bounded_json(r, LIMITS['receipt_cap'])
                    rows.append('JOB %s status=%s worker_reaped=%s credential_removed=%s exit=%s reason=%s' % (
                        j.name, g.get('status'), g.get('worker_reaped'), g.get('credential_removed'), g.get('exit_code'),
                        g.get('reason')))
                except SystemExit:
                    rows.append('JOB %s receipt INVALID' % j.name)
            else:
                rows.append('JOB %s receipt MISSING' % j.name)
    rows.append('UNCERTAIN_CARDS %s' % sorted(k for k, v in st['cards'].items() if v['status'] == 'BLOCKED_CLEANUP_UNCERTAIN'))
    rows.append('WORKER_FAILURE_STREAK %s' % st.get('worker_failure_streak', 0))
    rows.append('LOCK held by this handoff process only (pid %d)' % os.getpid())
    rows.append('ORCH_HASH live=%s state=%s' % (inv_hash(orch_source_inventory()), st['orch_hash']))
    return '\n'.join(rows)


def inline_tree(tree, cap):
    inv = inventory(tree)
    lines, total = [], 0
    for r in inv:
        data = (pathlib.Path(tree) / r[0]).read_bytes()
        total += len(data)
        if total > cap:
            sys.exit('HANDOFF_TOO_LARGE: parent tree exceeds %d bytes inline; slim the subject' % cap)
        lines.append('--- FILE %s ---\n%s\n--- END FILE ---' % (r[0], data.decode('utf-8', 'replace')))
    return inv, '\n'.join(lines)


def cmd_handoff(a):
    env = load_env()
    with Lock():
        st = load_state()
        hp = ROOT.parent / ('HANDOFF-%03d.txt' % a.seq)
        rp = ROOT.parent / ('RESULT-%03d.json' % a.seq)
        if hp.exists() or rp.exists():
            sys.exit('HANDOFF_OUTPUT_EXISTS %s / %s (pass a fresh --seq)' % (hp.name, rp.name))
        open_cards = [k for k, v in st['cards'].items() if v['status'] not in TERMINAL]
        if open_cards:
            sys.exit('HANDOFF_BLOCKED non-terminal cards: %s' % open_cards)
        live = inv_hash(orch_source_inventory())
        if live != st['orch_hash']:
            sys.exit('HANDOFF_BLOCKED orchestration source changed since init (%s != %s)' % (live[:12], st['orch_hash'][:12]))
        if st['orch_hash'] not in st['source_reviews'].values():
            sys.exit('HANDOFF_BLOCKED no accepted source review of the orchestration snapshot %s' % st['orch_hash'][:12])
        summary = e2e_summary_check()
        inv, sources = inline_tree(st['parent_dir'], LIMITS['handoff_cap'])
        card_files = {p.stem: read_bounded_json(p, 256 * 1024) for p in sorted((ROOT / 'cards').glob('*.json'))}
        ledger = (ROOT / 'ledger.jsonl').read_text() if (ROOT / 'ledger.jsonl').exists() else ''
        accounting = 'launches %d/%d, active %.1f/%.0f s, remaining %.1f s' % (
            st['launches_used'], LIMITS['cap_launches'], st['active_seconds'], ceiling(st), ceiling(st) - st['active_seconds'])
        subst = {'revision': st['parent_hash'], 'orch_hash': st['orch_hash'], 'accounting': accounting,
                 'allocations': json.dumps(st.get('allocations', []), sort_keys=True),
                 'cards': json.dumps(st['cards'], sort_keys=True), 'card_files': json.dumps(card_files, sort_keys=True),
                 'dispositions': json.dumps(st.get('dispositions', {}), sort_keys=True),
                 'reviews': json.dumps({'reviews': st['reviews'], 'source_reviews': st['source_reviews'],
                                        'smokes': st['smokes'], 'same_backend_approvals': st.get('same_backend_approvals', []),
                                        'last_review': st.get('last_review')}, sort_keys=True),
                 'e2e_summary': json.dumps(summary, sort_keys=True), 'preservation': preservation_report(env, st),
                 'inventory': '\n'.join('  %s %s %d %s' % tuple(r) for r in inv), 'sources': sources, 'ledger': ledger}
        prompt = REVIEW_TEMPLATE
        for k, v in subst.items():
            prompt = prompt.replace('{{%s}}' % k, v)
        if '{{' in prompt:
            sys.exit('HANDOFF_UNFILLED_PLACEHOLDER')
        verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED' else (
            'BLOCKED' if any(v['status'] == 'BLOCKED_CLEANUP_UNCERTAIN' for v in st['cards'].values()) else 'INCOMPLETE')
        text = '\n'.join(['HANDOFF-%03d' % a.seq, 'MILESTONE VERDICT: ' + verdict, 'REVISION: ' + st['parent_hash'],
                          'ACCOUNTING: ' + accounting, 'CARDS: ' + subst['cards'],
                          '=== FULL REVIEW PROMPT ===', prompt, '=== END ==='])
        hp.write_text(text)
        jwrite(rp, {'verdict': verdict, 'revision': st['parent_hash'], 'orch_hash': st['orch_hash'],
                    'launches_used': st['launches_used'], 'active_seconds': st['active_seconds'], 'time_ceiling': ceiling(st),
                    'handoff_sha': sha_bytes(text.encode())})
        print(text)
````
`main()`: REPLACE `sub.add_parser('handoff').set_defaults(f=cmd_handoff)` with
`p = sub.add_parser('handoff'); p.add_argument('--seq', type=int, default=11); p.set_defaults(f=cmd_handoff)`.
(C11 later adds the `milestone_revision` condition to the `verdict` line; the line `verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED'`
must stay recognisable — C11's stop condition depends on it.)

### `orch/env.sh.example` — one comment line appended (no key changes):
`# PLAN 013: CODEX_BIN must point at the Caskroom version actually installed (brew upgrades remove old versions; check before every smoke).`

### 5.2 `e2e/` deltas (root-authored; the suite runs as real subprocesses only)

**`e2e/fake_engine.py`** — pi branch: INSERT after the `elif sc == 'noop_done':` line pair:
````python
    elif sc == 'fifo':
        os.mkfifo('fifo'); edit(); print('CARD_DONE ' + cid)
````
planner branch: INSERT after `    if sc == 'toomany': c['allowed_paths'] = ['a', 'b', 'c', 'd']`:
````python
    if sc == 'claim': c['e2e']['argv'] = ['/usr/bin/true', os.environ.get('FAKE_PLAN_CLAIM', 'O99')]
````

**`e2e/fake_guardian.py`** — REPLACE `    p = subprocess.Popen(spec['argv'], cwd=spec['cwd'], env=spec['env'], stdin=subprocess.DEVNULL,` with:
````python
    wenv = dict(spec['env'])                     # knobs for the worker fake only; spec['env'] itself stays untouched (O53)
    if sc == 'worker_fail':
        wenv['FAKE_PI'] = 'fail_exit'
    if sc == 'worker_hang':
        wenv['FAKE_PI'] = 'ignore_term'
    p = subprocess.Popen(spec['argv'], cwd=spec['cwd'], env=wenv, stdin=subprocess.DEVNULL,
````
and extend the docstring knob list with `worker_fail | worker_hang`.

**`e2e/run_e2e.py`**
1. Imports: `import hashlib, json, os, pathlib, re, shutil, signal, subprocess, sys, tempfile, time, traceback`.
2. `Box.init` — REPLACE with (argparse keeps the LAST occurrence, so scenarios may still override):
````python
    def init(self, *extra):
        rc, o, e = self.loop('init', '--parent', self.parent, '--active-seconds', '24923.746', '--launches-used', '36', *extra)
        assert rc == 0, 'init failed: ' + e
        return o
````
3. `Box.loop` passthrough string becomes
   `'FAKE_ARGV_LOG,FAKE_PI,FAKE_REVIEW,FAKE_PLAN,FAKE_PLAN_BASE,FAKE_PLAN_CLAIM,FAKE_WRAP,FAKE_GUARDIAN,FAKE_GUARDIAN_AUTH_DIR'`.
4. `Box.snapshot` — INSERT before `        return d`:
````python
        if (self.orch / 'external').is_dir():
            shutil.copytree(self.orch / 'external', d / 'external')
````
5. New `Box` method:
````python
    def e2e_summary(self, ok=True):
        """The live-suite summary the handoff gate requires (D6/D8), bound to this box's orch sources."""
        src = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in self.orch.iterdir()
               if f.is_file() and f.suffix in ('.py', '.sh') and f.name != 'env.sh'}
        d = self.tmp / 'evidence-e2e-orch'
        d.mkdir(exist_ok=True)
        (d / 'summary.json').write_text(json.dumps({'results': [{'id': 'O00', 'pass': ok, 'secs': 0.1, 'error': None}],
                                                   'sources': src}))
````
6. Existing scenarios: in **O01** insert `b.e2e_summary()` before `rc, o, e = b.loop('handoff'); eq(rc, 0, e)`; in **O30**
   insert `b.e2e_summary()` before the final `rc, o, e = b.loop('handoff'); eq(rc, 0, e)`; in **O41** insert `b.e2e_summary()`
   before the `rc, o, e = b.loop('handoff'); eq(rc, 0, e)` that follows the second `b.source_review()`.
7. `main()` — REPLACE with (D8: collision-proof registry, unknown ids fatal, summary bound to sources, summary dir override):
````python
def source_hashes():
    out = {}
    for f in sorted(ORCH_SRC.iterdir()):
        if f.is_file() and f.suffix in ('.py', '.sh') and f.name != 'env.sh':
            out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    for f in sorted(HERE.glob('*.py')):
        if f.is_file():
            out['e2e/' + f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def registry_check(only):
    """Fatal: a scenario defined twice (Python would silently keep the last), registered twice, defined but not
    registered, or requested but unknown (a typo must never pass vacuously)."""
    names = [fn.__name__ for fn in SCENARIOS]
    defs = re.findall(r'^def (O[0-9A-Za-z_]+)\s*\(', pathlib.Path(__file__).read_text(), re.M)
    problems = []
    dups = sorted({n for n in names if names.count(n) > 1})
    if dups:
        problems.append('registered twice: %s' % dups)
    ddefs = sorted({n for n in defs if defs.count(n) > 1})
    if ddefs:
        problems.append('defined twice: %s' % ddefs)
    unreg = sorted(set(defs) - set(names))
    if unreg:
        problems.append('defined but not registered: %s' % unreg)
    unknown = sorted(only - set(names))
    if unknown:
        problems.append('unknown scenario ids: %s' % unknown)
    if problems:
        print('REGISTRY_INVALID ' + '; '.join(problems), flush=True)
        sys.exit(3)


def main():
    only = set(sys.argv[1:])
    registry_check(only)
    results = []
    for fn in SCENARIOS:
        if only and fn.__name__ not in only:
            continue
        b = Box(); t = time.time(); err = None
        try:
            fn(b)
        except BaseException:
            err = traceback.format_exc(limit=3)
        finally:
            b.close()
        results.append({'id': fn.__name__, 'pass': err is None, 'secs': round(time.time() - t, 1), 'error': err})
        print('%-8s %s %5.1fs' % (fn.__name__, 'PASS' if err is None else 'FAIL', time.time() - t), flush=True)
        if err:
            print(err, flush=True)
    if not results:
        print('NO_SCENARIOS_RAN', flush=True)
        sys.exit(3)
    out = pathlib.Path(os.environ.get('E2E_SUMMARY_DIR') or (HERE.parent / 'evidence-e2e-orch'))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.json').write_text(json.dumps({'results': results, 'sources': source_hashes(),
                                                  'orch_src': str(ORCH_SRC), 'wall': time.time()}, indent=1))
    failed = [r['id'] for r in results if not r['pass']]
    print('TOTAL %d FAILED %d %s' % (len(results), len(failed), failed))
    sys.exit(1 if failed else 0)
````
8. New scenarios O57–O69 (append before `SCENARIOS = [...]`; then append `O57, O58, O59, O60, O61, O62, O63, O64, O65, O66, O67, O68, O69` to the list):
````python
def O57(b):
    # allocate-time: the only way the ceiling moves; ledgered; gate honours it
    b.card('A'); b.init('--active-seconds', '31800')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); assert rc != 0; has(e, 'TIME_GATE_FAILED')
    rc, o, e = b.loop('allocate-time', '--ceiling', '40000', '--approval', ''); assert rc != 0; has(e, 'ALLOCATION_NEEDS_APPROVAL')
    rc, o, e = b.loop('allocate-time', '--ceiling', '32000', '--approval', 'op'); assert rc != 0; has(e, 'ALLOCATION_INVALID')
    rc, o, e = b.loop('allocate-time', '--ceiling', '200000', '--approval', 'op'); assert rc != 0; has(e, 'ALLOCATION_INVALID')
    assert 'time_ceiling' not in b.state()
    rc, o, e = b.loop('allocate-time', '--ceiling', '40000', '--approval', 'operator X 2026-10-24'); eq(rc, 0, e); has(o, 'ALLOCATED')
    st = b.state(); eq(st['time_ceiling'], 40000.0); eq(st['allocations'][0]['approval'], 'operator X 2026-10-24')
    assert any(r['event'] == 'allocate_time' and r['new'] == 40000.0 for r in b.ledger())
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)
    rc, o, e = b.loop('status'); has(o, '"time_ceiling": 40000.0')


def O58(b):
    # scenario-id registry: init and replan refuse ids claimed by live cards or defined in the parent's suite
    b.card('A', e2e={'argv': ['/usr/bin/true', 'O90'], 'expect_status': 0, 'expect_files': []})
    b.card('B', allowed_paths=['src/b.txt'], e2e={'argv': ['/usr/bin/true', 'O90'], 'expect_status': 0, 'expect_files': []})
    rc, o, e = b.loop('init', '--parent', b.parent, '--active-seconds', '24923.746', '--launches-used', '36')
    assert rc != 0; has(e, 'CARD_E2E_ID_COLLISION'); assert not (b.orch / 'state.json').exists()
    (b.orch / 'cards' / 'B.json').unlink()
    (b.parent / 'e2e').mkdir()
    (b.parent / 'e2e' / 'run_e2e.py').write_text('def O20_O21(b):\n    pass\n\n\ndef O03a(b):\n    pass\n')
    b.init()
    rc, o, e = b.source_review('findings'); eq(rc, 2, e)
    for claim in ('O90', 'O20', 'O21', 'O03a', 'O20_O21'):
        rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'claim', 'FAKE_PLAN_CLAIM': claim})
        assert rc != 0, claim; has(e, 'PLAN_E2E_ID_COLLISION'); assert not (b.orch / 'cards' / 'X1.json').exists()
    rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'claim', 'FAKE_PLAN_CLAIM': 'O91'}); eq(rc, 0, e)
    pk = sorted((b.orch / 'evidence').glob('plan-*/packet.txt'))[0].read_text()
    has(pk, 'CLAIMED_E2E_IDS: O90=A'); has(pk, 'EXISTING_E2E_IDS:'); has(pk, 'O03a'); has(pk, 'O21')


def O59(b):
    # add-card: validated like a planner card, collision-checked, replaces only retired cards, redirects dispositions
    b.card('A'); b.init()

    def cardfile(name, **kw):
        c = {'id': name, 'objective': 'one thing', 'depends_on': [], 'allowed_paths': ['src/b.txt'],
             'acceptance_rows': ['R1 x'], 'stop_condition': 'stop',
             'e2e': {'argv': ['/usr/bin/true', 'O95'], 'expect_status': 0, 'expect_files': []}, 'timeout': 60}
        c.update(kw); p = b.tmp / (name + '.json'); p.write_text(json.dumps(c)); return p
    rc, o, e = b.loop('add-card', cardfile('N1'), '--reason', '', '--approval', 'op'); assert rc != 0
    rc, o, e = b.loop('add-card', cardfile('A'), '--reason', 'r', '--approval', 'op'); assert rc != 0; has(e, 'CARD_DUPLICATE')
    rc, o, e = b.loop('add-card', cardfile('N1', depends_on=['ZZ']), '--reason', 'r', '--approval', 'op'); assert rc != 0; has(e, 'CARD_UNKNOWN_DEP')
    rc, o, e = b.loop('add-card', cardfile('N1', objective='fix <x>'), '--reason', 'r', '--approval', 'op'); assert rc != 0; has(e, 'CARD_INVALID')
    rc, o, e = b.loop('add-card', cardfile('N1', replaces='A'), '--reason', 'r', '--approval', 'op'); assert rc != 0; has(e, 'ADD_CARD_REPLACES_INVALID')
    rc, o, e = b.loop('add-card', b.tmp / 'nope.json', '--reason', 'r', '--approval', 'op'); assert rc != 0; has(e, 'ADD_CARD_FILE_INVALID')
    eq(sorted(p.name for p in (b.orch / 'cards').iterdir()), ['A.json'])
    rc, o, e = b.loop('add-card', cardfile('N1'), '--reason', 'root-authored per PLAN 013', '--approval', 'op 2026-10-24')
    eq(rc, 0, e); has(o, 'CARD_ADDED N1')
    st = b.state(); eq(st['cards']['N1']['status'], 'PENDING'); assert (b.orch / 'cards' / 'N1.json').is_file()
    assert any(r['event'] == 'add_card' and r['card'] == 'N1' and r['approval'] == 'op 2026-10-24' for r in b.ledger())
    rc, o, e = b.loop('add-card', cardfile('N2'), '--reason', 'r', '--approval', 'op'); assert rc != 0; has(e, 'CARD_E2E_ID_COLLISION')
    st = json.loads((b.orch / 'state.json').read_text()); st['dispositions'] = {'F1': 'card:A'}
    (b.orch / 'state.json').write_text(json.dumps(st))
    rc, o, e = b.loop('retire-card', 'A', '--reason', 'dup'); eq(rc, 0, e)
    rc, o, e = b.loop('add-card', cardfile('N3', replaces='A', e2e={'argv': ['/usr/bin/true', 'O96'], 'expect_status': 0,
                                                                   'expect_files': []}), '--reason', 'r', '--approval', 'op')
    eq(rc, 0, e)
    st = b.state(); eq(st['cards']['A']['status'], 'SUPERSEDED'); eq(st['cards']['A']['superseded_by'], ['N3'])
    eq(st['dispositions']['F1'], 'card:N3'); assert any(r['event'] == 'disposition_redirect' for r in b.ledger())
    rc, o, e = b.loop('run-card', 'N3', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)        # a root-added card runs normally


def O60(b):
    # retire-card --superseded-by (no dangling NEEDS_REPLAN subject) and set-disposition rules
    b.card('A'); b.card('B', allowed_paths=['src/b.txt'], e2e={'argv': ['/bin/cat', 'src/b.txt'], 'expect_status': 0, 'expect_files': []})
    b.card('C', depends_on=['A'], allowed_paths=['docs/c.txt'], e2e={'argv': ['/bin/cat', 'docs/c.txt'], 'expect_status': 0, 'expect_files': []})
    b.init()
    st = json.loads((b.orch / 'state.json').read_text())
    st['dispositions'] = {'F1': 'card:A', 'F2': 'deferred:later', 'F3': 'rejected:no'}
    (b.orch / 'state.json').write_text(json.dumps(st))
    rc, o, e = b.loop('retire-card', 'A', '--reason', 'dup of B', '--superseded-by', 'Z'); assert rc != 0; has(e, 'RETIRE_SUPERSEDER_INVALID')
    rc, o, e = b.loop('retire-card', 'A', '--reason', 'dup of B', '--superseded-by', 'A'); assert rc != 0
    rc, o, e = b.loop('retire-card', 'A', '--reason', 'dup of B', '--superseded-by', 'B'); eq(rc, 0, e)
    st = b.state(); eq(st['cards']['A']['status'], 'SUPERSEDED'); eq(st['cards']['A']['superseded_by'], ['B']); eq(st['dispositions']['F1'], 'card:B')
    rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'valid'}); assert rc != 0; has(e, 'NOTHING_TO_REPLAN')
    rc, o, e = b.loop('run-card', 'C', env={'FAKE_PI': 'ok'}); assert rc != 0; has(e, 'DEPENDENCY_NOT_ACCEPTED')
    accepted_card(b, 'B')
    rc, o, e = b.loop('run-card', 'C', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)          # dep A satisfied through B
    rc, o, e = b.loop('set-disposition', 'F3', 'root:orch-011 fixed', '--reason', 'r'); assert rc != 0; has(e, 'DISPOSITION_LOCKED')
    rc, o, e = b.loop('set-disposition', 'F2', 'maybe:x', '--reason', 'r'); assert rc != 0; has(e, 'DISPOSITION_VALUE_INVALID')
    rc, o, e = b.loop('set-disposition', 'F2', 'deferred:again', '--reason', 'r'); assert rc != 0; has(e, 'DISPOSITION_VALUE_INVALID')
    rc, o, e = b.loop('set-disposition', 'F2', 'card:ZZ', '--reason', 'r'); assert rc != 0; has(e, 'DISPOSITION_UNKNOWN_CARD')
    rc, o, e = b.loop('set-disposition', 'F2', 'card:C', '--reason', ''); assert rc != 0
    rc, o, e = b.loop('set-disposition', 'F2', 'card:C', '--reason', 'C implements F2'); eq(rc, 0, e)
    rc, o, e = b.loop('set-disposition', 'F9', 'root:orch-011 init defaults removed', '--reason', 'root fix'); eq(rc, 0, e)
    rc, o, e = b.loop('set-disposition', 'R005-F8', 'deferred:dirs invisible', '--reason', 'lost key'); eq(rc, 0, e)
    st = b.state(); eq(st['dispositions']['F2'], 'card:C'); eq(st['dispositions']['F9'], 'root:orch-011 init defaults removed')
    rc, o, e = b.loop('set-disposition', 'F2', 'card:B', '--reason', 'r'); assert rc != 0; has(e, 'DISPOSITION_LOCKED')
    eq(sum(1 for r in b.ledger() if r['event'] == 'set_disposition'), 3)


def O61(b):
    # a tree that carries e2e/run_e2e.py must keep its WHOLE suite green; the summary never lands in the tree
    stub = ("import os, sys, pathlib\nd = os.environ.get('E2E_SUMMARY_DIR')\n"
            "assert d and not os.path.abspath(d).startswith(os.getcwd()), d\n"
            "pathlib.Path(d).mkdir(parents=True, exist_ok=True)\n(pathlib.Path(d) / 'ran').write_text('1')\n"
            "if pathlib.Path('e2e/MUTATE').exists():\n    pathlib.Path('junk').write_text('x')\n"
            "sys.exit(int(pathlib.Path('e2e/EXIT').read_text()))\n")
    (b.parent / 'e2e').mkdir(); (b.parent / 'e2e' / 'run_e2e.py').write_text(stub); (b.parent / 'e2e' / 'EXIT').write_text('1')
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 1, e); has(e, 'suite status')
    st = b.state(); eq(st['cards']['A']['status'], 'FAILED'); eq(st['launches_used'], 37)
    assert (b.orch / 'evidence/A/1/suite/receipt.json').is_file() and (b.orch / 'evidence/A/1/suite-summary/ran').is_file()
    assert not (b.orch / 'jobs/A-1/tree/ran').exists()
    p2 = b.tmp / 'parent2'; shutil.copytree(b.parent, p2); (p2 / 'e2e' / 'EXIT').write_text('0')
    rc, o, e = b.loop('set-parent', p2); eq(rc, 0, e)
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)
    eq(b.state()['cards']['A']['status'], 'E2E_PASS'); assert (b.orch / 'evidence/A/2/suite-summary/ran').is_file()
    assert any(r['event'] == 'step' and r['label'] == 'A/2/suite' for r in b.ledger())
    b2 = Box()
    try:
        (b2.parent / 'e2e').mkdir(); (b2.parent / 'e2e' / 'run_e2e.py').write_text(stub)
        (b2.parent / 'e2e' / 'EXIT').write_text('0'); (b2.parent / 'e2e' / 'MUTATE').write_text('1')
        b2.card('A'); b2.init()
        rc, o, e = b2.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 1, e); has(e, 'SUITE_TREE_MUTATED')
        eq(b2.state()['cards']['A']['status'], 'FAILED')
    finally:
        b2.close()


def O62(b):
    # registry self-check of the suite itself: duplicate definitions and unknown ids are fatal, never vacuous passes
    d = b.tmp / 'e2ecopy'; d.mkdir()
    for f in HERE.glob('*.py'):
        shutil.copy2(f, d / f.name)
    r = subprocess.run([PY, '-B', str(d / 'run_e2e.py'), 'O9999'], capture_output=True, text=True, timeout=60)
    eq(r.returncode, 3, r.stdout + r.stderr); has(r.stdout, 'REGISTRY_INVALID'); has(r.stdout, 'unknown scenario ids')
    with open(d / 'run_e2e.py', 'a') as f:
        f.write('\n\ndef O01(b):\n    pass\n')
    r = subprocess.run([PY, '-B', str(d / 'run_e2e.py'), 'O01'], capture_output=True, text=True, timeout=60)
    eq(r.returncode, 3, r.stdout + r.stderr); has(r.stdout, 'defined twice')
    with open(d / 'run_e2e.py', 'a') as f:
        f.write('\n\ndef O8888(b):\n    pass\n')
    r = subprocess.run([PY, '-B', str(d / 'run_e2e.py'), 'O01'], capture_output=True, text=True, timeout=60)
    eq(r.returncode, 3, r.stdout + r.stderr); has(r.stdout, 'defined but not registered')


def O63(b):
    # external/ attachments are part of the orchestration hash, the snapshot and the review packet; symlinks refused
    b.card('A'); b.init(); h0 = b.state()['orch_hash']
    ext = b.orch / 'external'; ext.mkdir(); (ext / 'pi-profile.sb').write_text('(version 1)\n')
    rc, o, e = b.loop('rebind-orch'); eq(rc, 0, e); has(o, 'ORCH_REBOUND'); h1 = b.state()['orch_hash']; assert h1 != h0
    snap = b.snapshot('ext-snap'); assert (snap / 'external' / 'pi-profile.sb').is_file()
    rc, o, e = b.loop('review', '--subject', snap, '--name', 'orch', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    eq(b.state()['source_reviews']['orch'], h1)
    has((b.orch / 'evidence' / 'review-001' / 'packet.txt').read_text(), 'external/pi-profile.sb')
    os.symlink('/etc/hosts', ext / 'link')
    rc, o, e = b.loop('rebind-orch'); assert rc != 0; has(e, 'SYMLINK_IN_TREE')


def O64(b):
    # handoff: --seq, refuses existing outputs, demands a live all-pass e2e summary bound to the live sources,
    # inlines sources + ledger + preservation, no unfilled placeholder
    b.card('A'); b.init(); accepted_card(b)
    rc, o, e = b.loop('review', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    rc, o, e = b.source_review(); eq(rc, 0, e)
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'no e2e summary')
    b.e2e_summary(ok=False)
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'failures')
    b.e2e_summary()
    p = b.tmp / 'evidence-e2e-orch' / 'summary.json'
    s = json.loads(p.read_text()); s['sources']['loop.py'] = '0' * 64; p.write_text(json.dumps(s))
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'stale')
    b.e2e_summary()
    rc, o, e = b.loop('handoff', '--seq', '12'); eq(rc, 0, e)
    has(o, 'HANDOFF-012'); has(o, 'MILESTONE VERDICT: ACCEPTED'); has(o, '--- FILE src/a.txt ---'); has(o, 'edited by A')
    has(o, 'PRESERVATION'); has(o, 'AUTH_DIR'); has(o, '"event": "reserve"'); has(o, '"O00"'); has(o, 'CARD FILES')
    has(o, 'ALLOCATIONS'); assert '{{' not in o
    assert (b.tmp / 'HANDOFF-012.txt').is_file() and json.loads((b.tmp / 'RESULT-012.json').read_text())['verdict'] == 'ACCEPTED'
    rc, o, e = b.loop('handoff', '--seq', '12'); assert rc != 0; has(e, 'HANDOFF_OUTPUT_EXISTS')
    rc, o, e = b.loop('handoff', '--seq', 'x'); assert rc != 0


def O65(b):
    # F10: no baked accounting defaults
    b.card('A')
    rc, o, e = b.loop('init', '--parent', b.parent); assert rc != 0; has(e, 'active-seconds')
    assert not (b.orch / 'state.json').exists()
    b.init()


def O66(b): _fail_case(b, 'fifo', 'SPECIAL_FILE')


def O67(b):
    # guardian route: a cleanly reaped non-zero worker is an attempt failure (lock free), not uncertainty; two in a row brake
    rt = guardian_env(b)
    b.card('A'); b.card('B', allowed_paths=['src/b.txt'], e2e={'argv': ['/bin/cat', 'src/b.txt'], 'expect_status': 0, 'expect_files': []}, timeout=2)
    b.init()
    genv = {'FAKE_GUARDIAN_AUTH_DIR': str(rt / 'private-pi')}
    rc, o, e = b.loop('run-card', 'A', env=dict(genv, FAKE_GUARDIAN='worker_fail'))
    eq(rc, 1, e); has(e, 'worker-exit-3'); st = b.state()
    eq(st['cards']['A']['status'], 'FAILED'); eq(st['launches_used'], 37); eq(st['worker_failure_streak'], 1)
    assert not (b.orch / 'lock').exists() and not (rt / 'private-pi' / 'auth.json').exists()
    rc, o, e = b.loop('run-card', 'B', env=dict(genv, FAKE_GUARDIAN='worker_hang'))
    eq(rc, 1, e); has(e, 'worker-exit-'); eq(b.state()['worker_failure_streak'], 2); assert not (b.orch / 'lock').exists()
    g = json.loads((rt / 'jobs' / 'B-1' / 'guardian' / 'receipt.json').read_text())
    eq(g['status'], 'TERMINATED'); eq(g['reason'], 'timeout'); eq(g['credential_removed'], True)
    rc, o, e = b.loop('run-card', 'A', env=genv); assert rc != 0; has(e, 'WORKER_FAILURE_STREAK'); eq(b.state()['launches_used'], 38)
    rc, o, e = b.loop('run-card', 'A', '--acknowledge-streak', 'checked guardian/stdout: provider restored', env=genv); eq(rc, 0, e)
    eq(b.state()['worker_failure_streak'], 0); assert any(r['event'] == 'streak_acknowledged' for r in b.ledger())


def O68(b):
    # clear-lock: manual, ledgered, refused without reason / with credential residue; cards stay BLOCKED until retired
    b.card('A'); b.init()
    rc, o, e = b.loop('clear-lock', '--reason', 'x'); assert rc != 0; has(e, 'LOCK_NOT_HELD')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'grandchild'}); eq(rc, 71, e); assert (b.orch / 'lock').exists()
    rc, o, e = b.loop('clear-lock', '--reason', ''); assert rc != 0; assert (b.orch / 'lock').exists()
    rc, o, e = b.loop('clear-lock', '--reason', 'inspected: ps shows no job processes'); eq(rc, 0, e); has(o, 'LOCK_CLEARED')
    assert not (b.orch / 'lock').exists(); eq(b.state()['cards']['A']['status'], 'BLOCKED_CLEANUP_UNCERTAIN')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); assert rc != 0; has(e, 'CARD_NOT_RUNNABLE')
    rc, o, e = b.loop('retire-card', 'A', '--reason', 'uncertain job inspected'); eq(rc, 0, e); eq(b.state()['cards']['A']['status'], 'NEEDS_REPLAN')
    assert any(r['event'] == 'clear_lock' for r in b.ledger())
    b2 = Box()
    try:
        ad = b2.tmp / 'authdir'; ad.mkdir(); b2.write_env(AUTH_DIR=ad); b2.card('A'); b2.init()
        rc, o, e = b2.loop('run-card', 'A', env={'FAKE_PI': 'auth'}); eq(rc, 71, e)
        rc, o, e = b2.loop('clear-lock', '--reason', 'x'); assert rc != 0; has(e, 'credential residue'); assert (b2.orch / 'lock').exists()
    finally:
        b2.close()


def O69(b):
    # guardian route refuses stale/symlinked PI_BIN, SANDBOX_EXEC, PI_PROFILE before any slot is consumed
    rt = guardian_env(b)
    b.card('A'); b.init()
    genv = {'FAKE_GUARDIAN_AUTH_DIR': str(rt / 'private-pi')}
    for key, val, needle in (('PI_BIN', b.tmp / 'missing-pi', 'PI_BIN_INVALID'), ('SANDBOX_EXEC', b.tmp / 'nosb', 'SANDBOX_EXEC_INVALID'),
                             ('PI_PROFILE', b.tmp / 'no.sb', 'PI_PROFILE_INVALID')):
        guardian_env(b, **{key: val})
        rc, o, e = b.loop('run-card', 'A', env=genv); assert rc != 0, key; has(e, needle)
        eq(b.state()['launches_used'], 36); assert not (rt / 'jobs').exists()
    link = b.tmp / 'pilink'; os.symlink(b.fakes / 'pi', link); guardian_env(b, PI_BIN=link)
    rc, o, e = b.loop('run-card', 'A', env=genv); assert rc != 0; has(e, 'PI_BIN_INVALID')
    guardian_env(b)
    rc, o, e = b.loop('run-card', 'A', env=genv); eq(rc, 0, e)
````
Expected after P1: `TOTAL 65 FAILED 0`.

---------------------------------------------------------------------------------------------------
## 6. Card program (fixed; written byte-exact to `continuation-011/cards-round5/<id>.json`, inserted with `add-card`)

Conventions every card obeys (validated by `validate_card` + D2/D3): one objective line; `allowed_paths` ≤3 relative; every
single edit <3000 chars (RULES 3); `e2e.argv` = `/usr/bin/python3 -B e2e/run_e2e.py <OWN-ID>` with `e2e.timeout` 150;
the full suite also runs (D4); fresh scenario id from the registry (§10); `depends_on` = previous card (linear chain =
every worker sees all prior accepted edits, no merge ambiguity); `stop_condition` names the exact code shape whose absence
means the premise is false. Rows reference code by the names that exist in `frozen/orch-011` (Appendix A + §5).

### 6.1 Tier 1 — correctness of the loop itself (slots 37–41)

**C1** — unchanged (already in `orch/cards/C1.json`, O32): base-hash gate `PARENT_STALE` (review-005 F1).

**C9** (replaces C2; supersedes C7) — scenario **O70**
````json
{"id": "C9",
 "objective": "Re-verify the job tree after the card e2e step (re-hash, scope-check, or fail E2E_TREE_MUTATED) and make cmd_review refuse a stale revision for card and final scope",
 "depends_on": ["C1"], "allowed_paths": ["loop.py", "e2e/run_e2e.py"], "replaces": "C2",
 "acceptance_rows": [
  "R1 In loop.py cmd_run_card, immediately after the card e2e launch (the launch whose label ends in '/e2e') passes its expect_status and expect_files checks and BEFORE the suite step (the block starting `suite = tree / 'e2e' / 'run_e2e.py'`), compute post = inv_hash(inventory(tree)); if post != manifest['tree_hash']: compute ok2, probs2 = scope_verify(parent_inv, inventory(tree), set(c['allowed_paths'])); if not ok2 call fail_attempt(st, a.id, 'E2E_TREE_MUTATED: ' + '; '.join(probs2)); otherwise set manifest['tree_hash'] = post, rewrite job/'result-manifest.json' with jwrite, and append_ledger({'event': 'tree_rehash', 'card': a.id, 'attempt': attempt, 'old': <previous hash>, 'new': post}).",
  "R2 The existing SUITE_TREE_MUTATED comparison after the suite step and cs.update(... tree_hash=manifest['tree_hash']) are left as they are, so both now use the re-hashed value.",
  "R3 In loop.py cmd_review, for scope card (a.card set) and scope final (neither a.subject nor a.card), BEFORE the line `st['review_seq'] += 1`, compute live = inv_hash(inventory(tree)); if live != revision: append_ledger({'event': 'review_stale', 'scope': scope, 'stored': revision, 'live': live}) and sys.exit('REVISION_STALE %s stored=%s live=%s' % (scope, revision, live)); review_seq is not incremented, no evidence/review-* directory is created, no state other than the ledger changes.",
  "R4 e2e/run_e2e.py gains scenario O70 registered in SCENARIOS, in three parts using a fresh Box() for each part as O16 does: (a) card A with e2e argv ['/usr/bin/python3', '-c', \"open('junk.txt','w').write('x')\"]: run-card A exits 1, stderr contains E2E_TREE_MUTATED, state card A status FAILED, launches_used 37; (b) card A with e2e argv ['/usr/bin/python3', '-c', \"open('src/a.txt','a').write('e2e')\"]: run-card A exits 0, result-manifest.json tree_hash equals state cards.A.tree_hash, the ledger contains an event tree_rehash for card A, and review --card A with FAKE_REVIEW=accepted exits 0; (c) card A passes run-card with the default e2e argv, then the scenario appends one byte to orch/jobs/A-1/tree/src/a.txt; review --card A exits non-zero, stderr contains REVISION_STALE, state review_seq is unchanged, parent_hash is unchanged, cards.A.status is still E2E_PASS and no orch/evidence/review-001 directory exists.",
  "R5 No scenario other than O70 is added or changed; no function other than cmd_run_card and cmd_review changes."],
 "stop_condition": "print CARD_BLOCKED C9 if cmd_run_card has no suite step whose failure reason is 'SUITE_TREE_MUTATED', if scenario id O70 already exists in e2e/run_e2e.py, or if cmd_review does not derive `revision` from cs['tree_hash'] for card scope and from st['parent_hash'] for final scope",
 "e2e": {"argv": ["/usr/bin/python3", "-B", "e2e/run_e2e.py", "O70"], "expect_status": 0, "expect_files": [], "timeout": 150},
 "timeout": 540}
````

**C10** (replaces C5) — scenario **O71**
````json
{"id": "C10",
 "objective": "Make the RESERVED window of cmd_run_card recoverable: any failure between slot reservation and the coding launch marks the card FAILED with a recorded reason, and inputs_inline is validated at card-load time as a list of relative paths",
 "depends_on": ["C9"], "allowed_paths": ["loop.py", "e2e/run_e2e.py"], "replaces": "C5",
 "acceptance_rows": [
  "R1 In loop.py cmd_run_card, in BOTH branches (guardian and worker-pi.sh), the statements between `cs['status'] = 'RESERVED'; save_state(st)` and the coding `launch(...)` call (job dir checks and mkdir, shutil.copytree, assemble_prompt, prompt.write_text, coding_spec/jwrite(spec)) are wrapped in one try/except that catches SystemExit and OSError; on exception it sets cs['status'] = 'FAILED', cs['last_failure'] = 'PRELAUNCH ' + (str(exc.code) for SystemExit, else type(exc).__name__ + ': ' + str(exc)), calls save_state(st), append_ledger({'event': 'run_card_prelaunch_failed', 'card': a.id, 'attempt': attempt, 'reason': cs['last_failure']}) and re-raises the exception unchanged (exit code preserved); the slot stays consumed.",
  "R2 In loop.py validate_card, when the key inputs_inline is present it must be a list whose items are non-empty strings that do not start with '/' and have no '..' path part; otherwise return 'inputs_inline must be a list of relative paths'.",
  "R3 e2e/run_e2e.py gains scenario O71 registered in SCENARIOS: (a) a card with inputs_inline={'a': 'b'} makes init exit non-zero with CARD_INVALID and no state.json; (b) in a fresh Box, a valid card with inputs_inline=['src/missing.txt']: run-card exits non-zero, stderr contains INPUT_INVALID, state cards.<id>.status is FAILED and last_failure starts with 'PRELAUNCH', launches_used is 37, the ledger has run_card_prelaunch_failed; the scenario then rewrites orch/cards/<id>.json without inputs_inline and run-card exits 0 with launches_used 38 and status E2E_PASS; (c) in a fresh Box, orch/jobs/<id>-1 is pre-created before the first run-card: run-card exits non-zero, status FAILED, launches_used 37; the next run-card exits 0 using orch/jobs/<id>-2.",
  "R4 No scenario other than O71 is added or changed; no function other than cmd_run_card and validate_card changes."],
 "stop_condition": "print CARD_BLOCKED C10 if cmd_run_card does not contain `cs['status'] = 'RESERVED'` followed by shutil.copytree and assemble_prompt before launch(...), if validate_card does not exist, or if scenario id O71 already exists in e2e/run_e2e.py",
 "e2e": {"argv": ["/usr/bin/python3", "-B", "e2e/run_e2e.py", "O71"], "expect_status": 0, "expect_files": [], "timeout": 150},
 "timeout": 540}
````

**C11** (replaces C6) — scenario **O72**
````json
{"id": "C11",
 "objective": "Bind milestone acceptance to a revision so handoff reports ACCEPTED only when the current parent_hash is the revision that was final-reviewed, and any later parent change or replan clears the acceptance",
 "depends_on": ["C10"], "allowed_paths": ["loop.py", "e2e/run_e2e.py"], "replaces": "C6",
 "acceptance_rows": [
  "R1 In loop.py cmd_review, where `st['milestone'] = 'ACCEPTED'` is set, also set st['milestone_revision'] = revision; every dict appended to st['reviews'] gains the key 'revision' with the reviewed revision.",
  "R2 Define a helper milestone_reset(st, why) that, only when st['milestone'] == 'ACCEPTED', sets st['milestone'] = 'REPLANNED', sets st['milestone_revision'] = None and calls append_ledger({'event': 'milestone_reset', 'why': why, 'previous_revision': <old milestone_revision>}); call it in cmd_review right before `st['parent_dir'], st['parent_hash'] = tree, revision` (card acceptance), in cmd_set_parent right before the parent is rebound, and in cmd_replan right before new card files are written when len(new) > 0.",
  "R3 In loop.py cmd_handoff, the verdict line becomes: verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED' and st.get('milestone_revision') == st['parent_hash'] else ('BLOCKED' if any(v['status'] == 'BLOCKED_CLEANUP_UNCERTAIN' for v in st['cards'].values()) else 'INCOMPLETE'); when st['milestone'] == 'ACCEPTED' but the revisions differ, the printed text contains a line 'MILESTONE_STALE milestone_revision=<x> parent_hash=<y>' directly after the MILESTONE VERDICT line.",
  "R4 e2e/run_e2e.py gains scenario O72 registered in SCENARIOS: drive a Box to milestone ACCEPTED exactly like O01 up to and including the final review; assert state milestone_revision equals parent_hash and reviews[-1]['revision'] equals parent_hash; run source_review('findings') then replan with FAKE_PLAN=valid and FAKE_PLAN_BASE=0 and assert milestone is 'REPLANNED' and milestone_revision is None and the ledger has milestone_reset; run-card X1 and review --card X1 accepted; then edit state.json directly setting milestone to 'ACCEPTED' and milestone_revision to 'deadbeef', call b.source_review() accepted, b.e2e_summary(), and handoff --seq 12: output contains 'MILESTONE VERDICT: INCOMPLETE' and 'MILESTONE_STALE' and not 'MILESTONE VERDICT: ACCEPTED'; then review (final scope) accepted, b.e2e_summary(), handoff --seq 13: output contains 'MILESTONE VERDICT: ACCEPTED' and RESULT-013.json verdict is ACCEPTED.",
  "R5 O01, O30 and O41 still pass unchanged; no scenario other than O72 is added; no function other than cmd_review, cmd_set_parent, cmd_replan, cmd_handoff and the new milestone_reset changes."],
 "stop_condition": "print CARD_BLOCKED C11 if cmd_review does not contain `st['milestone'] = 'ACCEPTED'`, if cmd_handoff does not contain `verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED'`, if cmd_handoff has no --seq handling (HANDOFF-%03d), or if scenario id O72 already exists in e2e/run_e2e.py",
 "e2e": {"argv": ["/usr/bin/python3", "-B", "e2e/run_e2e.py", "O72"], "expect_status": 0, "expect_files": [], "timeout": 150},
 "timeout": 540}
````

**C12** (replaces C8) — scenario **O73**
````json
{"id": "C12",
 "objective": "Hash the reviewer packet before the model runs and detect a packet rewritten during the run, so packet_sha attests what the model was given",
 "depends_on": ["C11"], "allowed_paths": ["loop.py", "e2e/run_e2e.py", "e2e/fake_engine.py"], "replaces": "C8",
 "acceptance_rows": [
  "R1 In loop.py run_model, immediately after `pf.write_text(prompt_text)` compute pre_sha = sha(pf), call append_ledger({'event': 'packet_written', 'label': label, 'sha': pre_sha}), and return (pf, res, pre_sha) instead of (pf, res); both callers (cmd_review and cmd_replan) unpack three values.",
  "R2 In loop.py cmd_review, the ledger event review_packet and the 'packet_sha' stored in st['reviews'] use pre_sha; after run_model returns compute post = sha(pf); if post != pre_sha: append_ledger({'event': 'packet_tampered', 'label': label, 'pre': pre_sha, 'post': post}), append to st['reviews'] a dict {'seq': st['review_seq'], 'scope': scope, 'backend': st['reviewer_backend'], 'verdict': 'TAMPERED', 'findings': [], 'missing': 0, 'packet_sha': pre_sha, 'packet_tampered': True}, save_state(st), and sys.exit('REVIEW_PACKET_TAMPERED ' + label) before any verdict parsing; no acceptance, no parent/card/milestone change, pending_findings unchanged.",
  "R3 In e2e/fake_engine.py, in the review branch (after the provider-error knobs, before the verdict block is printed): if the environment variable FAKE_REVIEW_REWRITE_PACKET is set, append the line 'TAMPERED\\n' to the file at that path; no other fake behaviour changes. In e2e/run_e2e.py Box.loop the ORCH_ENV_PASSTHROUGH string gains ',FAKE_REVIEW_REWRITE_PACKET'.",
  "R4 e2e/run_e2e.py gains scenario O73 registered in SCENARIOS: (a) _to_e2e_pass(b); review --card A with FAKE_REVIEW=accepted and FAKE_REVIEW_REWRITE_PACKET=<orch>/evidence/review-001/packet.txt exits non-zero, stderr contains REVIEW_PACKET_TAMPERED, cards.A.status is E2E_PASS, parent_hash unchanged, reviews[-1]['packet_tampered'] is True and reviews[-1]['packet_sha'] equals the sha256 of packet.txt with its final 'TAMPERED\\n' line removed; the ledger has packet_written and packet_tampered; (b) a second review --card A with FAKE_REVIEW=accepted exits 0 and reviews[-1]['packet_sha'] equals the sha256 of evidence/review-002/packet.txt and has no packet_tampered key.",
  "R5 No scenario other than O73 is added or changed; no function other than run_model, cmd_review, cmd_replan (unpacking only) changes in loop.py."],
 "stop_condition": "print CARD_BLOCKED C12 if cmd_review currently records sha(pf) only after run_model returns (the finding's premise), if run_model does not write pf before launching, if scenario id O73 already exists in e2e/run_e2e.py, or if the fake reviewer cannot rewrite packet.txt without touching files outside allowed_paths",
 "e2e": {"argv": ["/usr/bin/python3", "-B", "e2e/run_e2e.py", "O73"], "expect_status": 0, "expect_files": [], "timeout": 150},
 "timeout": 480}
````

### 6.2 Tier 2 — low-severity findings F5–F8 (slots 42–45; added only after the §4.4 gate)

**C13** (F5) — **O74**: `cmd_replan` disposition guard. Rows: R1 before any card is written, every key in `plan['dispositions']`
must match `(card:[A-Za-z0-9_-]+|rejected:.+|deferred:.+)` else `sys.exit('PLAN_DISPOSITION_INVALID ' + key)`; R2 a key already in
`st['dispositions']` with a different value ⇒ `sys.exit('PLAN_DISPOSITION_OVERWRITE ' + key)` (identical value allowed); R3 every
`card:<id>` value (any key) must name a card in `new` or `existing` else `PLAN_DISPOSITION_UNKNOWN_CARD`; all three checks
happen before `jwrite` of any card and leave `pending_findings` unchanged; R4 `e2e/fake_engine.py` gains knob
`FAKE_PLAN=bad_disp` ⇒ `disp = {ids[0]: 'maybe:later'}` when ids non-empty; R5 scenario O74: (a) after a review with
findings, seed `state.dispositions = {'F1': 'deferred:old'}` by editing state.json, `replan` with `FAKE_PLAN=valid` ⇒ non-zero,
`PLAN_DISPOSITION_OVERWRITE`, no X1.json, pending_findings `['F1']`; (b) fresh Box, `FAKE_PLAN=bad_disp` ⇒ `PLAN_DISPOSITION_INVALID`;
(c) fresh Box, `FAKE_PLAN=valid` ⇒ exit 0 and dispositions `{'F1': 'card:X1'}`. allowed: `loop.py`, `e2e/run_e2e.py`,
`e2e/fake_engine.py`; depends_on `["C12"]`; timeout 420; stop: CARD_BLOCKED if `cmd_replan` lacks
`st['dispositions'] = dict(st.get('dispositions', {}), **plan['dispositions'])` or O74 exists.

**C14** (F6) — **O75**: `validate_card` type checks for optional keys: `base`/`replaces` strings matching `[A-Za-z0-9_-]{1,40}`;
`max_edit_chars` int 1..3000; `parent_manifest` str; `parent_hash` 64 lowercase hex; `e2e.expect_files` list of relative
non-empty strings without `..`; `e2e.timeout` int 1..200; each violation returns a distinct message starting with the key name.
O75: init rejects each bad shape with `CARD_INVALID <key…>` (one Box per shape or sequential card rewrites before init), and
`replan` with new knob `FAKE_PLAN=badtypes` (`c['replaces'] = ['A']`, `c['e2e']['timeout'] = 'x'`) ⇒ `PLAN_CARD_INVALID`, no card
written. allowed: `loop.py`, `e2e/run_e2e.py`, `e2e/fake_engine.py`; depends_on `["C13"]`; timeout 420; stop: CARD_BLOCKED if
`CARD_OPTIONAL` is not a set literal in loop.py or O75 exists.

**C15** (F7) — **O76**: `parse_verdict` typing: each finding needs `id`, `severity` ∈ {high, medium, low}, `location`, `evidence`
as non-empty strings (no extra keys); `missing_evidence` items non-empty strings; `coverage` exactly `{complete: bool, truncated: bool}`;
`cleanup` a string; else return None (⇒ `REVIEW_MALFORMED`). Knobs `FAKE_REVIEW=finding_no_evidence|bad_severity|missing_ev_nonstring|coverage_nonbool`.
O76: each knob ⇒ `review --card A` non-zero with `REVIEW_MALFORMED`, state unchanged (status E2E_PASS, pending_findings `[]`, reviews `[]`);
then `findings` knob still ⇒ exit 2 with pending `['F1']`. allowed: `loop.py`, `e2e/run_e2e.py`, `e2e/fake_engine.py`; depends_on
`["C14"]`; timeout 420; stop: CARD_BLOCKED if `parse_verdict` does not contain `isinstance(f.get('id'), str)` or O76 exists.

**C16** (F8) — **O77**: `cmd_review` uses a local `backend = a.backend or st['reviewer_backend']` for `run_model` and the smoke record;
`st['reviewer_backend'] = backend` is assigned only on the non-smoke path after `parse_verdict` succeeded and the revision matched
(immediately before `st['last_review'] = …`); smokes, malformed, transport and provider failures never change it. O77: init
(reviewer codex); `review --subject snap --name s --smoke --backend fable` with `FAKE_REVIEW=accepted` ⇒ exit 0, `smokes.s.backend == 'fable'`,
`reviewer_backend == 'codex'`; `_to_e2e_pass`; `review --card A --backend fable` with `FAKE_REVIEW=prose` ⇒ non-zero, `reviewer_backend`
still codex; `review --card A --backend fable` accepted ⇒ `reviewer_backend == 'fable'`; then `replan` default backend is codex (argv log
shows kind codex for the planner). allowed: `loop.py`, `e2e/run_e2e.py`; depends_on `["C15"]`; timeout 420; stop: CARD_BLOCKED if
`cmd_review` does not contain `if a.backend:` followed by `st['reviewer_backend'] = a.backend`, or O77 exists.

### 6.3 Tier 3 — F4 and F9 (slots 46–47; only after the §4.4 gate; otherwise stay `deferred:` with the existing reasons)

**C17** (F4) — **O78**: sandbox the card e2e and suite launches. R1 `cmd_run_card` writes `job/'e2e.sb'` with exactly:
`(version 1)\n(allow default)\n(deny file-write*)\n(allow file-write* (subpath "<tree>"))\n(allow file-write* (subpath "<ev>"))\n(deny network-outbound (remote unix-socket))\n(allow network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))\n(allow network-outbound (remote unix-socket (path-literal "/var/run/mDNSResponder")))\n(deny signal)\n(allow signal (target self) (target children))\n`
where `<tree>` and `<ev>` are the absolute job tree and `evidence/<card>/<attempt>` paths; R2 both the e2e and suite launches use
argv `[env['SANDBOX_EXEC'], '-f', str(job / 'e2e.sb')] + <original argv>` and extra env additionally `TMPDIR=str(ev / 'tmp')` (directory
created first, 0700); R3 O78: `argv_entries()` contains two entries with kind `sandbox` whose `args[1]` is the job's `e2e.sb` path,
one followed by the card's e2e argv and one by `e2e/run_e2e.py` (use a parent with the O61 stub so the suite step runs); the profile file
contains the tree path, the evidence path and `(deny file-write*)`; O37 (`e2e status`) still passes. allowed: `loop.py`, `e2e/run_e2e.py`;
depends_on `["C16"]`; timeout 480. Real enforcement of the profile is proven only by a real run and is recorded as such in the handoff.
stop: CARD_BLOCKED if the e2e launch argv in `cmd_run_card` is not `list(e['argv'])` or O78 exists.

**C18** (F9) — **O79**: `base_env` honours `ORCH_ENV_PASSTHROUGH` only when `os.environ.get('ORCH_E2E_HARNESS') == '1'`; `Box.loop`
sets `ORCH_E2E_HARNESS='1'`. O79: a direct `subprocess.run` of `loop.py run-card A` with `ORCH_ENV_PASSTHROUGH=FAKE_PI,FAKE_ARGV_LOG`,
`FAKE_PI=blocked` and NO marker ⇒ exit 0 and `E2E_PASS` (the knob did not reach the fake, which defaulted to ok); the same command with
`ORCH_E2E_HARNESS=1` ⇒ exit 1 and `CARD_BLOCKED`. allowed: `loop.py`, `e2e/run_e2e.py`; depends_on `["C17"]`; timeout 360;
stop: CARD_BLOCKED if `base_env` does not read `ORCH_ENV_PASSTHROUGH` or O79 exists.

### 6.4 Disposition provenance (keys collided across reviews; recorded so the frontier reviewer can audit)
| review | finding | today's key/value in state | after P4 |
|---|---|---|---|
| 005 | F1 base-hash gate | key overwritten by 012-F1 | C1 (unchanged card) |
| 005 | F2 e2e mutates tree after hash | overwritten | C9 (`F1: card:C9` after retire C7 --superseded-by C9) |
| 005 | F3 milestone not revision-bound | overwritten | C11 (`F2: card:C11`) |
| 005 | F4 RESERVED dead end | overwritten | C10 |
| 005 | F5 e2e argv unsandboxed | overwritten by 012-F4 text | C17 or `deferred:` |
| 005 | F6 packet hash after run | overwritten | C12 (`F3: card:C12`) |
| 005 | F7 stale comment | fixed root orch-008 | unchanged |
| 005 | F8 dirs invisible | lost | `R005-F8: deferred:…` |
| 005 | F9 passthrough | `F9: deferred:` | C18 or deferred |
| 005 | F10 baked defaults | `F10: deferred:` | `root:orch-011 D7` |
| 012 | F1 post-e2e hash | `card:C7` | `card:C9` |
| 012 | F2 milestone | `deferred:` | `card:C11` |
| 012 | F3 packet sha | `card:C8` | `card:C12` |
| 012 | F4 e2e sandbox | `deferred:` | `card:C17` or deferred |
| 012 | F5–F8 | `deferred:` | C13–C16 or deferred |
| 012 | M0–M3 | `deferred:` | `root:orch-011 external/…` |
| 012 | M4 | `rejected:` | unchanged |

---------------------------------------------------------------------------------------------------
## 7. The final printed review prompt
Produced only by `loop.py handoff --seq 12` (§5 D6 `REVIEW_TEMPLATE`): revision + orch hash, accounting + allocations, card
state + card files, every disposition, full review history (incl. same-backend approvals and the last verdict JSON), the
per-scenario E2E results bound to the live source hashes, preservation report (AUTH_DIR listing, every guardian receipt,
uncertain cards, failure streak), source inventory AND full source contents of the tree in force, and the complete ledger.
Any unfilled `{{…}}` ⇒ `HANDOFF_UNFILLED_PLACEHOLDER` (refuse). It is written to `HANDOFF-012.txt` and printed in full.

---------------------------------------------------------------------------------------------------
## 8. Accounting (worst case = the gates; typical from round-4 measurements: plan ≈60–100 s, review ≈300 s, suite 37 s)

| step | gate / cap | worst s | typical s | slots |
|---|---|---|---|---|
| P0+P1 root work (D1–D15, O57–O69, attachments, freeze) | `note-interval`, honest wall-anchored | 14400 | 7200 | 0 |
| P2 Astra smoke | 120 | 120 | 15 | 0 |
| P3 source review orch-011 (+1 replan, +1 re-review) | 600 (+300, +600) | 1500 | 500 | 0 |
| Tier-1 card (×5: C1, C9–C12): run-card `card_need` = timeout+30+150+300+180; review 600 | 1260 + 600 | 1860 each → 9300 | 750 each → 3750 | 5 |
| Tier-2 card (×4) | 1230 + 600 | 7320 | 3000 | 4 |
| Tier-3 card (×2) | 1290 + 600 | 3780 | 1500 | 2 |
| P5 promotion + suite + freeze (root) + source review + final review + handoff | 600 + 600 + 600 + 60 | 1860 | 1000 | 0 |
| **Tier 1 program total** | | **≈27200** | **≈12500** | 5 |
| **Full program total** | | **≈38300** | **≈17000** | 11 |

Remaining today: 697.2 s, 12 slots. Recommended first allocation `--ceiling 61200` (room 29497 s ≥ Tier-1 worst case).
Tier 2/3 require a second `allocate-time` (each call ≤ +86400) decided after Tier 1 lands. Retries: each attempt costs a
slot; with 11 cards and 12 slots the whole program tolerates ONE retry — hence the tier gates in §4.4.

---------------------------------------------------------------------------------------------------
## 9. Stop rules (any one fires ⇒ stop launching, keep evidence, go to P6)
1. `TIME_GATE_FAILED` or `SLOT_CAP_REACHED` for the next required step; never raise a cap except via a ledgered `allocate-time`.
2. Slot rule: do not start a card (or a retry) when remaining slots < remaining cards of the approved tiers + 1.
3. `BLOCKED_CLEANUP_UNCERTAIN` (exit 71) or `LOCK_HELD`: inspect by hand (ps, `private-pi/`, receipts); `clear-lock --reason` only
   after verification; `retire-card`; no automatic salvage; the handoff states it.
4. `BLOCKED_PROVIDER_UNAVAILABLE` (75) or `PROVIDER_ERROR` (74) on a review/replan: no fallback model; retry once after the
   provider's stated return; otherwise stop. `WORKER_FAILURE_STREAK`: inspect before `--acknowledge-streak`; a third clean worker
   failure in the round ⇒ stop (coding provider outage).
5. Three failed attempts on one card ⇒ `NEEDS_REPLAN` ⇒ `replan` (different backend or recorded approval) before any retry.
6. Two non-accepted source reviews on root mechanics with new findings, or two malformed reviews in a row ⇒ stop.
7. Any binding differs from §0 (PI_BIN, CLAUDE_BIN, CODEX_BIN, profile/guardian sha) ⇒ rebind + disclose, or stop if unavailable.
8. Any card whose stop condition is true ⇒ the worker prints `CARD_BLOCKED` (slot spent, attempt failed) ⇒ root retires the card
   (`retire-card … --superseded-by` or replan) instead of re-launching the same premise.
9. `~/.codex/auth.json` mtime changed by us, `private-pi/` non-empty, or any write outside `continuation-011/`,
   `pi-runtime-v2/jobs/`, `orch/evidence/` ⇒ stop and report.

---------------------------------------------------------------------------------------------------
## 10. Scenario-id registry and edge-case coverage (ids are function names in `e2e/run_e2e.py`; D8 makes duplicates fatal)

| range | owner | ids |
|---|---|---|
| existing | orch-010 | O01 O02 O03a O03b O04–O31 O33–O42 O44–O54 (52) |
| pending card | C1 | O32 |
| root orch-011 | §5.2 | O57 O58 O59 O60 O61 O62 O63 O64 O65 O66 O67 O68 O69 |
| Tier 1 cards | C9 C10 C11 C12 | O70 O71 O72 O73 |
| Tier 2 cards | C13 C14 C15 C16 | O74 O75 O76 O77 |
| Tier 3 cards | C17 C18 | O78 O79 |
| released by retirement | C2 (O43), C5/C7 (O55), C6/C8 (O56) | not reused this round (avoid history confusion) |
| planner replans | next free ≥ O80 | validated by D2 against suite ∪ claimed |

| edge case (operator list) | scenarios |
|---|---|
| timeouts (worker, guardian-killed worker, e2e, suite) | O04, O67, O37, O61 |
| output overflow | O05 |
| orphans / grandchildren holding pipes | O08, O51 |
| interrupts (SIGINT mid-launch) | O09 |
| concurrent runs | O10 |
| torn writes | O11 |
| tamper (parent, packet, tree, packet rewrite during run) | O16, O26, O70, O73 |
| symlinks / special files | O03b, O17, O63, O66, O69 |
| credential residue / lifecycle | O18, O42, O49, O50, O52, O68 |
| malformed / spoofed / truncated review output | O19, O20_O21, O47, O76 |
| provider outage (review, plan, coding) | O22, O40, O45, O67 |
| planner == reviewer | O23 |
| invalid cards (schema, placeholders, cycles, types, inputs) | O24, O38, O59, O71, O75 |
| scenario-id collisions / registry | O58, O59, O62 |
| budgets (time gate, allocation, slot cap, attempts, deps, streak) | O12, O13, O14, O15, O36, O57, O67 |
| guardian contract (receipt gate, stdin liveness, spec vector, bindings) | O29, O48–O53, O69 |
| handoff gates (terminal cards, source review, e2e summary bound to sources, placeholders, seq) | O30, O41, O64, O72 |
| dispositions provenance | O25, O60, O74 |

---------------------------------------------------------------------------------------------------
## 11. Verification (how the operator and the frontier reviewer check this round)
- After P1: `python3 -B e2e/run_e2e.py` ⇒ `TOTAL 65 FAILED 0`; `frozen/orch-011.manifest.json.inventory_hash == state.orch_hash == state.parent_hash`;
  `python3 -B e2e/run_e2e.py O9999` ⇒ exit 3 `REGISTRY_INVALID`.
- After each card: `E2E_PASS` line, `evidence/<card>/<n>/{code,e2e,suite}/receipt.json` all `ok`+`reaped`; guardian receipt
  `TERMINATED/worker_reaped/credential_removed/exit 0`; `private-pi/` empty; lock absent; `REVIEW_ACCEPTED card:<id>`.
- After P5: suite `TOTAL 65+N FAILED 0` on the live source; `source_reviews['orch-012'] == orch_hash`; `milestone == ACCEPTED`
  with `milestone_revision == parent_hash` (C11), or an honest INCOMPLETE.
- P6: `HANDOFF-012.txt` printed; `RESULT-012.json.handoff_sha == sha256(HANDOFF-012.txt)`; no `{{` in the text.
- Hygiene: `~/.codex/auth.json` mtime unchanged; no file under `continuation-008/` changed except `pi-runtime-v2/jobs/*`;
  `continuation-010/`, `frozen/orch-00*` untouched.

Out of scope (unchanged): LoRA/training, dataset generation, wider esy fault matrix, general controller repairs, import into
original source. Even ACCEPTED authorizes none of these.

---------------------------------------------------------------------------------------------------
## Appendix A — orchestration scripts, verbatim baseline (`frozen/orch-010` == live `orch/`+`e2e/` on 2026-10-24) and out-of-tree contracts

Materialize these byte-exact on any machine, then apply §5. Fences use five backticks because the sources contain triple
backticks. Absolute machine paths appear ONLY in `env.sh` (never committed; see `env.sh.example`) and in the two sandbox
profiles (`pi-nofork-v3.sb`, `review-readonly.sb`), which must be regenerated for a different checkout path.

### orch/run_bounded.py  (sha256 30996abb900fcc59e0902c653042680d7b60449339e78a20dd6d47017dd7ad61, 6034 bytes)
`````python
#!/usr/bin/env python3
"""Sole process launcher: deadline, byte caps, process-group ownership, durable receipt.

Usage: run_bounded.py RECEIPT_JSON TIMEOUT_S CAP_BYTES CWD [--stdin FILE | --stdin-pipe] -- argv...
--stdin-pipe: the child's stdin is the read end of an os.pipe(); the launcher holds the write end
    open until the child is reaped (guardian liveness contract: EOF on stdin means the launcher is gone).
Exit: 0 receipt published (child may still have failed), 70 launcher refused, 71 ownership/reap uncertain.
"""
import json, os, selectors, signal, subprocess, sys, time

GRACE_TERM = 3.0     # SIGTERM -> SIGKILL
GRACE_EOF = 5.0      # reaped leader but pipes still open => descendants hold them => uncertain


def main():
    a = sys.argv[1:]
    sep = a.index('--')
    receipt, timeout, cap, cwd = a[0], float(a[1]), int(a[2]), a[3]
    stdin_path = None
    stdin_pipe = False
    opts = a[4:sep]
    while opts:
        if opts[0] == '--stdin' and len(opts) > 1:
            stdin_path = opts[1]; opts = opts[2:]
        elif opts[0] == '--stdin-pipe':
            stdin_pipe = True; opts = opts[1:]
        else:
            print('unknown option: ' + opts[0], file=sys.stderr)
            return 70
    argv = a[sep + 1:]
    start_wall, start = time.time(), time.monotonic()
    rec = {'schema': 1, 'argv_len': len(argv), 'start_wall': start_wall, 'status': 'launcher-error',
           'reaped': False, 'signal': None, 'timed_out': False, 'stdin_mode':
           'pipe' if stdin_pipe else ('file' if stdin_path else 'devnull'),
           'overflow': {'out': False, 'err': False}, 'ownership_uncertain': False}
    out_p, err_p = receipt + '.out', receipt + '.err'
    for p in (receipt, out_p, err_p, receipt + '.tmp'):
        if os.path.lexists(p):
            print('refusing to overwrite ' + p, file=sys.stderr)
            return 70
    child = None
    pipe_w = None
    bufs = {'out': bytearray(), 'err': bytearray()}
    try:
        if stdin_pipe:
            r_fd, pipe_w = os.pipe()
            stdin = os.fdopen(r_fd, 'rb')          # read end becomes the child's stdin
        else:
            stdin = open(stdin_path, 'rb') if stdin_path else subprocess.DEVNULL
        child = subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, close_fds=True)
        if stdin_path or stdin_pipe:              # DEVNULL is not a file object; parents keep only pipe_w
            stdin.close()
        rec['pid'] = child.pid
        sel = selectors.DefaultSelector()
        for name, pipe in (('out', child.stdout), ('err', child.stderr)):
            os.set_blocking(pipe.fileno(), False)
            sel.register(pipe, selectors.EVENT_READ, name)
        deadline = start + timeout
        term_at = None
        reaped_at = None
        reaped = False

        def send(sig, label):
            rec['signal'] = label
            try:
                os.killpg(child.pid, sig)   # only while the direct leader is owned and unreaped
            except ProcessLookupError:
                pass

        while True:
            now = time.monotonic()
            if not reaped:
                pid, st = os.waitpid(child.pid, os.WNOHANG)
                if pid:
                    reaped, reaped_at = True, now
                    rec['reaped'] = True
                    rec['exit'] = os.waitstatus_to_exitcode(st)
            if reaped and not sel.get_map():
                break
            if not reaped:
                if now >= deadline and rec['signal'] is None:
                    rec['timed_out'] = True
                    term_at = now
                    send(signal.SIGTERM, 'TERM')
                elif rec['signal'] == 'TERM' and now >= term_at + GRACE_TERM:
                    send(signal.SIGKILL, 'KILL')
                if any(rec['overflow'].values()) and rec['signal'] is None:
                    term_at = now
                    send(signal.SIGTERM, 'TERM')
            elif now > reaped_at + GRACE_EOF:
                rec['ownership_uncertain'] = True
                break
            events = sel.select(0.05) if sel.get_map() else (time.sleep(0.05) or [])
            for key, _ in events:
                data = os.read(key.fileobj.fileno(), 16384)
                if not data:
                    sel.unregister(key.fileobj)
                    continue
                b = bufs[key.data]
                room = cap - len(b)
                b.extend(data[:max(0, room)])
                if len(data) > room:
                    rec['overflow'][key.data] = True
        if pipe_w is not None:                     # child reaped (or loop exited): release the liveness pipe
            os.close(pipe_w)
            pipe_w = None
        if rec['ownership_uncertain']:
            rec['status'] = 'uncertain'
        elif rec['timed_out']:
            rec['status'] = 'timeout'
        elif any(rec['overflow'].values()):
            rec['status'] = 'overflow'
        else:
            rec['status'] = 'ok' if rec.get('exit') == 0 else 'child-failed'
    except BaseException as e:   # protect acquisition and interrupts; never claim a clean child
        rec['error'] = type(e).__name__
        if child is not None and not rec['reaped']:
            rec['ownership_uncertain'] = True
            rec['status'] = 'uncertain'
    finally:
        if pipe_w is not None:
            try:
                os.close(pipe_w)
            except OSError:
                pass
        rec['elapsed'] = round(time.monotonic() - start, 3)
        for p, b in ((out_p, bufs['out']), (err_p, bufs['err'])):
            with open(p, 'xb') as f:
                f.write(bytes(b)); f.flush(); os.fsync(f.fileno())
        tmp = receipt + '.tmp'
        with open(tmp, 'x') as f:
            json.dump(rec, f, sort_keys=True); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, receipt)
    return 71 if rec['ownership_uncertain'] else 0


if __name__ == '__main__':
    sys.exit(main())

`````

### orch/loop.py (orch-010 baseline; apply §5 D1–D15)  (sha256 0c433755eb7b89f5a86d440ffd5f1ac3f402b79a1cca0d988f5260d03d55d4d1, 54027 bytes)
`````python
#!/usr/bin/env python3
"""Workflow-loop driver. Stdlib only. Every gate fails closed; nothing 'continues anyway'."""
import argparse, hashlib, json, os, pathlib, re, shutil, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent
LIMITS = {'cap_launches': 48, 'time_ceiling': 32400.0, 'reserve': 180.0, 'code_need': 840.0,
          'review_need': 480.0, 'job_timeout': 600, 'review_timeout': 300, 'cap_bytes': 2 * 1024 * 1024,
          'max_attempts': 3, 'packet_cap': 400 * 1024, 'inputs_cap': 200 * 1024, 'receipt_cap': 16384,
          'smoke_timeout': 120}
# Workers get a fixed env, never the supervisor's full environment (mirrors bootstrap/launch_worker.py).
ENV_ALLOW = ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'SHELL', 'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS')


def base_env():
    e = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
    for k in filter(None, os.environ.get('ORCH_ENV_PASSTHROUGH', '').split(',')):   # explicit, for E2E fakes only
        if k in os.environ:
            e[k] = os.environ[k]
    return e
TERMINAL = {'ACCEPTED', 'SUPERSEDED', 'NEEDS_REPLAN', 'BLOCKED_CLEANUP_UNCERTAIN'}

RULES = """RULES (violating any rule = failure):
1. One objective. Edit ONLY files listed in ALLOWED_PATHS. Create nothing else.
2. Use only read/edit/write tools. Do not run, import, compile, test, or call providers.
3. Each single edit < 3000 characters; split larger changes into several edits.
4. Do not touch history, config/, uv.lock, adapters, or any file not in ALLOWED_PATHS.
5. Finish by printing exactly one line: CARD_DONE <card-id>. If blocked print CARD_BLOCKED <card-id>: <reason> and stop.
6. If instructions conflict, stop with CARD_BLOCKED. Never guess.
7. Never print or write credentials, tokens, or paths under private-pi.
"""


# ---------------------------------------------------------------- primitives
def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def jwrite(p, obj):
    t = str(p) + '.tmp'
    with open(t, 'w') as f:
        json.dump(obj, f, sort_keys=True, indent=1); f.flush(); os.fsync(f.fileno())
    os.replace(t, p)


def append_ledger(rec):
    rec = dict(rec, wall=time.time())
    fd = os.open(ROOT / 'ledger.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(rec, sort_keys=True) + '\n').encode()); os.fsync(fd)
    finally:
        os.close(fd)


def strict_json(b):
    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate key')
        return dict(pairs)
    return json.loads(b, object_pairs_hook=hook)


def read_bounded_json(path, limit):
    with open(path, 'rb') as f:
        b = f.read(limit + 1)          # read limit+1 BEFORE parsing
    if len(b) > limit:
        sys.exit('RECEIPT_TOO_LARGE ' + str(path))
    try:
        return strict_json(b)
    except ValueError as e:
        sys.exit('RECEIPT_INVALID %s: %s' % (path, e))


def load_env():
    env = {}
    p = ROOT / 'env.sh'
    if not p.is_file():
        sys.exit('ENV_MISSING: copy env.sh.example to env.sh')
    for line in p.read_text().splitlines():
        m = re.match(r'\s*export\s+([A-Z_]+)=(.*?)\s*(#.*)?$', line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"\'')
    return env


def load_state():
    p = ROOT / 'state.json'
    if not p.is_file():
        sys.exit('NOT_INITIALIZED')
    return read_bounded_json(p, 8 * 1024 * 1024)


def save_state(st):
    jwrite(ROOT / 'state.json', st)


class Lock:
    def __enter__(self):
        try:
            self.fd = os.open(ROOT / 'lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            sys.exit('LOCK_HELD: previous run uncertain or still active; inspect evidence')
        os.write(self.fd, str(os.getpid()).encode())
        self.keep = False
        return self

    def __exit__(self, *exc):
        os.close(self.fd)
        if not self.keep:
            os.unlink(ROOT / 'lock')
        return False


# ---------------------------------------------------------------- inventory / scope
def inventory(root):
    out = []
    for p in sorted(pathlib.Path(root).rglob('*')):
        if p.is_symlink():
            raise SystemExit('SYMLINK_IN_TREE ' + str(p))
        if p.is_dir():
            continue
        if not p.is_file():
            raise SystemExit('SPECIAL_FILE ' + str(p))
        out.append([str(p.relative_to(root)), oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
    return out


def inv_hash(inv):
    return sha_bytes(json.dumps(inv, sort_keys=True).encode())


def orch_source_inventory():
    """Inventory of the orchestration source itself: orch/*.py, orch/*.sh, env.sh.example, ../review-readonly.sb,
    ../e2e/*.py. A frozen snapshot with this exact relative layout hashes identically (see `review --subject`)."""
    rows = []
    for p in sorted(ROOT.iterdir()):
        if p.is_file() and not p.is_symlink() and p.name != 'env.sh' \
                and (p.suffix in ('.py', '.sh') or p.name == 'env.sh.example'):
            rows.append([p.name, oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
    sb = ROOT.parent / 'review-readonly.sb'
    if sb.is_file() and not sb.is_symlink():
        rows.append([sb.name, oct(sb.stat().st_mode & 0o777), sb.stat().st_size, sha(sb)])
    e2e = ROOT.parent / 'e2e'
    if e2e.is_dir():
        for p in sorted(e2e.glob('*.py')):
            if p.is_file() and not p.is_symlink():
                rows.append(['e2e/' + p.name, oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
    return sorted(rows)


def scope_verify(parent_inv, new_inv, allowed):
    p = {r[0]: r for r in parent_inv}
    n = {r[0]: r for r in new_inv}
    probs = []
    for path in sorted(set(p) | set(n)):
        if p.get(path) != n.get(path):
            if path not in allowed:
                probs.append('OUT_OF_SCOPE ' + path)
            if path not in n:
                probs.append('DELETED ' + path)
    for r in new_inv:
        if r[2] > LIMITS['cap_bytes']:
            probs.append('OVERSIZE ' + r[0])
    return (not probs, probs)


# ---------------------------------------------------------------- gates
def time_gate(st, need_total):
    avail = LIMITS['time_ceiling'] - st['active_seconds']
    if avail < need_total:
        sys.exit('TIME_GATE_FAILED avail=%.1f need=%.1f' % (avail, need_total))


def slot_gate(st):
    if st['launches_used'] >= LIMITS['cap_launches']:
        sys.exit('SLOT_CAP_REACHED')


def reserve_slot(st, card, attempt):
    st['launches_used'] += 1             # consumed BEFORE launch; never refunded
    append_ledger({'event': 'reserve', 'slot': st['launches_used'], 'card': card, 'attempt': attempt})
    save_state(st)


def check_auth_clean(env):
    d = env.get('AUTH_DIR')
    if d and (pathlib.Path(d) / 'auth.json').exists():
        return False
    return True


def guardian_bindings(env):
    """Validate the guardian-route bindings (absolute, non-symlink). Exits on any bad value."""
    for key, kind in (('PI_GUARDIAN', 'file'), ('PI_RUNTIME', 'dir'), ('BOOT_PYTHON', 'exe')):
        p = pathlib.Path(env.get(key) or '')
        if not str(p).startswith('/') or p.is_symlink() or not p.exists():
            sys.exit('%s_INVALID (absolute existing non-symlink %s required)' % (key, kind))
        if kind == 'file' and not p.is_file():
            sys.exit('PI_GUARDIAN_INVALID')
        if kind == 'dir' and not p.is_dir():
            sys.exit('PI_RUNTIME_INVALID')
        if kind == 'exe' and not (p.is_file() and os.access(p, os.X_OK)):
            sys.exit('BOOT_PYTHON_INVALID')


def worker_env(env):
    """Proven worker env (continuation-010/launch-correction.py): fixed allowlist + private runtime dirs."""
    r = pathlib.Path(env['PI_RUNTIME'])
    e = {k: os.environ[k] for k in ('PATH', 'LANG', 'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS') if k in os.environ}
    e.update(HOME=str(r / 'home'), PI_CODING_AGENT_DIR=str(r / 'private-pi'),
             PI_CODING_AGENT_SESSION_DIR=str(r / 'sessions'), PI_TELEMETRY='0', TMPDIR=str(r))
    return e


def coding_spec(env, tree, prompt, output, timeout):
    """Guardian spec whose argv is the exact worker-pi.sh vector (single source of truth for both)."""
    return {'argv': [env['SANDBOX_EXEC'], '-f', env['PI_PROFILE'], env['PI_BIN'], '--print', '--mode', 'json',
                     '--provider', env['PI_PROVIDER'], '--model', env['PI_CODING_MODEL'], '--thinking', 'high',
                     '--no-session', '--no-extensions', '--no-mcp', '--no-skills', '--no-prompt-templates',
                     '--no-context-files', '--no-themes', '--no-approve', '--offline', '--tools', 'read,edit,write',
                     '@' + str(prompt)],
            'env': worker_env(env), 'cwd': str(tree), 'output': str(output), 'timeout': int(timeout),
            'cap': LIMITS['cap_bytes'], 'auth_source': 'real'}


# ---------------------------------------------------------------- launching
def launch(lock, st, label, argv, timeout, cap, cwd, extra_env=None, stdin_pipe=False):
    """Run argv through run_bounded. Uncertainty keeps the lock and aborts; returns (receipt, out_text)."""
    d = ROOT / 'evidence' / label
    d.mkdir(parents=True, exist_ok=False)
    rc = d / 'receipt.json'
    cmd = [sys.executable, '-B', str(ROOT / 'run_bounded.py'), str(rc), str(timeout), str(cap), str(cwd)] \
        + (['--stdin-pipe'] if stdin_pipe else []) + ['--'] + argv
    env = dict(base_env(), **(extra_env or {}))
    p = subprocess.Popen(cmd, start_new_session=True, env=env)
    try:
        code = p.wait()
    except BaseException:
        lock.keep = True                   # interrupted: ownership uncertain, retain lock + evidence
        append_ledger({'event': 'interrupted', 'label': label})
        raise
    if code != 0 or not rc.exists():
        lock.keep = True
        append_ledger({'event': 'uncertain', 'label': label, 'runner_exit': code})
        return None, None
    rec = read_bounded_json(rc, LIMITS['receipt_cap'])
    st['active_seconds'] += rec['elapsed']
    save_state(st)
    append_ledger({'event': 'step', 'label': label, 'status': rec['status'], 'elapsed': rec['elapsed'],
                   'exit': rec.get('exit')})
    out = pathlib.Path(str(rc) + '.out').read_bytes().decode('utf-8', 'replace')
    return rec, out


def uncertain_stop(lock, st, card_id=None):
    lock.keep = True
    if card_id:
        st['cards'][card_id]['status'] = 'BLOCKED_CLEANUP_UNCERTAIN'
    save_state(st)
    sys.stderr.write('BLOCKED_CLEANUP_UNCERTAIN: lock and evidence retained; no automatic salvage\n')
    sys.exit(71)


# ---------------------------------------------------------------- cards
CARD_KEYS = {'id', 'objective', 'depends_on', 'allowed_paths', 'acceptance_rows', 'stop_condition', 'e2e', 'timeout'}
CARD_OPTIONAL = {'inputs_inline', 'base', 'replaces', 'max_edit_chars', 'parent_manifest', 'parent_hash'}


def validate_card(c):
    if not isinstance(c, dict):
        return 'card not an object'
    miss = CARD_KEYS - set(c)
    if miss:
        return 'missing keys %s' % sorted(miss)
    extra = set(c) - CARD_KEYS - CARD_OPTIONAL
    if extra:
        return 'unknown keys %s' % sorted(extra)
    if not isinstance(c['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', c['id']):
        return 'bad id'
    if not isinstance(c['objective'], str) or not c['objective'].strip() or '\n' in c['objective']:
        return 'objective must be one non-empty line'
    ap = c['allowed_paths']
    if not isinstance(ap, list) or not 1 <= len(ap) <= 3:
        return 'allowed_paths must list 1..3 paths'
    for x in ap:
        if not isinstance(x, str) or x.startswith('/') or '..' in pathlib.PurePosixPath(x).parts or not x:
            return 'bad allowed path %r' % (x,)
    if not isinstance(c['timeout'], int) or not 1 <= c['timeout'] <= LIMITS['job_timeout']:
        return 'timeout must be int 1..600'
    e = c['e2e']
    if not isinstance(e, dict) or not isinstance(e.get('argv'), list) or not e['argv'] \
            or not all(isinstance(x, str) for x in e['argv']) or not isinstance(e.get('expect_status'), int):
        return 'e2e needs argv list and int expect_status'
    if not isinstance(c['depends_on'], list) or not isinstance(c['acceptance_rows'], list) or not c['acceptance_rows']:
        return 'depends_on / acceptance_rows malformed'
    machine = {'id': c['id'], 'objective': c['objective'], 'allowed_paths': ap, 'depends_on': c['depends_on'],
               'argv': e['argv'], 'expect_files': e.get('expect_files', []), 'inputs_inline': c.get('inputs_inline', [])}
    if re.search(r'<[^<>\n]*>|TODO', json.dumps(machine)):      # prose rows may quote "<card-id>" legitimately
        return 'placeholder text (<...> or TODO) in a machine-consumed field'
    return None


def check_acyclic(cards):
    seen = {}

    def visit(i, stack):
        if i in stack:
            return False
        if seen.get(i):
            return True
        for d in cards[i]['depends_on']:
            if d in cards and not visit(d, stack | {i}):
                return False
        seen[i] = True
        return True
    return all(visit(i, frozenset()) for i in cards)


def load_cards():
    cards = {}
    for p in sorted((ROOT / 'cards').glob('*.json')):
        c = read_bounded_json(p, 256 * 1024)
        err = validate_card(c)
        if err:
            sys.exit('CARD_INVALID %s: %s' % (p.name, err))
        if c['id'] in cards:
            sys.exit('CARD_DUPLICATE ' + c['id'])
        cards[c['id']] = c
    if not check_acyclic(cards):
        sys.exit('CARD_CYCLE')
    return cards


def dep_satisfied(st, d):
    s = st['cards'].get(d)
    if not s:
        return False
    if s['status'] == 'ACCEPTED':
        return True
    if s['status'] == 'SUPERSEDED' and s.get('superseded_by'):
        return all(dep_satisfied(st, x) for x in s['superseded_by'])
    return False


def assemble_prompt(c, st, base_dir):
    parts = [RULES, 'CARD_ID: %s' % c['id'], 'OBJECTIVE: %s' % c['objective'],
             'PARENT_HASH: %s' % st['parent_hash'], 'ALLOWED_PATHS: %s' % ','.join(c['allowed_paths']),
             'ACCEPTANCE_ROWS:'] + ['- ' + r for r in c['acceptance_rows']]
    parts.append('STOP_CONDITION: %s' % c['stop_condition'])
    total = 0
    for rel in c.get('inputs_inline', []):
        p = pathlib.Path(base_dir) / rel
        if p.is_symlink() or not p.is_file() or rel.startswith('/') or '..' in pathlib.PurePosixPath(rel).parts:
            sys.exit('INPUT_INVALID ' + rel)
        data = p.read_bytes()
        total += len(data)
        if total > LIMITS['inputs_cap']:
            sys.exit('INPUTS_TOO_LARGE')
        parts.append('--- INPUT %s ---\n%s\n--- END INPUT ---' % (rel, data.decode('utf-8', 'replace')))
    parts.append('Finish per rule 5 now.')
    return '\n'.join(parts) + '\n'


# ---------------------------------------------------------------- commands
def cmd_init(a):
    if (ROOT / 'state.json').exists():
        sys.exit('ALREADY_INITIALIZED')
    env = load_env()
    for k in ('PI_BIN', 'SANDBOX_EXEC', 'PI_PROFILE', 'REVIEW_PROFILE'):
        v = env.get(k, '')
        if not v.startswith('/') or os.path.islink(v) or not os.path.exists(v):
            sys.exit('ENV_BAD %s=%r (absolute existing non-symlink required)' % (k, v))
    parent = pathlib.Path(a.parent).resolve()
    inv = inventory(parent)
    h = inv_hash(inv)
    if a.expected_entries is not None and len(inv) != a.expected_entries:
        sys.exit('PARENT_ENTRY_COUNT %d != %d' % (len(inv), a.expected_entries))
    if a.expected_hash and h != a.expected_hash:
        sys.exit('PARENT_HASH_MISMATCH')
    st = {'launches_used': a.launches_used, 'active_seconds': a.active_seconds, 'parent_dir': str(parent),
          'parent_hash': h, 'cards': {}, 'reviews': [], 'reviewer_backend': 'codex', 'pending_findings': [],
          'review_subjects': [], 'milestone': 'OPEN', 'review_seq': 0,
          'orch_hash': inv_hash(orch_source_inventory()), 'source_reviews': {}, 'smokes': {}}
    cards = load_cards()
    for cid in cards:
        st['cards'][cid] = {'status': 'PENDING', 'attempts': 0}
    save_state(st)
    append_ledger({'event': 'init', 'parent_hash': h, 'entries': len(inv), 'cards': sorted(cards)})
    print('INIT_OK parent_hash=%s entries=%d cards=%d' % (h, len(inv), len(cards)))


def cmd_status(a):
    print(json.dumps(load_state(), sort_keys=True, indent=1))


def cmd_rebind_orch(a):
    """After a root-authored orchestration fix: bind the new source hash. Acceptance needs a fresh source review."""
    with Lock():
        st = load_state()
        old, new = st['orch_hash'], inv_hash(orch_source_inventory())
        if old == new:
            print('ORCH_UNCHANGED ' + new)
            return
        st['orch_hash'] = new
        save_state(st)
        append_ledger({'event': 'rebind_orch', 'old': old, 'new': new})
        print('ORCH_REBOUND %s -> %s (source review required again)' % (old[:12], new[:12]))


def cmd_backfill_review(a):
    """Re-parse a retained review receipt into state.last_review (for reviews run before persistence existed)."""
    with Lock():
        st = load_state()
        rec = [r for r in st['reviews'] if r['seq'] == a.seq]
        if len(rec) != 1:
            sys.exit('REVIEW_SEQ_UNKNOWN')
        outp = ROOT / 'evidence' / ('review-%03d' % a.seq) / 'run' / 'receipt.json.out'
        if not outp.is_file() or outp.is_symlink():
            sys.exit('REVIEW_EVIDENCE_MISSING')
        out = outp.read_text()
        v = parse_verdict(out)
        if v is None or [f['id'] for f in v['findings']] != rec[0]['findings']:
            sys.exit('REVIEW_EVIDENCE_MISMATCH')
        st['last_review'] = {'seq': a.seq, 'scope': rec[0]['scope'], 'revision': v['revision'],
                             'verdict': {k: v[k] for k in ('revision', 'findings', 'missing_evidence', 'coverage',
                                                           'cleanup', 'verdict')}, 'backfilled_from': str(outp),
                             'out_sha': sha_bytes(out.encode())}
        save_state(st)
        append_ledger({'event': 'backfill_review', 'seq': a.seq, 'out_sha': st['last_review']['out_sha']})
        print('REVIEW_BACKFILLED seq=%d findings=%d' % (a.seq, len(v['findings'])))


def cmd_set_parent(a):
    """Point future cards at a newer frozen tree. Refused while any card is mid-flight."""
    with Lock():
        st = load_state()
        busy = [k for k, v in st['cards'].items() if v['status'] in ('RESERVED', 'E2E_PASS', 'REVIEW_FINDINGS')]
        if busy:
            sys.exit('SET_PARENT_BLOCKED mid-flight cards: %s' % busy)
        d = pathlib.Path(a.dir)
        if not d.is_absolute() or d.is_symlink() or not d.is_dir():
            sys.exit('PARENT_INVALID')
        new = inv_hash(inventory(d))
        append_ledger({'event': 'set_parent', 'old': st['parent_hash'], 'new': new, 'dir': str(d)})
        st['parent_dir'], st['parent_hash'] = str(d), new
        save_state(st)
        print('PARENT_SET %s' % new)


def cmd_note_interval(a):
    """Record root-authored active time that no launch receipt covers. Only ever adds time."""
    with Lock():
        st = load_state()
        if not (0 < a.seconds <= 36000):
            sys.exit('INTERVAL_INVALID')
        st['active_seconds'] += a.seconds
        save_state(st)
        append_ledger({'event': 'root_interval', 'seconds': a.seconds, 'basis': a.basis,
                       'start_wall': a.start_wall, 'end_wall': a.end_wall})
        print('INTERVAL_NOTED active=%.3f remaining=%.3f' % (st['active_seconds'],
                                                             LIMITS['time_ceiling'] - st['active_seconds']))


def cmd_read_receipt(a):
    print(json.dumps(read_bounded_json(a.file, LIMITS['receipt_cap']), sort_keys=True))


def fail_attempt(st, cid, why):
    cs = st['cards'][cid]
    cs['status'] = 'NEEDS_REPLAN' if cs['attempts'] >= LIMITS['max_attempts'] else 'FAILED'
    cs['last_failure'] = why
    save_state(st)
    append_ledger({'event': 'attempt_failed', 'card': cid, 'attempt': cs['attempts'], 'why': why})
    sys.stderr.write('ATTEMPT_FAILED %s: %s -> %s\n' % (cid, why, cs['status']))
    sys.exit(1)


def cmd_retire_card(a):
    """Root-authored retirement of a card back to NEEDS_REPLAN (e.g. planner defect found before launch)."""
    if not a.reason or not a.reason.strip():
        sys.exit('RETIRE_NEEDS_REASON')
    with Lock():
        st = load_state()
        cs = st['cards'].get(a.id)
        if not cs:
            sys.exit('UNKNOWN_CARD')
        if cs['status'] not in ('PENDING', 'FAILED'):
            sys.exit('RETIRE_BLOCKED status=' + cs['status'])
        cs['status'] = 'NEEDS_REPLAN'
        cs['retired_reason'] = a.reason
        save_state(st)
        append_ledger({'event': 'retire_card', 'card': a.id, 'reason': a.reason})
        print('CARD_RETIRED %s -> NEEDS_REPLAN (replan must replace it)' % a.id)


def cmd_run_card(a):
    env = load_env()
    with Lock() as L:
        st = load_state()
        cards = load_cards()
        if a.id not in cards:
            sys.exit('UNKNOWN_CARD')
        c = cards[a.id]
        cs = st['cards'].setdefault(a.id, {'status': 'PENDING', 'attempts': 0})
        if cs['status'] not in ('PENDING', 'FAILED'):
            sys.exit('CARD_NOT_RUNNABLE status=' + cs['status'])
        if cs['attempts'] >= LIMITS['max_attempts']:
            sys.exit('ATTEMPTS_EXHAUSTED: replan required')
        for d in c['depends_on']:
            if not dep_satisfied(st, d):
                sys.exit('DEPENDENCY_NOT_ACCEPTED ' + d)
        if env.get('PI_GUARDIAN'):
            guardian_bindings(env)
        base_id = c.get('base')
        if base_id:
            bs = st['cards'].get(base_id, {})
            if not bs.get('tree'):
                sys.exit('BASE_TREE_MISSING ' + base_id)
            base_dir, base_hash = bs['tree'], bs['tree_hash']
        else:
            base_dir, base_hash = st['parent_dir'], st['parent_hash']
        parent_inv = inventory(base_dir)
        if inv_hash(parent_inv) != base_hash:
            sys.exit('PARENT_HASH_MISMATCH')
        if not check_auth_clean(env):
            uncertain_stop(L, st)
        slot_gate(st)
        time_gate(st, LIMITS['code_need'])
        attempt = cs['attempts'] + 1
        reserve_slot(st, a.id, attempt)
        cs['attempts'] = attempt
        cs['status'] = 'RESERVED'
        save_state(st)
        job_timeout = min(c['timeout'], LIMITS['job_timeout'])
        if env.get('PI_GUARDIAN'):
            # Real-credential route: the job tree MUST live under PI_RUNTIME (the pi profile denies reads/writes
            # elsewhere under /Users/psac); the worker runs via the guardian with auth_source=real.
            job = pathlib.Path(env['PI_RUNTIME']) / 'jobs' / ('%s-%d' % (a.id, attempt))
            if job.exists():
                fail_attempt(st, a.id, 'JOB_DIR_EXISTS ' + str(job))
            job.mkdir(parents=True, mode=0o700)
            tree = job / 'tree'
            shutil.copytree(base_dir, tree)
            prompt = job / 'prompt.txt'
            prompt.write_text(assemble_prompt(dict(c), dict(st, parent_hash=base_hash), base_dir))
            append_ledger({'event': 'prompt', 'card': a.id, 'attempt': attempt, 'sha': sha(prompt)})
            spec = coding_spec(env, tree, prompt, job / 'guardian', job_timeout)
            jwrite(job / 'spec.json', spec)
            append_ledger({'event': 'guardian_spec', 'card': a.id, 'attempt': attempt, 'sha': sha(job / 'spec.json'),
                           'output': str(job / 'guardian')})
            rec, _ = launch(L, st, '%s/%d/code' % (a.id, attempt),
                            [env['BOOT_PYTHON'], '-B', env['PI_GUARDIAN'], str(job / 'spec.json')],
                            job_timeout + 30, 1 << 20, str(job), stdin_pipe=True)
            if rec is None:
                uncertain_stop(L, st, a.id)
            if rec['status'] != 'ok' or not rec.get('reaped'):
                uncertain_stop(L, st, a.id)
            gp = job / 'guardian' / 'receipt.json'
            g = None
            if gp.is_file() and not gp.is_symlink():
                try:
                    g = read_bounded_json(gp, LIMITS['receipt_cap'])
                except SystemExit:
                    g = None
            append_ledger({'event': 'guardian_receipt', 'card': a.id, 'attempt': attempt,
                           'status': None if g is None else g.get('status'),
                           'worker_reaped': None if g is None else g.get('worker_reaped'),
                           'exit_code': None if g is None else g.get('exit_code'),
                           'credential_removed': None if g is None else g.get('credential_removed'),
                           'reason': None if g is None else g.get('reason')})
            if g is None or g.get('status') != 'TERMINATED' or g.get('worker_reaped') is not True \
                    or g.get('credential_removed') is not True or g.get('exit_code') != 0:
                uncertain_stop(L, st, a.id)      # never interpret a missing/bad receipt as "zero children"
            gout = job / 'guardian' / 'stdout'
            out = gout.read_bytes()[:LIMITS['cap_bytes']].decode('utf-8', 'replace') if gout.is_file() else ''
        else:
            job = ROOT / 'jobs' / ('%s-%d' % (a.id, attempt))
            if job.exists():
                fail_attempt(st, a.id, 'JOB_DIR_EXISTS ' + str(job))
            job.mkdir(parents=True, mode=0o700)
            tree = job / 'tree'
            shutil.copytree(base_dir, tree)
            prompt = job / 'prompt.txt'
            prompt.write_text(assemble_prompt(dict(c), dict(st, parent_hash=base_hash), base_dir))
            append_ledger({'event': 'prompt', 'card': a.id, 'attempt': attempt, 'sha': sha(prompt)})
            rec, out = launch(L, st, '%s/%d/code' % (a.id, attempt),
                              ['/bin/bash', str(ROOT / 'worker-pi.sh'), 'code', str(tree), str(prompt), env['PI_PROFILE']],
                              job_timeout, LIMITS['cap_bytes'], str(tree))
            if rec is None:
                uncertain_stop(L, st, a.id)
            if rec['status'] == 'uncertain':
                uncertain_stop(L, st, a.id)
            if rec['status'] != 'ok':
                fail_attempt(st, a.id, 'worker-' + rec['status'])
        if ('CARD_BLOCKED %s' % a.id) in out:
            fail_attempt(st, a.id, 'worker reported CARD_BLOCKED')
        if ('CARD_DONE %s' % a.id) not in out:
            fail_attempt(st, a.id, 'missing CARD_DONE')
        if not check_auth_clean(env):
            uncertain_stop(L, st, a.id)
        try:
            new_inv = inventory(tree)
        except SystemExit as e:
            fail_attempt(st, a.id, str(e))
        ok, probs = scope_verify(parent_inv, new_inv, set(c['allowed_paths']))
        if not ok:
            fail_attempt(st, a.id, 'scope: ' + '; '.join(probs))
        if inv_hash(new_inv) == inv_hash(parent_inv):
            fail_attempt(st, a.id, 'no change produced')
        manifest = {'card': a.id, 'attempt': attempt, 'parent_hash': base_hash, 'inventory': new_inv,
                    'tree_hash': inv_hash(new_inv)}
        jwrite(job / 'result-manifest.json', manifest)
        e = c['e2e']
        t = int(e.get('timeout', 20))
        rec2, _ = launch(L, st, '%s/%d/e2e' % (a.id, attempt), list(e['argv']), min(t, 200), 1 << 20, str(tree))
        if rec2 is None or rec2['status'] == 'uncertain':
            uncertain_stop(L, st, a.id)
        if not rec2['reaped'] or rec2.get('exit') != e['expect_status'] or rec2['status'] in ('timeout', 'overflow'):
            fail_attempt(st, a.id, 'e2e status %s/%s' % (rec2['status'], rec2.get('exit')))
        for f in e.get('expect_files', []):
            if not (tree / f).is_file():
                fail_attempt(st, a.id, 'e2e missing file ' + f)
        cs.update(status='E2E_PASS', tree=str(tree), tree_hash=manifest['tree_hash'])
        save_state(st)
        print('E2E_PASS %s attempt=%d tree_hash=%s' % (a.id, attempt, manifest['tree_hash']))


# ---------------------------------------------------------------- review / plan
def text_candidates(raw):
    cands = [raw]

    def walk(x):
        if isinstance(x, str):
            cands.append(x)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)
    for chunk in [raw] + raw.splitlines():
        try:
            walk(json.loads(chunk))
        except ValueError:
            pass
    return cands


def extract_block(raw):
    blocks = set()
    for t in text_candidates(raw):
        for m in re.findall(r'```json\s*(\{.*?\})\s*```', t, re.S):
            blocks.add(m)
    if len(blocks) != 1:
        return None
    try:
        return strict_json(next(iter(blocks)))
    except ValueError:
        return None


UNAVAILABLE_MARKERS = ('usage limit', 'rate limit', 'quota', 'not logged in', 'unauthorized', 'authentication')


def provider_error(raw):
    """Codex emits JSONL {'type':'error'|'turn.failed'}; Claude emits one object with is_error/result."""
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get('type') in ('error', 'turn.failed'):
            err = ev.get('error') if isinstance(ev.get('error'), dict) else {}
            return str(ev.get('message') or err.get('message') or ev.get('type'))
        if ev.get('type') == 'result' and ev.get('is_error'):
            return str(ev.get('result') or 'is_error')
    return None


def provider_stop(st, label, msg):
    """Classify a provider-side failure: unavailable (75) versus other provider error (74). Never a fallback."""
    append_ledger({'event': 'provider_failed', 'label': label, 'message': msg[:300]})
    save_state(st)
    if any(m in msg.lower() for m in UNAVAILABLE_MARKERS):
        sys.stderr.write('BLOCKED_PROVIDER_UNAVAILABLE: %s\n' % msg[:300])
        sys.exit(75)
    sys.stderr.write('PROVIDER_ERROR: %s\n' % msg[:300])
    sys.exit(74)


def parse_verdict(raw):
    v = extract_block(raw)
    if v is None:
        return None
    need = {'revision', 'findings', 'missing_evidence', 'coverage', 'cleanup', 'verdict'}
    if set(v) != need or v['verdict'] not in ('ACCEPTED', 'INCOMPLETE', 'BLOCKED'):
        return None
    if not isinstance(v['findings'], list) or not isinstance(v['missing_evidence'], list) \
            or not isinstance(v['coverage'], dict):
        return None
    for f in v['findings']:
        if not isinstance(f, dict) or not isinstance(f.get('id'), str):
            return None
    if v['coverage'].get('complete') is not True or v['coverage'].get('truncated') is not False:
        v['verdict'] = 'INCOMPLETE' if v['verdict'] == 'ACCEPTED' else v['verdict']
        v['_coverage_bad'] = True
    if v['findings'] or v['missing_evidence']:
        v['verdict'] = 'INCOMPLETE' if v['verdict'] == 'ACCEPTED' else v['verdict']
    return v


def run_model(L, st, env, label, role, prompt_text, backend, timeout=None):
    """One model invocation with a private runtime (proven route: private CODEX_HOME/TMPDIR under the writable
    evidence subtree; auth.json is a SYMLINK to the real credential, created just before launch and unlinked after)."""
    d = ROOT / 'evidence' / label
    d.mkdir(parents=True, exist_ok=False)
    pf = d / 'packet.txt'
    pf.write_text(prompt_text)
    ws = d / 'ws'
    ws.mkdir(mode=0o700)
    rt = d / 'runtime'
    for sub in ('codex', 'tmp', 'claude'):
        (rt / sub).mkdir(parents=True, mode=0o700)
    extra = {'REVIEW_BACKEND': backend, 'TMPDIR': str(rt / 'tmp')}
    auth_link = None
    if backend == 'codex':
        extra['CODEX_HOME'] = str(rt / 'codex')
        real = pathlib.Path.home() / '.codex' / 'auth.json'
        if real.is_file():
            auth_link = rt / 'codex' / 'auth.json'
            os.symlink(real, auth_link)            # never a copy; the sandbox denies writes to the real file
    else:
        extra.update(DISABLE_AUTOUPDATER='1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
        # Private config dir => CLI reports "Not logged in" (observed). CLAUDE_REAL_CONFIG=1 keeps the real
        # config dir untouched; the strict review profile stays authoritative either way and already permitted
        # every write the real-config route needed (review-004/005, plan-008) - it was never widened (F7).
        if env.get('CLAUDE_REAL_CONFIG') != '1':
            extra['CLAUDE_CONFIG_DIR'] = str(rt / 'claude')
    try:
        res = launch(L, st, label + '/run',
                     ['/bin/bash', str(ROOT / 'worker-claude.sh'), role, str(ws), str(pf), env['REVIEW_PROFILE']],
                     timeout or LIMITS['review_timeout'], 1 << 20, str(ws), extra)
    finally:
        if auth_link is not None:
            try:
                os.unlink(auth_link)
            except FileNotFoundError:
                pass
            if os.path.lexists(auth_link):
                L.keep = True
                append_ledger({'event': 'credential_residue', 'label': label})
                sys.exit('CREDENTIAL_RESIDUE: %s still present; lock retained' % auth_link)
        append_ledger({'event': 'credential_lifecycle', 'label': label, 'backend': backend,
                       'symlink_used': auth_link is not None, 'removed': True})
    return pf, res


def build_packet(st, scope, subject_tree, revision, subjects):
    lines = ['ROLE: REVIEWER', 'SCOPE: %s' % scope, 'REVISION: %s' % revision,
             'NO TOOLS: you cannot read files or run commands; everything is inline. Do not emit tool calls.',
             'You are an independent reviewer. Do not edit or execute. Return exactly ONE fenced json block with keys '
             'revision, findings[{id,severity,location,evidence}], missing_evidence[], coverage{complete,truncated}, '
             'cleanup, verdict (ACCEPTED|INCOMPLETE|BLOCKED). ACCEPTED requires zero findings and zero missing evidence.',
             'ACCOUNTING: launches_used=%d/%d active_seconds=%.1f/%.0f' % (
                 st['launches_used'], LIMITS['cap_launches'], st['active_seconds'], LIMITS['time_ceiling'])]
    inv = inventory(subject_tree)
    lines.append('INVENTORY:')
    lines += ['  %s %s %d %s' % tuple(r) for r in inv]
    lines.append('DISPOSITIONS: ' + json.dumps(st.get('dispositions', {}), sort_keys=True) +
                 ' (standing dispositions for prior findings; re-raise a finding only if the disposition no '
                 'longer holds, and say what changed)')
    total = 0
    for r in inv:
        data = (pathlib.Path(subject_tree) / r[0]).read_bytes()
        total += len(data)
        if total > LIMITS['packet_cap']:
            sys.exit('PACKET_TOO_LARGE: indexed review parts are not implemented; split scope')
        lines.append('--- FILE %s ---\n%s\n--- END FILE ---' % (r[0], data.decode('utf-8', 'replace')))
    for s in subjects:
        lines.append('PRIOR_DISPOSITIONS: ' + json.dumps(s))
    return '\n'.join(lines) + '\n'


def cmd_review(a):
    env = load_env()
    with Lock() as L:
        st = load_state()
        if a.backend:
            st['reviewer_backend'] = a.backend
        if st['pending_findings']:
            sys.exit('UNDISPOSED_FINDINGS: replan must disposition %s' % st['pending_findings'])
        time_gate(st, LIMITS['review_need'])
        if a.smoke and not a.subject:
            sys.exit('SMOKE_NEEDS_SUBJECT')
        if a.subject and a.card:
            sys.exit('SUBJECT_AND_CARD_EXCLUSIVE')
        if a.subject:
            sd = pathlib.Path(a.subject)
            if not sd.is_absolute() or sd.is_symlink() or not sd.is_dir():
                sys.exit('SUBJECT_INVALID')
            name = a.name or sd.name
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}', name):
                sys.exit('SUBJECT_NAME_INVALID')
            tree, revision = str(sd), inv_hash(inventory(sd))
            scope = ('smoke:' if a.smoke else 'source:') + name
        elif a.card:
            cs = st['cards'].get(a.card)
            if not cs or cs['status'] != 'E2E_PASS':
                sys.exit('CARD_NOT_REVIEWABLE')
            tree, revision = cs['tree'], cs['tree_hash']
            scope = 'card:' + a.card
        else:
            open_cards = [k for k, v in st['cards'].items() if v['status'] not in ('ACCEPTED', 'SUPERSEDED')]
            if open_cards:
                sys.exit('FINAL_REVIEW_BLOCKED open cards: %s' % open_cards)
            tree, revision, scope = st['parent_dir'], st['parent_hash'], 'final'
        st['review_seq'] += 1
        save_state(st)
        label = 'review-%03d' % st['review_seq']
        if a.packet:
            pf = pathlib.Path(a.packet)
            if not pf.is_file() or pf.is_symlink() or sha(pf) != a.sha:
                sys.exit('PACKET_HASH_MISMATCH')
            text = pf.read_text()
        else:
            text = build_packet(st, scope, tree, revision, st['reviews'][-3:] and [
                {'id': r['seq'], 'verdict': r['verdict']} for r in st['reviews'][-3:]])
        if a.smoke:
            text += ('SMOKE: this is a transport smoke. In the "cleanup" field write the string "MODEL=<your model '
                     'name>" so provenance can be checked. Keep the response under 2000 characters.\n')
        pf, (rec, out) = run_model(L, st, env, label, 'review', text, st['reviewer_backend'],
                                   LIMITS['smoke_timeout'] if a.smoke else None)
        append_ledger({'event': 'review_packet', 'label': label, 'sha': sha(pf), 'scope': scope})
        if rec is None or rec['status'] == 'uncertain':
            uncertain_stop(L, st)
        if rec.get('exit') == 75:
            save_state(st)
            sys.stderr.write('BLOCKED_PROVIDER_UNAVAILABLE: no fallback model is permitted\n')
            sys.exit(75)
        perr = provider_error(out)
        if perr:
            provider_stop(st, label, perr)
        if rec['status'] != 'ok':
            save_state(st)
            sys.exit('REVIEW_TRANSPORT_FAILED ' + rec['status'])
        v = parse_verdict(out)
        if v is None:
            save_state(st)
            sys.exit('REVIEW_MALFORMED: no acceptance; a fresh review is required')
        if v['revision'] != revision:
            save_state(st)
            sys.exit('REVIEW_REVISION_MISMATCH')
        if a.smoke:   # transport proven; never touches acceptance state
            st['smokes'][name] = {'backend': st['reviewer_backend'], 'exit': rec.get('exit'), 'elapsed': rec['elapsed'],
                                  'out_sha': sha_bytes(out.encode()), 'verdict': v['verdict'],
                                  'cleanup': str(v.get('cleanup'))[:200], 'label': label}
            save_state(st)
            append_ledger({'event': 'smoke', 'name': name, 'backend': st['reviewer_backend'], 'label': label})
            print('SMOKE_OK %s backend=%s cleanup=%s' % (name, st['reviewer_backend'], str(v.get('cleanup'))[:200]))
            return
        accepted = (v['verdict'] == 'ACCEPTED' and not v['findings'] and not v['missing_evidence']
                    and not v.get('_coverage_bad'))
        st['last_review'] = {'seq': st['review_seq'], 'scope': scope, 'revision': revision,
                             'verdict': {k: v[k] for k in ('revision', 'findings', 'missing_evidence', 'coverage',
                                                           'cleanup', 'verdict')}}
        st['reviews'].append({'seq': st['review_seq'], 'scope': scope, 'backend': st['reviewer_backend'],
                              'verdict': 'ACCEPTED' if accepted else (v['verdict'] if v['verdict'] != 'ACCEPTED' else 'INCOMPLETE'),
                              'findings': [f['id'] for f in v['findings']], 'missing': len(v['missing_evidence']),
                              'packet_sha': sha(pf)})
        if accepted:
            if a.subject:
                st['source_reviews'][name] = revision
            elif a.card:
                cs['status'] = 'ACCEPTED'
                st['parent_dir'], st['parent_hash'] = tree, revision
            else:
                st['milestone'] = 'ACCEPTED'
            save_state(st)
            print('REVIEW_ACCEPTED ' + scope)
            return
        ids = [f['id'] for f in v['findings']]
        for i in range(len(v['missing_evidence'])):
            mid = 'M%d' % i
            while mid in ids:                       # never collide with reviewer-authored M-ids
                mid += 'x'
            ids.append(mid)
        if not ids:
            ids = ['COVERAGE']
        undispositioned = [i for i in ids if i not in st.get('dispositions', {})]
        st['pending_findings'] = undispositioned    # a finding WITH a standing disposition does not block (§8)
        st['review_subjects'] = [a.card] if a.card else []
        if a.card:
            st['cards'][a.card]['status'] = 'REVIEW_FINDINGS'
        save_state(st)
        sys.stderr.write('REVIEW_NOT_ACCEPTED findings=%s\n' % ids)
        sys.exit(2)


def cmd_replan(a):
    env = load_env()
    with Lock() as L:
        st = load_state()
        other = 'fable' if st['reviewer_backend'] == 'codex' else 'codex'
        backend = a.backend or other
        if backend == st['reviewer_backend']:
            if not a.same_backend_approved:
                sys.exit('PLANNER_MUST_DIFFER from reviewer backend (pass --same-backend-approved "<who/when>")')
            st.setdefault('same_backend_approvals', []).append(
                {'backend': backend, 'approval': a.same_backend_approved, 'review_seq': st['review_seq'],
                 'wall': time.time()})
            append_ledger({'event': 'same_backend_approval', 'backend': backend, 'approval': a.same_backend_approved})
        time_gate(st, LIMITS['review_need'])
        subjects = [k for k, v in st['cards'].items() if v['status'] in ('REVIEW_FINDINGS', 'NEEDS_REPLAN')]
        if not st['pending_findings'] and not subjects:
            sys.exit('NOTHING_TO_REPLAN')
        existing = load_cards()
        inv = inventory(st['parent_dir'])
        e2e_src = pathlib.Path(st['parent_dir']) / 'e2e' / 'run_e2e.py'
        try:
            e2e_ids = sorted(set(re.findall(r'^def (O\d+)\b', e2e_src.read_text(), re.M))) if e2e_src.is_file() else []
        except OSError:
            e2e_ids = []
        example = {'id': 'X1', 'objective': 'one-line concern', 'depends_on': [], 'allowed_paths': ['loop.py'],
                   'acceptance_rows': ['R1 ...'], 'stop_condition': 'print CARD_BLOCKED if ...',
                   'e2e': {'argv': ['/usr/bin/python3', '-B', 'e2e/run_e2e.py', 'O01'], 'expect_status': 0,
                           'expect_files': []}, 'timeout': 600}
        prompt = '\n'.join([
            'ROLE: PLANNER',
            'NO TOOLS: you cannot read files, list directories or run commands. Everything you need is in this packet. '
            'Do not emit tool calls; answer with text only.',
            'Emit ONE fenced json block {"cards":[...],"dispositions":{...}} (<=4 cards).',
            'EXAMPLE_CARD: ' + json.dumps(example, sort_keys=True),
            'PARENT_TREE (cards edit paths relative to this tree; e2e argv runs with cwd=tree, no shell):',
            ] + ['  %s %s %d %s' % tuple(r) for r in inv] + [
            'REVIEW_JSON: ' + json.dumps(st.get('last_review'), sort_keys=True),
            'Each card keys: id,objective(one line),depends_on,allowed_paths(1-3 relative),acceptance_rows,'
            'stop_condition,e2e{argv,expect_status,expect_files},timeout(<=600); optional base,replaces - both are '
            'CARD IDS only, never hashes: base = build on that accepted card\'s tree instead of the parent tree, '
            'replaces = the subject card id this new card supersedes. One concern per card.',
            'No placeholders. Dispositions are required ONLY for the ids in FINDING_IDS (often none) as '
            'card:<id> | rejected:<why> | deferred:<why>; existing dispositions stand unchanged - do not '
            're-disposition already-dispositioned findings.',
            'EXISTING_DISPOSITIONS: ' + json.dumps(st.get('dispositions', {}), sort_keys=True),
            'EXISTING_E2E_IDS: ' + ','.join(e2e_ids),
            'Any e2e scenario id a new card references (in e2e.argv or acceptance rows) must NOT be in '
            'EXISTING_E2E_IDS; pick fresh ids larger than every listed id.',
            'FINDING_IDS: ' + ','.join(st['pending_findings']), 'REPLACES: ' + ','.join(subjects),
            'EXISTING_CARD_IDS: ' + ','.join(sorted(existing)),
            'BUDGET: launches_used=%d/%d active=%.1f/%.0f' % (st['launches_used'], LIMITS['cap_launches'],
                                                             st['active_seconds'], LIMITS['time_ceiling']),
            'PARENT_HASH: ' + st['parent_hash'], RULES])
        st['review_seq'] += 1
        save_state(st)
        pf, (rec, out) = run_model(L, st, env, 'plan-%03d' % st['review_seq'], 'plan', prompt, backend)
        if rec is None or rec['status'] == 'uncertain':
            uncertain_stop(L, st)
        if rec.get('exit') == 75:
            save_state(st)
            sys.stderr.write('BLOCKED_PROVIDER_UNAVAILABLE\n')
            sys.exit(75)
        perr = provider_error(out)
        if perr:
            provider_stop(st, 'plan-%03d' % st['review_seq'], perr)
        if rec['status'] != 'ok':
            save_state(st)
            sys.exit('PLANNER_TRANSPORT_FAILED ' + rec['status'])
        plan = extract_block(out)
        if not isinstance(plan, dict) or set(plan) != {'cards', 'dispositions'} or not isinstance(plan['cards'], list) \
                or not 0 <= len(plan['cards']) <= 4 or not isinstance(plan['dispositions'], dict):
            save_state(st)
            sys.exit('PLAN_MALFORMED')
        new = {}
        for c in plan['cards']:
            err = validate_card(c)
            if err:
                save_state(st)
                sys.exit('PLAN_CARD_INVALID: ' + str(err))
            if c['id'] in existing or c['id'] in new:
                save_state(st)
                sys.exit('PLAN_CARD_DUPLICATE ' + c['id'])
            new[c['id']] = c
        allc = dict(existing, **new)
        for c in new.values():
            for d in c['depends_on'] + ([c['base']] if c.get('base') else []):
                if d not in allc:
                    sys.exit('PLAN_UNKNOWN_DEP ' + d)
        if not check_acyclic(allc):
            sys.exit('PLAN_CYCLE')
        for fid in st['pending_findings']:
            disp = plan['dispositions'].get(fid)
            if not isinstance(disp, str) or not re.fullmatch(r'(card:[A-Za-z0-9_-]+|rejected:.+|deferred:.+)', disp):
                sys.exit('PLAN_MISSING_DISPOSITION ' + fid)
            if disp.startswith('card:') and disp[5:] not in new:
                sys.exit('PLAN_DISPOSITION_UNKNOWN_CARD ' + disp)
        replaced = {}
        for c in new.values():
            if c.get('replaces'):
                replaced.setdefault(c['replaces'], []).append(c['id'])
        for s in subjects:
            if s not in replaced:
                sys.exit('PLAN_DOES_NOT_REPLACE ' + s)
        for k, ids in replaced.items():
            if k not in subjects:
                sys.exit('PLAN_REPLACES_NON_SUBJECT ' + k)
        for cid, c in new.items():
            jwrite(ROOT / 'cards' / (cid + '.json'), c)
            st['cards'][cid] = {'status': 'PENDING', 'attempts': 0}
        for k, ids in replaced.items():
            st['cards'][k].update(status='SUPERSEDED', superseded_by=ids)
        append_ledger({'event': 'replan', 'planner': backend, 'new_cards': sorted(new),
                       'dispositions': plan['dispositions']})
        st['dispositions'] = dict(st.get('dispositions', {}), **plan['dispositions'])
        st['pending_findings'] = []
        save_state(st)
        print('REPLAN_OK planner=%s new=%s' % (backend, sorted(new)))


# ---------------------------------------------------------------- handoff
REVIEW_TEMPLATE = """You are the independent final reviewer of review-worker adapter acceptance ONLY. You may not edit,
execute code, delegate, or infer runtime evidence from source closure. Read ALL inline material.
REVISION: {{revision}}
CARDS & DISPOSITIONS: {{cards}}
DISPOSITIONS: {{dispositions}}
ACCOUNTING: {{accounting}}
REVIEW HISTORY: {{reviews}}
SOURCE INVENTORY:
{{inventory}}
TASK: check correctness, regressions, provenance, process ownership, finite-failure contract, every acceptance
criterion. Zero findings with missing evidence is NOT acceptance. Return exactly ONE fenced json block with keys
revision, findings[{id,severity,location,evidence}], missing_evidence[], coverage{complete,truncated}, cleanup,
verdict (ACCEPTED|INCOMPLETE|BLOCKED). Output outside the block is ignored.
"""


def cmd_handoff(a):
    with Lock() as L:
        st = load_state()
        open_cards = [k for k, v in st['cards'].items() if v['status'] not in TERMINAL]
        if open_cards:
            sys.exit('HANDOFF_BLOCKED non-terminal cards: %s' % open_cards)
        live = inv_hash(orch_source_inventory())
        if live != st['orch_hash']:
            sys.exit('HANDOFF_BLOCKED orchestration source changed since init (%s != %s)' % (live[:12], st['orch_hash'][:12]))
        if st['orch_hash'] not in st['source_reviews'].values():
            sys.exit('HANDOFF_BLOCKED no accepted source review of the orchestration snapshot %s' % st['orch_hash'][:12])
        inv = inventory(st['parent_dir'])
        parts = [REVIEW_TEMPLATE]
        subst = {'revision': st['parent_hash'], 'cards': json.dumps(st['cards'], sort_keys=True),
                 'dispositions': json.dumps(st.get('dispositions', {}), sort_keys=True),
                 'accounting': 'launches %d/%d, active %.1f/%.0f s, remaining %.1f s' % (
                     st['launches_used'], LIMITS['cap_launches'], st['active_seconds'], LIMITS['time_ceiling'],
                     LIMITS['time_ceiling'] - st['active_seconds']),
                 'reviews': json.dumps({'reviews': st['reviews'], 'source_reviews': st['source_reviews'],
                                        'smokes': st['smokes'], 'orch_hash': st['orch_hash']}, sort_keys=True),
                 'inventory': '\n'.join('  %s %s %d %s' % tuple(r) for r in inv)}
        prompt = REVIEW_TEMPLATE
        for k, v in subst.items():
            prompt = prompt.replace('{{%s}}' % k, v)
        if '{{' in prompt:
            sys.exit('HANDOFF_UNFILLED_PLACEHOLDER')
        verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED' else (
            'BLOCKED' if any(v['status'] == 'BLOCKED_CLEANUP_UNCERTAIN' for v in st['cards'].values()) else 'INCOMPLETE')
        ledger = (ROOT / 'ledger.jsonl').read_text() if (ROOT / 'ledger.jsonl').exists() else ''
        text = '\n'.join(['HANDOFF-011', 'MILESTONE VERDICT: ' + verdict, 'REVISION: ' + st['parent_hash'],
                          'ACCOUNTING: ' + subst['accounting'], 'CARDS: ' + subst['cards'],
                          'LEDGER:', ledger, '=== FULL REVIEW PROMPT ===', prompt, '=== END ==='])
        out_dir = ROOT.parent
        (out_dir / 'HANDOFF-011.txt').write_text(text)
        jwrite(out_dir / 'RESULT-011.json', {'verdict': verdict, 'revision': st['parent_hash'],
                                              'launches_used': st['launches_used'], 'active_seconds': st['active_seconds'],
                                              'handoff_sha': sha_bytes(text.encode())})
        print(text)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('init'); p.add_argument('--parent', required=True)
    p.add_argument('--active-seconds', type=float, default=24923.746)
    p.add_argument('--launches-used', type=int, default=36)
    p.add_argument('--expected-hash'); p.add_argument('--expected-entries', type=int)
    p.set_defaults(f=cmd_init)
    sub.add_parser('status').set_defaults(f=cmd_status)
    sub.add_parser('rebind-orch').set_defaults(f=cmd_rebind_orch)
    p = sub.add_parser('note-interval'); p.add_argument('--seconds', type=float, required=True)
    p.add_argument('--basis', required=True); p.add_argument('--start-wall', type=float); p.add_argument('--end-wall', type=float)
    p.set_defaults(f=cmd_note_interval)
    p = sub.add_parser('read-receipt'); p.add_argument('file'); p.set_defaults(f=cmd_read_receipt)
    p = sub.add_parser('run-card'); p.add_argument('id'); p.set_defaults(f=cmd_run_card)
    p = sub.add_parser('retire-card'); p.add_argument('id'); p.add_argument('--reason', required=True)
    p.set_defaults(f=cmd_retire_card)
    p = sub.add_parser('review'); p.add_argument('--card'); p.add_argument('--backend', choices=['codex', 'fable'])
    p.add_argument('--packet'); p.add_argument('--sha')
    p.add_argument('--subject'); p.add_argument('--name'); p.add_argument('--smoke', action='store_true')
    p.set_defaults(f=cmd_review)
    p = sub.add_parser('replan'); p.add_argument('--backend', choices=['codex', 'fable'])
    p.add_argument('--same-backend-approved', help='explicit user approval text; required when planner == reviewer')
    p.set_defaults(f=cmd_replan)
    p = sub.add_parser('set-parent'); p.add_argument('dir'); p.set_defaults(f=cmd_set_parent)
    p = sub.add_parser('backfill-review'); p.add_argument('--seq', type=int, required=True); p.set_defaults(f=cmd_backfill_review)
    sub.add_parser('handoff').set_defaults(f=cmd_handoff)
    a = ap.parse_args()
    try:
        a.f(a)
    except KeyboardInterrupt:
        sys.stderr.write('INTERRUPTED: lock retained if a launch was in flight\n')
        sys.exit(130)


if __name__ == '__main__':
    main()

`````

### orch/worker-common.sh  (sha256 eaeb222c7222de1948386864f2e6e5b2c1017c442f2fcf33904b79be4274250c, 363 bytes)
`````bash
die(){ echo "worker: $*" >&2; exit 64; }
abs_file(){ [[ "$1" = /* && -f "$1" && ! -L "$1" ]] || die "absolute regular non-symlink file required: $2"; }
abs_dir(){  [[ "$1" = /* && -d "$1" && ! -L "$1" ]] || die "absolute non-symlink dir required: $2"; }
abs_exe(){  [[ "$1" = /* && -x "$1" && ! -L "$1" ]] || die "absolute executable non-symlink required: $2"; }

`````

### orch/worker-claude.sh  (sha256 38ef74e29ebef801152c47bff28bf35810bf994b0b6645ba50e6919a590ea35c, 1507 bytes)
`````bash
#!/bin/bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/worker-common.sh"; . "$here/env.sh"
[[ $# -eq 4 ]] || die "usage: ROLE WORKSPACE PROMPT PROFILE"
role=$1; ws=$2; prompt=$3; profile=$4
abs_dir "$ws" workspace; abs_file "$prompt" prompt; abs_file "$profile" profile
abs_exe "${SANDBOX_EXEC:-}" SANDBOX_EXEC
case "$role" in
  review|plan)
    case "${REVIEW_BACKEND:-codex}" in
      codex) exec /bin/bash "$here/worker-codex.sh" "$role" "$ws" "$prompt" "$profile" ;;
      fable) : "${CLAUDE_BIN:?}"; : "${CLAUDE_FABLE_MODEL:?}"; abs_exe "$CLAUDE_BIN" CLAUDE_BIN
             cd "$ws"
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

`````

### orch/worker-codex.sh  (sha256 95d84e148bf07d7388fa68845d32c4f75b1a235c9d20e903fc124cf0ec0c7142, 359 bytes)
`````bash
#!/bin/bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/worker-common.sh"; . "$here/env.sh"
[[ $# -eq 4 ]] || die "usage: ROLE WORKSPACE PROMPT PROFILE"
abs_exe "${CODEX_BIN:-}" CODEX_BIN; abs_file "${CODEX_WORKER:-}" CODEX_WORKER
exec /bin/bash "$CODEX_WORKER" "$1" "$2" "$3" "$4" "$CODEX_BIN"   # model/sandbox fixed inside frozen script

`````

### orch/worker-pi.sh  (sha256 2b6b3a65582bce07667e679a7a6ebe16105adc1d724cb40a9635bf6146f1ebc3, 726 bytes)
`````bash
#!/bin/bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/worker-common.sh"; . "$here/env.sh"
[[ $# -eq 4 && "$1" = code ]] || die "usage: code WORKSPACE PROMPT PROFILE"
ws=$2; prompt=$3; profile=$4
abs_dir "$ws" workspace; abs_file "$prompt" prompt; abs_file "$profile" profile
abs_exe "${PI_BIN:-}" PI_BIN; abs_exe "${SANDBOX_EXEC:-}" SANDBOX_EXEC
: "${PI_PROVIDER:?}"; : "${PI_CODING_MODEL:?}"
cd "$ws"
exec "$SANDBOX_EXEC" -f "$profile" "$PI_BIN" --print --mode json --provider "$PI_PROVIDER" --model "$PI_CODING_MODEL" \
  --thinking high --no-session --no-extensions --no-mcp --no-skills --no-prompt-templates \
  --no-context-files --no-themes --no-approve --offline --tools read,edit,write "@$prompt"

`````

### orch/env.sh.example  (sha256 9e62f5745c02c242b4d0c2d81782be4e5e2a85268d7d338c0865b785e7bd7bf2, 723 bytes)
`````bash
# Copy to env.sh. All values absolute. One `export KEY=VALUE` per line (loop.py parses this file literally).
export CLAUDE_BIN=/absolute/path/to/claude
export CLAUDE_FABLE_MODEL=claude-fable-5-1
export CLAUDE_CODING_MODEL=
export CODEX_BIN=/absolute/path/to/codex
export CODEX_WORKER=/absolute/path/to/codex-worker.sh
export PI_BIN=/opt/homebrew/bin/pi
export PI_PROVIDER=openai-codex
export PI_CODING_MODEL=gpt-6-luna
export SANDBOX_EXEC=/usr/bin/sandbox-exec
export PI_PROFILE=/absolute/path/to/pi-nofork-v3.sb
export REVIEW_PROFILE=/absolute/path/to/review-readonly.sb
export PI_RUNTIME=/absolute/path/to/pi-runtime-v2
export PI_GUARDIAN=
export BOOT_PYTHON=/usr/bin/python3
export AUTH_DIR=
export CLAUDE_REAL_CONFIG=0

`````

### review-readonly.sb (REVIEW_PROFILE; paths are checkout-specific)  (sha256 5de083549af36aa541d86c9d9aef82600dc93df1c0b3ee0e23f40e59905bb861, 661 bytes)
`````text
(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-011/orch/evidence"))
(allow file-write* (subpath "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-011/tmp"))
(deny network-outbound (remote unix-socket))
(allow network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))
(allow network-outbound (remote unix-socket (path-literal "/var/run/mDNSResponder")))
(deny signal)
(allow signal (target self) (target children))

`````

### e2e/run_e2e.py (orch-010 baseline; apply §5.2)  (sha256 267274ad1e3cb25696034216b9392d4a9a6dc75d4a292beb74fcf24d622a3ca0, 41090 bytes)
`````python
#!/usr/bin/env python3
"""E2E-ORCH suite. Every case copies the REAL orch/ scripts into a temp root, points env.sh at fake CLIs
(run as real processes) and drives loop.py / the worker scripts as subprocesses. No imports of orch code."""
import json, os, pathlib, shutil, signal, subprocess, sys, tempfile, time, traceback

HERE = pathlib.Path(__file__).resolve().parent
# In the continuation layout the orch scripts sit in ../orch; in a flat card tree (loop.py next to
# e2e/) the tree root IS the orch source, so a card's own e2e.argv can run this file in-tree.
ORCH_SRC = HERE.parent / 'orch' if (HERE.parent / 'orch').is_dir() else HERE.parent
ENGINE = HERE / 'fake_engine.py'
PY = sys.executable


class Box:
    def __init__(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='orche2e-')).resolve()
        self.orch = self.tmp / 'orch'
        self.orch.mkdir()
        (self.orch / 'cards').mkdir()
        for f in ORCH_SRC.iterdir():
            if f.is_file() and f.suffix in ('.py', '.sh'):
                shutil.copy2(f, self.orch / f.name)
        self.fakes = self.tmp / 'fakes'
        self.fakes.mkdir()
        for name, kind in (('pi', 'pi'), ('claude', 'claude'), ('codex', 'codex'), ('sandbox-exec', 'sandbox')):
            self.fake(name, '#!/bin/bash\nexec %s %s %s "$@"\n' % (PY, ENGINE, kind))
        self.fake('codex-worker.sh', '#!/bin/bash\nexec "$5" "$1" --prompt "$3"\n')
        (self.tmp / 'pi.sb').write_text('(version 1)\n')
        (self.tmp / 'review.sb').write_text('(version 1)\n')
        self.parent = self.tmp / 'parent'
        for rel, txt in (('src/a.txt', 'a\n'), ('src/b.txt', 'b\n'), ('docs/c.txt', 'c\n')):
            p = self.parent / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt)
        self.argv_log = self.tmp / 'argv.log'
        self.write_env()

    def fake(self, name, body):
        p = self.fakes / name
        p.write_text(body)
        p.chmod(0o755)

    def write_env(self, **over):
        v = dict(CLAUDE_BIN=self.fakes / 'claude', CLAUDE_FABLE_MODEL='claude-fable-5-1', CLAUDE_CODING_MODEL='',
                 CODEX_BIN=self.fakes / 'codex', CODEX_WORKER=self.fakes / 'codex-worker.sh',
                 PI_BIN=self.fakes / 'pi', PI_PROVIDER='openai-codex', PI_CODING_MODEL='gpt-6-luna',
                 SANDBOX_EXEC=self.fakes / 'sandbox-exec', PI_PROFILE=self.tmp / 'pi.sb',
                 REVIEW_PROFILE=self.tmp / 'review.sb', PI_GUARDIAN='', PI_RUNTIME='',
                 BOOT_PYTHON=pathlib.Path(PY).resolve(),
                 AUTH_DIR='', CLAUDE_REAL_CONFIG='0')
        v.update(over)
        (self.orch / 'env.sh').write_text(''.join('export %s=%s\n' % (k, x) for k, x in v.items()))

    def card(self, cid, **kw):
        c = {'id': cid, 'objective': 'edit the file', 'depends_on': [], 'allowed_paths': ['src/a.txt'],
             'acceptance_rows': ['R1 file edited'], 'stop_condition': 'stop if unsure',
             'e2e': {'argv': ['/bin/cat', 'src/a.txt'], 'expect_status': 0, 'expect_files': ['src/a.txt']},
             'timeout': 30}
        c.update(kw)
        (self.orch / 'cards' / (cid + '.json')).write_text(json.dumps(c))

    def loop(self, *args, env=None, timeout=90):
        e = dict(os.environ, FAKE_ARGV_LOG=str(self.argv_log), LEAK_CANARY='1',
                 ORCH_ENV_PASSTHROUGH='FAKE_ARGV_LOG,FAKE_PI,FAKE_REVIEW,FAKE_PLAN,FAKE_PLAN_BASE,FAKE_WRAP,'
                                      'FAKE_GUARDIAN,FAKE_GUARDIAN_AUTH_DIR',
                 **(env or {}))
        r = subprocess.run([PY, '-B', str(self.orch / 'loop.py')] + [str(a) for a in args], capture_output=True,
                           text=True, env=e, timeout=timeout)
        return r.returncode, r.stdout, r.stderr

    def init(self, *extra):
        rc, o, e = self.loop('init', '--parent', self.parent, *extra)
        assert rc == 0, 'init failed: ' + e
        return o

    def state(self):
        return json.loads((self.orch / 'state.json').read_text())

    def ledger(self):
        p = self.orch / 'ledger.jsonl'
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def argv_entries(self):
        return [json.loads(x) for x in self.argv_log.read_text().splitlines()] if self.argv_log.exists() else []

    def snapshot(self, name='snap'):
        """Frozen copy of the orchestration source with the layout orch_source_inventory() hashes."""
        d = self.tmp / name
        d.mkdir()
        for f in self.orch.iterdir():
            if f.is_file() and f.suffix in ('.py', '.sh') and f.name != 'env.sh':
                shutil.copy2(f, d / f.name)
        return d

    def source_review(self, scen='accepted'):
        return self.loop('review', '--subject', self.snapshot('snap-%d' % len(list(self.tmp.iterdir()))),
                         '--name', 'orch', env={'FAKE_REVIEW': scen})

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def eq(a, b, msg=''):
    assert a == b, '%s expected %r got %r' % (msg, b, a)


def has(hay, needle, msg=''):
    assert needle in hay, '%s missing %r in %r' % (msg, needle, hay[-400:])


def accepted_card(b, cid='A'):
    rc, o, e = b.loop('run-card', cid, env={'FAKE_PI': 'ok'})
    eq(rc, 0, 'run-card ' + e)
    rc, o, e = b.loop('review', '--card', cid, env={'FAKE_REVIEW': 'accepted'})
    eq(rc, 0, 'review ' + e)


def guardian_env(b, **over):
    """Point env.sh at the real e2e/fake_guardian.py (run as a real process via BOOT_PYTHON)."""
    rt = b.tmp / 'pi-runtime'
    (rt / 'private-pi').mkdir(parents=True, exist_ok=True)
    b.write_env(PI_GUARDIAN=HERE / 'fake_guardian.py', PI_RUNTIME=rt, BOOT_PYTHON=pathlib.Path(PY).resolve(),
                AUTH_DIR=rt / 'private-pi', **over)
    return rt


# ------------------------------------------------------------------ scenarios
def O01(b):
    b.card('A'); b.init()
    accepted_card(b)
    st = b.state()
    eq(st['cards']['A']['status'], 'ACCEPTED'); eq(st['launches_used'], 37)
    assert st['parent_hash'] != '' and not (b.orch / 'lock').exists()
    assert any(r['event'] == 'reserve' and r['slot'] == 37 for r in b.ledger())
    rc, o, e = b.loop('review', env={'FAKE_REVIEW': 'accepted'})
    eq(rc, 0, e); eq(b.state()['milestone'], 'ACCEPTED')
    rc, o, e = b.source_review(); eq(rc, 0, e)
    rc, o, e = b.loop('handoff'); eq(rc, 0, e)
    has(o, 'MILESTONE VERDICT: ACCEPTED'); has(o, 'FULL REVIEW PROMPT'); has(o, 'source_reviews')


def _fail_case(b, scen, needle, status='FAILED'):
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': scen})
    eq(rc, 1, e); has(e, needle)
    st = b.state()
    eq(st['cards']['A']['status'], status); eq(st['launches_used'], 37)
    return st


def O02(b): _fail_case(b, 'oos', 'OUT_OF_SCOPE evil.txt')
def O03a(b): _fail_case(b, 'delete', 'DELETED src/a.txt')
def O03b(b): _fail_case(b, 'symlink', 'SYMLINK_IN_TREE')
def O06(b): _fail_case(b, 'blocked', 'CARD_BLOCKED'); assert not (b.orch / 'evidence/A/1/e2e').exists()
def O07(b): _fail_case(b, 'silent', 'missing CARD_DONE')
def O34(b): _fail_case(b, 'fail_exit', 'worker-child-failed')
def O35(b): _fail_case(b, 'noop_done', 'no change produced')


def O04(b):
    b.card('A', timeout=1); b.init()
    t = time.time()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ignore_term'})
    eq(rc, 1, e); has(e, 'worker-timeout')
    r = json.loads((b.orch / 'evidence/A/1/code/receipt.json').read_text())
    eq(r['signal'], 'KILL'); assert r['reaped'] and r['timed_out'], r
    assert time.time() - t < 20


def O05(b):
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'overflow'})
    eq(rc, 1, e); has(e, 'worker-overflow')
    rp = b.orch / 'evidence/A/1/code/receipt.json'
    r = json.loads(rp.read_text())
    assert r['overflow']['out'] and r['reaped'], r
    assert os.path.getsize(str(rp) + '.out') <= 2 * 1024 * 1024


def O08(b):
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'grandchild'})
    eq(rc, 71, e); has(e, 'BLOCKED_CLEANUP_UNCERTAIN')
    assert (b.orch / 'lock').exists()
    eq(b.state()['cards']['A']['status'], 'BLOCKED_CLEANUP_UNCERTAIN')
    rc, o, e = b.loop('run-card', 'A'); assert rc != 0; has(e, 'LOCK_HELD')
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'LOCK_HELD')


def O09(b):
    b.card('A'); b.init()
    env = dict(os.environ, FAKE_PI='slow', FAKE_ARGV_LOG=str(b.argv_log), ORCH_ENV_PASSTHROUGH='FAKE_ARGV_LOG,FAKE_PI')
    p = subprocess.Popen([PY, '-B', str(b.orch / 'loop.py'), 'run-card', 'A'], env=env, stderr=subprocess.PIPE, text=True)
    rp = b.orch / 'evidence/A/1/code'
    for _ in range(100):
        if rp.exists():
            break
        time.sleep(0.1)
    time.sleep(0.5)
    p.send_signal(signal.SIGINT)
    err = p.communicate(timeout=30)[1]
    eq(p.returncode, 130, err)
    assert (b.orch / 'lock').exists()
    eq(b.state()['cards']['A']['status'], 'RESERVED')
    rc, o, e = b.loop('run-card', 'A'); assert rc != 0; has(e, 'LOCK_HELD')
    for _ in range(100):                      # let the orphaned supervised worker finish by itself
        if (rp / 'receipt.json').exists():
            break
        time.sleep(0.1)


def O10(b):
    b.card('A'); b.card('B', allowed_paths=['src/b.txt'], e2e={'argv': ['/bin/cat', 'src/b.txt'], 'expect_status': 0, 'expect_files': []})
    b.init()
    env = dict(os.environ, FAKE_PI='slow', FAKE_ARGV_LOG=str(b.argv_log), ORCH_ENV_PASSTHROUGH='FAKE_ARGV_LOG,FAKE_PI')
    p1 = subprocess.Popen([PY, '-B', str(b.orch / 'loop.py'), 'run-card', 'A'], env=env, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    rc, o, e = b.loop('run-card', 'B', env={'FAKE_PI': 'ok'})
    assert rc != 0; has(e, 'LOCK_HELD')
    eq(p1.wait(timeout=60), 0)
    eq(b.state()['cards']['A']['status'], 'E2E_PASS')
    eq(b.state()['launches_used'], 37)


def O11(b):
    b.card('A'); b.init()
    (b.orch / 'state.json.tmp').write_text('{garbage')
    rc, o, e = b.loop('status'); eq(rc, 0, e)
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)
    eq(b.state()['cards']['A']['status'], 'E2E_PASS')


def O12(b):
    b.card('A'); b.init('--launches-used', '48')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'})
    assert rc != 0; has(e, 'SLOT_CAP_REACHED')
    assert not (b.orch / 'jobs').exists(); eq(b.state()['launches_used'], 48)


def O13(b):
    b.card('A'); b.init('--active-seconds', '31800')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'})
    assert rc != 0; has(e, 'TIME_GATE_FAILED')
    assert not (b.orch / 'jobs').exists(); eq(b.state()['launches_used'], 36)


def O14(b):
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'silent'}); eq(rc, 1, e)
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)
    eq([r['slot'] for r in b.ledger() if r['event'] == 'reserve'], [37, 38])
    eq(b.state()['cards']['A']['attempts'], 2)


def O15(b):
    b.card('A'); b.init()
    for _ in range(3):
        rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'silent'}); eq(rc, 1, e)
    eq(b.state()['cards']['A']['status'], 'NEEDS_REPLAN')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); assert rc != 0; has(e, 'CARD_NOT_RUNNABLE')
    eq(b.state()['launches_used'], 39)


def O16(b):
    b.card('A'); b.init()
    (b.parent / 'src/b.txt').write_text('tampered\n')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); assert rc != 0; has(e, 'PARENT_HASH_MISMATCH')
    eq(b.state()['launches_used'], 36)
    b2 = Box()
    try:
        b2.card('A')
        rc, o, e = b2.loop('init', '--parent', b2.parent, '--expected-hash', '0' * 64)
        assert rc != 0; has(e, 'PARENT_HASH_MISMATCH')
        rc, o, e = b2.loop('init', '--parent', b2.parent, '--expected-entries', '82')
        assert rc != 0; has(e, 'PARENT_ENTRY_COUNT')
    finally:
        b2.close()


def O17(b):
    ws = b.tmp / 'ws'; ws.mkdir()
    pr = b.tmp / 'p.txt'; pr.write_text('x')
    def run(**over):
        b.write_env(**over)
        r = subprocess.run(['/bin/bash', str(b.orch / 'worker-pi.sh'), 'code', str(ws), str(pr), str(b.tmp / 'pi.sb')],
                           capture_output=True, text=True)
        return r.returncode, r.stderr
    rc, e = run(PI_BIN='relative/pi'); eq(rc, 64); has(e, 'PI_BIN')
    link = b.tmp / 'pilink'; os.symlink(b.fakes / 'pi', link)
    rc, e = run(PI_BIN=link); eq(rc, 64); has(e, 'PI_BIN')
    (b.fakes / 'nox').write_text('#!/bin/bash\n')
    rc, e = run(PI_BIN=b.fakes / 'nox'); eq(rc, 64)
    r = subprocess.run(['/bin/bash', str(b.orch / 'worker-claude.sh'), 'review', str(ws), str(pr), str(b.tmp / 'review.sb'), 'extra'],
                       capture_output=True, text=True); eq(r.returncode, 64)
    r = subprocess.run(['/bin/bash', str(b.orch / 'worker-claude.sh'), 'bogus', str(ws), str(pr), str(b.tmp / 'review.sb')],
                       capture_output=True, text=True); eq(r.returncode, 64)


def O18(b):
    ad = b.tmp / 'authdir'; ad.mkdir()
    b.write_env(AUTH_DIR=ad)
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'auth'})
    eq(rc, 71, e); assert (b.orch / 'lock').exists()
    eq(b.state()['cards']['A']['status'], 'BLOCKED_CLEANUP_UNCERTAIN')
    b2 = Box()
    try:
        ad2 = b2.tmp / 'authdir'; ad2.mkdir(); (ad2 / 'auth.json').write_text('{}')
        b2.write_env(AUTH_DIR=ad2); b2.card('A'); b2.init()
        rc, o, e = b2.loop('run-card', 'A', env={'FAKE_PI': 'ok'})
        eq(rc, 71, e); assert not (b2.orch / 'jobs').exists()
    finally:
        b2.close()


def _to_e2e_pass(b):
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)


def O19(b):
    _to_e2e_pass(b)
    for scen in ('two_blocks', 'extra_keys', 'prose', 'truncated', 'badrev'):
        rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': scen})
        assert rc != 0, scen
        eq(b.state()['cards']['A']['status'], 'E2E_PASS', scen)
        eq(b.state()['pending_findings'], [], scen)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'accept_with_findings'})
    eq(rc, 2, e); eq(b.state()['cards']['A']['status'], 'REVIEW_FINDINGS')


def O20_O21(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'trunc_cov'})
    eq(rc, 2, e); eq(b.state()['reviews'][-1]['verdict'], 'INCOMPLETE')
    b2 = Box()
    try:
        _to_e2e_pass(b2)
        rc, o, e = b2.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'missing_ev'})
        eq(rc, 2, e); eq(b2.state()['pending_findings'], ['M0'])
        rc, o, e = b2.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'accepted'})
        assert rc != 0; has(e, 'UNDISPOSED_FINDINGS')
    finally:
        b2.close()


def O22(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'unavailable'})
    eq(rc, 75, e); has(e, 'BLOCKED_PROVIDER_UNAVAILABLE')
    eq(b.state()['cards']['A']['status'], 'E2E_PASS')
    kinds = [x['kind'] for x in b.argv_entries()]
    assert 'claude' not in kinds, kinds          # no substitution of another model
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'findings'}); eq(rc, 2, e)
    rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'unavailable'}); eq(rc, 75, e)


def O23(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'findings'}); eq(rc, 2, e)
    rc, o, e = b.loop('replan', '--backend', 'codex', env={'FAKE_PLAN': 'valid'})
    assert rc != 0; has(e, 'PLANNER_MUST_DIFFER')
    assert not (b.orch / 'cards/X1.json').exists()
    rc, o, e = b.loop('replan', '--backend', 'codex', '--same-backend-approved', 'user ok', env={'FAKE_PLAN': 'valid'})
    eq(rc, 0, e); assert (b.orch / 'cards/X1.json').exists()
    st = b.state(); eq(st['same_backend_approvals'][0]['approval'], 'user ok')
    assert st['last_review']['verdict']['findings'][0]['id'] == 'F1'
    plans = sorted((b.orch / 'evidence').glob('plan-*/packet.txt')); eq(len(plans), 1)
    pk = plans[0].read_text()
    has(pk, 'REVIEW_JSON'); has(pk, '"evidence": "bad"'); has(pk, 'src/a.txt')      # review + parent tree inlined


def O47(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'findings'}); eq(rc, 2, e)
    st = json.loads((b.orch / 'state.json').read_text()); del st['last_review']
    (b.orch / 'state.json').write_text(json.dumps(st))                      # simulate a pre-persistence review
    rc, o, e = b.loop('backfill-review', '--seq', '9'); assert rc != 0; has(e, 'REVIEW_SEQ_UNKNOWN')
    rc, o, e = b.loop('backfill-review', '--seq', '1'); eq(rc, 0, e)
    lr = b.state()['last_review']; eq(lr['verdict']['findings'][0]['id'], 'F1'); assert lr['out_sha']
    outp = b.orch / 'evidence/review-001/run/receipt.json.out'
    outp.write_text(outp.read_text().replace('"F1"', '"F9"'))
    rc, o, e = b.loop('backfill-review', '--seq', '1'); assert rc != 0; has(e, 'REVIEW_EVIDENCE_MISMATCH')


def O46(b):
    b.card('A'); b.init()
    h0 = b.state()['parent_hash']
    rc, o, e = b.loop('set-parent', 'relative'); assert rc != 0; has(e, 'PARENT_INVALID')
    np = b.tmp / 'parent2'; shutil.copytree(b.parent, np); (np / 'src/a.txt').write_text('v2\n')
    rc, o, e = b.loop('set-parent', np); eq(rc, 0, e)
    st = b.state(); assert st['parent_hash'] != h0; eq(st['parent_dir'], str(np))
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)
    assert open(b.orch / 'jobs/A-1/tree/src/a.txt').read().startswith('v2')
    rc, o, e = b.loop('set-parent', b.parent); assert rc != 0; has(e, 'SET_PARENT_BLOCKED')


def O24(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'findings'}); eq(rc, 2, e)
    for scen in ('placeholder', 'placeholder_argv', 'badpath', 'toomany', 'cyclic', 'nodisp'):
        rc, o, e = b.loop('replan', env={'FAKE_PLAN': scen})
        assert rc != 0, scen
        eq(sorted(p.name for p in (b.orch / 'cards').iterdir()), ['A.json'], scen)
        eq(b.state()['pending_findings'], ['F1'], scen)
    eq(b.state()['cards']['A']['status'], 'REVIEW_FINDINGS')
    rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'angle_in_rows'}); eq(rc, 0, e)   # prose may quote <card-id>
    assert (b.orch / 'cards/X1.json').exists()


def O25(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'findings'}); eq(rc, 2, e)
    rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'valid'}); eq(rc, 0, e)
    st = b.state()
    eq(st['cards']['A']['status'], 'SUPERSEDED'); eq(st['pending_findings'], []); eq(st['dispositions'], {'F1': 'card:X1'})
    rc, o, e = b.loop('run-card', 'X1', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)
    rc, o, e = b.loop('review', '--card', 'X1', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    rc, o, e = b.loop('review', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    st = b.state()
    eq(st['milestone'], 'ACCEPTED'); eq(st['launches_used'], 38)
    assert open(b.orch / 'jobs/X1-1/tree/src/a.txt').read().count('edited') == 2   # built on A's tree
    kinds = [x['kind'] for x in b.argv_entries()]
    assert 'claude' in kinds and 'codex' in kinds, kinds                            # planner != reviewer backend
    assert any(r['event'] == 'replan' and r['planner'] == 'fable' for r in b.ledger())


def O26(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', '--packet', b.tmp / 'nope.txt', '--sha', '0' * 64)
    assert rc != 0; has(e, 'PACKET_HASH_MISMATCH')
    pk = b.tmp / 'pk.txt'; pk.write_text('x')
    rc, o, e = b.loop('review', '--card', 'A', '--packet', pk, '--sha', '0' * 64)
    assert rc != 0; has(e, 'PACKET_HASH_MISMATCH')
    assert not (b.orch / 'evidence/review-001/run').exists()


def O27(b):
    good = b.tmp / 'good.json'; good.write_text('{"a": 1}')
    rc, o, e = b.loop('read-receipt', good); eq(rc, 0, e)
    big = b.tmp / 'big.json'; big.write_text('{"a": "' + 'x' * 16384 + '"}')
    rc, o, e = b.loop('read-receipt', big); assert rc != 0; has(e, 'RECEIPT_TOO_LARGE')
    dup = b.tmp / 'dup.json'; dup.write_text('{"a": 1, "a": 2}')
    rc, o, e = b.loop('read-receipt', dup); assert rc != 0; has(e, 'RECEIPT_INVALID')
    exact = b.tmp / 'exact.json'; body = '{"a": "' ; exact.write_text(body + 'x' * (16384 - len(body) - 2) + '"}')
    eq(os.path.getsize(exact), 16384)
    rc, o, e = b.loop('read-receipt', exact); eq(rc, 0, e)


def O28(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', '--backend', 'fable', env={'FAKE_REVIEW': 'accepted', 'FAKE_WRAP': 'json'})
    eq(rc, 0, e)                                   # also proves JSON-wrapped output parsing
    ent = [x for x in b.argv_entries() if x['kind'] == 'claude']; eq(len(ent), 1)
    a = ent[0]['args']
    i = a.index('--tools'); eq(a[i + 1], '', 'no tools')
    for flag in ('--restricted', '--strict-mcp-config', '--no-session-persistence', '--print'):
        assert flag in a, flag
    eq(a[a.index('--model') + 1], 'claude-fable-5-1')
    eq(a[a.index('--mcp-config') + 1], '{"mcpServers":{}}')
    assert 'Read' not in a and 'Edit' not in a


def O29(b):
    _to_e2e_pass(b)
    ent = [x for x in b.argv_entries() if x['kind'] == 'pi']; eq(len(ent), 1)
    a = ent[0]['args']
    for flag in ('--thinking', '--offline', '--no-themes', '--no-approve', '--no-session', '--no-extensions', '--no-mcp',
                 '--no-skills', '--no-prompt-templates', '--no-context-files'):
        assert flag in a, flag
    eq(a[a.index('--thinking') + 1], 'high'); eq(a[a.index('--tools') + 1], 'read,edit,write')
    eq(a[a.index('--model') + 1], 'gpt-6-luna'); eq(a[a.index('--provider') + 1], 'openai-codex')
    assert a[-1].startswith('@/'), a
    # guardian path: the spec argv carries the same proven vector
    rt = guardian_env(b)
    b.card('G', allowed_paths=['src/b.txt'],
           e2e={'argv': ['/bin/cat', 'src/b.txt'], 'expect_status': 0, 'expect_files': []})
    rc, o, e = b.loop('run-card', 'G', env={'FAKE_GUARDIAN_AUTH_DIR': str(rt / 'private-pi')}); eq(rc, 0, e)
    spec = json.loads((rt / 'jobs' / 'G-1' / 'spec.json').read_text())
    g = spec['argv']
    for flag in ('--thinking', '--offline', '--no-themes', '--no-approve', '--no-session', '--no-extensions',
                 '--no-mcp', '--no-skills', '--no-prompt-templates', '--no-context-files'):
        assert flag in g, flag
    eq(g[g.index('--thinking') + 1], 'high'); eq(g[g.index('--tools') + 1], 'read,edit,write')
    eq(g[0], str(b.fakes / 'sandbox-exec')); eq(g[1], '-f'); eq(g[2], str(b.tmp / 'pi.sb'))
    eq(g[g.index('--model') + 1], 'gpt-6-luna'); eq(g[g.index('--provider') + 1], 'openai-codex')
    assert g[-1].startswith('@/'), g[-1]


def O30(b):
    b.card('A'); b.init()
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'HANDOFF_BLOCKED')
    accepted_card(b)
    rc, o, e = b.loop('review', '--backend', 'codex', env={'FAKE_REVIEW': 'findings'}); eq(rc, 2, e)
    rc, o, e = b.loop('review', env={'FAKE_REVIEW': 'accepted'}); assert rc != 0; has(e, 'UNDISPOSED_FINDINGS')
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'no accepted source review')
    rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'valid', 'FAKE_PLAN_BASE': '0'}); eq(rc, 0, e)
    rc, o, e = b.source_review(); eq(rc, 0, e)
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'HANDOFF_BLOCKED non-terminal')
    rc, o, e = b.loop('run-card', 'X1', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)
    rc, o, e = b.loop('review', '--card', 'X1', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    rc, o, e = b.loop('handoff'); eq(rc, 0, e)
    text = (b.tmp / 'HANDOFF-011.txt').read_text()
    eq(o, text + '\n'); has(o, 'MILESTONE VERDICT: INCOMPLETE'); assert '{{' not in o
    res = json.loads((b.tmp / 'RESULT-011.json').read_text()); eq(res['verdict'], 'INCOMPLETE')


def O31(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    ent = [x for x in b.argv_entries() if x['kind'] == 'codex']; eq(len(ent), 1)
    eq(ent[0]['args'][0], 'review'); assert ent[0]['args'][1] == '--prompt'


def O33(b):
    # PI_GUARDIAN set without a valid PI_RUNTIME: refuse before any slot is consumed
    (b.tmp / 'g.py').write_text('x')
    b.write_env(PI_GUARDIAN=b.tmp / 'g.py', PI_RUNTIME='', BOOT_PYTHON=PY)
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'})
    assert rc != 0; has(e, 'PI_RUNTIME_INVALID'); eq(b.state()['launches_used'], 36)
    assert not (b.orch / 'jobs').exists()
    b.write_env(PI_GUARDIAN='', PI_RUNTIME=b.tmp)
    (b.tmp / 'gg.py').write_text('x')
    b.write_env(PI_GUARDIAN=b.tmp / 'gg.py', PI_RUNTIME=b.tmp, BOOT_PYTHON=b.tmp / 'nopython')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'})
    assert rc != 0; has(e, 'BOOT_PYTHON_INVALID'); eq(b.state()['launches_used'], 36)


def O36(b):
    b.card('A'); b.card('B', depends_on=['A'], allowed_paths=['src/b.txt'],
                       e2e={'argv': ['/bin/cat', 'src/b.txt'], 'expect_status': 0, 'expect_files': []})
    b.init()
    rc, o, e = b.loop('run-card', 'B', env={'FAKE_PI': 'ok'}); assert rc != 0; has(e, 'DEPENDENCY_NOT_ACCEPTED')
    rc, o, e = b.loop('review', env={'FAKE_REVIEW': 'accepted'}); assert rc != 0; has(e, 'FINAL_REVIEW_BLOCKED')
    eq(b.state()['launches_used'], 36)


def O37(b):
    # e2e command itself failing is an attempt failure with its own status
    b.card('A', e2e={'argv': ['/bin/cat', 'src/missing.txt'], 'expect_status': 0, 'expect_files': []}); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); eq(rc, 1, e); has(e, 'e2e status')


def O38(b):
    # invalid cards are rejected at init, nothing initialized
    b.card('A', objective='fix <this>')
    rc, o, e = b.loop('init', '--parent', b.parent); assert rc != 0; has(e, 'CARD_INVALID')
    assert not (b.orch / 'state.json').exists()


def O39(b):
    b.init()
    h = b.state()['orch_hash']
    rc, o, e = b.loop('review', '--subject', 'relative/dir', '--name', 'x'); assert rc != 0; has(e, 'SUBJECT_INVALID')
    rc, o, e = b.loop('review', '--smoke'); assert rc != 0; has(e, 'SMOKE_NEEDS_SUBJECT')
    rc, o, e = b.source_review('prose'); assert rc != 0; has(e, 'REVIEW_MALFORMED')
    eq(b.state()['source_reviews'], {})
    rc, o, e = b.source_review('accepted'); eq(rc, 0, e)
    eq(b.state()['source_reviews'], {'orch': h})            # snapshot hash == live orchestration hash
    b2 = Box()
    try:
        b2.init()
        rc, o, e = b2.source_review('findings'); eq(rc, 2, e)
        st = b2.state(); eq(st['source_reviews'], {}); eq(st['pending_findings'], ['F1'])
        rc, o, e = b2.source_review('accepted'); assert rc != 0; has(e, 'UNDISPOSED_FINDINGS')
    finally:
        b2.close()


def O40(b):
    b.card('A'); b.init()
    snap = b.snapshot('smoke-subject')
    rc, o, e = b.loop('review', '--subject', snap, '--name', 's1', '--smoke', env={'FAKE_REVIEW': 'findings'})
    eq(rc, 0, e); has(o, 'SMOKE_OK s1')
    st = b.state()
    assert 's1' in st['smokes'] and st['smokes']['s1']['backend'] == 'codex', st['smokes']
    eq(st['pending_findings'], []); eq(st['reviews'], []); eq(st['milestone'], 'OPEN'); eq(st['source_reviews'], {})
    eq(st['cards']['A']['status'], 'PENDING'); eq(st['launches_used'], 36)
    rc, o, e = b.loop('review', '--subject', snap, '--name', 's2', '--smoke', '--backend', 'fable',
                      env={'FAKE_REVIEW': 'prose'})
    assert rc != 0; has(e, 'REVIEW_MALFORMED'); assert 's2' not in b.state()['smokes']
    rc, o, e = b.loop('review', '--subject', snap, '--name', 's3', '--smoke', env={'FAKE_REVIEW': 'unavailable'})
    eq(rc, 75, e); assert 's3' not in b.state()['smokes']
    assert any(r['event'] == 'smoke' and r['name'] == 's1' for r in b.ledger())


def O41(b):
    b.card('A'); b.init()
    accepted_card(b)
    rc, o, e = b.loop('review', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'no accepted source review')
    rc, o, e = b.source_review(); eq(rc, 0, e)
    with open(b.orch / 'worker-pi.sh', 'a') as f:
        f.write('# drift\n')
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'orchestration source changed')
    assert not (b.tmp / 'HANDOFF-011.txt').exists()
    rc, o, e = b.loop('rebind-orch'); eq(rc, 0, e); has(o, 'ORCH_REBOUND')
    rc, o, e = b.loop('handoff'); assert rc != 0; has(e, 'no accepted source review')
    rc, o, e = b.source_review(); eq(rc, 0, e)                     # fresh snapshot of the changed source
    rc, o, e = b.loop('handoff'); eq(rc, 0, e)
    rc, o, e = b.loop('rebind-orch'); eq(rc, 0, e); has(o, 'ORCH_UNCHANGED')


def O42(b):
    _to_e2e_pass(b)
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    ent = [x for x in b.argv_entries() if x['kind'] == 'codex']; eq(len(ent), 1)
    x = ent[0]
    rt = b.orch / 'evidence/review-001/runtime'
    eq(x['codex_home'], str(rt / 'codex')); eq(x['tmpdir'], str(rt / 'tmp')); eq(x['canary'], False, 'env leaked')
    eq(x['auth_link'], os.path.isfile(os.path.expanduser('~/.codex/auth.json')), 'symlink present during run')
    assert not os.path.lexists(rt / 'codex/auth.json'), 'auth symlink must be removed after the run'
    assert any(r['event'] == 'credential_lifecycle' and r['removed'] for r in b.ledger())
    rc, o, e = b.loop('review', '--subject', b.snapshot('s'), '--name', 'f', '--smoke', '--backend', 'fable',
                      env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    y = [x for x in b.argv_entries() if x['kind'] == 'claude'][0]
    eq(y['claude_cfg'], str(b.orch / 'evidence/review-002/runtime/claude')); eq(y['canary'], False)
    pi = [x for x in b.argv_entries() if x['kind'] == 'pi'][0]; eq(pi['canary'], False)
    b.write_env(CLAUDE_REAL_CONFIG='1')
    rc, o, e = b.loop('review', '--subject', b.snapshot('s2'), '--name', 'f2', '--smoke', '--backend', 'fable',
                      env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    z = [x for x in b.argv_entries() if x['kind'] == 'claude'][-1]
    eq(z['claude_cfg'], None, 'real-config mode must not override CLAUDE_CONFIG_DIR'); eq(z['canary'], False)


def O45(b):
    _to_e2e_pass(b)
    for scen, rc_want, needle in (('usage_limit', 75, 'BLOCKED_PROVIDER_UNAVAILABLE'),
                                  ('not_logged_in', 75, 'BLOCKED_PROVIDER_UNAVAILABLE'),
                                  ('other_error', 74, 'PROVIDER_ERROR')):
        rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': scen})
        eq(rc, rc_want, scen + ' ' + e); has(e, needle)
        st = b.state(); eq(st['cards']['A']['status'], 'E2E_PASS'); eq(st['pending_findings'], []); eq(st['reviews'], [])
    assert sum(1 for r in b.ledger() if r['event'] == 'provider_failed') == 3
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'findings'}); eq(rc, 2, e)
    rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'unavailable'}); eq(rc, 75, e)


def O44(b):
    b.init()
    a0 = b.state()['active_seconds']
    rc, o, e = b.loop('note-interval', '--seconds', '10', '--basis', 'test'); eq(rc, 0, e)
    eq(b.state()['active_seconds'], a0 + 10)
    rc, o, e = b.loop('note-interval', '--seconds', '-5', '--basis', 'test'); assert rc != 0; has(e, 'INTERVAL_INVALID')
    eq(b.state()['active_seconds'], a0 + 10)
    assert any(r['event'] == 'root_interval' and r['seconds'] == 10 for r in b.ledger())


def O48(b):
    # guardian happy path: job under PI_RUNTIME, receipt fields, CARD_DONE from guardian stdout
    rt = guardian_env(b)
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_GUARDIAN_AUTH_DIR': str(rt / 'private-pi')}); eq(rc, 0, e)
    st = b.state(); eq(st['cards']['A']['status'], 'E2E_PASS'); eq(st['launches_used'], 37)
    job = rt / 'jobs' / 'A-1'
    g = json.loads((job / 'guardian' / 'receipt.json').read_text())
    eq(g['status'], 'TERMINATED'); eq(g['worker_reaped'], True); eq(g['exit_code'], 0)
    eq(g['credential_removed'], True); assert isinstance(g['worker_pid'], int)
    assert (job / 'guardian' / 'ready.json').is_file() and (job / 'guardian' / 'auth-ready.json').is_file()
    has((job / 'guardian' / 'stdout').read_text(), 'CARD_DONE A')
    assert (job / 'tree' / 'src' / 'a.txt').read_text().count('edited') == 1
    assert (job / 'prompt.txt').is_file() and (job / 'spec.json').is_file()
    assert not (rt / 'private-pi' / 'auth.json').exists()
    rr = json.loads((b.orch / 'evidence/A/1/code/receipt.json').read_text())
    eq(rr['stdin_mode'], 'pipe'); eq(rr['status'], 'ok'); assert rr['reaped']
    assert not (b.orch / 'jobs').exists()                     # job tree lives under PI_RUNTIME, not orch/
    ev = [x['event'] for x in b.ledger()]
    assert 'guardian_spec' in ev and 'guardian_receipt' in ev
    rc, o, e = b.loop('review', '--card', 'A', env={'FAKE_REVIEW': 'accepted'}); eq(rc, 0, e)
    eq(b.state()['cards']['A']['status'], 'ACCEPTED')


def O49(b):
    rt = guardian_env(b)
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_GUARDIAN': 'cred_left',
                                                 'FAKE_GUARDIAN_AUTH_DIR': str(rt / 'private-pi')})
    eq(rc, 71, e); has(e, 'BLOCKED_CLEANUP_UNCERTAIN')
    assert (b.orch / 'lock').exists()
    eq(b.state()['cards']['A']['status'], 'BLOCKED_CLEANUP_UNCERTAIN')
    assert (rt / 'private-pi' / 'auth.json').exists()         # residue left behind
    g = json.loads((rt / 'jobs' / 'A-1' / 'guardian' / 'receipt.json').read_text())
    eq(g['credential_removed'], False)


def O50(b):
    rt = guardian_env(b)
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_GUARDIAN': 'cleanup_unverified',
                                                 'FAKE_GUARDIAN_AUTH_DIR': str(rt / 'private-pi')})
    eq(rc, 71, e); has(e, 'BLOCKED_CLEANUP_UNCERTAIN')
    assert (b.orch / 'lock').exists()
    g = json.loads((rt / 'jobs' / 'A-1' / 'guardian' / 'receipt.json').read_text())
    eq(g['status'], 'CLEANUP_UNVERIFIED'); eq(g['worker_reaped'], False)
    assert not (rt / 'private-pi' / 'auth.json').exists()


def O51(b):
    # (a) contract level: a pre-existing output dir kills the guardian before spawn, loudly, without receipt
    d = b.tmp / 'g51'; d.mkdir()
    (d / 'guardian').mkdir()
    spec = {'argv': ['/bin/echo', 'hi'], 'env': {}, 'cwd': str(d), 'output': str(d / 'guardian'),
            'timeout': 10, 'cap': 65536, 'auth_source': 'fixture'}
    sp = d / 'spec.json'; sp.write_text(json.dumps(spec))
    r = subprocess.run([PY, '-B', str(HERE / 'fake_guardian.py'), str(sp)], capture_output=True, text=True)
    assert r.returncode != 0 and not (d / 'guardian' / 'receipt.json').exists()
    # (b) loop level: a guardian that publishes no receipt is NEVER treated as zero-children
    rt = guardian_env(b)
    b.card('A'); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_GUARDIAN': 'no_receipt',
                                                 'FAKE_GUARDIAN_AUTH_DIR': str(rt / 'private-pi')})
    eq(rc, 71, e); has(e, 'BLOCKED_CLEANUP_UNCERTAIN'); assert (b.orch / 'lock').exists()
    assert not (rt / 'jobs' / 'A-1' / 'guardian' / 'receipt.json').exists()


def O52(b):
    # the liveness pipe is load-bearing: DEVNULL makes the guardian fail before spawn; --stdin-pipe works
    d = b.tmp / 'g52'; d.mkdir()
    ad = d / 'authdir'; ad.mkdir()

    def spec_for(name):
        return {'argv': ['/bin/echo', 'CARD_DONE T'], 'env': {}, 'cwd': str(d), 'output': str(d / name),
                'timeout': 20, 'cap': 65536, 'auth_source': 'fixture'}

    def run_rb(receipt, sp, *opts):
        return subprocess.run(
            [PY, '-B', str(ORCH_SRC / 'run_bounded.py'), str(d / receipt), '30', '65536', str(d)] + list(opts)
            + ['--', PY, '-B', str(HERE / 'fake_guardian.py'), str(sp)],
            capture_output=True, text=True, env=dict(os.environ, FAKE_GUARDIAN_AUTH_DIR=str(ad)))

    sp1 = d / 's1.json'; sp1.write_text(json.dumps(spec_for('o1')))
    r1 = run_rb('r1.json', sp1)                               # default stdin = DEVNULL
    eq(r1.returncode, 0, r1.stderr)
    rec1 = json.loads((d / 'r1.json').read_text())
    eq(rec1['stdin_mode'], 'devnull'); eq(rec1['status'], 'ok')
    g1 = json.loads((d / 'o1' / 'receipt.json').read_text())
    eq(g1['status'], 'CLEANUP_UNVERIFIED'); eq(g1['worker_reaped'], False)
    has(g1['reason'] or '', 'fake-guardian:RuntimeError')
    has((d / 'r1.json.err').read_text(), 'launcher absent before spawn')
    sp2 = d / 's2.json'; sp2.write_text(json.dumps(spec_for('o2')))
    r2 = run_rb('r2.json', sp2, '--stdin-pipe')
    eq(r2.returncode, 0, r2.stderr)
    rec2 = json.loads((d / 'r2.json').read_text())
    eq(rec2['stdin_mode'], 'pipe'); eq(rec2['status'], 'ok'); assert rec2['reaped']
    g2 = json.loads((d / 'o2' / 'receipt.json').read_text())
    eq(g2['status'], 'TERMINATED'); eq(g2['exit_code'], 0); eq(g2['credential_removed'], True)
    has((d / 'o2' / 'stdout').read_text(), 'CARD_DONE T')


def O53(b):
    # spec.json serializes the exact worker-pi.sh vector and a minimal env (no supervisor leakage)
    rt = guardian_env(b)
    b.card('A', timeout=90); b.init()
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_GUARDIAN_AUTH_DIR': str(rt / 'private-pi')}); eq(rc, 0, e)
    job = rt / 'jobs' / 'A-1'
    spec = json.loads((job / 'spec.json').read_text())
    eq(spec['argv'], [str(b.fakes / 'sandbox-exec'), '-f', str(b.tmp / 'pi.sb'), str(b.fakes / 'pi'),
                      '--print', '--mode', 'json', '--provider', 'openai-codex', '--model', 'gpt-6-luna',
                      '--thinking', 'high', '--no-session', '--no-extensions', '--no-mcp', '--no-skills',
                      '--no-prompt-templates', '--no-context-files', '--no-themes', '--no-approve', '--offline',
                      '--tools', 'read,edit,write', '@' + str(job / 'prompt.txt')])
    we = spec['env']
    eq({k: we[k] for k in we if k not in ('PATH', 'LANG', 'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS')},
       {'HOME': str(rt / 'home'), 'PI_CODING_AGENT_DIR': str(rt / 'private-pi'),
        'PI_CODING_AGENT_SESSION_DIR': str(rt / 'sessions'), 'PI_TELEMETRY': '0', 'TMPDIR': str(rt)})
    assert 'LEAK_CANARY' not in we and 'FAKE_ARGV_LOG' not in we and 'FAKE_PI' not in we
    eq(spec['cwd'], str(job / 'tree')); eq(spec['timeout'], 90)
    eq(spec['cap'], 2 * 1024 * 1024); eq(spec['auth_source'], 'real')
    eq(spec['output'], str(job / 'guardian'))


def O54(b):
    b.card('A'); b.card('B', allowed_paths=['src/b.txt'],
                        e2e={'argv': ['/bin/cat', 'src/b.txt'], 'expect_status': 0, 'expect_files': []})
    b.init()
    rc, o, e = b.loop('retire-card', 'A', '--reason', '')
    assert rc != 0
    rc, o, e = b.loop('retire-card', 'A', '--reason', 'scenario id collision'); eq(rc, 0, e)
    has(o, 'CARD_RETIRED'); eq(b.state()['cards']['A']['status'], 'NEEDS_REPLAN')
    rc, o, e = b.loop('retire-card', 'A', '--reason', 'again'); assert rc != 0; has(e, 'RETIRE_BLOCKED')
    rc, o, e = b.loop('retire-card', 'Z', '--reason', 'x'); assert rc != 0; has(e, 'UNKNOWN_CARD')
    rc, o, e = b.loop('run-card', 'A', env={'FAKE_PI': 'ok'}); assert rc != 0; has(e, 'CARD_NOT_RUNNABLE')
    assert any(r['event'] == 'retire_card' and r['card'] == 'A' for r in b.ledger())
    rc, o, e = b.loop('run-card', 'B', env={'FAKE_PI': 'ok'}); eq(rc, 0, e)
    rc, o, e = b.loop('retire-card', 'B', '--reason', 'mid-flight'); assert rc != 0; has(e, 'RETIRE_BLOCKED')
    # a retired card is a replan subject and must be replaced
    rc, o, e = b.loop('replan', env={'FAKE_PLAN': 'valid'}); eq(rc, 0, e)
    eq(b.state()['cards']['A']['status'], 'SUPERSEDED')
    assert (b.orch / 'cards' / 'X1.json').exists()


SCENARIOS = [O01, O02, O03a, O03b, O04, O05, O06, O07, O08, O09, O10, O11, O12, O13, O14, O15, O16, O17, O18, O19,
             O20_O21, O22, O23, O24, O25, O26, O27, O28, O29, O30, O31, O33, O34, O35, O36, O37, O38, O39, O40, O41,
             O42, O44, O45, O46, O47, O48, O49, O50, O51, O52, O53, O54]


def main():
    only = set(sys.argv[1:])
    results = []
    for fn in SCENARIOS:
        if only and fn.__name__ not in only:
            continue
        b = Box(); t = time.time(); err = None
        try:
            fn(b)
        except BaseException:
            err = traceback.format_exc(limit=3)
        finally:
            b.close()
        results.append({'id': fn.__name__, 'pass': err is None, 'secs': round(time.time() - t, 1), 'error': err})
        print('%-8s %s %5.1fs' % (fn.__name__, 'PASS' if err is None else 'FAIL', time.time() - t), flush=True)
        if err:
            print(err, flush=True)
    out = HERE.parent / 'evidence-e2e-orch'
    out.mkdir(exist_ok=True)
    (out / 'summary.json').write_text(json.dumps(results, indent=1))
    failed = [r['id'] for r in results if not r['pass']]
    print('TOTAL %d FAILED %d %s' % (len(results), len(failed), failed))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()

`````

### e2e/fake_engine.py (apply §5.2)  (sha256 d121e4cfe4247bd115f3bf3db650364c97caf7b62f82aab38c166a576a358fe2, 6327 bytes)
`````python
#!/usr/bin/env python3
"""Deterministic fake for pi / claude / codex CLIs. Usage: fake_engine.py KIND [args...]. Behavior from env."""
import json, os, signal, subprocess, sys, time

kind = sys.argv[1]
args = sys.argv[2:]
log = os.environ.get('FAKE_ARGV_LOG')
if log:
    ch = os.environ.get('CODEX_HOME')
    with open(log, 'a') as f:
        f.write(json.dumps({'kind': kind, 'args': args, 'codex_home': ch, 'tmpdir': os.environ.get('TMPDIR'),
                            'claude_cfg': os.environ.get('CLAUDE_CONFIG_DIR'),
                            'auth_link': bool(ch) and os.path.islink(os.path.join(ch, 'auth.json')),
                            'canary': 'LEAK_CANARY' in os.environ}) + '\n')


def field(text, name):
    for line in text.splitlines():
        if line.startswith(name + ': '):
            return line[len(name) + 2:].strip()
    return ''


if kind == 'sandbox':          # fake sandbox-exec: drop "-f PROFILE", exec the rest
    rest = args[2:]
    os.execv(rest[0], rest)

if kind == 'pi':
    prompt = open(args[-1][1:]).read()
    cid = field(prompt, 'CARD_ID')
    allowed = field(prompt, 'ALLOWED_PATHS').split(',')
    sc = os.environ.get('FAKE_PI', 'ok')

    def edit():
        p = allowed[0]
        os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
        with open(p, 'a') as f:
            f.write('edited by %s\n' % cid)
    if sc == 'ok':
        edit(); print('CARD_DONE ' + cid)
    elif sc == 'oos':
        edit(); open('evil.txt', 'w').write('x'); print('CARD_DONE ' + cid)
    elif sc == 'delete':
        os.remove(allowed[0]); print('CARD_DONE ' + cid)
    elif sc == 'symlink':
        edit(); os.symlink('/etc/hosts', 'link'); print('CARD_DONE ' + cid)
    elif sc == 'ignore_term':
        signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)
    elif sc == 'overflow':
        for _ in range(40):
            sys.stdout.write('x' * 100000); sys.stdout.flush(); time.sleep(0.02)
    elif sc == 'blocked':
        print('CARD_BLOCKED %s: cannot' % cid)
    elif sc == 'silent':
        pass
    elif sc == 'grandchild':
        subprocess.Popen(['/bin/sleep', '9']); edit(); print('CARD_DONE ' + cid)
    elif sc == 'slow':
        time.sleep(3); edit(); print('CARD_DONE ' + cid)
    elif sc == 'auth':
        d = os.environ['AUTH_DIR']; open(os.path.join(d, 'auth.json'), 'w').write('{}'); edit(); print('CARD_DONE ' + cid)
    elif sc == 'fail_exit':
        sys.exit(3)
    elif sc == 'noop_done':
        print('CARD_DONE ' + cid)
    sys.exit(0)

# claude / codex: model roles
if '--prompt' in args:
    prompt = open(args[args.index('--prompt') + 1]).read()
else:
    prompt = sys.stdin.read()


def wrap(text):
    if os.environ.get('FAKE_WRAP') == 'json':
        return json.dumps({'type': 'result', 'result': text})
    return text


if prompt.startswith('ROLE: PLANNER'):      # packets inline source that may mention roles; only the header counts
    sc = os.environ.get('FAKE_PLAN', 'valid')
    if sc == 'unavailable':
        sys.exit(75)
    ids = [x for x in field(prompt, 'FINDING_IDS').split(',') if x]
    repl = [x for x in field(prompt, 'REPLACES').split(',') if x]

    def card(i, **kw):
        c = {'id': i, 'objective': 'fix one thing', 'depends_on': [], 'allowed_paths': ['src/a.txt'],
             'acceptance_rows': ['R1 file edited'], 'stop_condition': 'stop if unsure',
             'e2e': {'argv': ['/bin/cat', 'src/a.txt'], 'expect_status': 0, 'expect_files': ['src/a.txt']},
             'timeout': 60}
        c.update(kw)
        return c
    extra = {'replaces': repl[0], 'base': repl[0]} if repl and os.environ.get('FAKE_PLAN_BASE', '1') == '1' else (
        {'replaces': repl[0]} if repl else {})
    c = card('X1', **extra)
    if sc == 'placeholder': c['objective'] = 'fix <thing>'
    if sc == 'placeholder_argv': c['e2e']['argv'] = ['/bin/cat', '<file>']
    if sc == 'angle_in_rows': c['acceptance_rows'] = ['R1 print STALE_BASE <card-id> and exit non-zero']
    if sc == 'badpath': c['allowed_paths'] = ['../escape']
    if sc == 'toomany': c['allowed_paths'] = ['a', 'b', 'c', 'd']
    cards = [c]
    if sc == 'cyclic':
        cards = [card('X1', depends_on=['X2']), card('X2', depends_on=['X1'])]
    disp = {i: 'card:X1' for i in ids}
    if sc == 'nodisp':
        disp = {}
    print(wrap('plan:\n```json\n' + json.dumps({'cards': cards, 'dispositions': disp}) + '\n```\n'))
    sys.exit(0)

sc = os.environ.get('FAKE_REVIEW', 'accepted')
if sc == 'unavailable':
    sys.exit(75)
if sc == 'usage_limit':          # real Codex 0.163 shape observed on 2026-10-23
    print('{"type":"thread.started","thread_id":"t"}\n{"type":"turn.started"}\n'
          '{"type":"error","message":"You\\u2019ve hit your usage limit. Visit https://chatgpt.com/settings/usage"}\n'
          '{"type":"turn.failed","error":{"message":"You\\u2019ve hit your usage limit."}}')
    sys.exit(1)
if sc == 'not_logged_in':        # real Claude CLI shape observed in bootstrap/claude-smoke-002.stdout
    print(json.dumps({'type': 'result', 'is_error': True, 'result': 'Not logged in · Please run /login',
                      'subtype': 'success'}))
    sys.exit(1)
if sc == 'other_error':
    print('{"type":"turn.failed","error":{"message":"model overloaded"}}')
    sys.exit(1)
rev = field(prompt, 'REVISION')
base = {'revision': rev, 'findings': [], 'missing_evidence': [], 'coverage': {'complete': True, 'truncated': False},
        'cleanup': 'ok', 'verdict': 'ACCEPTED'}
if sc == 'findings':
    base.update(findings=[{'id': 'F1', 'severity': 'high', 'location': 'src/a.txt', 'evidence': 'bad'}], verdict='INCOMPLETE')
if sc == 'accept_with_findings':
    base.update(findings=[{'id': 'F1', 'severity': 'low', 'location': 'x', 'evidence': 'y'}])
if sc == 'trunc_cov':
    base['coverage'] = {'complete': True, 'truncated': True}
if sc == 'missing_ev':
    base['missing_evidence'] = ['no hashes']
if sc == 'extra_keys':
    base['bonus'] = 1
if sc == 'badrev':
    base['revision'] = 'deadbeef'
block = '```json\n' + json.dumps(base) + '\n```\n'
if sc == 'two_blocks':
    other = dict(base, cleanup='different')
    block += '```json\n' + json.dumps(other) + '\n```\n'
if sc == 'prose':
    block = 'Looks good to me, ACCEPTED.\n'
if sc == 'truncated':
    block = block[:len(block) // 2]
print(wrap('review:\n' + block))

`````

### e2e/fake_guardian.py (apply §5.2)  (sha256 0edefe538df56c008b33fa90564840b583e3dac9b8fd60e7daf1dec825f971e4, 5568 bytes)
`````python
#!/usr/bin/env python3
"""Fake guardian honouring the continuation-008/guardian-v2.py contract, for E2E-ORCH.

Differences from the real guardian: it never reads or copies real credentials (the credential
lifecycle is simulated as an auth.json created/removed inside FAKE_GUARDIAN_AUTH_DIR), and its
behavior knob is the FAKE_GUARDIAN env var: ok (default) | cred_left | cleanup_unverified |
no_receipt. The wire contract is identical: one argv (spec path), spec keys argv/env/cwd/output/
timeout/cap/auth_source, output must not pre-exist, stdin must be an open pipe (EOF before spawn
= 'launcher absent before spawn'), writes output/{auth-ready.json,ready.json,stdout,stderr,
receipt.json} with the contract receipt keys.
"""
import json, os, pathlib, select, selectors, signal, subprocess, sys, time

spec = json.loads(pathlib.Path(sys.argv[1]).read_text())
out = pathlib.Path(spec['output'])
out.mkdir(exist_ok=False)                      # contract: output must not pre-exist
sc = os.environ.get('FAKE_GUARDIAN', 'ok')
started = time.monotonic()
deadline = started + spec['timeout']
logs = {'stdout': bytearray(), 'stderr': bytearray()}
p = None
reaped = False
status = None
reason = None
credential_removed = False
authpath = None
try:
    # contract: stdin must be an open liveness pipe; EOF before spawn means the launcher is gone
    r, _, _ = select.select([sys.stdin.buffer], [], [], 0)
    if r and not os.read(sys.stdin.fileno(), 1):
        raise RuntimeError('launcher absent before spawn')
    authdir = pathlib.Path(os.environ.get('FAKE_GUARDIAN_AUTH_DIR') or (out.parent / 'fake-auth'))
    authdir.mkdir(parents=True, exist_ok=True)
    authpath = authdir / 'auth.json'
    fd = os.open(authpath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    (out / 'auth-ready.json').write_text(json.dumps({'credential_mode': 384}))
    p = subprocess.Popen(spec['argv'], cwd=spec['cwd'], env=spec['env'], stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    (out / 'ready.json').write_text(json.dumps({'guardian_pid': os.getpid(), 'worker_pid': p.pid}))
    sel = selectors.DefaultSelector()
    sel.register(sys.stdin.buffer, selectors.EVENT_READ, 'parent')
    for pipe, name in ((p.stdout, 'stdout'), (p.stderr, 'stderr')):
        os.set_blocking(pipe.fileno(), False)
        sel.register(pipe, selectors.EVENT_READ, name)
    exit_deadline = None
    while True:
        if not reaped:
            pid, st = os.waitpid(p.pid, os.WNOHANG)
            if pid:
                reaped = True
                status = os.waitstatus_to_exitcode(st)
        if reaped and not any(k.data != 'parent' for k in sel.get_map().values()):
            break
        if time.monotonic() >= deadline and reason is None:
            reason = 'timeout'
        if reason and not reaped:
            try:
                os.kill(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if exit_deadline is None:
                exit_deadline = time.monotonic() + 5
        if exit_deadline and time.monotonic() >= exit_deadline:
            break
        for key, _ in sel.select(0.02):
            data = os.read(key.fileobj.fileno(), 16384)
            if key.data == 'parent':
                if not data:
                    sel.unregister(key.fileobj)
                    if not reaped:
                        reason = reason or 'launcher-eof'
                continue
            if not data:
                sel.unregister(key.fileobj)
                continue
            buf = logs[key.data]
            left = spec['cap'] - len(buf)
            buf.extend(data[:max(0, left)])
            if len(data) > left:
                reason = reason or 'output-cap'
    sel.close()
except BaseException as e:                      # includes 'launcher absent before spawn'
    reason = 'fake-guardian:' + type(e).__name__
    sys.stderr.write('fake-guardian: %s: %s\n' % (type(e).__name__, e))
finally:
    if p is not None and not reaped:
        try:
            os.kill(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        until = time.monotonic() + 5
        while time.monotonic() < until:
            pid, st = os.waitpid(p.pid, os.WNOHANG)
            if pid:
                reaped = True
                status = os.waitstatus_to_exitcode(st)
                break
            time.sleep(0.01)
    if authpath is not None:
        if sc == 'cred_left':
            credential_removed = False          # residue deliberately left behind
        else:
            try:
                os.unlink(authpath)
            except FileNotFoundError:
                pass
            credential_removed = not authpath.exists()
    (out / 'stdout').write_bytes(bytes(logs['stdout']))
    (out / 'stderr').write_bytes(bytes(logs['stderr']))
    if sc != 'no_receipt':
        forced_unverified = (sc == 'cleanup_unverified')
        result = {'status': 'CLEANUP_UNVERIFIED' if (forced_unverified or not reaped) else 'TERMINATED',
                  'worker_pid': p.pid if p else None,
                  'worker_reaped': False if forced_unverified else reaped,
                  'exit_code': None if forced_unverified else status, 'reason': reason,
                  'elapsed_seconds': round(time.monotonic() - started, 3),
                  'credential_removed': credential_removed}
        (out / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
    sys.exit(0)

`````

### continuation-008/guardian-v2.py (PI_GUARDIAN; frozen contract, copied to external/, never edited)  (sha256 0168a443a677349c14d6ff32482976407b09568bbed18fe37c7d7105ef45aa6f, 5273 bytes)
`````python
"""Trusted single-child supervisor; experimental, not accepted workflow control."""
import base64,json,os,selectors,signal,stat,subprocess,sys,time
from pathlib import Path
spec_path=Path(sys.argv[1]); spec=json.loads(spec_path.read_text()); out=Path(spec['output']);out.mkdir(exist_ok=False)
signal.signal(signal.SIGCHLD,signal.SIG_DFL)
D=Path(__file__).resolve().parent;runtime=D/'pi-runtime-v2';authdir=runtime/'private-pi';authfd=None;auth_created=False;credential_removed=False
p=None;sel=selectors.DefaultSelector();logs={'stdout':bytearray(),'stderr':bytearray()};reason=None;reaped=False;status=None;started=time.monotonic();deadline=started+spec['timeout'];exit_deadline=None
try:
 for directory in [runtime,authdir]:
  if directory.is_symlink():raise RuntimeError('symlink directory')
  directory.mkdir(mode=0o700,exist_ok=True)
  st=directory.stat()
  if stat.S_IMODE(st.st_mode)!=0o700 or st.st_uid!=os.getuid():raise RuntimeError('private directory mode/owner')
 if runtime.resolve()!=runtime or authdir.resolve()!=authdir:raise RuntimeError('path redirection')
 for ancestor in D.parents:
  st=ancestor.stat()
  if st.st_mode & 0o022 and not (st.st_mode & stat.S_ISVTX):raise RuntimeError('writable ancestor')
 authfd=os.open(authdir,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 source=Path.home()/'.codex/auth.json' if spec['auth_source']=='real' else D/'tests/fixture-auth.json'
 if spec['auth_source'] not in ['real','fixture']:raise RuntimeError('unknown auth source')
 tokens=json.loads(source.read_text())['tokens'];access=tokens['access_token'];body=access.split('.')[1];claims=json.loads(base64.urlsafe_b64decode(body+'='*((-len(body))%4)));expiry=claims['exp']*1000
 if expiry<time.time()*1000+600000:raise RuntimeError('insufficient access token lifetime')
 credential={'openai-codex':{'type':'oauth','access':access,'refresh':'','expires':expiry,'accountId':tokens['account_id']}}
 fd=os.open('auth.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=authfd);auth_created=True
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o600 or st.st_uid!=os.getuid():raise RuntimeError('credential mode/owner')
  with os.fdopen(fd,'w',closefd=False) as stream:json.dump(credential,stream);stream.flush();os.fsync(fd)
 finally:os.close(fd)
 (out/'auth-ready.json').write_text(json.dumps({'credential_mode':384,'private_parent_mode':448}))
 if spec.get('inject')=='after-auth':raise RuntimeError('injected setup failure')
 import select
 if select.select([sys.stdin.buffer],[],[],0)[0] and not os.read(sys.stdin.fileno(),1):raise RuntimeError('launcher absent before spawn')
 p=subprocess.Popen(spec['argv'],cwd=spec['cwd'],env=spec['env'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True)
 (out/'ready.json').write_text(json.dumps({'guardian_pid':os.getpid(),'worker_pid':p.pid,'started_epoch':time.time()}))
 sel.register(sys.stdin.buffer,selectors.EVENT_READ,'parent')
 for pipe,name in [(p.stdout,'stdout'),(p.stderr,'stderr')]:os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ,name)
 while True:
  if not reaped:
   pid,st=os.waitpid(p.pid,os.WNOHANG)
   if pid:
    reaped=True;status=os.waitstatus_to_exitcode(st);p.returncode=status
  if reaped and not any(k.data!='parent' for k in sel.get_map().values()):break
  if time.monotonic()>=deadline and reason is None:reason='timeout'
  if reason and not reaped:
   # This direct child has not been reaped. Its PID cannot be reused.
   try:os.kill(p.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   if exit_deadline is None:exit_deadline=time.monotonic()+5
  if exit_deadline and time.monotonic()>=exit_deadline:break
  for key,_ in sel.select(.02):
   data=os.read(key.fileobj.fileno(),16384)
   if key.data=='parent':
    if not data:
     sel.unregister(key.fileobj)
     if not reaped:reason=reason or 'launcher-eof'
    continue
   if not data:sel.unregister(key.fileobj);continue
   buf=logs[key.data];left=spec['cap']-len(buf);buf.extend(data[:max(0,left)])
   if len(data)>left:reason=reason or 'output-cap'
except BaseException as e:reason='guardian-exception:'+type(e).__name__
finally:
 if p is not None and not reaped:
  try:os.kill(p.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  until=time.monotonic()+5
  while time.monotonic()<until:
   pid,st=os.waitpid(p.pid,os.WNOHANG)
   if pid:reaped=True;status=os.waitstatus_to_exitcode(st);p.returncode=status;break
   time.sleep(.01)
 if authfd is not None:
  if auth_created and (p is None or reaped):
   try:os.unlink('auth.json',dir_fd=authfd)
   except FileNotFoundError:pass
   try:os.stat('auth.json',dir_fd=authfd,follow_symlinks=False)
   except FileNotFoundError:credential_removed=True
  os.close(authfd)
 sel.close()
 for k,v in logs.items():(out/k).write_bytes(v)
 result={'status':'TERMINATED' if reaped else 'CLEANUP_UNVERIFIED','worker_pid':p.pid if p else None,'worker_reaped':reaped,'exit_code':status,'reason':reason,'elapsed_seconds':round(time.monotonic()-started,3),'single_worker_assumption':'requires separately proven native process-fork denial','credential_removed':credential_removed}
 (out/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result),flush=True)

`````

### continuation-008/pi-nofork-v3.sb (PI_PROFILE; copied to external/)  (sha256 6f5bd2ea5f14e95d4583167d7362a4a136655c1195b62b3d09448eb2c1b089c7, 1787 bytes)
`````text
(version 1)
(allow default)
(deny process-fork)
(deny file-write*)
(allow file-write* (subpath "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008/pi-runtime-v2"))
(deny network-outbound (remote unix-socket))
(allow network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))
(allow network-outbound (remote unix-socket (path-literal "/var/run/mDNSResponder")))
(deny signal)
(allow signal (target self) (target children))
(deny file-read* (subpath "/Users/psac"))
(allow file-read* (subpath "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008/pi-runtime-v2"))
(deny file-read* (subpath "/Users/psac/.codex"))
(deny file-write* (subpath "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008/pi-runtime-v2/private-pi"))
(allow file-write* (subpath "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008/pi-runtime-v2/private-pi/auth.json.lock"))
(allow file-read-metadata (literal "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008") (literal "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001") (literal "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning") (literal "/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts") (literal "/Users/psac/development/prometheansacrifice/ocaml-rl-sft") (literal "/Users/psac/development/prometheansacrifice") (literal "/Users/psac/development") (literal "/Users/psac"))

`````

### candidate/scripts/esy-repair/codex-worker.sh (CODEX_WORKER; frozen, copied to external/)  (sha256 e036f5ced62399dda7e9c5e18063b148df9e89b8a3f146a0786703ab7e2579d2, 1425 bytes)
`````bash
#!/bin/bash
# Frozen role template. Every argument is supplied by the verified controller;
# no environment variable can replace the executable, model, sandbox, or prompt.
set -euo pipefail
if [[ $# -ne 5 ]]; then
  echo "usage: codex-worker.sh ROLE WORKSPACE PROMPT PROFILE CODEX_EXECUTABLE" >&2
  exit 64
fi
role=$1
workspace=$2
prompt=$3
profile=$4
codex_bin=$5
case "$role" in
  code) model=gpt-6-luna; sandbox=danger-full-access; shell_flag=--enable ;;
  plan|review) model=gpt-6-astra; sandbox=read-only; shell_flag=--disable ;;
  *) echo "unsupported role" >&2; exit 64 ;;
esac
[[ "$workspace" = /* && -d "$workspace" && ! -L "$workspace" ]] || { echo "verified absolute workspace required" >&2; exit 64; }
[[ "$prompt" = /* && -f "$prompt" && ! -L "$prompt" ]] || { echo "verified absolute prompt required" >&2; exit 64; }
[[ "$profile" = /* && -f "$profile" && ! -L "$profile" ]] || { echo "verified absolute sandbox profile required" >&2; exit 64; }
[[ "$codex_bin" = /* && -x "$codex_bin" && ! -L "$codex_bin" ]] || { echo "verified absolute Codex executable required" >&2; exit 64; }

cd "$workspace"
exec /usr/bin/sandbox-exec -f "$profile" "$codex_bin" exec --disable apps --disable plugins --disable hooks --disable multi_agent --disable shell_snapshot "$shell_flag" shell_tool --ignore-user-config --ephemeral --skip-git-repo-check --model "$model" --sandbox "$sandbox" --cd "$workspace" --json - < "$prompt"

`````

### Current `orch/env.sh` bindings (values only; CODEX_BIN must be rebound per Decision 4)
`````bash
export CLAUDE_BIN=/opt/homebrew/Caskroom/claude-code@latest/2.1.309/claude
export CLAUDE_FABLE_MODEL=claude-fable-5-1
export CLAUDE_CODING_MODEL=
export CODEX_BIN=/opt/homebrew/Caskroom/codex/0.163.0/bin/codex
export CODEX_WORKER=/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/candidate/scripts/esy-repair/codex-worker.sh
export PI_BIN=/opt/homebrew/Cellar/pi-coding-agent/1.4.0/bin/pi
export PI_PROVIDER=openai-codex
export PI_CODING_MODEL=gpt-6-luna
export SANDBOX_EXEC=/usr/bin/sandbox-exec
export PI_PROFILE=/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008/pi-nofork-v3.sb
export REVIEW_PROFILE=/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-011/review-readonly.sb
export PI_RUNTIME=/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008/pi-runtime-v2
export PI_GUARDIAN=/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008/guardian-v2.py
export BOOT_PYTHON=/usr/bin/python3
export AUTH_DIR=/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-008/pi-runtime-v2/private-pi
export CLAUDE_REAL_CONFIG=1

`````

--- end of PLAN 013 Round 5 ---
