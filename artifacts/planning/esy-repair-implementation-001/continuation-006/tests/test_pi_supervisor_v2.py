import base64,json,os,signal,subprocess,sys,time
from pathlib import Path
D=Path(__file__).resolve().parents[1];R=D/'pi-runtime-v2';PYTHON=sys._base_executable
if len(sys.argv)>1 and sys.argv[1]=='--launch':
 p=subprocess.Popen([PYTHON,'-B',str(D/'guardian-v2.py'),sys.argv[2]],stdin=subprocess.PIPE,start_new_session=True);time.sleep(20);p.stdin.close();p.wait(timeout=10);raise SystemExit()
R.mkdir(mode=0o700);(R/'workspace').mkdir(mode=0o700);(R/'home').mkdir(mode=0o700);(R/'escape').symlink_to(Path.home()/'.codex/auth.json')
body=base64.urlsafe_b64encode(json.dumps({'exp':int(time.time())+3600}).encode()).decode().rstrip('=');(D/'tests/fixture-auth.json').write_text(json.dumps({'tokens':{'access_token':'fake.'+body+'.fake','refresh_token':'not-a-real-secret','account_id':'fixture'}}))
env={'PATH':os.environ['PATH'],'HOME':str(R/'home'),'LANG':'en_US.UTF-8'};rows=[]
probe='''import errno,json,os,socket,time
from pathlib import Path
R=Path(%r);checks={}
for label,path in [('original',Path('/Users/psac/.codex/auth.json')),('escape',R/'escape')]:
 try:fd=os.open(path,os.O_RDONLY)
 except PermissionError:checks[label]=True
 else:os.close(fd);checks[label]=False
try:fd=os.open(R/'private-pi/auth.json',os.O_WRONLY)
except PermissionError:checks['auth_write_denied']=True
else:os.close(fd);checks['auth_write_denied']=False
try:
 pid=os.fork()
 if pid==0:os._exit(0)
 os.waitpid(pid,0);checks['fork_denied']=False
except PermissionError:checks['fork_denied']=True
v=json.loads((R/'private-pi/auth.json').read_text());checks['empty_refresh']=v['openai-codex']['refresh']==''
(R/'workspace/probe.json').write_text(json.dumps(checks));print(json.dumps(checks),flush=True)
if not all(checks.values()):raise SystemExit(3)
%s
''' 
for name,inject,kill in [('policy',None,False),('setup-failure','after-auth',False),('launcher-death',None,True)]:
 marker=R/'workspace/probe.json';marker.unlink(missing_ok=True);out=D/('v2-'+name)
 code=probe%(str(R),'time.sleep(30)' if kill else '')
 spec={'argv':['/usr/bin/sandbox-exec','-f',str(D/'pi-nofork.sb'),PYTHON,'-B','-c',code],'env':env,'cwd':str(R/'workspace'),'output':str(out),'timeout':5,'cap':4096,'auth_source':'fixture','inject':inject};sp=D/(name+'-v2.spec.json');sp.write_text(json.dumps(spec))
 old=os.umask(0)
 try:p=subprocess.Popen([PYTHON,'-B',str(Path(__file__).resolve()),'--launch',str(sp)],start_new_session=True) if kill else subprocess.Popen([PYTHON,'-B',str(D/'guardian-v2.py'),str(sp)],stdin=subprocess.PIPE,start_new_session=True)
 finally:os.umask(old)
 try:
  if kill:
   until=time.monotonic()+3
   while not marker.exists() and time.monotonic()<until:time.sleep(.01)
   assert marker.exists(),'active worker not observed';p.kill();p.wait(timeout=3)
  else:p.wait(timeout=10)
  until=time.monotonic()+8
  while not (out/'receipt.json').exists() and time.monotonic()<until:time.sleep(.01)
  receipt=json.loads((out/'receipt.json').read_text());absent=not (R/'private-pi/auth.json').exists();passed=receipt['credential_removed'] and absent
  if inject:passed=passed and receipt['worker_pid'] is None
  elif kill:passed=passed and receipt['worker_reaped'] and receipt['reason']=='launcher-eof' and receipt['exit_code']==-9
  else:passed=passed and receipt['worker_reaped'] and receipt['exit_code']==0 and receipt['reason'] is None and all(json.loads(marker.read_text()).values())
  rows.append({'scenario':name,'passed':passed,'receipt':receipt,'credential_absent':absent})
 finally:
  if p.poll() is None:p.kill();p.wait(timeout=3)
(D/'pi-supervisor-v2-e2e.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows));raise SystemExit(0 if all(x['passed'] for x in rows) else 1)
