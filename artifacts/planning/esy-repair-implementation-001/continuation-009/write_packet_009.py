"""Preserve blocked evidence and print a complete indexed review handoff."""
from pathlib import Path
import hashlib,json,stat,time,difflib,os
D=Path(__file__).resolve().parent;S=D.parent;ROOT=S.parents[2];C=D/'candidate'
def sha(b):return hashlib.sha256(b).hexdigest()
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def rec(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
packet=S/'frontier-packet-009';packet.mkdir(exist_ok=False)
old=json.loads((S/'artifact-index-008.json').read_text())
for r in old['files']:
 if rec(Path(r['path']))!=r:raise RuntimeError('Historical artifact changed: '+r['path'])
baseline=json.loads((S/'baseline-manifest.json').read_text())
for r in baseline:
 p=ROOT/r['path'];assert not p.is_symlink() and p.is_file() and sha(p.read_bytes())==r['sha256'] and stat.S_IMODE(p.stat().st_mode)==r['mode']
manifest=[];parts=[]
for p in sorted(C.rglob('*')):
 if p.is_symlink() or not(p.is_file() or p.is_dir()):raise RuntimeError('Unsupported candidate entry')
 if not p.is_file():continue
 rel=str(p.relative_to(C));manifest.append({'path':rel,'mode':stat.S_IMODE(p.stat().st_mode),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
 bp=S/'baseline'/rel;before=bp.read_text() if bp.exists() else '';after=p.read_text()
 if before!=after:
  dest=packet/('source-%03d.txt'%len(parts));dest.write_text('FILE '+rel+'\nCOMPLETE WORKING SOURCE\n'+after+'\nACCUMULATED DIFF\n'+''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='baseline/'+rel,tofile='working/'+rel)));parts.append(rec(dest))
write(S/'candidate-manifest-009.json',manifest);revision=sha(canon(manifest))
proposal=D/'coding-jobs/B1a-E2E-025/frozen/tests/e2e/test_review_adapter_e2e.py';dest=packet/'proposal-025.txt';dest.write_text('UNREVIEWED AND UNEXECUTED E2E PROPOSAL25; NOT MERGED INTO WORKING CANDIDATE OR ORIGINAL\n'+json.dumps(rec(proposal))+'\nCOMPLETE SOURCE\n'+proposal.read_text()+'\nACCUMULATED DIFF\n'+''.join(difflib.unified_diff([],proposal.read_text().splitlines(True),fromfile='/dev/null',tofile='tests/e2e/test_review_adapter_e2e.py')));parts.append(rec(dest))
history=packet/'review-history.txt';history.write_text('\n\n'.join('JOB '+p.parent.name+'\nRECEIPT\n'+(p.parent/'receipt.json').read_text()+'\nFINAL\n'+p.read_text() for p in sorted((S/'jobs').glob('A9-*/final.txt'))));parts.append(rec(history))
scripts=[C/'scripts/esy-repair'/n for n in ['claude-worker.sh','pi-worker.sh','codex-worker.sh','controller.py']]+[S/'bootstrap/trusted-codex-worker-003.sh',S/'bootstrap/launch_worker.py',D/'claude-worker.sh',D/'launch-bootstrap-review.py',D/'launch-B1a.py',D/'launch-B1a-e2e.py',S/'continuation-008/guardian-v2.py',S/'continuation-008/pi-nofork-v3.sb',D/'fable-smoke.py',D/'fable-smoke-001/claude-worker.sh']
dest=packet/'inline-orchestration.txt';dest.write_text('COMPLETE INLINE SCRIPTS. No unattended controller accepted. Each coding dispatch approval was one-launch-specific and has been consumed. Candidate B1a is primary routing only; the temporary fallback smoke wrapper does not implement accepted fallback policy. The unchanged candidate Codex adapter takes five arguments; B1a forwards all five. Final four-argument portable target remains incomplete. Runtime authentication and caches are excluded.\n\n'+'\n\n'.join('FILE '+str(p)+'\nSHA256 '+sha(p.read_bytes())+'\n'+p.read_text() for p in scripts));parts.append(rec(dest))
a=json.loads((D/'allocation.json').read_text());used=json.loads((D/'coding-ledger.json').read_text())['coding_launches_consumed'];active=round(a['prior_active_seconds']+time.time()-a['current_turn_started_epoch'],3)
result={'status':'INCOMPLETE','reason':'Astra E2E source review returned explicit capacity failure; user-authorized Fable fallback smoke failed authentication: OAuth session expired and could not be refreshed. Neither route available for required review.','coding_launches_consumed':used,'coding_launch_cap':36,'coding_launches_remaining':36-used,'active_seconds_consumed_at_packet':active,'active_seconds_limit':32400,'active_seconds_remaining_at_packet':round(32400-active,3),'working_candidate':str(C),'working_candidate_sha256':revision,'proposal25':rec(proposal),'proposal25_full_manifest':rec(D/'coding-jobs/B1a-E2E-025/result-manifest.json'),'original_entries_verified':len(baseline),'original_mismatches':[],'historical_artifacts_verified':len(old['files']),'imported':False,'containers_created':False,'completed_this_continuation':['Reconciled prior activity and preserved original72 plus prior1634 indexed files','Native containment and authenticated high-Luna smoke passed','B1a primary review-routing adapter authored in coding24 and independently statically approved with no findings','Public-process E2E draft authored in coding25; not executed','Explicit Astra availability failure recorded; Fable fallback smoke attempted and rejected on authentication failure','All recorded process groups absent and temporary credential links removed'],'not_completed':['B1a public E2Es and real primary routing smoke','B1 fallback policy/envelope implementation and successful Fable preflight','B2/B3 accepted supervision/controller E2Es','S1/E1/S2/E2/S3/E3 and all H/E/A lifecycle cards','Full authentic lifecycle suite, full esy matrix, global import gates'],'next_step':'Restore an available review route (Astra capacity or valid Claude authentication), reconcile idle/active time, then review exact frozen25. Route findings to fresh separate Astra planning before further coding. No new allocation required.'}
write(S/'RESULT-009.json',result)
scenarios=json.loads((S/'required-esy-scenario-status-008.json').read_text());scenarios['continuation009']='No public adapter test or lifecycle/runner scenario executed. Adapter static approval and provider smoke are not E2E acceptance.';write(S/'required-esy-scenario-status-009.json',scenarios)
write(packet/'coverage.json',{'required_parts':parts,'historical_context':[rec(S/'FRONTIER_HANDOFF-008.txt'),rec(S/'handoff-008-subagent-review.json')],'required_authorized_plan':rec(D/'authorized-plan.txt'),'rule':'Read required parts and relevant indexed receipts completely. Hash verification is not semantic review. Missing context is BLOCKED.'})
lock=S/'exclusive-supervised-workflow.lock';assert json.loads(lock.read_text())['state']==str(D);assert json.loads((D/'final-cleanup-check.json').read_text())['matching_processes']==[];lock.unlink()
with (D/'events.jsonl').open('a') as f:f.write(json.dumps({'event':'INCOMPLETE_REVIEW_PROVIDERS','epoch':time.time(),'coding_consumed':used,'active_seconds_checkpoint':active,'lock_released_after_reconciliation':True})+'\n');f.flush();os.fsync(f.fileno())
paths={Path(r['path']) for r in old['files']};paths.update([S/'artifact-index-008.json',S/'FRONTIER_HANDOFF-008.txt',S/'handoff-008-subagent-review.json'])
for base in [D,packet]:
 for p in base.rglob('*'):
  if any(x in ('pi-runtime-v2','runtime','uv-cache','__pycache__') for x in p.relative_to(base).parts):continue
  if p.is_file() and not p.is_symlink() and p.name not in ('auth.json','.credentials.json'):paths.add(p)
for job in (S/'jobs').glob('A9-*'):
 for p in job.iterdir():
  if p.is_file() and not p.is_symlink():paths.add(p)
paths.update(S/n for n in ['candidate-manifest-009.json','RESULT-009.json','required-esy-scenario-status-009.json'])
index=[rec(p) for p in sorted(paths)];evidence=sha(canon(index));write(S/'artifact-index-009.json',{'evidence_sha256':evidence,'files':index,'excluded':['provider runtimes','authentication files','uv caches'],'historical_evidence_verified':True})
prompt='''You are the independent frontier reviewer of this lifecycle repair batch.
Do not treat previous approval, worker prose, a successful provider call or exit zero as proof.

OBJECTIVE AND SCOPE
Fix lifecycle executable identity checks, fork-failure classification, cleanup status, public E2E harness, and supervised small-agent workflow. No unit tests, dataset work, training, model promotion or original import. This does not establish full esy or training readiness.

FINAL STATUS AND ACCOUNTING
'''+json.dumps(result,indent=2)
prompt+='\nREPOSITORY '+str(ROOT)+'\nBASELINE '+json.dumps(rec(S/'baseline-manifest.json'))+'\nREVISION SHA256 '+revision+'\nEVIDENCE SHA256 '+evidence+'\nARTIFACT INDEX '+str(S/'artifact-index-009.json')+'\nSTARTING GIT CONTEXT\n'+(S/'bootstrap.json').read_text()
prompt+='''\nLATEST AUTHORITY AND PROVIDER POLICY
User authorized implementation of the complete plan included below. Review entrypoint is claude-worker.sh: Codex gpt-6-astra first, Claude literal fable only after proven availability failure. Never fall back for substantive findings, malformed output, identity/context/auth/permission/safety failures, or cleanup uncertainty. The fallback's authentication failure stops the loop; do not evade it. Planner remains a separate fresh Astra process without fallback. Coding is exact gpt-6-luna high via isolated Pi openai-codex; alternatives need independent preflight. No budget reset; exclude user idle intervals and include planning/review active time.

IMPLEMENTED AND STILL UNACCEPTED
Isolated working candidate starts with candidate22 plus frozen23 supervisor. Coding24 changed only claude-worker.sh: its review route now forwards to the sibling five-argument Codex adapter before requiring Claude variables. Independent Astra static review returned no findings. This is not full B1, not fallback-policy activation, and not a successful public E2E.
Coding25 authored only tests/e2e/test_review_adapter_e2e.py. It is preserved separately as proposal25, not merged into the working candidate or original. Complete Pi envelope, exact model, single-file scope and cleanup were verified. AST parsing is not testing. Root noticed potential missing result-file publication, unbounded record reads, arity coverage errors, negative sleep and post-reap signal risks; these are UNREVIEWED OBSERVATIONS requiring independent review and separate planning, not accepted fixes.
The E2E source reviewer failed with explicit Astra capacity. Fable was attempted through a separate tools-disabled read-only Claude worker with only a temporary link to the existing credential file. It returned is_error=true and OAuth session expired/could not refresh; no model identity was established and no review ran. Temporary links were removed. Do not count subtype success in that envelope as provider success.
Earlier E2E planning attempt timed out at180seconds and remains FAILED. A fresh narrower planner completed. All failed receipts are preserved. New bootstrap routing scripts and draft outer-test wrapper are not an accepted unattended supervisor; the outer-test wrapper has not been reviewed or executed.

RUNTIME INVARIANTS AND PROVENANCE
Base sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267.
Derivative sha256:06095e22e6fb4cedaaff8fa57e7951338bb7a80e2ac8b6d1d4d6bcc0b9727459.
Read-only root; network none; user1000:1000; cap-drop ALL; no-new-privileges; PID128; CPU2; memory2GiB; independent container deadline<=120sec. /work executable128MiB; both project cache mounts32MiB; TMPDIR=/work. Never writable /home/opam/.esy or runtime esy install.
Compiler /home/opam/.esy/4____________________________________________________________________/i/ocaml-5.5.1000-cb879550/bin/ocamlopt.opt; SHA256 361d667103077d597d0e9cfaecaa1db997ceaa03de4b7144ff823e9f77fa4f24; version5.5.1, package5.5.1000, esy0.9.2. Complete historical build and seed/package/lock inventories are indexed. Diagnostic compilation does not satisfy public runner acceptance. Executable-binding snapshots detect observed changes, not arbitrary transient TOCTOU swaps.

EXACT AUTHORIZED PLAN, SMALL CARDS, INLINE TARGET SCRIPTS AND LOOP
'''+(D/'authorized-plan.txt').read_text()
prompt+='\nCURRENT SEPARATE FRONTIER CARDS\n'+(S/'jobs/A9-B1a-plan-001/final.txt').read_text()+'\n'+(S/'jobs/A9-B1a-e2e-plan-002/final.txt').read_text()
prompt+='\nPRIOR INDEPENDENT REVIEW / OPEN FINDINGS\n'+(S/'handoff-008-subagent-review.json').read_text()
prompt+='\nFULL REQUIRED RUNNER SCENARIO STATUS\n'+json.dumps(scenarios,indent=2)+'\nREQUIRED SOURCE, DIFF, SCRIPT AND HISTORY PARTS\n'+json.dumps(parts,indent=2)
prompt+='''\nREVIEW INSTRUCTIONS
Read every required part and relevant indexed receipts. Prior unread broader-controller/runner sections remain gaps. Partition review with exact coverage receipts if necessary; no silent truncation or claims from hashes alone. Verify source/evidence identity, expected/actual E2E coverage, bootstrap authority, provider failure classification, accounting, cleanup and scope. Native containment/smoke are not native lifecycle acceptance. All original72 files are unchanged and no import/post-import verification occurred. Missing tests are not proof they are impossible. Return PASS only with zero findings and missing evidence for the clearly stated batch; never clear wider gates implicitly.
RETURN STRICT JSON
'''+json.dumps({'revision_sha256':revision,'evidence_sha256':evidence,'verdict':'PASS | CHANGES_REQUIRED | BLOCKED','findings':[{'id':'stable identifier','severity':'severity','location':'file or scenario','problem':'concrete defect','required_change':'required behavior','required_e2e':'observable E2E acceptance'}],'missing_evidence':[]},indent=2)+'''
MANDATORY FOLLOW-UP
Every finding goes to a fresh separate Astra planner for bounded cards. Small workers author, root freezes and validates scope, fresh review precedes fixed E2Es, then fresh review covers actual evidence. Route through claude-worker.sh with the explicit availability-only fallback policy. Do not ignore returned reviews, substitute planners, reset budgets, weaken restrictions, or import unaccepted changes. Stop INCOMPLETE for provider/containment/cleanup/context/budget gates. Resume only after reconciling this checkpoint and later active intervals; do not charge idle user waits.
This handoff is supervisor-generated because the rejected controller cannot supply an accepted print-handoff command. It does not clear that missing gate.
'''
(S/'FRONTIER_HANDOFF-009.txt').write_text(prompt)
for r in index:
 if rec(Path(r['path']))!=r:raise RuntimeError('Evidence changed')
print(prompt)
