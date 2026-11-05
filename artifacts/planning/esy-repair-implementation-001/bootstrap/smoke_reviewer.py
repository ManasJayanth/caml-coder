import hashlib,json,os,selectors,signal,subprocess,time
from pathlib import Path
b=Path(__file__).resolve().parent; state=b.parent
runtime=b/'runtime'; (runtime/'tmp').mkdir(exist_ok=True); (runtime/'claude').mkdir(exist_ok=True)
env={k:os.environ[k] for k in ('PATH','HOME','USER','LOGNAME','LANG','SHELL','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS') if k in os.environ}
env.update(CLAUDE_BIN='/opt/homebrew/bin/claude',CLAUDE_CONFIG_DIR=str(runtime/'claude'),TMPDIR=str(runtime/'tmp'),DISABLE_AUTOUPDATER='1',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
cmd=['/bin/bash',str(state/'candidate/scripts/esy-repair/claude-worker.sh'),'review',str(b/'work'),str(b/'prompt.txt'),str(b/'review.sb')]
started=time.monotonic(); p=subprocess.Popen(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
sel=selectors.DefaultSelector(); sel.register(p.stdout,selectors.EVENT_READ,'stdout'); sel.register(p.stderr,selectors.EVENT_READ,'stderr'); logs={k:bytearray() for k in ('stdout','stderr')}; reason=None
try:
 while sel.get_map():
  if time.monotonic()-started>120: reason='timeout'; break
  for key,_ in sel.select(.2):
   raw=os.read(key.fileobj.fileno(),16384)
   if not raw: sel.unregister(key.fileobj); continue
   name=key.data
   if len(logs[name])+len(raw)>262144: reason='output-cap'; break
   logs[name].extend(raw)
  if reason: break
finally:
 if p.poll() is None:
  try: os.killpg(p.pid,signal.SIGKILL)
  except ProcessLookupError: pass
  except PermissionError: reason='cleanup-permission-denied'
 try: p.wait(timeout=5)
 except subprocess.TimeoutExpired: reason='cleanup-unverified'
 sel.close()
for name,raw in logs.items(): (b/('claude-smoke-003.'+name)).write_bytes(raw)
report={'command':cmd,'requested_model':'fable','exit_code':p.returncode,'failure':reason,'elapsed_seconds':round(time.monotonic()-started,3),'logs':{k:{'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in logs.items()},'status':'UNVALIDATED'}
try:
 value=json.loads(logs['stdout']); result=json.loads(value.get('result',''))
 passed=p.returncode==0 and not reason and not value.get('is_error',False) and result=={'smoke':'ok'}
except (ValueError,TypeError,AttributeError): passed=False
report['status']='PASSED' if passed else 'FAILED'
(b/'claude-smoke-003.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report)); print(logs['stderr'].decode(errors='replace')[:3000]); print(logs['stdout'].decode(errors='replace')[:3000])
raise SystemExit(0 if passed else 1)
