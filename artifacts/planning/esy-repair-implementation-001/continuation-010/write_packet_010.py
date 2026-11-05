"""Supervisor evidence publication only; does not execute candidate code."""
from pathlib import Path
import ast,hashlib,json,stat,time,difflib,os
D=Path(__file__).resolve().parent;S=D.parent;ROOT=S.parents[2];C=D/'candidate'
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def rec(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
def write(p,x):
 with p.open('x') as f:json.dump(x,f,indent=2);f.write('\n')
old=json.loads((S/'artifact-index-009.json').read_text())
for r in old['files']:
 assert rec(Path(r['path']))==r,'historical evidence changed: '+r['path']
baseline=json.loads((S/'baseline-manifest.json').read_text())
for r in baseline:
 p=ROOT/r['path'];assert p.is_file() and not p.is_symlink() and sha(p.read_bytes())==r['sha256'] and stat.S_IMODE(p.stat().st_mode)==r['mode']
assert json.loads((D/'final-cleanup-check.json').read_text())['matching_processes']==[]
assert not (S/'continuation-008/pi-runtime-v2/private-pi/auth.json').exists()
packet=S/'frontier-packet-010';packet.mkdir(exist_ok=False);parts=[];manifest=[]
for p in sorted(C.rglob('*')):
 assert not p.is_symlink() and (p.is_file() or p.is_dir())
 if not p.is_file():continue
 rel=str(p.relative_to(C));manifest.append({'path':rel,'mode':stat.S_IMODE(p.stat().st_mode),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
 bp=S/'baseline'/rel;before=bp.read_text() if bp.exists() else '';after=p.read_text()
 if before!=after:
  dest=packet/('source-%03d.txt'%len(parts));dest.write_text('FILE '+rel+'\nCOMPLETE SOURCE\n'+after+'\nEXACT ACCUMULATED DIFF\n'+''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='baseline/'+rel,tofile='candidate/'+rel)));parts.append(rec(dest))
write(S/'candidate-manifest-010.json',manifest);canonical_revision=sha(canonical(manifest))
reviewed_manifest=D/'coding-jobs/B1a-Diagnostics-036/result-manifest.json'
reviewed_rows=json.loads(reviewed_manifest.read_text())
assert [{'path':x['path'],'mode':x['mode'],'size':x['bytes'],'sha256':x['sha256']} for x in manifest]==reviewed_rows
revision=sha(reviewed_manifest.read_bytes())
review_paths=sorted(D.glob('*review*.json'));plan_paths=sorted(D.glob('astra-plan*.json'))+[D/'astra-correction-plan-026.json',D/'execution-envelope-plan.json',D/'remaining-frontier-plan.json']
for label,paths in [('review-history',review_paths),('separate-frontier-cards',plan_paths)]:
 p=packet/(label+'.txt');p.write_text('\n\n'.join('ARTIFACT '+str(f)+'\nSHA256 '+sha(f.read_bytes())+'\n'+f.read_text() for f in paths));parts.append(rec(p))
scripts=[C/'scripts/esy-repair'/n for n in ['claude-worker.sh','pi-worker.sh','codex-worker.sh','controller.py']]+[D/'launch-correction.py',D/'pi-smoke-high.py',D/'validate-coding-evidence.py',D/'assemble-card-prompt.py',S/'bootstrap/trusted-codex-worker-003.sh',S/'bootstrap/launch_worker.py',S/'continuation-008/guardian-v2.py',S/'continuation-008/pi-nofork-v3.sb']
p=packet/'inline-orchestration.txt';p.write_text('Complete actual scripts. Rejected controller remains disabled. Every coding approval is consumed; no dispatch37 authority. Latest review policy: Astra only, Claude unavailable and disabled. Alternative coding adapters are not activated. Native sandbox/runtime auth checks remain mandatory.\n\n'+'\n\n'.join('FILE '+str(f)+'\nSHA256 '+sha(f.read_bytes())+'\n'+f.read_text() for f in scripts));parts.append(rec(p))
target=(S/'continuation-009/authorized-plan.txt').read_text().split('### `run-repair-loop.sh`',1)[1].split('```bash',1)[1].split('```',1)[0]
with (packet/'inline-orchestration.txt').open('a') as f:f.write('\nUNACCEPTED TARGET LOOP, INCLUDED INLINE FOR PORTABILITY; NOT ACTIVATABLE\n'+target)
parts[-1]=rec(packet/'inline-orchestration.txt')
a=json.loads((D/'allocation.json').read_text());used=json.loads((D/'coding-ledger.json').read_text())['coding_launches_consumed'];assert used==36
active=round(a['prior_active_seconds']+time.time()-a['current_turn_started_epoch'],3)
jobs=[]
for j in sorted((D/'coding-jobs').iterdir()):
 if not j.is_dir():continue
 r=json.loads((j/'guardian/receipt.json').read_text());jobs.append({'job':j.name,'receipt':rec(j/'guardian/receipt.json'),'exit_code':r['exit_code'],'reason':r['reason'],'worker_reaped':r['worker_reaped'],'credential_removed':r['credential_removed'],'status':'FAILED_UNACCEPTED' if r['exit_code']!=0 else 'SOURCE_ONLY_RUNTIME_UNACCEPTED'})
result={'status':'INCOMPLETE','reason':'Authorized coding cap36 exhausted. Complete result receipt/invocation inventory and independently reviewed outer execution wrapper are missing; public adapter/lifecycle/runner E2Es have not run. Broader supervisor/controller/import gates remain open.','review_policy':'Astra only. Claude/Fable unavailable and disabled by latest human instruction.','coding_launches_consumed':used,'coding_launch_cap':36,'coding_launches_remaining':0,'active_seconds_consumed_at_packet':active,'active_seconds_limit':32400,'active_seconds_remaining_at_packet':round(32400-active,3),'working_candidate':str(C),'working_candidate_sha256':revision,'revision_identity_definition':'SHA256 of exact final coding result-manifest.json; candidate files independently matched its 82 entries','normalized_candidate_inventory_sha256':canonical_revision,'last_coding_revision_manifest':rec(D/'coding-jobs/B1a-Diagnostics-036/result-manifest.json'),'original_entries_verified':len(baseline),'historical_artifacts_verified':len(old['files']),'original_mismatches':[],'imported':False,'containers_created':False,'public_candidate_e2es_executed':False,'source_review_final':rec(D/'astra-source-review-036.json'),'remaining_frontier_plan':rec(D/'remaining-frontier-plan.json'),'jobs':jobs,'next_step':'New human coding allocation is required before any further coding. Reconcile tail active time and idle intervals, preserve all budgets, bind future cards to this source, and satisfy missing receipts/wrapper and real E2Es before acceptance. No automatic import or dispatch.'}
write(S/'RESULT-010.json',result)
source=(C/'tests/e2e/test_review_adapter_e2e.py').read_text();tree=ast.parse(source);names=[]
for node in ast.walk(tree):
 if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument' and node.args and isinstance(node.args[0],ast.Constant) and node.args[0].value=='--scenario':
  for kw in node.keywords:
   if kw.arg=='choices':names=list(ast.literal_eval(kw.value))
scenarios={'public_adapter_scenarios':[{'scenario':n,'actual':'NOT_RUN','evidence':None,'reason':'Execution prerequisites incomplete; source review is not runtime evidence'} for n in names],'historical_runner_matrix':json.loads((S/'required-esy-scenario-status-009.json').read_text()),'native_containment':rec(D/'native-probe.json'),'real_luna_smoke':rec(D/'pi-smoke-high-result.json'),'independent_smoke_validation':rec(D/'smoke-independent-check.json'),'note':'Containment and authenticated worker smoke passed. No adapter routing E2E, lifecycle E2E or esy runner E2E was executed this continuation.'}
write(S/'required-esy-scenario-status-010.json',scenarios)
write(packet/'coverage.json',{'required_parts':parts,'historical_context':[rec(S/'FRONTIER_HANDOFF-009.txt'),rec(S/'handoff-008-subagent-review.json')],'authorized_original_plan':rec(S/'continuation-009/authorized-plan.txt'),'latest_override':'Use Codex Astra in a separate agent; Claude unavailable. No Fable fallback.','coverage_limit':'Reviews025-036 are source-card reviews only, through explicit user-authorized separate Astra agents. They do not satisfy final CLI-through-adapter review, public E2E, broader controller/source coverage or final acceptance. Read every indexed required part; unread context is BLOCKED.'})
lock=S/'exclusive-supervised-workflow.lock';assert json.loads(lock.read_text())['continuation']==str(D);lock.unlink()
with (D/'events.jsonl').open('a') as f:f.write(json.dumps({'event':'INCOMPLETE_CODING_CAP_EXHAUSTED','epoch':time.time(),'coding_consumed':used,'active_seconds_checkpoint':active,'lock_released_after_verified_cleanup':True})+'\n');f.flush();os.fsync(f.fileno())
paths={Path(r['path']) for r in old['files']};paths.update([S/'artifact-index-009.json',S/'FRONTIER_HANDOFF-009.txt',S/'handoff-009-print.txt'])
for base in (D,packet):
 for p in base.rglob('*'):
  if any(x in ('runtime','pi-runtime-v2','uv-cache','__pycache__') for x in p.relative_to(base).parts):continue
  if p.is_file() and not p.is_symlink() and p.name not in ('auth.json','.credentials.json'):paths.add(p)
paths.update(S/n for n in ['candidate-manifest-010.json','RESULT-010.json','required-esy-scenario-status-010.json'])
index=[rec(p) for p in sorted(paths)];evidence=sha(canonical(index));write(S/'artifact-index-010.json',{'evidence_sha256':evidence,'files':index,'excluded':['private provider runtime/authentication files','caches'],'historical_evidence_verified':True})
prompt='''You are the independent frontier reviewer of this esy lifecycle repair continuation.
Do not treat model approval, AST parsing, worker prose or exit zero as runtime proof.

OBJECTIVE
Review the current adapter E2E source and supervised small-agent fixes; keep broader esy lifecycle/controller/import and training gates separate. No training/dataset generation/import authorized. No unit tests.

FINAL STATUS AND ACCOUNTING
'''+json.dumps(result,indent=2)
prompt+='\nREPOSITORY '+str(ROOT)+'\nBASELINE '+json.dumps(rec(S/'baseline-manifest.json'))+'\nCANDIDATE REVISION SHA256 '+revision+'\nEVIDENCE MANIFEST SHA256 '+evidence+'\nARTIFACT INDEX '+str(S/'artifact-index-010.json')+'\nSTARTING GIT CONTEXT\n'+(S/'bootstrap.json').read_text()
prompt+='''\nLATEST HUMAN AUTHORITY
Go. In a separate agent, Retry the review with Astra and continue addressing the findings.
Claude unavailable: use Codex Astra. This overrides every historical Fable/fallback clause below and in indexed artifacts. No new allocation was granted;36 is a hard coding cap. Astra planning/review remains separate from Luna coding. Do not launch coding37 or silently reset consumption.

WHAT HAPPENED
Fresh separate Astra review025 found seven source defects. Fresh separate Astra planners created bounded cards; Luna high via Pi authored in private no-fork sandboxes; independent Astra reviewed each frozen result. Ownership, deadline, raw record bounds, per-invocation routing, argument counts and diagnostic limits received source corrections. See final review for exact dispositions; none are claimed E2E-accepted. Failed coding32 hit2MiB output cap, was killed and reaped, auth removed, partial source preserved and rejected. Coding33 restarted reviewed31 with smaller edits. All eleven launches26-36 count. No public candidate tests, containers or imports occurred. Source review used explicit separate Astra agents per current human request; an actual final review via the candidate adapter remains missing. Rejected unattended controller never activated.

EXACT SOURCE, ACCUMULATED DIFF AND PORTABLE SCRIPTS
'''
prompt+='\nCURRENT COMPLETE TEST SOURCE\n'+source+'\nCURRENT COMPLETE TEST DIFF FROM BASELINE\n'+''.join(difflib.unified_diff([],source.splitlines(True),fromfile='baseline/absent',tofile='candidate/tests/e2e/test_review_adapter_e2e.py'))
prompt+='\nCOMPLETE INLINE ORCHESTRATION\n'+(packet/'inline-orchestration.txt').read_text()
prompt+='\nFINAL SOURCE REVIEW\n'+(D/'astra-source-review-036.json').read_text()+'\nSEPARATE FRONTIER DISPOSITION AND REMAINING CARDS\n'+(D/'remaining-frontier-plan.json').read_text()
prompt+='\nFULL SCENARIO STATUS\n'+json.dumps(scenarios,indent=2)+'\nMANDATORY INDEXED SOURCE, DIFF, CARD AND HISTORY PARTS\n'+json.dumps(parts,indent=2)
prompt+='''\nPROVENANCE AND INVARIANTS
Historical base image sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267; derivative sha256:06095e22e6fb4cedaaff8fa57e7951338bb7a80e2ac8b6d1d4d6bcc0b9727459. No new image checks or builds this continuation. Historical inventories/build receipts remain indexed, not reasserted as fresh verification.
Compiler /home/opam/.esy/4____________________________________________________________________/i/ocaml-5.5.1000-cb879550/bin/ocamlopt.opt; SHA256361d667103077d597d0e9cfaecaa1db997ceaa03de4b7144ff823e9f77fa4f24; OCaml5.5.1, package5.5.1000, esy0.9.2.
Read-only root; network disabled; user1000:1000; drop capabilities; no-new-privileges; PID128/CPU2/memory2GiB; container deadline<=120sec; executable /work128MiB; two cache tmpfs32MiB; TMPDIR=/work; /home/opam/.esy never writable; no runtime esy install. Snapshot identity checks detect observed swaps, not arbitrary transient TOCTOU changes.

REVIEW INSTRUCTIONS
Read every required part completely; if context is insufficient, split into indexed bounded reviews and record coverage. Hash verification is not semantic coverage. Original72 dirty/untracked baseline files remain unchanged. No import or post-import tests exist. Require full result receipts/invocation inventory, independently safe execution envelope, all public E2Es with expected/actual outcomes, exact model/adapter smoke and final bound review before claiming acceptance. Existing supervisor23 defects and harness/controller/global import gates remain open in historical reviews. Do not relabel diagnostic compiler probes as runner acceptance, or source review as E2E evidence. Missing tests are not proof tests are impossible.
RETURN STRICT JSON
'''+json.dumps({'revision_sha256':revision,'evidence_sha256':evidence,'verdict':'PASS | CHANGES_REQUIRED | BLOCKED','findings':[{'id':'stable identifier','severity':'severity','location':'file/scenario','problem':'concrete defect','required_change':'required behavior','required_e2e':'observable public E2E'}],'missing_evidence':[]},indent=2)+'''
MANDATORY FOLLOW-UP
Every finding goes to a fresh separate Codex Astra planner, then bounded small-model cards only within new human authorization. Preserve budgets and failed attempts. Invoke final review through the reviewed claude-worker.sh Codex-Astra route when that route and execution gates are accepted; Claude/Fable stays disabled. Repeat coding/E2Es/review until zero findings and missing evidence, or stop INCOMPLETE for authorization/budget/provider/containment/cleanup/context gates. Never import unaccepted changes. The current coding cap is exhausted: planning is not authority to dispatch. Reconcile active time after this checkpoint and exclude user idle periods on resume.
This prompt is printed by a supervising artifact publisher because the rejected controller cannot supply an accepted print-handoff command. It does not close that gate.
'''
(S/'FRONTIER_HANDOFF-010.txt').write_text(prompt)
for r in index:assert rec(Path(r['path']))==r
print(prompt)
