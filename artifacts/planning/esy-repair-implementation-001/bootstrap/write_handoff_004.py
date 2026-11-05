"""Supervised evidence writer. Not the unaccepted workflow controller."""
from pathlib import Path
import json,hashlib,stat,time,difflib,datetime
S=Path(__file__).resolve().parents[1]; ROOT=S.parents[2]
def sha(b): return hashlib.sha256(b).hexdigest()
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def rec(p): return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
def write(p,v): p.write_text(json.dumps(v,indent=2)+'\n')
baseline=json.loads((S/'baseline-manifest.json').read_text()); changed=[]
for r in baseline:
 p=ROOT/r['path']
 if not p.is_file() or p.is_symlink() or sha(p.read_bytes())!=r['sha256'] or stat.S_IMODE(p.stat().st_mode)!=r['mode']: changed.append(r['path'])
manifest=[]
for p in sorted((S/'candidate').rglob('*')):
 if p.is_symlink(): raise RuntimeError('Unexpected symlink '+str(p))
 if p.is_file(): manifest.append({'path':str(p.relative_to(S/'candidate')),'mode':stat.S_IMODE(p.stat().st_mode),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
write(S/'candidate-manifest-004.json',manifest); revision=sha(canon(manifest))
final_review=json.loads((S/'jobs/N6-final-review-001/final.txt').read_text())
result={'status':'INCOMPLETE','reason':'All 18 allocated coding launches consumed; independent review requires fixes; full real E2E matrix and controller acceptance remain missing. No import.','imported':False,'coding_launches_consumed':18,'limits':{'coding_launches':18,'active_seconds':21600},'active_seconds_consumed':round(7007.971+time.time()-1792662024.26525,3),'reviewer':'fresh Codex gpt-6-astra','candidate_sha256':revision,'original_files_verified':len(baseline),'original_files_changed':changed,'derivative_image':'sha256:06095e22e6fb4cedaaff8fa57e7951338bb7a80e2ac8b6d1d4d6bcc0b9727459','diagnostic_fresh_compile_runs_passed':2,'public_runner_acceptance':False,'planning_limitations':['Broad final replanning timed out; preserved failed attempt.','Targeted three-card plan and earlier seven lifecycle cards are prospective, not acceptance.','Proposed E2E commands are not currently runnable; use uv with the existing locked project when implementing authorized cards.'],'controller':'DEFERRED_UNACCEPTED','final_review':str(S/'jobs/N6-final-review-001/final.txt'),'final_review_result':final_review,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
write(S/'RESULT-004.json',result); write(S/'STATUS-004.json',result)
scenarios=json.loads((S/'required-esy-scenario-status-003.json').read_text())
for row in scenarios['required_scenarios']: row.update(actual='NOT_RUN_THROUGH_PUBLIC_RUNNER',reason='Seeded image built and fixed diagnostic passed twice; public runner remains unaccepted with lifecycle findings.',report_sha256=None)
scenarios['test_source_sha256']=sha((S/'candidate/artifacts/planning/esy-reference-proposal-001/tests/test_esy_reference_runtime_e2e.py').read_bytes())
scenarios['separate_diagnostics']=[rec(S/'probes'/n/'receipt.json') for n in ['seed-compile-001','seed-compile-002','seed-compile-003']]
write(S/'required-esy-scenario-status-004.json',scenarios)
packet=S/'frontier-packet-004'; packet.mkdir(exist_ok=False)
parts=[]
for i,r in enumerate(manifest):
 rel=r['path']; p=S/'candidate'/rel; b=S/'baseline'/rel
 after=p.read_text(); before=b.read_text() if b.is_file() else ''
 if before==after: continue
 diff=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='baseline/'+rel,tofile='candidate/'+rel))
 out=packet/f'source-{i:03d}.txt'; out.write_text('FILE '+rel+'\nMANIFEST '+json.dumps(r)+'\nCOMPLETE SOURCE\n'+after+'\nEXACT DIFF\n'+diff); parts.append(rec(out))
(packet/'events-snapshot.jsonl').write_bytes((S/'events.jsonl').read_bytes())
history=packet/'review-history.txt'; history.write_text('\n\n'.join('JOB '+p.parent.name+'\n'+p.read_text() for p in sorted((S/'jobs').glob('*/final.txt'))))
files=[S/n for n in ['bootstrap.json','baseline-manifest.json','candidate-manifest-004.json','RESULT-004.json','required-esy-scenario-status-004.json','C01-deferred-cards.json','CURRENT_REVIEW_POLICY.md','FOLLOWUP_PLAN_NOTES-003.json']]
files+=list(S.glob('*-004.json'))+list(S.glob('budget-*.json'))
for d in ['jobs','reviews','builds','probes']:
 for p in sorted((S/d).rglob('*')):
  if 'runtime' in p.relative_to(S).parts: continue
  if p.is_file() and not p.is_symlink(): files.append(p)
for p in (S/'bootstrap').iterdir():
 if p.is_file() and not p.is_symlink(): files.append(p)
files+=list(packet.iterdir())
files=[p for p in sorted(set(files)) if p.is_file() and p.name not in ['STATUS-004.json','artifact-index-004.json']]
index=[rec(p) for p in files]; evidence=sha(canon(index)); write(S/'artifact-index-004.json',{'evidence_sha256':evidence,'files':index})
prior=(S/'FRONTIER_HANDOFF-003.txt').read_text(); invariants=prior.split('RUNTIME INVARIANTS\n',1)[1].split('\nFINAL STATUS',1)[0]
prompt='''You are the independent frontier reviewer of an esy reference-runner repair.
Review this exact revision and evidence. Prior approvals, worker prose, and process exit zero are not proof of correctness.
This is an explicit indexed multi-part packet; read every source/diff and review part. No source is silently truncated. The supervising agent generated this handoff because the public workflow controller remains unaccepted. It does not establish controller print-handoff acceptance.

OBJECTIVE AND SCOPE
Repair offline esy execution using disposable writable caches and read-only compiler/dependencies. No datasets, training, adapters or promotion. macOS; uv if needed; preserve lockfile. Do not import until complete acceptance.

CURRENT REVIEW POLICY
User replaced Claude Fable with fresh Codex gpt-6-astra. Coding gpt-6-luna; separate fresh Astra planning and review. Native worker containment; no worker Docker access. Reviewed host execution only. Coding launches18/18 (12 original plus6 explicitly authorized); six-hour cumulative active limit NOT reset. No more coding launches without explicit allocation. Historical Fable records are superseded only in policy, never deleted.

RUNTIME INVARIANTS
'''+invariants+'\nFINAL STATUS\n'+json.dumps(result,indent=2)+'\nREPOSITORY AND STARTING STATE\n'+json.dumps(json.loads((S/'bootstrap.json').read_text()),indent=2)
prompt+='\nFULL CANDIDATE REVISION SHA256 '+revision+'\nEVIDENCE INDEX SHA256 '+evidence+'\nBASELINE MANIFEST '+json.dumps(rec(S/'baseline-manifest.json'))
prompt+='\nIMAGE AND COMPILER PROVENANCE\n'+(S/'builds/N3-002/build-receipt.json').read_text()+'\n'+(S/'base-compiler-identity-probe-004.json').read_text()+'\n'+(S/'seed-inventory-semantic-check-004.json').read_text()
prompt+='\nDIAGNOSTIC LIMITS\nTwo fixed supervisor probes compiled and executed exact stdout in fresh restricted containers, with TMPDIR=/work and verified cleanup. The earlier probe without TMPDIR failed and is preserved. These are NOT public runner E2Es. Build receipt seed_inventory_verified=false reflects build-time status; the later full inventory probe/semantic comparison records separate seed evidence. No runtime esy install or package rebuild occurred.\n'
prompt+='\nORCHESTRATION SCENARIOS\n'+(S/'orchestration-scenario-status-004.json').read_text()
prompt+='\nSEPARATE FRONTIER REPAIR CARDS\n'+(S/'jobs/N5-deferred-plan-001/final.txt').read_text()+'\nNEW FINDINGS TARGETED PLAN\n'+(S/'jobs/N6-targeted-plan-001/final.txt').read_text()+'\nBROAD PLANNING ATTEMPT FAILED: TIMEOUT. Preserved jobs/N6-final-plan-001; no completed plan inferred.\n'
prompt+='\nFULL REQUIRED SCENARIO RESULTS\n'+json.dumps(scenarios,indent=2)+'\nIMPLEMENTATION SOURCE/DIFF PARTS\n'+json.dumps(parts,indent=2)+'\nREVIEW HISTORY\n'+json.dumps(rec(history))+'\nARTIFACT INDEX\n'+str(S/'artifact-index-004.json')
prompt+='''
RESUME
Read allocation-004, budget-014, RESULT-004 and latest Astra future cards. Retain18 consumed launches and recorded active time; do not reset budgets. Reconcile source identities and owned processes/containers before any continuation. Controller is not accepted: do not activate unattended operation. Never infer authorization from a model file. No import occurred; compare original manifests before any future guarded import.

REVIEW INSTRUCTIONS
1. Check every approved requirement, full source, exact diff, revision and evidence identity.
2. Inspect actual raw artifacts; verify all index hashes. Check missing scenarios, false positives, unsafe cleanup and overwritten user edits.
3. Review orchestration and import as well as runtime. Explicit MISSING rows are not test passes. Fault-test difficulty is not evidence of impossibility.
4. Read the separate Astra future plan. Any remaining findings require fresh separate Astra planning into bounded small coding cards with inputs, allowed paths, prerequisites, exact behavior, real E2E commands/outcomes and evidence. Planning does not authorize exceeding coding allocation.
5. Return PASS only with zero findings and zero missing evidence. If context is insufficient, return BLOCKED with missing context. Never waive gates because limits are reached.
RETURN STRICT JSON
{"revision_sha256":"reviewed full candidate hash","evidence_sha256":"reviewed evidence index hash","verdict":"PASS | CHANGES_REQUIRED | BLOCKED","findings":[{"id":"stable ID","severity":"severity","location":"file/scenario","problem":"concrete defect","required_change":"required behavior","required_e2e":"observable acceptance"}],"missing_evidence":[]}
'''
(S/'FRONTIER_HANDOFF-004.txt').write_text(prompt)
for r in index:
 if rec(Path(r['path']))!=r: raise RuntimeError('Changed indexed artifact '+r['path'])
print(json.dumps({'status':'INCOMPLETE','handoff':str(S/'FRONTIER_HANDOFF-004.txt'),'indexed_files':len(index),'original_changes':changed,'revision_sha256':revision,'evidence_sha256':evidence}))
