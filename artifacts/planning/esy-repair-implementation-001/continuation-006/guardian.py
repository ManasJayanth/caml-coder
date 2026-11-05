"""Trusted single-child supervisor; experimental, not accepted workflow control."""
import json,os,selectors,signal,subprocess,sys,time
from pathlib import Path
spec_path=Path(sys.argv[1]); spec=json.loads(spec_path.read_text()); out=Path(spec['output']);out.mkdir(exist_ok=False)
signal.signal(signal.SIGCHLD,signal.SIG_DFL)
p=None;sel=selectors.DefaultSelector();logs={'stdout':bytearray(),'stderr':bytearray()};reason=None;reaped=False;status=None;started=time.monotonic();deadline=started+spec['timeout'];exit_deadline=None
try:
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
 sel.close()
 for k,v in logs.items():(out/k).write_bytes(v)
 result={'status':'TERMINATED' if reaped else 'CLEANUP_UNVERIFIED','worker_pid':p.pid if p else None,'worker_reaped':reaped,'exit_code':status,'reason':reason,'elapsed_seconds':round(time.monotonic()-started,3),'single_worker_assumption':'requires separately proven native process-fork denial'}
 (out/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result),flush=True)
