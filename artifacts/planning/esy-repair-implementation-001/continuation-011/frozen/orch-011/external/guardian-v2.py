"""Trusted single-child supervisor; experimental, not accepted workflow control."""
import base64,json,os,selectors,signal,stat,subprocess,sys,time
from pathlib import Path
spec_path=Path(sys.argv[1]); spec=json.loads(spec_path.read_text()); out=Path(spec['output']);out.mkdir(exist_ok=False)
signal.signal(signal.SIGCHLD,signal.SIG_DFL)
D=Path(__file__).resolve().parent;runtime=D/'pi-runtime-v2';authdir=runtime/'private-pi';authfd=None;auth_created=False;credential_removed=False
p=None;sel=selectors.DefaultSelector();logs={'stdout':bytearray(),'stderr':bytearray()};reason=None;reaped=False;status=None;started=time.monotonic();deadline=started+spec['timeout'];exit_deadline=None
try:
 for directory in [runtime,authdir]:
  if directory.is_symlink():raise RuntimeError('symlink directory')
  directory.mkdir(mode=0o700,exist_ok=True)
  st=directory.stat()
  if stat.S_IMODE(st.st_mode)!=0o700 or st.st_uid!=os.getuid():raise RuntimeError('private directory mode/owner')
 if runtime.resolve()!=runtime or authdir.resolve()!=authdir:raise RuntimeError('path redirection')
 for ancestor in D.parents:
  st=ancestor.stat()
  if st.st_mode & 0o022 and not (st.st_mode & stat.S_ISVTX):raise RuntimeError('writable ancestor')
 authfd=os.open(authdir,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 source=Path.home()/'.codex/auth.json' if spec['auth_source']=='real' else D/'tests/fixture-auth.json'
 if spec['auth_source'] not in ['real','fixture']:raise RuntimeError('unknown auth source')
 tokens=json.loads(source.read_text())['tokens'];access=tokens['access_token'];body=access.split('.')[1];claims=json.loads(base64.urlsafe_b64decode(body+'='*((-len(body))%4)));expiry=claims['exp']*1000
 if expiry<time.time()*1000+600000:raise RuntimeError('insufficient access token lifetime')
 credential={'openai-codex':{'type':'oauth','access':access,'refresh':'','expires':expiry,'accountId':tokens['account_id']}}
 fd=os.open('auth.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=authfd);auth_created=True
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o600 or st.st_uid!=os.getuid():raise RuntimeError('credential mode/owner')
  with os.fdopen(fd,'w',closefd=False) as stream:json.dump(credential,stream);stream.flush();os.fsync(fd)
 finally:os.close(fd)
 (out/'auth-ready.json').write_text(json.dumps({'credential_mode':384,'private_parent_mode':448}))
 if spec.get('inject')=='after-auth':raise RuntimeError('injected setup failure')
 import select
 if select.select([sys.stdin.buffer],[],[],0)[0] and not os.read(sys.stdin.fileno(),1):raise RuntimeError('launcher absent before spawn')
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
 if authfd is not None:
  if auth_created and (p is None or reaped):
   try:os.unlink('auth.json',dir_fd=authfd)
   except FileNotFoundError:pass
   try:os.stat('auth.json',dir_fd=authfd,follow_symlinks=False)
   except FileNotFoundError:credential_removed=True
  os.close(authfd)
 sel.close()
 for k,v in logs.items():(out/k).write_bytes(v)
 result={'status':'TERMINATED' if reaped else 'CLEANUP_UNVERIFIED','worker_pid':p.pid if p else None,'worker_reaped':reaped,'exit_code':status,'reason':reason,'elapsed_seconds':round(time.monotonic()-started,3),'single_worker_assumption':'requires separately proven native process-fork denial','credential_removed':credential_removed}
 (out/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result),flush=True)
