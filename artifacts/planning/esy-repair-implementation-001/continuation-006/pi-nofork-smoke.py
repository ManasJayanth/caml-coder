"""Bounded optional-backend capability check, never edits the candidate."""
import base64,hashlib,json,os,subprocess,sys,time
from pathlib import Path
D=Path(__file__).resolve().parent;runtime=D/'nofork-runtime';work=runtime/'pi-smoke';work.mkdir();(work/'probe.txt').write_text('before\n');config=runtime/'pi';config.mkdir();auth=config/'auth.json'
# Only an unexpired access credential is copied. No refresh capability is granted.
tokens=json.loads((Path.home()/'.codex/auth.json').read_text())['tokens'];access=tokens['access_token'];body=access.split('.')[1];claims=json.loads(base64.urlsafe_b64decode(body+'='*((-len(body))%4)));expiry=claims['exp']*1000
if expiry < time.time()*1000+600000:raise SystemExit('Access token has insufficient remaining lifetime; no refresh attempted')
auth.write_text(json.dumps({'openai-codex':{'type':'oauth','access':access,'refresh':'','expires':expiry,'accountId':tokens['account_id']}}));auth.chmod(0o600)
env={k:os.environ[k] for k in ['PATH','HOME','USER','LANG','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS'] if k in os.environ};env.update(PI_CODING_AGENT_DIR=str(config),PI_CODING_AGENT_SESSION_DIR=str(config/'sessions'),PI_TELEMETRY='0',TMPDIR=str(runtime))
argv=['/usr/bin/sandbox-exec','-f',str(D/'nofork.sb'),'/opt/homebrew/bin/pi','--print','--mode','json','--provider','openai-codex','--model','gpt-6-luna','--no-session','--no-extensions','--no-mcp','--no-skills','--no-prompt-templates','--no-context-files','--no-themes','--no-approve','--offline','--tools','read,edit,write','Use your file tools to change only probe.txt from before to after, retaining its newline. Do not run commands. This is an isolated capability smoke, not repository implementation.']
spec={'argv':argv,'env':env,'cwd':str(work),'output':str(D/'pi-nofork-smoke'),'timeout':120,'cap':131072};p=D/'pi-nofork-smoke.spec.json'
try:
 p.write_text(json.dumps(spec,indent=2));proc=subprocess.Popen([sys.executable,'-B',str(D/'guardian.py'),str(p)],stdin=subprocess.PIPE,start_new_session=True)
 try:proc.wait(timeout=130)
 except subprocess.TimeoutExpired:proc.stdin.close();proc.wait(timeout=10)
 receipt=json.loads((D/'pi-nofork-smoke/receipt.json').read_text());result={'requested_provider':'openai-codex','requested_model':'gpt-6-luna','fixture_after':(work/'probe.txt').read_text(),'expected':'after\n','guardian':receipt,'runner_coding_launches_consumed':0,'profile_sha256':hashlib.sha256((D/'nofork.sb').read_bytes()).hexdigest()};(D/'pi-nofork-smoke-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
finally:auth.unlink(missing_ok=True)
