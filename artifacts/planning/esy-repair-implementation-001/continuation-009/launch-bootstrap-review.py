"""Supervised bootstrap launcher; not the accepted unattended controller."""
import argparse,hashlib,json,os,selectors,signal,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--role',choices=['code','plan','review'],required=True); p.add_argument('--job',required=True); p.add_argument('--prompt',type=Path,required=True); p.add_argument('--timeout',type=int,default=600); a=p.parse_args()
s=Path('/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001'); candidate=s/'candidate'; jobs=s/'jobs'; jobs.mkdir(exist_ok=True)
if not a.job.replace('-','').replace('_','').isalnum(): raise SystemExit('invalid job')
j=jobs/a.job; j.mkdir(exist_ok=False); runtime=j/'runtime'; runtime.mkdir(); (runtime/'tmp').mkdir(); (runtime/'codex').mkdir()
(j/'prompt.txt').write_bytes(a.prompt.read_bytes())
wrapper=s/'continuation-009/claude-worker.sh'; (j/'worker.sh').write_bytes(wrapper.read_bytes())
profile='(version 1)\n(allow default)\n(deny file-write*)\n(allow file-write* (subpath '+json.dumps(str(runtime))+'))\n(deny network-outbound (remote unix-socket))\n(allow network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))\n(allow network-outbound (remote unix-socket (path-literal "/var/run/mDNSResponder")))\n(deny signal)\n(allow signal (target self) (target children))\n'
if a.role=='code': profile+='(allow file-write* (subpath '+json.dumps(str(candidate))+'))\n'
(j/'sandbox.sb').write_text(profile)
auth=runtime/'codex/auth.json'; auth.symlink_to(Path.home()/'.codex/auth.json')
env={k:os.environ[k] for k in ('PATH','HOME','USER','LOGNAME','LANG','SHELL','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS') if k in os.environ}; env.update(CODEX_BIN='/opt/homebrew/bin/codex',CODEX_HOME=str(runtime/'codex'),TMPDIR=str(runtime/'tmp'))
cmd=['/bin/bash',str(j/'worker.sh'),a.role,str(candidate),str(j/'prompt.txt'),str(j/'sandbox.sb')]
started=time.monotonic(); proc=subprocess.Popen(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
(j/'started.json').write_text(json.dumps({'pid':proc.pid,'role':a.role,'command':cmd,'timeout':a.timeout,'wall_started':time.time()}))
sel=selectors.DefaultSelector(); sel.register(proc.stdout,selectors.EVENT_READ,'stdout'); sel.register(proc.stderr,selectors.EVENT_READ,'stderr'); logs={k:bytearray() for k in ('stdout','stderr')}; reason=None
try:
 while sel.get_map():
  if time.monotonic()-started>a.timeout: reason='timeout'; break
  for key,_ in sel.select(.2):
   raw=os.read(key.fileobj.fileno(),16384)
   if not raw: sel.unregister(key.fileobj); continue
   buf=logs[key.data]
   if len(buf)+len(raw)>2*1024*1024: reason='output-cap'; break
   buf.extend(raw)
  if reason: break
finally:
 if proc.poll() is None:
  try: os.killpg(proc.pid,signal.SIGKILL)
  except ProcessLookupError: pass
  except PermissionError: reason='cleanup-denied'
 try: proc.wait(timeout=5)
 except subprocess.TimeoutExpired: reason='cleanup-unverified'
 sel.close(); auth.unlink(missing_ok=True)
for name,raw in logs.items(): (j/name).write_bytes(raw)
report={'role':a.role,'requested_model':'gpt-6-luna' if a.role=='code' else 'gpt-6-astra','exit_code':proc.returncode,'failure':reason,'elapsed_seconds':round(time.monotonic()-started,3),'command':cmd,'status':'FAILED'}
try:
 events=[json.loads(line) for line in logs['stdout'].splitlines() if line.strip()]; messages=[e['item']['text'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']; (j/'final.txt').write_text(messages[-1] if messages else '')
 if proc.returncode==0 and not reason and messages and any(e.get('type')=='turn.completed' for e in events) and not any(e.get('type') in ('error','turn.failed') for e in events): report['status']='PROVIDER_COMPLETED'
except (ValueError,TypeError,KeyError): report['failure']='invalid-provider-output'
(j/'receipt.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report)); print((j/'final.txt').read_text()[:12000] if (j/'final.txt').exists() else logs['stderr'].decode(errors='replace')[-2000:])
raise SystemExit(0 if report['status']=='PROVIDER_COMPLETED' else 1)
