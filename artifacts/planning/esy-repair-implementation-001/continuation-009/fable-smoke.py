"""One manually supervised fallback smoke; no automatic retry or review activation."""
from pathlib import Path
import hashlib,json,os,selectors,signal,subprocess,time
D=Path(__file__).resolve().parent;J=D/'fable-smoke-001';J.mkdir(mode=0o700);R=J/'runtime';R.mkdir(mode=0o700);config=R/'claude';config.mkdir(mode=0o700);tmp=R/'tmp';tmp.mkdir(mode=0o700)
auth=config/'.credentials.json';auth.symlink_to(Path.home()/'.claude/.credentials.json')
profile=J/'sandbox.sb';profile.write_text('(version 1)\n(allow default)\n(deny file-write*)\n(allow file-write* (subpath '+json.dumps(str(R))+'))\n(deny network-outbound (remote unix-socket))\n(allow network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))\n(allow network-outbound (remote unix-socket (path-literal "/var/run/mDNSResponder")))\n(deny signal)\n(allow signal (target self) (target children))\n')
worker=J/'claude-worker.sh';worker.write_text('''#!/bin/bash
set -euo pipefail
[[ $# -eq 4 && "$1" = review ]] || exit 64
cd "$2"
exec /usr/bin/sandbox-exec -f "$4" /opt/homebrew/bin/claude --print --model fable --output-format json --no-session-persistence --safe-mode --restricted --disable-slash-commands --setting-sources "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --permission-mode plan --tools "" < "$3"
''')
prompt=J/'prompt.txt';prompt.write_text('Return exactly this JSON and nothing else: {"smoke":"ok"}. Do not use tools. This is a bounded authenticated availability check, not approval of code.\n')
env={k:os.environ[k] for k in ['PATH','HOME','USER','LOGNAME','LANG','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS'] if k in os.environ};env.update(CLAUDE_CONFIG_DIR=str(config),TMPDIR=str(tmp),DISABLE_AUTOUPDATER='1',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
argv=['/bin/bash',str(worker),'review',str(J),str(prompt),str(profile)];p=None;sel=selectors.DefaultSelector();logs={'stdout':bytearray(),'stderr':bytearray()};reason=None;started=time.monotonic();reaped=False
try:
 p=subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 (J/'started.json').write_text(json.dumps({'pid':p.pid,'pgid':p.pid,'argv':argv,'epoch':time.time()})+'\n')
 for pipe,n in [(p.stdout,'stdout'),(p.stderr,'stderr')]:os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ,n)
 while sel.get_map():
  if time.monotonic()-started>=90:reason='timeout';break
  for key,_ in sel.select(.1):
   try:raw=os.read(key.fd,8192)
   except BlockingIOError:continue
   if not raw:sel.unregister(key.fileobj);continue
   n=key.data;remaining=131072-len(logs[n]);logs[n].extend(raw[:max(0,remaining)])
   if len(raw)>remaining:reason='output-overflow';break
  if reason:break
except BaseException as e:reason='exception:'+type(e).__name__
finally:
 if p is not None:
  try:p.wait(timeout=1);reaped=True
  except subprocess.TimeoutExpired:
   try:os.killpg(p.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   except PermissionError:reason=reason or 'cleanup-denied'
   try:p.wait(timeout=5);reaped=True
   except subprocess.TimeoutExpired:reason=reason or 'cleanup-unverified'
 sel.close();auth.unlink(missing_ok=True)
 for n,b in logs.items():(J/n).write_bytes(b)
def strict(pairs):
 r={}
 for k,v in pairs:
  if k in r:raise ValueError('duplicate JSON key')
  r[k]=v
 return r
value=None;parse_error=None;semantic=False;models=[]
try:
 value=json.loads(logs['stdout'],object_pairs_hook=strict);semantic=isinstance(value,dict) and value.get('is_error') is False and value.get('type')=='result' and value.get('subtype')=='success' and json.loads(value.get('result',''),object_pairs_hook=strict)=={'smoke':'ok'};models=list(value.get('modelUsage',{}))
except (ValueError,TypeError,AttributeError):parse_error='invalid-complete-envelope'
r={'requested_model':'fable','argv':argv,'process_exit':p.returncode if p else None,'failure':reason,'leader_reaped':reaped,'credential_link_removed':not auth.is_symlink(),'parse_error':parse_error,'semantic_smoke':semantic,'reported_model_usage_keys':models,'identity_verified':models==['fable'],'elapsed_seconds':time.monotonic()-started,'status':'UNVALIDATED','activation':False}
r['status']='SMOKE_PASSED_PENDING_GROUP_CHECK' if reaped and p.returncode==0 and reason is None and semantic and r['identity_verified'] else 'FAILED_OR_UNVERIFIED'
(J/'receipt.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r));print(bytes(logs['stderr']).decode(errors='replace')[:1200])
raise SystemExit(0 if r['status']=='SMOKE_PASSED_PENDING_GROUP_CHECK' else 1)
