"""Supervisor evidence packaging only; does not execute or accept candidate code."""
from pathlib import Path
import hashlib,json,stat,time,difflib,os
D=Path(__file__).resolve().parent; S=D.parent; ROOT=S.parents[2]
def sha(b):return hashlib.sha256(b).hexdigest()
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def rec(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
packet=S/'frontier-packet-008';packet.mkdir(exist_ok=False)
old=json.loads((S/'artifact-index-007.json').read_text())
for r in old['files']:
 if rec(Path(r['path']))!=r:raise RuntimeError('Historical evidence changed: '+r['path'])
baseline=json.loads((S/'baseline-manifest.json').read_text());mismatches=[]
for r in baseline:
 p=ROOT/r['path']
 if p.is_symlink() or not p.is_file() or sha(p.read_bytes())!=r['sha256'] or stat.S_IMODE(p.stat().st_mode)!=r['mode']:mismatches.append(r['path'])
assert not mismatches
manifest=[];parts=[]
for p in sorted((S/'candidate').rglob('*')):
 if p.is_symlink() or not(p.is_file() or p.is_dir()):raise RuntimeError('Unsupported candidate entry')
 if not p.is_file():continue
 rel=str(p.relative_to(S/'candidate'));manifest.append({'path':rel,'mode':stat.S_IMODE(p.stat().st_mode),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
 bp=S/'baseline'/rel; before=bp.read_text() if bp.exists() else '';after=p.read_text()
 if before!=after:
  dst=packet/('source-%03d.txt'%len(parts));dst.write_text('FILE '+rel+'\nCOMPLETE CANDIDATE SOURCE\n'+after+'\nACCUMULATED DIFF\n'+''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='baseline/'+rel,tofile='candidate/'+rel)));parts.append(rec(dst))
write(S/'candidate-manifest-008.json',manifest);revision=sha(canon(manifest))
proposal=D/'coding-jobs/L1a-023/frozen/artifacts/planning/esy-reference-proposal-001/esy_lifecycle.py'
rel='artifacts/planning/esy-reference-proposal-001/esy_lifecycle.py';before=(S/'candidate'/rel).read_text();after=proposal.read_text()
p=packet/'proposal-023.txt';p.write_text('UNREVIEWED PROPOSAL23, NOT MERGED INTO CANDIDATE OR ORIGINAL\n'+json.dumps(rec(proposal))+'\nCOMPLETE SOURCE\n'+after+'\nDIFF AGAINST CANDIDATE22\n'+''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='candidate22/'+rel,tofile='proposal23/'+rel)));parts.append(rec(p))
history=packet/'review-history.txt';history.write_text('\n\n'.join('JOB '+p.parent.name+'\nRECEIPT\n'+(p.parent/'receipt.json').read_text()+'\nFINAL\n'+p.read_text() for p in sorted((S/'jobs').glob('A8-*/final.txt'))));parts.append(rec(history))
scripts=[S/'candidate/scripts/esy-repair'/n for n in ['claude-worker.sh','pi-worker.sh','codex-worker.sh','controller.py']]+[S/'bootstrap/trusted-codex-worker-003.sh',S/'bootstrap/launch_worker.py',D/'launch-pi-card-high.py',D/'guardian-v2.py',D/'pi-nofork-v3.sb']
p=packet/'inline-orchestration.txt';p.write_text('Full scripts inline. Controller and portable adapters remain rejected; do not activate. Bootstrap is individually supervised, not unattended. Dispatch approvals were launch-specific, exhausted by launch23. Latest policy is fresh Codex Astra review, separate fresh Astra planning, Luna coding. Historical Fable references do not override that policy.\n\n'+'\n\n'.join('FILE '+str(q)+'\nSHA256 '+sha(q.read_bytes())+'\n'+q.read_text() for q in scripts));parts.append(rec(p))
a=json.loads((D/'allocation.json').read_text());used=json.loads((D/'coding-ledger.json').read_text())['coding_launches_consumed'];active=round(a['prior_active_seconds']+time.time()-a['current_turn_started_epoch'],3)
result={'status':'INCOMPLETE','reason':'Required fresh Astra review failed: Selected model is at capacity. No fallback. Proposal23 unreviewed; public lifecycle and esy acceptance remain unrun; controller rejected.','reviewer':'Codex gpt-6-astra','planner':'separate fresh Codex gpt-6-astra','coding_model':'gpt-6-luna via Pi openai-codex, explicit high reasoning for23','coding_launches_consumed':used,'coding_launch_cap':36,'coding_launches_remaining':36-used,'active_seconds_consumed_at_packet':active,'active_seconds_limit':32400,'active_seconds_remaining_at_packet':round(32400-active,3),'candidate_sha256':revision,'proposal23':rec(proposal),'proposal23_full_revision_manifest':rec(D/'coding-jobs/L1a-023/result-manifest.json'),'imported':False,'original_entries_checked':len(baseline),'original_mismatches':mismatches,'historical_indexed_files_verified':len(old['files']),'containers_created_this_continuation':False,'public_lifecycle_e2e':'NOT_RUN: exact-source approval unavailable','public_esy_e2e':'NOT_ACCEPTED; prior blockers remain','next_step':'When Astra is available, reconcile lock/processes/accounting and rerun independent source review of frozen23. Address every finding through separate Astra planning. Obtain one-launch authorization before harness24. No budget reset.'}
write(S/'RESULT-008.json',result)
scenarios=json.loads((S/'required-esy-scenario-status-007.json').read_text());scenarios['continuation008']='No public runner or lifecycle scenario executed; source drafts and provider smoke checks cannot close any row.';write(S/'required-esy-scenario-status-008.json',scenarios)
write(packet/'coverage.json',{'required_parts':parts,'historical_context':rec(S/'FRONTIER_HANDOFF-007.txt'),'rule':'Reviewer must read every source/diff/scripts/history part and relevant indexed evidence. Missing context is BLOCKED, never implicit approval.'})
lock=S/'exclusive-supervised-workflow.lock';lv=json.loads(lock.read_text());assert lv['state']==str(D) and lv['turn_id']=='01a1665d-5905-75f3-86f7-3863cbc7eaa3';assert json.loads((D/'final-cleanup-check.json').read_text())['matching_processes']==[];lock.unlink()
with (D/'events.jsonl').open('a') as f:f.write(json.dumps({'event':'INCOMPLETE_PROVIDER_CAPACITY','epoch':time.time(),'coding_consumed':used,'active_seconds_checkpoint':active,'workflow_lock_released_after_cleanup':True,'original_unchanged':True})+'\n');f.flush();os.fsync(f.fileno())
paths={Path(r['path']) for r in old['files']};paths.update([S/'artifact-index-007.json',S/'FRONTIER_HANDOFF-007.txt'])
for base in [D,packet]:
 for p in base.rglob('*'):
  if any(x in ('pi-runtime-v2','runtime','uv-cache','__pycache__') for x in p.relative_to(base).parts):continue
  if p.is_file() and not p.is_symlink() and p.name not in ('auth.json','.credentials.json'):paths.add(p)
for j in (S/'jobs').glob('A8-*'):
 for p in j.iterdir():
  if p.is_file() and not p.is_symlink():paths.add(p)
paths.update(S/n for n in ['candidate-manifest-008.json','RESULT-008.json','required-esy-scenario-status-008.json'])
index=[rec(p) for p in sorted(paths)];evidence=sha(canon(index));write(S/'artifact-index-008.json',{'evidence_sha256':evidence,'files':index,'excluded':['private provider runtimes','authentication files','uv caches'],'historical_evidence_verified':True})
prompt='''You are the independent frontier reviewer of an esy runner repair.
Review exact source and evidence. Previous approval, worker prose and exit zero are not proof.

OBJECTIVE
Repair offline esy execution using disposable writable caches with read-only dependencies/compiler, exact identities, bounded execution and reliable cleanup. No datasets, training, adapter experiments or model promotion. E2E only, uv, existing lockfile, macOS.

FINAL STATUS, BUDGET, REVISION
'''+json.dumps(result,indent=2)
prompt+='\nREPOSITORY '+str(ROOT)+'\nCANDIDATE '+str(S/'candidate')+'\nBASELINE '+json.dumps(rec(S/'baseline-manifest.json'))+'\nEVIDENCE SHA256 '+evidence+'\nARTIFACT INDEX '+str(S/'artifact-index-008.json')
prompt+='\nSTARTING GIT AND DIRTY/UNTRACKED CONTEXT\n'+(S/'bootstrap.json').read_text()
prompt+='''\nAUTHORITY AND ACCOUNTING
The user chose the dedicated lifecycle supervisor and added 12 coding launches and 3 active hours, then said Execute plan. Caps36/32400 preserve prior use; allocation.json records reconciled active intervals and excluded user waits. Latest user instruction replaces Fable with Codex Astra. Separate fresh Astra plans; smaller Luna codes. Review capacity failure is a blocker, not permission to substitute. No unattended controller or original import. Final cleanup query found all recorded workers absent and no temporary authentication links; this continuation created no containers. Lock was explicitly released after reconciliation, not stolen by age.

RUNTIME INVARIANTS
Base sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267.
Derivative sha256:06095e22e6fb4cedaaff8fa57e7951338bb7a80e2ac8b6d1d4d6bcc0b9727459.
Read-only root; network none; user1000:1000; cap-drop ALL; no-new-privileges; PID128; CPU2; memory2GiB; independent container deadline<=120sec. /work executable128MiB; project _esy and node_modules/.cache tmpfs32MiB each; TMPDIR=/work. Never writable /home/opam/.esy or runtime esy install.
Compiler /home/opam/.esy/4____________________________________________________________________/i/ocaml-5.5.1000-cb879550/bin/ocamlopt.opt; SHA256 361d667103077d597d0e9cfaecaa1db997ceaa03de4b7144ff823e9f77fa4f24; version5.5.1, package5.5.1000, esy0.9.2. Complete build receipts and inventories are indexed historical evidence; two diagnostic successes do not establish public-runner acceptance. Exact original inventories; root-mtime exception only for copied/restored cache roots.

IMPLEMENTATION AND VERIFICATION
Historical19–21 are partial source repairs, not accepted runner E2Es. This continuation verified all1316 prior indexed artifacts and original72 source entries. Native no-fork containment refresh passed actual denied original-file/auth access, denied spawn and Docker-socket access, and allowed private writes. Default and explicit-high real Pi/Luna smokes passed. These are provider checks only.
Launch22 added the standalone supervisor and public E2E harness, changed only two allowed files, and was rejected by Astra with14 findings before execution. Launch23 changed only the supervisor under a separate Astra L1a card. It is frozen separately, not merged into candidate22 or original. The provider envelope, identity, scope and cleanup passed; AST parsing is not an E2E. Source review of23 failed because Astra was at capacity. No new authored source was executed.
Earlier review/planning attempts with cleanup-denied receipts remain FAILED, even though subsequent complete process queries found their groups absent. Fresh successful replacements provided the dispatch approval and separate correction plan. Do not rely on failed-response prose as authority.
Open work: supervisor23 source review and corrections; separate L1b harness correction; five live public lifecycle scenarios; ownership/create/query/deadline integration; seed comparisons; real allocation/OOM evidence; full esy matrix; independently rejected controller/import gates. C17 and N6 findings remain open until actual observable E2E evidence closes them. No post-import verification occurred because no import occurred.

REVIEW HISTORY / SEPARATE CORRECTION PLAN
'''+(S/'jobs/A8-L1-review-001/final.txt').read_text()+'\n'+(S/'jobs/A8-L1-correction-plan-002/final.txt').read_text()
prompt+='\nFULL REQUIRED RUNNER SCENARIO STATUS\n'+json.dumps(scenarios,indent=2)+'\nREQUIRED INDEXED PARTS (complete source/diff/scripts inline within each part)\n'+json.dumps(parts,indent=2)
prompt+='''\nREVIEW INSTRUCTIONS
Read every required part, prior handoff007 and indexed evidence supporting every claim. Verify hashes and distinguish candidate22 from proposed23. If context is insufficient, return BLOCKED and identify missing parts; no silent truncation. Check scope, safety, expected/actual E2E outcomes, exact image/revision binding, stale approvals, false positives, process cleanup, accounting, controller authority and guarded import. Never treat absent tests as impossible tests or diagnostic probes as runner acceptance.
Return PASS only with zero findings and zero missing evidence. Current packet deliberately records unresolved findings and missing E2Es.
RETURN STRICT JSON
'''+json.dumps({'revision_sha256':revision,'evidence_sha256':evidence,'verdict':'PASS | CHANGES_REQUIRED | BLOCKED','findings':[{'id':'stable ID','severity':'severity','location':'file/scenario','problem':'concrete defect','required_change':'required behavior','required_e2e':'observable end-to-end acceptance'}],'missing_evidence':[]},indent=2)+'''
FOLLOW-UP LOOP
Every finding goes to a fresh separate Codex gpt-6-astra planner for bounded small-worker cards: exact hashes/inputs, allowed paths, prerequisites, behavior, forbidden changes, fixed public E2E recipes, expected outcomes and evidence. Small Luna workers implement; fresh Codex Astra reviews exact source before host execution and exact E2E evidence afterward. Repeat until no findings/missing evidence, or stop INCOMPLETE for provider/containment/cleanup/context/budget gates. Three failed coding attempts on one objective require separate replanning. Do not reset budgets or broaden scope. Preserve originals and concurrent edits; import only after all global gates, backed up and hash-verified, then final E2Es and fresh review. No unit tests.
This handoff was printed by the supervising agent because the rejected controller cannot provide trusted print-handoff. It does not satisfy that controller gate. Resume by reconciling this packet and inactive intervals; do not charge user idle time or reset consumption.
'''
(S/'FRONTIER_HANDOFF-008.txt').write_text(prompt)
for r in index:
 if rec(Path(r['path']))!=r:raise RuntimeError('Indexed artifact changed')
print(prompt)
