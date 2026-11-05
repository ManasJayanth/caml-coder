from pathlib import Path
import datetime,difflib,hashlib,json,stat
s=Path(__file__).resolve().parents[1]; root=s.parents[2]
def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(v): return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
baseline=json.loads((s/'baseline-manifest.json').read_text()); start=json.loads((s/'bootstrap.json').read_text())
changes=[]
for row in baseline:
 p=root/row['path']
 if not p.is_file() or p.is_symlink() or sha(p.read_bytes())!=row['sha256'] or stat.S_IMODE(p.stat().st_mode)!=row['mode']: changes.append(row['path'])
if changes: raise RuntimeError('Concurrent baseline changes: '+repr(changes))
manifest=[]
for p in sorted((s/'candidate').rglob('*')):
 if p.is_symlink(): raise RuntimeError('Unexpected candidate symlink')
 if p.is_file(): manifest.append({'path':str(p.relative_to(s/'candidate')),'kind':'file','mode':stat.S_IMODE(p.stat().st_mode),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
(s/'candidate-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
now=datetime.datetime.now(datetime.timezone.utc); elapsed=(now-datetime.datetime.fromisoformat(start['started_at'])).total_seconds()
result={'status':'INCOMPLETE','reason':'Required sandboxed Claude fable reviewer availability gate did not pass: isolated runtime lacked authentication, then minimal existing-credential retry timed out after 120 seconds without output. Root cause of authenticated timeout is not established.','baseline_sha256':start['baseline_sha256'],'candidate_sha256':sha(canonical(manifest)),'original_files_verified':len(baseline),'original_files_changed':changes,'imported':False,'coding_rounds_consumed':0,'active_seconds_consumed':round(elapsed,3),'limits':{'coding_rounds':12,'active_seconds':21600},'completed':['Frozen 72 relevant current files, including dirty and untracked inputs','Prepared isolated candidate with three worker adapters','Passed 12 bootstrap containment probes','Preserved required reviewer smoke failure evidence','Removed temporary read-only credential reference','Post-timeout process inspection found no reviewer process'],'incomplete':['C0: full lifecycle, detached-child cleanup and provider gates remain unproven','C1: controller, strict schemas and full provider parsing not implemented','C2: derivative cache image not built','C3-C4: runner unchanged','C5-C6: full repair/orchestration E2Es not implemented or run','C7: no acceptance review, import, or final verification'],'resume':'Diagnose the sandboxed Fable timeout without weakening isolation or substituting models. Repeat a bounded smoke via candidate/scripts/esy-repair/claude-worker.sh review with exact --model fable. Preserve failures under new IDs. Then finish C0 and independently reviewed C1 before unattended work. Retain this baseline, consumed active time, and user work; no budget reset.','finished_at':now.isoformat()}
(s/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
with (s/'events.jsonl').open('a') as f: f.write(json.dumps({'event':'bootstrap-incomplete',**result})+'\n')
files=[s/'bootstrap.json',s/'baseline-manifest.json',s/'candidate-manifest.json',s/'RESULT.json',s/'events.jsonl']
files+=sorted(p for p in (s/'bootstrap').iterdir() if p.is_file() and p.suffix in ('.json','.stdout','.stderr','.py','.sb','.txt'))
files+=sorted((s/'candidate/scripts/esy-repair').glob('*.sh'))
index=[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())} for p in files]
evidence_sha=sha(canonical(index)); (s/'artifact-index.json').write_text(json.dumps({'evidence_sha256':evidence_sha,'files':index},indent=2)+'\n')
parts=['You are the independent frontier reviewer of an INCOMPLETE esy reference-runner repair bootstrap. Review the exact evidence below. No code has been imported and no esy repair has been claimed. Do not infer success from the 12 bootstrap probes.', '\nFINAL STATUS\n'+json.dumps(result,indent=2), '\nREPOSITORY AND STARTING STATE\n'+json.dumps(start,indent=2), '''\nSCOPE AND LOCKED DECISIONS
macOS only. uv package management. Isolated working copies of actual dirty/untracked bytes. No original checkout overwrite, hardlinks, shared writable Git, destructive reset, or credential copying. Codex gpt-6-luna coding; separate Codex gpt-6-astra planning; Claude worker literal --model fable review. 12 coding rounds, six cumulative active hours, explicit incomplete resume without resetting consumption. Three failed coding attempts require frontier replanning. E2E only. No dataset generation, adapter experimentation, training or promotion.
C0/C1 supervised bootstrap must pass containment and real provider checks and independent review before unattended operation. Model workers have no Docker access. Host-side proposed code requires a Fable diff review before fixed trusted E2E commands execute. This is reviewed local execution, not an adversarial-code sandbox guarantee.
The derivative image must preserve base sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267; no new image was built. esy0.9.2/npm OCaml5.5.1000/compiler5.5.1 pins remain unchanged. Runtime must seed _esy and node_modules/.cache, remove esy install, retain readonly root/dependencies and network none, user1000, capdropALL/nnp, 2GiB RAM, 120s container deadline, /work128MiB and caches32MiB each. Compiler canonical path/hash and complete package/lock inventories must match before and after. None of these repairs has been implemented yet.
Required esy E2Es remain outstanding: positive, wrong result, syntax, caches writable/dependencies readonly, missing installation, corrupt/missing seeds, image/package/lock/compiler mismatch, added/missing locks, fresh-repeat, timeout, output overflow, exhaustion, startup failure, run-ID rejection/immutability, concurrency and post-run integrity.
Required controller E2Es remain outstanding: public-command full loop, frontier replanning, three-attempt escalation, strict malformed/duplicate/truncated/stale/error parsing, model identity/no fallback, output/time caps and detached descendants, lock/concurrency/resume, budgets, scope/symlink/special-file limits, dirty state and guarded import recovery, complete handoff.
No required provider smoke passed. Pi and Codex were not invoked. The frontier planning subagent was read-only; no smaller coding worker ran because bootstrap remains gated.
''','\nARTIFACT INDEX\n'+json.dumps({'evidence_sha256':evidence_sha,'files':index},indent=2)]
for p in files:
 if p.name in ('baseline-manifest.json','candidate-manifest.json','events.jsonl','bootstrap.json','RESULT.json'): continue
 parts.append('\nFILE '+str(p)+'\n'+p.read_text(errors='strict'))
parts.append('\nEXACT CANDIDATE DIFF (only new worker adapters; existing runner unchanged)\n')
for p in sorted((s/'candidate/scripts/esy-repair').glob('*.sh')):
 parts.append(''.join(difflib.unified_diff([],p.read_text().splitlines(keepends=True),fromfile='/dev/null',tofile=str(p.relative_to(s/'candidate')))))
runner=s/'baseline/artifacts/planning/esy-reference-proposal-001/run_esy_reference.py'
parts.extend(['\nEXISTING UNCHANGED RUNNER\n'+runner.read_text(), '''\nREVIEW REQUEST
Check the bootstrap evidence and proposed wrappers, diagnose the missing required reviewer gate, and identify the next bounded repair cards. Do not approve unimplemented work. Check preservation, containment scope, provider authentication exposure, cleanup, incomplete lifecycle coverage and honest status.
Return strict JSON with keys revision_sha256, evidence_sha256, verdict (PASS|CHANGES_REQUIRED|BLOCKED), findings (id,severity,location,problem,required_change,required_e2e), missing_evidence. PASS requires zero findings and zero missing evidence and is unavailable for full repair acceptance on this packet.
Every finding must be sent to a separate frontier planner and broken into small coding cards. All subsequent acceptance review must run via claude-worker.sh with literal --model fable. Do not replace it with a Codex review, weaken isolation, waive evidence, broaden scope or reset budgets.
''', '\nREVIEW IDENTITIES\n'+json.dumps({'revision_sha256':result['candidate_sha256'],'evidence_sha256':evidence_sha})])
(s/'FRONTIER_HANDOFF.txt').write_text('\n'.join(parts))
print(json.dumps({'status':'INCOMPLETE','handoff':str(s/'FRONTIER_HANDOFF.txt'),'bytes':(s/'FRONTIER_HANDOFF.txt').stat().st_size,'evidence_sha256':evidence_sha,'baseline_files_verified':len(baseline)}))
