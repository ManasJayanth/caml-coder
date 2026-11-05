"""Single fixed public E2E invocation; no controller or provider activation."""
import hashlib,json,os,selectors,signal,subprocess,time
from pathlib import Path
D=Path(__file__).resolve().parent;ROOT=D.parent.parents[2]
F=D/'coding-jobs/B1a-E2E-025/frozen';run=D/'B1a-e2e-run-001';run.mkdir(mode=0o700);out=run/'fixtures';out.mkdir(mode=0o700)
paths=[F/'tests/e2e/test_review_adapter_e2e.py',F/'scripts/esy-repair/claude-worker.sh',F/'scripts/esy-repair/codex-worker.sh']
def hashes():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
before=hashes();argv=['/opt/homebrew/bin/uv','run','--project',str(ROOT),'--locked','--no-sync','python','-B',str(paths[0]),'--adapter',str(paths[1]),'--output-dir',str(out)]
env={'PATH':'/opt/homebrew/bin:/usr/bin:/bin','HOME':str(run),'LANG':'C','UV_CACHE_DIR':str(D/'uv-cache')}
start=time.monotonic();deadline=start+200;finish=None;reason=None;status=None;reaped=False;sent=False;logs={'stdout':bytearray(),'stderr':bytearray()};eof={x:False for x in logs};counts={x:0 for x in logs};sel=selectors.DefaultSelector()
p=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
(run/'started.json').write_text(json.dumps({'pid':p.pid,'pgid':p.pid,'argv':argv,'before':before,'epoch':time.time()})+'\n')
for pipe,n in [(p.stdout,'stdout'),(p.stderr,'stderr')]:os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ,n)
try:
 while True:
  now=time.monotonic()
  if now>=deadline and reason is None:reason='timeout';finish=now+5
  if reason and not reaped and not sent:
   try:os.killpg(p.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   sent=True
  if not reaped:
   got,raw=os.waitpid(p.pid,os.WNOHANG)
   if got:reaped=True;status=os.waitstatus_to_exitcode(raw);p.returncode=status
  if reaped and all(eof.values()):break
  if finish is not None and now>=finish:break
  for key,_ in sel.select(.05):
   try:data=os.read(key.fd,8192)
   except BlockingIOError:continue
   if not data:eof[key.data]=True;sel.unregister(key.fileobj);continue
   n=key.data;counts[n]+=len(data);logs[n].extend(data[:max(0,65536-len(logs[n]))])
   if counts[n]>65536 and reason is None:reason='output-overflow';finish=time.monotonic()+5
finally:
 sel.close()
 for n,b in logs.items():(run/n).write_bytes(b)
 after=hashes();receipt={'argv':argv,'exit_code':status,'failure':reason,'leader_reaped':reaped,'eof':eof,'observed_bytes':counts,'elapsed_seconds':time.monotonic()-start,'source_unchanged':before==after,'before':before,'after':after,'descendant_cleanup':'requires independent process-group query; leader reap alone is insufficient'};(run/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
raise SystemExit(0 if reaped and status==0 and reason is None and all(eof.values()) and before==after else 1)
