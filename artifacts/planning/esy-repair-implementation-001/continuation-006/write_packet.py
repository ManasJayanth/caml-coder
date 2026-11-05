"""Supervisor packet writer. Does not execute candidate code or establish acceptance."""
from pathlib import Path
import datetime, difflib, hashlib, json, stat, time

D = Path(__file__).resolve().parent
S = D.parent
ROOT = S.parents[2]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()

def record(path):
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path.read_bytes())}

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

packet = S / 'frontier-packet-006'
packet.mkdir(exist_ok=False)
baseline = json.loads((S / 'baseline-manifest.json').read_text())
changed = []
for row in baseline:
    p = ROOT / row['path']
    if p.is_symlink() or not p.is_file() or sha(p.read_bytes()) != row['sha256'] or stat.S_IMODE(p.stat().st_mode) != row['mode']:
        changed.append(row['path'])
manifest = []
parts = []
for p in sorted((S / 'candidate').rglob('*')):
    if p.is_symlink() or not (p.is_dir() or p.is_file()):
        raise RuntimeError('Unsupported candidate entry: ' + str(p))
    if not p.is_file():
        continue
    rel = str(p.relative_to(S / 'candidate'))
    manifest.append({'path': rel, 'mode': stat.S_IMODE(p.stat().st_mode), 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())})
    before_path = S / 'baseline' / rel
    before = before_path.read_text() if before_path.exists() else ''
    after = p.read_text()
    if before != after:
        diff = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='baseline/' + rel, tofile='candidate/' + rel))
        part = packet / ('source-%03d.txt' % len(parts))
        part.write_text('FILE ' + rel + '\nCOMPLETE SOURCE\n' + after + '\nEXACT ACCUMULATED DIFF\n' + diff)
        parts.append(record(part))
write(S / 'candidate-manifest-006.json', manifest)
revision = sha(canonical(manifest))
allocation = json.loads((D / 'allocation.json').read_text())
used = json.loads((D / 'coding-ledger.json').read_text())['coding_launches_consumed']
active = round(allocation['prior_active_seconds'] + time.time() - allocation['current_turn_started_epoch'], 3)
result = {
    'status': 'INCOMPLETE',
    'reason': 'Astra rejected real-container execution pending lifecycle, query, deadline and seed prerequisites. Controller and global acceptance remain rejected/incomplete. No original-source import.',
    'reviewer': 'fresh Codex gpt-6-astra', 'planner': 'separate fresh Codex gpt-6-astra',
    'coding_model': 'gpt-6-luna', 'coding_backend': 'Pi openai-codex, individually reviewed no-fork supervised launches only',
    'coding_launches_consumed': used, 'coding_launch_cap': 24, 'coding_launches_remaining': 24-used,
    'active_seconds_consumed_at_packet': active, 'active_seconds_limit': 21600,
    'candidate_sha256': revision, 'imported': False, 'original_entries_checked': len(baseline), 'original_mismatches': changed,
    'implemented_unaccepted': ['R01: retain verified cleanup; compute sleep remainder once', 'R01b: complete missing-evidence rows in early CLI failure', 'R02a: finally cleanup with separate supervision and cleanup outcomes; fixed log-write-fault scenario'],
    'tested': ['R01b public CLI expected-failure reporting contract, not real runner acceptance', 'native no-fork containment and guardian lifecycle cases', 'real Pi Luna authenticated edit smoke'],
    'real_runner_e2es': 'NOT_RUN; explicitly blocked by independent review',
    'current_review': str(S / 'jobs/A6-R02a-source-review-001/final.txt'),
    'followup_plan': str(S / 'jobs/A6-resumption-plan-001/final.txt'),
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
write(S / 'RESULT-006.json', result)
scenarios = json.loads((S / 'required-esy-scenario-status-004.json').read_text())
for row in scenarios['required_scenarios']:
    row.update(actual='NOT_ACCEPTED_THROUGH_PUBLIC_RUNNER', reason='Real execution blocked by Astra lifecycle and seed review; source-only partial repairs do not close tests.', report_sha256=None)
scenarios['reporting_contract_only'] = record(D / 'R01b-assertions-002.json')
scenarios['source_sha256'] = sha((S / 'candidate/artifacts/planning/esy-reference-proposal-001/tests/test_esy_reference_runtime_e2e.py').read_bytes())
write(S / 'required-esy-scenario-status-006.json', scenarios)
history = packet / 'review-history.txt'
history.write_text('\n\n'.join('JOB ' + p.parent.name + '\n' + p.read_text() for p in sorted((S / 'jobs').glob('*/final.txt'))))
orchestration = packet / 'inline-orchestration.txt'
scripts = [S / 'candidate/scripts/esy-repair' / n for n in ['claude-worker.sh', 'pi-worker.sh', 'codex-worker.sh', 'controller.py']]
scripts += [S / 'bootstrap/trusted-codex-worker-003.sh', S / 'bootstrap/launch_worker.py', D / 'launch-pi-card.py', D / 'guardian-v2.py', D / 'pi-nofork-v3.sb']
orchestration.write_text('COMPLETE INLINE IMPLEMENTATIONS. Candidate controller/adapters are NOT accepted and must not be activated. Bootstrap launcher is for individually supervised read-only Astra roles only. Pi dispatcher approvals were one-launch-specific. This packet does not establish portable unattended orchestration or authorize launch22.\n\n' + '\n\n'.join('FILE ' + str(p) + '\nSHA256 ' + sha(p.read_bytes()) + '\n' + p.read_text() for p in scripts))
parts += [record(history), record(orchestration)]
write(packet / 'coverage.json', {'required_parts': parts, 'policy': 'Read every part and indexed evidence relevant to each claim. Missing context means BLOCKED. No final complete-context review has passed.'})
paths = set()
for old in ['artifact-index-004.json', 'artifact-index-005.json']:
    p = S / old
    paths.add(p)
    for row in json.loads(p.read_text())['files']:
        q = Path(row['path'])
        if record(q) != row:
            raise RuntimeError('Historical evidence changed: ' + str(q))
        paths.add(q)
for base in [D, packet]:
    for p in base.rglob('*'):
        rel = p.relative_to(base)
        if any(x in ('nofork-runtime', 'pi-runtime-v2', 'runtime', 'uv-cache', '__pycache__') for x in rel.parts):
            continue
        if p.is_file() and not p.is_symlink() and p.name not in ('auth.json', '.credentials.json'):
            paths.add(p)
for job in (S / 'jobs').glob('A6-*'):
    for p in job.iterdir():
        if p.is_file() and not p.is_symlink():
            paths.add(p)
paths.update(S / n for n in ['candidate-manifest-006.json', 'RESULT-006.json', 'required-esy-scenario-status-006.json'])
index = [record(p) for p in sorted(paths)]
evidence = sha(canonical(index))
write(S / 'artifact-index-006.json', {'evidence_sha256': evidence, 'files': index, 'excluded': ['all provider runtime directories', 'all authentication files', 'uv caches'], 'historical_evidence_verified': True})
prompt = '''You are the independent frontier reviewer of an esy reference-runner repair.
Review exact source and evidence; worker prose, prior approval and zero exit codes are not proof.

OBJECTIVE AND SCOPE
Offline esy execution with disposable writable caches, read-only compiler/dependencies, exact identities, bounded execution and reliable cleanup. No datasets, training, experiments or promotion. macOS only. uv and existing lockfile. Original source is not imported.

AUTHORITY
Latest human instruction replaces Fable with Codex Astra. Fresh Codex gpt-6-astra reviews; a separate fresh Astra process plans; smaller gpt-6-luna implements. Preserve historical reviewer records. Six additional coding launches were authorized after18; total cap24. No budget reset, no unattended controller. Read allocation.json for reconciled intervals and coding-ledger.json for consumption. Runtimes are deliberately excluded to protect credentials.

FINAL STATUS AND ACCOUNTING
''' + json.dumps(result, indent=2)
prompt += '\nREPOSITORY ' + str(ROOT) + '\nISOLATED CANDIDATE ' + str(S / 'candidate') + '\nBASELINE ' + json.dumps(record(S / 'baseline-manifest.json'))
prompt += '\nREVISION SHA256 ' + revision + '\nEVIDENCE SHA256 ' + evidence + '\nARTIFACT INDEX ' + str(S / 'artifact-index-006.json')
prompt += '\nSTARTING GIT AND DIRTY/UNTRACKED CONTEXT\n' + (S / 'bootstrap.json').read_text()
prompt += '''\nRUNTIME INVARIANTS
Base sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267.
Derivative sha256:06095e22e6fb4cedaaff8fa57e7951338bb7a80e2ac8b6d1d4d6bcc0b9727459.
Read-only root, network none, user1000:1000, cap-drop ALL, no-new-privileges, PID128, CPU2, memory2GiB, independently enforced container deadline<=120sec required.
/work executable128MiB; project _esy and node_modules/.cache tmpfs32MiB each; TMPDIR=/work. Never writable /home/opam/.esy or runtime esy install.
Canonical compiler /home/opam/.esy/4____________________________________________________________________/i/ocaml-5.5.1000-cb879550/bin/ocamlopt.opt; hash361d667103077d597d0e9cfaecaa1db997ceaa03de4b7144ff823e9f77fa4f24; version5.5.1, package5.5.1000, esy0.9.2.
Image build, base layers, full seed/package/lock inventories and two fixed diagnostic compile runs are indexed historical evidence. Diagnostics are not public runner E2Es. Original inventory comparisons must be exact; root-mtime exception only for copied/restored roots.

IMPLEMENTATION AND VERIFICATION
Read complete source and accumulated diffs in every source part. Read full raw coding/review envelopes, receipts and exact argv in indexed jobs. Launch19 implemented cleanup guard and captured sleep remainder;20 fixed reporting;21 added finally cleanup outcome retention. No new real Docker test was run in continuation006.
R01b CLI expected failure: exit1, complete three MISSING_FAILED rows, no output/expectation path creation; see R01b-e2e-002.json and assertions. Attempt001 was blocked by uv cache access and preserved. The positive reporting contract is not a positive esy result.
Codex no-fork edit smoke failed because code-mode requires child spawn. Pi with the SAME Luna model passed authenticated edit smoke under proven native no-fork profile. Credential handling/guardian changes and rejected earlier variants are indexed. Scope is individual supervised coding, not controller acceptance. Guardian host-death/SIGKILL and broad controller lifecycle guarantees remain limited.
Independent Astra source review rejects real runtime execution for open C17-01/03/05/06 and N6-01/02 gates. C17-04/07 have source fixes but missing runtime evidence. C17-02 is partial; N6-03 remains unchanged. Do not promote any source-only result to a closed E2E finding.
No import or post-import tests occurred. Original72-file verification is recorded; full controller/import E2Es remain outstanding. No overall acceptance or training readiness is established. The broad post-R02a planner timed out at240seconds; its partial prose is not a plan. A narrower resumption planner follows; inspect its receipt before relying on it.
'''
prompt += '\nFULL REQUIRED RUNNER SCENARIOS\n' + json.dumps(scenarios, indent=2)
prompt += '\nLATEST REVIEW\n' + (S / 'jobs/A6-R02a-source-review-001/final.txt').read_text()
prompt += '\nSEPARATE FRONTIER RESPONSE / NEXT CARDS\n' + (S / 'jobs/A6-resumption-plan-001/final.txt').read_text()
prompt += '\nINDEXED MULTIPART COVERAGE\n' + json.dumps(parts, indent=2)
prompt += '''
REVIEW INSTRUCTIONS
Read every indexed source/diff/orchestration/history part and verify artifact hashes. Source and all scripts are complete inline in their named parts; this explicit packet avoids silent truncation. If supported context cannot cover required parts, return BLOCKED with missing parts. Do not infer complete context from this cover prompt.
Check every requirement, exact revision/image/evidence binding, false positives, missing scenarios, unsafe cleanup, budget accounting, control authority, provider identity, concurrency and guarded import. Recheck immutable inputs before any future dispatch. Unaccepted controller must not authorize itself.
Return PASS only with zero findings and zero missing evidence. This packet currently has known missing evidence and execution blockers.
RETURN STRICT JSON:
{"revision_sha256":"''' + revision + '","evidence_sha256":"' + evidence + '''","verdict":"PASS | CHANGES_REQUIRED | BLOCKED","findings":[{"id":"stable identifier","severity":"severity","location":"file/scenario","problem":"concrete defect","required_change":"required behavior","required_e2e":"observable E2E acceptance"}],"missing_evidence":[]}

FOLLOW-UP
Send all findings to a fresh separate Codex gpt-6-astra planner. Produce bounded cards with exact inputs/hashes, allowed paths, prerequisites, behavior, forbidden changes, fixed public-process E2Es, expected outcomes and evidence. Smaller coding workers implement only authorized cards. Fresh Codex Astra reviews pre-execution and exact resulting evidence. Repeat until zero findings and missing evidence, or stop INCOMPLETE for genuine prerequisite/budget/context gates. No reviewer substitution, budget resets, unit tests, broad cleanup, weakened defaults or imported unaccepted changes. Three launches remain if ledger is still21; no request for another allocation is implied.
This handoff is supervisor-generated because controller print-handoff is unaccepted. It does not pass that missing controller gate.
'''
(S / 'FRONTIER_HANDOFF-006.txt').write_text(prompt)
for row in index:
    if record(Path(row['path'])) != row:
        raise RuntimeError('Indexed artifact changed: ' + row['path'])
print(prompt)
