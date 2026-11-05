import hashlib,json,os,selectors,signal,subprocess,time
from pathlib import Path
b=Path(__file__).resolve().parent; state=b.parent
runtime=b/'runtime'; (runtime/'tmp').mkdir(exist_ok=True); (runtime/'claude').mkdir(exist_ok=True)
env={k:os.environ[k] for k in ('PATH','HOME','USER','LOGNAME','LANG','SHELL','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS') if k in os.environ}
env.update(CODEX_BIN='/opt/homebrew/bin/codex',CODEX_HOME=str(runtime/'codex'),TMPDIR=str(runtime/'tmp'))
cmd=['/bin/bash',str(state/'candidate/scripts/esy-repair/codex-worker.sh'),'review',str(b/'work'),str(b/'prompt.txt'),str(b/'review-002.sb')]
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
for name,raw in logs.items(): (b/('codex-astra-smoke-002.'+name)).write_bytes(raw)
report={'command':cmd,'requested_model':'gpt-6-astra','exit_code':p.returncode,'failure':reason,'elapsed_seconds':round(time.monotonic()-started,3),'logs':{k:{'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in logs.items()},'status':'UNVALIDATED'}
try:
 events=[json.loads(line) for line in logs['stdout'].splitlines() if line.strip()]
 messages=[e['item']['text'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
 result=json.loads(messages[-1]) if messages else None
 passed=p.returncode==0 and not reason and result=={'smoke':'ok'} and any(e.get('type')=='turn.completed' for e in events) and not any(e.get('type') in ('error','turn.failed') for e in events)
except (ValueError,TypeError,AttributeError): passed=False
report['status']='PASSED' if passed else 'FAILED'
(b/'codex-astra-smoke-002.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report)); print(logs['stderr'].decode(errors='replace')[:3000]); print(logs['stdout'].decode(errors='replace')[:3000])
raise SystemExit(0 if passed else 1)
