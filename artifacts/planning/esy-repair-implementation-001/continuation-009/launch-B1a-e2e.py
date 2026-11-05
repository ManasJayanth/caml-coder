"""Supervised single-card dispatch only; no test execution or import."""
import hashlib,json,os,shutil,stat,subprocess,sys,time
from pathlib import Path
D=Path(__file__).resolve().parent;S=D.parent;R=S/'continuation-008/pi-runtime-v2';job=sys.argv[1];card=Path(sys.argv[2]);round_number=int(sys.argv[3]);assert job.replace('-','').isalnum();assert 24<=round_number<=36
lock=D/'coding-dispatch.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
jobdir=D/'coding-jobs'/job;jobdir.mkdir(parents=True,exist_ok=False);workspace=R/('workspace-'+job);guardian_reaped=False
try:
 allocation=json.loads((D/'allocation.json').read_text());remaining=32400-allocation['prior_active_seconds']-(time.time()-allocation['current_turn_started_epoch']);assert remaining>=660,'active budget insufficient'
 ledger=D/'coding-ledger.json';used=json.loads(ledger.read_text())['coding_launches_consumed'] if ledger.exists() else 23;assert round_number==used+1
 source=D/'candidate'
 for p in source.rglob('*'):
  if p.is_symlink() or not(p.is_dir() or p.is_file()):raise RuntimeError('unsupported source entry')
 shutil.copytree(source,workspace,copy_function=shutil.copy2)
 def manifest(root):
  rows=[]
  for p in sorted(root.rglob('*')):
   if p.is_symlink() or not(p.is_dir() or p.is_file()):raise RuntimeError('unsupported entry')
   if p.is_file():rows.append({'path':str(p.relative_to(root)),'mode':stat.S_IMODE(p.stat().st_mode),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size})
  return rows
 parent=manifest(source);assert parent==manifest(workspace);(jobdir/'parent-manifest.json').write_text(json.dumps(parent,indent=2));(jobdir/'prompt.txt').write_bytes(card.read_bytes());prompt=R/(job+'-prompt.txt');prompt.write_bytes(card.read_bytes())
 env={k:os.environ[k] for k in ['PATH','LANG','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS'] if k in os.environ};env.update(HOME=str(R/'home'),PI_CODING_AGENT_DIR=str(R/'private-pi'),PI_CODING_AGENT_SESSION_DIR=str(R/'sessions'),PI_TELEMETRY='0',TMPDIR=str(R))
 argv=['/usr/bin/sandbox-exec','-f',str(S/'continuation-008/pi-nofork-v3.sb'),'/opt/homebrew/bin/pi','--print','--mode','json','--provider','openai-codex','--model','gpt-6-luna','--thinking','high','--no-session','--no-extensions','--no-mcp','--no-skills','--no-prompt-templates','--no-context-files','--no-themes','--no-approve','--offline','--tools','read,edit,write','@'+str(prompt)]
 spec={'argv':argv,'env':env,'cwd':str(workspace),'output':str(jobdir/'guardian'),'timeout':600,'cap':2097152,'auth_source':'real'};sp=jobdir/'spec.json';sp.write_text(json.dumps(spec,indent=2))
 with ledger.open('w') as f:json.dump({'coding_launches_consumed':round_number,'coding_launch_cap':36,'reserved_job':job,'epoch':time.time()},f);f.flush();os.fsync(f.fileno())
 p=subprocess.Popen([sys._base_executable,'-B',str(S/'continuation-008/guardian-v2.py'),str(sp)],stdin=subprocess.PIPE,start_new_session=True)
 try:p.wait(timeout=615)
 except subprocess.TimeoutExpired:p.stdin.close();p.wait(timeout=10)
 receipt=json.loads((jobdir/'guardian/receipt.json').read_text());guardian_reaped=receipt['worker_reaped'];assert guardian_reaped and receipt['credential_removed'],'cleanup unverified'
 current=manifest(workspace);(jobdir/'result-manifest.json').write_text(json.dumps(current,indent=2));assert manifest(source)==parent,'candidate changed concurrently'
 before={x['path']:x for x in parent};after={x['path']:x for x in current};changed=[k for k in sorted(set(before)|set(after)) if before.get(k)!=after.get(k)];allow={'tests/e2e/test_review_adapter_e2e.py'}
 result={'status':'UNACCEPTED','coding_round':round_number,'changed_paths':changed,'scope_valid':set(changed)<=allow,'receipt':receipt,'workspace':str(workspace),'imported':False}
 shutil.copytree(workspace,jobdir/'frozen',copy_function=shutil.copy2);(jobdir/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
finally:
 if guardian_reaped:lock.unlink()
