import hashlib,json,os,subprocess,sys
from pathlib import Path
D=Path(__file__).resolve().parent;R=D.parent/'continuation-008/pi-runtime-v2';work=R/'workspace';(work/'probe.txt').write_text('before\n')
env={k:os.environ[k] for k in ['PATH','LANG','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS'] if k in os.environ};env.update(HOME=str(R/'home'),PI_CODING_AGENT_DIR=str(R/'private-pi'),PI_CODING_AGENT_SESSION_DIR=str(R/'sessions'),PI_TELEMETRY='0',TMPDIR=str(R))
argv=['/usr/bin/sandbox-exec','-f',str(D.parent/'continuation-008/pi-nofork-v3.sb'),'/opt/homebrew/bin/pi','--print','--mode','json','--provider','openai-codex','--model','gpt-6-luna','--thinking','high','--no-session','--no-extensions','--no-mcp','--no-skills','--no-prompt-templates','--no-context-files','--no-themes','--no-approve','--offline','--tools','read,edit,write','Use read/edit/write tools to change only probe.txt from before to after, retaining newline. Do not run commands. This is an isolated capability test.']
spec={'argv':argv,'env':env,'cwd':str(work),'output':str(D/'pi-smoke-high'),'timeout':120,'cap':131072,'auth_source':'real'};sp=D/'pi-smoke-high.spec.json';sp.write_text(json.dumps(spec,indent=2));p=subprocess.Popen([sys._base_executable,'-B',str(D.parent/'continuation-008/guardian-v2.py'),str(sp)],stdin=subprocess.PIPE,start_new_session=True)
try:p.wait(timeout=135)
except subprocess.TimeoutExpired:p.stdin.close();p.wait(timeout=10)
receipt=json.loads((D/'pi-smoke-high/receipt.json').read_text())
def strict(pairs):
 out={}
 for k,v in pairs:
  if k in out:raise ValueError('duplicate JSON key')
  out[k]=v
 return out
identity=[];parse_error=None
try:
 events=[json.loads(line,object_pairs_hook=strict) for line in (D/'pi-smoke-high/stdout').read_text().splitlines() if line.strip()]
 for e in events:
  m=e.get('message',{})
  if e.get('type')=='message_end' and m.get('role')=='assistant':identity.append({'provider':m.get('provider'),'model':m.get('model'),'stopReason':m.get('stopReason')})
except (ValueError,TypeError) as e:parse_error=type(e).__name__
checks={'exact_fixture':(work/'probe.txt').read_bytes()==b'after\n','reaped':receipt['worker_reaped'],'exit0':receipt['exit_code']==0,'no_failure':receipt['reason'] is None,'credential_removed':receipt['credential_removed'] and not (R/'private-pi/auth.json').exists(),'model_identity':bool(identity) and all(x['provider']=='openai-codex' and x['model']=='gpt-6-luna' and x['stopReason'] not in ['error','aborted'] for x in identity),'complete_json':parse_error is None}
result={'status':'PASSED' if all(checks.values()) else 'FAILED','checks':checks,'reported_identity':identity,'guardian':receipt,'profile_sha256':hashlib.sha256((D.parent/'continuation-008/pi-nofork-v3.sb').read_bytes()).hexdigest(),'scope':'isolated provider smoke only'};(D/'pi-smoke-high-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));raise SystemExit(0 if result['status']=='PASSED' else 1)
