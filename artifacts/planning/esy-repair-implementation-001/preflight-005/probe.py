import hashlib,json,os,selectors,signal,socket,subprocess,sys,time,tempfile
from pathlib import Path
D=Path(__file__).resolve().parent

def run(argv,env,limit,name):
 start=time.monotonic(); p=subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True); sel=selectors.DefaultSelector(); logs={k:bytearray() for k in ('stdout','stderr')}; failure=None
 (D/(name+'.started.json')).write_text(json.dumps({'pid':p.pid,'argv':argv,'epoch':time.time()}))
 for stream,key in [(p.stdout,'stdout'),(p.stderr,'stderr')]: sel.register(stream,selectors.EVENT_READ,key)
 try:
  while sel.get_map():
   if time.monotonic()-start>=limit: failure='timeout'; break
   for key,_ in sel.select(.1):
    raw=os.read(key.fileobj.fileno(),16384)
    if not raw: sel.unregister(key.fileobj); continue
    buf=logs[key.data]; left=262144-len(buf); buf.extend(raw[:max(0,left)])
    if len(raw)>left: failure='output-cap'; break
   if failure: break
 finally:
  p.poll()
  try:
   os.killpg(p.pid,0)
   os.killpg(p.pid,signal.SIGKILL)
  except ProcessLookupError: pass
  except PermissionError: failure='cleanup-denied'
  try: p.wait(timeout=5)
  except subprocess.TimeoutExpired: failure='cleanup-unverified'
  sel.close()
  try: os.killpg(p.pid,0); group_absent=False
  except ProcessLookupError: group_absent=True
  except PermissionError: group_absent=False
 for k,v in logs.items(): (D/(name+'.'+k)).write_bytes(v)
 result={'argv':argv,'exit_code':p.returncode,'failure':failure,'elapsed_seconds':round(time.monotonic()-start,3),'owned_group_absent':group_absent,'logs':{k:{'size':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in logs.items()}}
 (D/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n'); return result,logs

env={k:os.environ[k] for k in ['PATH','HOME','USER','LOGNAME','LANG','SHELL','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS'] if k in os.environ}
env.update(CLAUDE_BIN='/opt/homebrew/bin/claude',CLAUDE_CONFIG_DIR=str(D/'runtime/claude'),TMPDIR=str(D/'runtime/tmp'),DISABLE_AUTOUPDATER='1',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
auth=D/'runtime/claude/.credentials.json'; auth.symlink_to(Path.home()/'.claude/.credentials.json')
try:
 r,_=run(['/opt/homebrew/bin/claude','--version'],env,10,'claude-version'); print(json.dumps({'version_check':r}),flush=True)
 sockdir=tempfile.TemporaryDirectory(prefix='esy005-',dir='/private/tmp'); sockpath=str(Path(sockdir.name)/'s')
 probe='''import os,socket,json
from pathlib import Path
checks={}
for label,path in [('original',%r),('prompt',%r)]:
 try: fd=os.open(path,os.O_WRONLY)
 except PermissionError: checks[label]=True
 else: os.close(fd);checks[label]=False
p=Path(%r);p.write_text('probe');checks['runtime_write']=p.read_text()=='probe'
s=socket.socket(socket.AF_UNIX)
try:s.connect(%r)
except PermissionError:checks['socket_denied']=True
except OSError:checks['socket_denied']=False
else:checks['socket_denied']=False
print(json.dumps(checks));raise SystemExit(0 if all(checks.values()) else 1)
''' % (str(D.parents[3]/'pyproject.toml'),str(D/'prompt.txt'),str(D/'runtime/canary'),sockpath)
 server=socket.socket(socket.AF_UNIX); server.bind(sockpath);server.listen(1)
 r,_=run(['/usr/bin/sandbox-exec','-f',str(D/'review.sb'),sys.executable,'-c',probe],env,10,'containment');server.close();Path(sockpath).unlink();sockdir.cleanup();print(json.dumps({'containment':r}),flush=True)
 if r['exit_code']!=0 or r['failure']: raise SystemExit(2)
 argv=['/bin/bash',str(D/'claude-worker.sh'),'review',str(D/'work'),str(D/'prompt.txt'),str(D/'review.sb')]
 r,logs=run(argv,env,120,'fable-smoke');r['requested_model']='fable';r['status']='FAILED'
 def strict(pairs):
  d={}
  for k,v in pairs:
   if k in d: raise ValueError('duplicate key')
   d[k]=v
  return d
 try:
  envelope=json.loads(logs['stdout'],object_pairs_hook=strict); answer=json.loads(envelope['result'],object_pairs_hook=strict)
  r['envelope_type']=envelope.get('type');r['envelope_subtype']=envelope.get('subtype');r['reported_model_usage']=list(envelope.get('modelUsage',{}))
  if r['exit_code']==0 and not r['failure'] and r['owned_group_absent'] and envelope.get('type')=='result' and envelope.get('subtype')=='success' and not envelope.get('is_error') and answer=={'smoke':'ok'}: r['status']='RESPONSE_VALID_MODEL_IDENTITY_REQUIRES_VERIFICATION'
 except (ValueError,KeyError,TypeError): r['parse']='NO_VALID_COMPLETE_SUCCESS_ENVELOPE'
 (D/'fable-smoke.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
finally: auth.unlink(missing_ok=True)
