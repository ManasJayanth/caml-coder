import hashlib,json,os,subprocess,sys
from pathlib import Path
D=Path(__file__).resolve().parent;runtime=D/'nofork-runtime';work=runtime/'smoke';work.mkdir();(work/'probe.txt').write_text('before\n');config=runtime/'codex';config.mkdir();auth=config/'auth.json';auth.symlink_to(Path.home()/'.codex/auth.json')
env={k:os.environ[k] for k in ['PATH','HOME','USER','LANG','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS'] if k in os.environ};env.update(CODEX_HOME=str(config),TMPDIR=str(runtime))
argv=['/usr/bin/sandbox-exec','-f',str(D/'nofork.sb'),'/opt/homebrew/bin/codex','exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','--model','gpt-6-luna','--sandbox','danger-full-access','--cd',str(work),'--disable','apps','--disable','plugins','--disable','hooks','--disable','multi_agent','--disable','shell_snapshot','--disable','shell_tool','--json','Use apply_patch to change only probe.txt from before to after, retaining its newline. Do not run any commands. Report whether the patch tool succeeded. This is an isolated capability smoke, not a repository implementation task.']
spec={'argv':argv,'env':env,'cwd':str(work),'output':str(D/'codex-nofork-smoke'),'timeout':120,'cap':131072};p=D/'codex-nofork-smoke.spec.json';p.write_text(json.dumps(spec,indent=2))
try:
 proc=subprocess.Popen([sys.executable,'-B',str(D/'guardian.py'),str(p)],stdin=subprocess.PIPE,start_new_session=True)
 try:proc.wait(timeout=130)
 except subprocess.TimeoutExpired:
  proc.stdin.close();proc.wait(timeout=10)
 receipt=json.loads((D/'codex-nofork-smoke/receipt.json').read_text());result={'fixture_before':'before\n','fixture_after':(work/'probe.txt').read_text(),'expected':'after\n','guardian':receipt,'runner_coding_launches_consumed':0,'scope':'isolated provider capability smoke only, candidate unmodified','profile_sha256':hashlib.sha256((D/'nofork.sb').read_bytes()).hexdigest()};(D/'codex-nofork-smoke-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
finally:auth.unlink(missing_ok=True)
