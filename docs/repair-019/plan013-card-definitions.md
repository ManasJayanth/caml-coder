**C1** — unchanged (already in `orch/cards/C1.json`, O32): base-hash gate `PARENT_STALE` (review-005 F1).

**C21** (replaces C2; supersedes C7) — scenario **O81**
````json
{"id": "C21",
 "objective": "Re-verify the job tree after the card e2e step (re-hash, scope-check, or fail E2E_TREE_MUTATED) and make cmd_review refuse a stale revision for card and final scope",
 "depends_on": ["C1"], "allowed_paths": ["loop.py", "e2e/run_e2e.py"], "replaces": "C2",
 "acceptance_rows": [
  "R1 In loop.py cmd_run_card, immediately after the card e2e launch (the launch whose label ends in '/e2e') passes its expect_status and expect_files checks and BEFORE the suite step (the block starting `suite = tree / 'e2e' / 'run_e2e.py'`), compute post = inv_hash(inventory(tree)); if post != manifest['tree_hash']: compute ok2, probs2 = scope_verify(parent_inv, inventory(tree), set(c['allowed_paths'])); if not ok2 call fail_attempt(st, a.id, 'E2E_TREE_MUTATED: ' + '; '.join(probs2)); otherwise set manifest['tree_hash'] = post, rewrite job/'result-manifest.json' with jwrite, and append_ledger({'event': 'tree_rehash', 'card': a.id, 'attempt': attempt, 'old': <previous hash>, 'new': post}).",
  "R2 The existing SUITE_TREE_MUTATED comparison after the suite step and cs.update(... tree_hash=manifest['tree_hash']) are left as they are, so both now use the re-hashed value.",
  "R3 In loop.py cmd_review, for scope card (a.card set) and scope final (neither a.subject nor a.card), BEFORE the line `st['review_seq'] += 1`, compute live = inv_hash(inventory(tree)); if live != revision: append_ledger({'event': 'review_stale', 'scope': scope, 'stored': revision, 'live': live}) and sys.exit('REVISION_STALE %s stored=%s live=%s' % (scope, revision, live)); review_seq is not incremented, no evidence/review-* directory is created, no state other than the ledger changes.",
  "R4 e2e/run_e2e.py gains scenario O81 registered in SCENARIOS, in three parts using a fresh Box() for each part as O16 does: (a) card A with e2e argv ['/usr/bin/python3', '-c', \"open('junk.txt','w').write('x')\"]: run-card A exits 1, stderr contains E2E_TREE_MUTATED, state card A status FAILED, launches_used 37; (b) card A with e2e argv ['/usr/bin/python3', '-c', \"open('src/a.txt','a').write('e2e')\"]: run-card A exits 0, result-manifest.json tree_hash equals state cards.A.tree_hash, the ledger contains an event tree_rehash for card A, and review --card A with FAKE_REVIEW=accepted exits 0; (c) card A passes run-card with the default e2e argv, then the scenario appends one byte to orch/jobs/A-1/tree/src/a.txt; review --card A exits non-zero, stderr contains REVISION_STALE, state review_seq is unchanged, parent_hash is unchanged, cards.A.status is still E2E_PASS and no orch/evidence/review-001 directory exists.",
  "R5 No scenario other than O81 is added or changed; no function other than cmd_run_card and cmd_review changes."],
 "stop_condition": "print CARD_BLOCKED C21 if cmd_run_card has no suite step whose failure reason is 'SUITE_TREE_MUTATED', if scenario id O81 already exists in e2e/run_e2e.py, or if cmd_review does not derive `revision` from cs['tree_hash'] for card scope and from st['parent_hash'] for final scope",
 "e2e": {"argv": ["/usr/bin/python3", "-B", "e2e/run_e2e.py", "O81"], "expect_status": 0, "expect_files": [], "timeout": 150},
 "timeout": 540}
````

**C22** (replaces C5) — scenario **O82**
````json
{"id": "C22",
 "objective": "Make the RESERVED window of cmd_run_card recoverable: any failure between slot reservation and the coding launch marks the card FAILED with a recorded reason, and inputs_inline is validated at card-load time as a list of relative paths",
 "depends_on": ["C21"], "allowed_paths": ["loop.py", "e2e/run_e2e.py"], "replaces": "C5",
 "acceptance_rows": [
  "R1 In loop.py cmd_run_card, in BOTH branches (guardian and worker-pi.sh), the statements between `cs['status'] = 'RESERVED'; save_state(st)` and the coding `launch(...)` call (job dir checks and mkdir, shutil.copytree, assemble_prompt, prompt.write_text, coding_spec/jwrite(spec)) are wrapped in one try/except that catches SystemExit and OSError; on exception it sets cs['status'] = 'FAILED', cs['last_failure'] = 'PRELAUNCH ' + (str(exc.code) for SystemExit, else type(exc).__name__ + ': ' + str(exc)), calls save_state(st), append_ledger({'event': 'run_card_prelaunch_failed', 'card': a.id, 'attempt': attempt, 'reason': cs['last_failure']}) and re-raises the exception unchanged (exit code preserved); the slot stays consumed.",
  "R2 In loop.py validate_card, when the key inputs_inline is present it must be a list whose items are non-empty strings that do not start with '/' and have no '..' path part; otherwise return 'inputs_inline must be a list of relative paths'.",
  "R3 e2e/run_e2e.py gains scenario O82 registered in SCENARIOS: (a) a card with inputs_inline={'a': 'b'} makes init exit non-zero with CARD_INVALID and no state.json; (b) in a fresh Box, a valid card with inputs_inline=['src/missing.txt']: run-card exits non-zero, stderr contains INPUT_INVALID, state cards.<id>.status is FAILED and last_failure starts with 'PRELAUNCH', launches_used is 37, the ledger has run_card_prelaunch_failed; the scenario then rewrites orch/cards/<id>.json without inputs_inline and run-card exits 0 with launches_used 38 and status E2E_PASS; (c) in a fresh Box, orch/jobs/<id>-1 is pre-created before the first run-card: run-card exits non-zero, status FAILED, launches_used 37; the next run-card exits 0 using orch/jobs/<id>-2.",
  "R4 No scenario other than O82 is added or changed; no function other than cmd_run_card and validate_card changes."],
 "stop_condition": "print CARD_BLOCKED C22 if cmd_run_card does not contain `cs['status'] = 'RESERVED'` followed by shutil.copytree and assemble_prompt before launch(...), if validate_card does not exist, or if scenario id O82 already exists in e2e/run_e2e.py",
 "e2e": {"argv": ["/usr/bin/python3", "-B", "e2e/run_e2e.py", "O82"], "expect_status": 0, "expect_files": [], "timeout": 150},
 "timeout": 540}
````

**C23** (replaces C6) — scenario **O83**
````json
{"id": "C23",
 "objective": "Bind milestone acceptance to a revision so handoff reports ACCEPTED only when the current parent_hash is the revision that was final-reviewed, and any later parent change or replan clears the acceptance",
 "depends_on": ["C22"], "allowed_paths": ["loop.py", "e2e/run_e2e.py"], "replaces": "C6",
 "acceptance_rows": [
  "R1 In loop.py cmd_review, where `st['milestone'] = 'ACCEPTED'` is set, also set st['milestone_revision'] = revision; every dict appended to st['reviews'] gains the key 'revision' with the reviewed revision.",
  "R2 Define a helper milestone_reset(st, why) that, only when st['milestone'] == 'ACCEPTED', sets st['milestone'] = 'REPLANNED', sets st['milestone_revision'] = None and calls append_ledger({'event': 'milestone_reset', 'why': why, 'previous_revision': <old milestone_revision>}); call it in cmd_review right before `st['parent_dir'], st['parent_hash'] = tree, revision` (card acceptance), in cmd_set_parent right before the parent is rebound, and in cmd_replan right before new card files are written when len(new) > 0.",
  "R3 In loop.py cmd_handoff, the verdict line becomes: verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED' and st.get('milestone_revision') == st['parent_hash'] else ('BLOCKED' if any(v['status'] == 'BLOCKED_CLEANUP_UNCERTAIN' for v in st['cards'].values()) else 'INCOMPLETE'); when st['milestone'] == 'ACCEPTED' but the revisions differ, the printed text contains a line 'MILESTONE_STALE milestone_revision=<x> parent_hash=<y>' directly after the MILESTONE VERDICT line.",
  "R4 e2e/run_e2e.py gains scenario O83 registered in SCENARIOS: drive a Box to milestone ACCEPTED exactly like O01 up to and including the final review; assert state milestone_revision equals parent_hash and reviews[-1]['revision'] equals parent_hash; run source_review('findings') then replan with FAKE_PLAN=valid and FAKE_PLAN_BASE=0 and assert milestone is 'REPLANNED' and milestone_revision is None and the ledger has milestone_reset; run-card X1 and review --card X1 accepted; then edit state.json directly setting milestone to 'ACCEPTED' and milestone_revision to 'deadbeef', call b.source_review() accepted, b.e2e_summary(), and handoff --seq 12: output contains 'MILESTONE VERDICT: INCOMPLETE' and 'MILESTONE_STALE' and not 'MILESTONE VERDICT: ACCEPTED'; then review (final scope) accepted, b.e2e_summary(), handoff --seq 13: output contains 'MILESTONE VERDICT: ACCEPTED' and RESULT-013.json verdict is ACCEPTED.",
  "R5 O01, O30 and O41 still pass unchanged; no scenario other than O83 is added; no function other than cmd_review, cmd_set_parent, cmd_replan, cmd_handoff and the new milestone_reset changes."],
 "stop_condition": "print CARD_BLOCKED C23 if cmd_review does not contain `st['milestone'] = 'ACCEPTED'`, if cmd_handoff does not contain `verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED'`, if cmd_handoff has no --seq handling (HANDOFF-%03d), or if scenario id O83 already exists in e2e/run_e2e.py",
 "e2e": {"argv": ["/usr/bin/python3", "-B", "e2e/run_e2e.py", "O83"], "expect_status": 0, "expect_files": [], "timeout": 150},
 "timeout": 540}
````

**C24** (replaces C8) — scenario **O84**
````json
{"id": "C24",
 "objective": "Hash the reviewer packet before the model runs and detect a packet rewritten during the run, so packet_sha attests what the model was given",
 "depends_on": ["C23"], "allowed_paths": ["loop.py", "e2e/run_e2e.py", "e2e/fake_engine.py"], "replaces": "C8",
 "acceptance_rows": [
  "R1 In loop.py run_model, immediately after `pf.write_text(prompt_text)` compute pre_sha = sha(pf), call append_ledger({'event': 'packet_written', 'label': label, 'sha': pre_sha}), and return (pf, res, pre_sha) instead of (pf, res); both callers (cmd_review and cmd_replan) unpack three values.",
  "R2 In loop.py cmd_review, the ledger event review_packet and the 'packet_sha' stored in st['reviews'] use pre_sha; after run_model returns compute post = sha(pf); if post != pre_sha: append_ledger({'event': 'packet_tampered', 'label': label, 'pre': pre_sha, 'post': post}), append to st['reviews'] a dict {'seq': st['review_seq'], 'scope': scope, 'backend': st['reviewer_backend'], 'verdict': 'TAMPERED', 'findings': [], 'missing': 0, 'packet_sha': pre_sha, 'packet_tampered': True}, save_state(st), and sys.exit('REVIEW_PACKET_TAMPERED ' + label) before any verdict parsing; no acceptance, no parent/card/milestone change, pending_findings unchanged.",
  "R3 In e2e/fake_engine.py, in the review branch (after the provider-error knobs, before the verdict block is printed): if the environment variable FAKE_REVIEW_REWRITE_PACKET is set, append the line 'TAMPERED\\n' to the file at that path; no other fake behaviour changes. In e2e/run_e2e.py Box.loop the ORCH_ENV_PASSTHROUGH string gains ',FAKE_REVIEW_REWRITE_PACKET'.",
  "R4 e2e/run_e2e.py gains scenario O84 registered in SCENARIOS: (a) _to_e2e_pass(b); review --card A with FAKE_REVIEW=accepted and FAKE_REVIEW_REWRITE_PACKET=<orch>/evidence/review-001/packet.txt exits non-zero, stderr contains REVIEW_PACKET_TAMPERED, cards.A.status is E2E_PASS, parent_hash unchanged, reviews[-1]['packet_tampered'] is True and reviews[-1]['packet_sha'] equals the sha256 of packet.txt with its final 'TAMPERED\\n' line removed; the ledger has packet_written and packet_tampered; (b) a second review --card A with FAKE_REVIEW=accepted exits 0 and reviews[-1]['packet_sha'] equals the sha256 of evidence/review-002/packet.txt and has no packet_tampered key.",
  "R5 No scenario other than O84 is added or changed; no function other than run_model, cmd_review, cmd_replan (unpacking only) changes in loop.py."],
 "stop_condition": "print CARD_BLOCKED C24 if cmd_review currently records sha(pf) only after run_model returns (the finding's premise), if run_model does not write pf before launching, if scenario id O84 already exists in e2e/run_e2e.py, or if the fake reviewer cannot rewrite packet.txt without touching files outside allowed_paths",
 "e2e": {"argv": ["/usr/bin/python3", "-B", "e2e/run_e2e.py", "O84"], "expect_status": 0, "expect_files": [], "timeout": 150},
 "timeout": 480}
````

### 6.2 Tier 2 — low-severity findings F5–F8 (slots 42–45; added only after the §4.4 gate)

**C25** (F5) — **O85**: `cmd_replan` disposition guard. Rows: R1 before any card is written, every key in `plan['dispositions']`
must match `(card:[A-Za-z0-9_-]+|rejected:.+|deferred:.+)` else `sys.exit('PLAN_DISPOSITION_INVALID ' + key)`; R2 a key already in
`st['dispositions']` with a different value ⇒ `sys.exit('PLAN_DISPOSITION_OVERWRITE ' + key)` (identical value allowed); R3 every
`card:<id>` value (any key) must name a card in `new` or `existing` else `PLAN_DISPOSITION_UNKNOWN_CARD`; all three checks
happen before `jwrite` of any card and leave `pending_findings` unchanged; R4 `e2e/fake_engine.py` gains knob
`FAKE_PLAN=bad_disp` ⇒ `disp = {ids[0]: 'maybe:later'}` when ids non-empty; R5 scenario O85: (a) after a review with
findings, seed `state.dispositions = {'F1': 'deferred:old'}` by editing state.json, `replan` with `FAKE_PLAN=valid` ⇒ non-zero,
`PLAN_DISPOSITION_OVERWRITE`, no X1.json, pending_findings `['F1']`; (b) fresh Box, `FAKE_PLAN=bad_disp` ⇒ `PLAN_DISPOSITION_INVALID`;
(c) fresh Box, `FAKE_PLAN=valid` ⇒ exit 0 and dispositions `{'F1': 'card:X1'}`. allowed: `loop.py`, `e2e/run_e2e.py`,
`e2e/fake_engine.py`; depends_on `["C24"]`; timeout 420; stop: CARD_BLOCKED if `cmd_replan` lacks
`st['dispositions'] = dict(st.get('dispositions', {}), **plan['dispositions'])` or O85 exists.

**C26** (F6) — **O86**: `validate_card` type checks for optional keys: `base`/`replaces` strings matching `[A-Za-z0-9_-]{1,40}`;
`max_edit_chars` int 1..3000; `parent_manifest` str; `parent_hash` 64 lowercase hex; `e2e.expect_files` list of relative
non-empty strings without `..`; `e2e.timeout` int 1..200; each violation returns a distinct message starting with the key name.
O86: init rejects each bad shape with `CARD_INVALID <key…>` (one Box per shape or sequential card rewrites before init), and
`replan` with new knob `FAKE_PLAN=badtypes` (`c['replaces'] = ['A']`, `c['e2e']['timeout'] = 'x'`) ⇒ `PLAN_CARD_INVALID`, no card
written. allowed: `loop.py`, `e2e/run_e2e.py`, `e2e/fake_engine.py`; depends_on `["C25"]`; timeout 420; stop: CARD_BLOCKED if
`CARD_OPTIONAL` is not a set literal in loop.py or O86 exists.

**C27** (F7) — **O87**: `parse_verdict` typing: each finding needs `id`, `severity` ∈ {high, medium, low}, `location`, `evidence`
as non-empty strings (no extra keys); `missing_evidence` items non-empty strings; `coverage` exactly `{complete: bool, truncated: bool}`;
`cleanup` a string; else return None (⇒ `REVIEW_MALFORMED`). Knobs `FAKE_REVIEW=finding_no_evidence|bad_severity|missing_ev_nonstring|coverage_nonbool`.
O87: each knob ⇒ `review --card A` non-zero with `REVIEW_MALFORMED`, state unchanged (status E2E_PASS, pending_findings `[]`, reviews `[]`);
then `findings` knob still ⇒ exit 2 with pending `['F1']`. allowed: `loop.py`, `e2e/run_e2e.py`, `e2e/fake_engine.py`; depends_on
`["C26"]`; timeout 420; stop: CARD_BLOCKED if `parse_verdict` does not contain `isinstance(f.get('id'), str)` or O87 exists.

**C28** (F8) — **O88**: `cmd_review` uses a local `backend = a.backend or st['reviewer_backend']` for `run_model` and the smoke record;
`st['reviewer_backend'] = backend` is assigned only on the non-smoke path after `parse_verdict` succeeded and the revision matched
(immediately before `st['last_review'] = …`); smokes, malformed, transport and provider failures never change it. O88: init
(reviewer codex); `review --subject snap --name s --smoke --backend fable` with `FAKE_REVIEW=accepted` ⇒ exit 0, `smokes.s.backend == 'fable'`,
`reviewer_backend == 'codex'`; `_to_e2e_pass`; `review --card A --backend fable` with `FAKE_REVIEW=prose` ⇒ non-zero, `reviewer_backend`
still codex; `review --card A --backend fable` accepted ⇒ `reviewer_backend == 'fable'`; then `replan` default backend is codex (argv log
shows kind codex for the planner). allowed: `loop.py`, `e2e/run_e2e.py`; depends_on `["C27"]`; timeout 420; stop: CARD_BLOCKED if
`cmd_review` does not contain `if a.backend:` followed by `st['reviewer_backend'] = a.backend`, or O88 exists.

### 6.3 Tier 3 — F4 and F9 (slots 46–47; only after the §4.4 gate; otherwise stay `deferred:` with the existing reasons)

**C29** (F4) — **O89**: sandbox the card e2e and suite launches. R1 `cmd_run_card` writes `job/'e2e.sb'` with exactly:
`(version 1)\n(allow default)\n(deny file-write*)\n(allow file-write* (subpath "<tree>"))\n(allow file-write* (subpath "<ev>"))\n(deny network-outbound (remote unix-socket))\n(allow network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))\n(allow network-outbound (remote unix-socket (path-literal "/var/run/mDNSResponder")))\n(deny signal)\n(allow signal (target self) (target children))\n`
where `<tree>` and `<ev>` are the absolute job tree and `evidence/<card>/<attempt>` paths; R2 both the e2e and suite launches use
argv `[env['SANDBOX_EXEC'], '-f', str(job / 'e2e.sb')] + <original argv>` and extra env additionally `TMPDIR=str(ev / 'tmp')` (directory
created first, 0700); R3 O89: `argv_entries()` contains two entries with kind `sandbox` whose `args[1]` is the job's `e2e.sb` path,
one followed by the card's e2e argv and one by `e2e/run_e2e.py` (use a parent with the O61 stub so the suite step runs); the profile file
contains the tree path, the evidence path and `(deny file-write*)`; O37 (`e2e status`) still passes. allowed: `loop.py`, `e2e/run_e2e.py`;
depends_on `["C28"]`; timeout 480. Real enforcement of the profile is proven only by a real run and is recorded as such in the handoff.
stop: CARD_BLOCKED if the e2e launch argv in `cmd_run_card` is not `list(e['argv'])` or O89 exists.

**C30** (F9) — **O90**: `base_env` honours `ORCH_ENV_PASSTHROUGH` only when `os.environ.get('ORCH_E2E_HARNESS') == '1'`; `Box.loop`
sets `ORCH_E2E_HARNESS='1'`. O90: a direct `subprocess.run` of `loop.py run-card A` with `ORCH_ENV_PASSTHROUGH=FAKE_PI,FAKE_ARGV_LOG`,
`FAKE_PI=blocked` and NO marker ⇒ exit 0 and `E2E_PASS` (the knob did not reach the fake, which defaulted to ok); the same command with
`ORCH_E2E_HARNESS=1` ⇒ exit 1 and `CARD_BLOCKED`. allowed: `loop.py`, `e2e/run_e2e.py`; depends_on `["C29"]`; timeout 360;
stop: CARD_BLOCKED if `base_env` does not read `ORCH_ENV_PASSTHROUGH` or O90 exists.

### 6.4 Disposition provenance (keys collided across reviews; recorded so the frontier reviewer can audit)
| review | finding | today's key/value in state | after P4 |
|---|---|---|---|
| 005 | F1 base-hash gate | key overwritten by 012-F1 | C1 (unchanged card) |
| 005 | F2 e2e mutates tree after hash | overwritten | C21 (`F1: card:C21` after retire C7 --superseded-by C21) |
| 005 | F3 milestone not revision-bound | overwritten | C23 (`F2: card:C23`) |
| 005 | F4 RESERVED dead end | overwritten | C22 |
| 005 | F5 e2e argv unsandboxed | overwritten by 012-F4 text | C29 or `deferred:` |
| 005 | F6 packet hash after run | overwritten | C24 (`F3: card:C24`) |
| 005 | F7 stale comment | fixed root orch-008 | unchanged |
| 005 | F8 dirs invisible | lost | `R005-F8: deferred:…` |
| 005 | F9 passthrough | `F9: deferred:` | C30 or deferred |
| 005 | F10 baked defaults | `F10: deferred:` | `root:orch-011 D7` |
| 012 | F1 post-e2e hash | `card:C7` | `card:C21` |
| 012 | F2 milestone | `deferred:` | `card:C23` |
| 012 | F3 packet sha | `card:C8` | `card:C24` |
| 012 | F4 e2e sandbox | `deferred:` | `card:C29` or deferred |
| 012 | F5–F8 | `deferred:` | C25–C28 or deferred |
| 012 | M0–M3 | `deferred:` | `root:orch-011 external/…` |
| 012 | M4 | `rejected:` | unchanged |

---------------------------------------------------------------------------------------------------
