"""Public guardian process E2Es using trusted bounded OS fixtures."""
import json,os,signal,subprocess,sys,time
from pathlib import Path
D=Path(__file__).resolve().parent;env={k:os.environ[k] for k in ['PATH','HOME','USER','LANG'] if k in os.environ};rows=[]
for name,code,timeout,cap,expected in [
 ('normal','print("ok")',2,1024,None),
 ('timeout','import time;time.sleep(30)',.2,1024,'timeout'),
 ('overflow','print("x"*10000)',2,100,'output-cap'),
 ('detached-single','import os,time;os.setsid();os.close(1);os.close(2);time.sleep(30)',.2,1024,'timeout'),
 ('parent-eof','import time;time.sleep(30)',10,1024,'launcher-eof')]:
 out=D/('guardian-test-'+name);spec={'argv':['/usr/bin/sandbox-exec','-f',str(D/'nofork.sb'),sys.executable,'-B','-c',code],'env':env,'cwd':str(D),'output':str(out),'timeout':timeout,'cap':cap};path=D/(name+'.spec.json');path.write_text(json.dumps(spec))
 p=subprocess.Popen([sys.executable,'-B',str(D/'guardian.py'),str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 try:
  if name=='parent-eof':
   until=time.monotonic()+3
   while not (out/'ready.json').exists() and time.monotonic()<until:time.sleep(.01)
   p.stdin.close()
  p.wait(timeout=12);r=json.loads((out/'receipt.json').read_text());rows.append({'scenario':name,'passed':r['worker_reaped'] and r['reason']==expected,'receipt':r})
 finally:
  if p.poll() is None:p.stdin.close();p.wait(timeout=10)
(D/'guardian-e2e.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows));raise SystemExit(0 if all(x['passed'] for x in rows) else 1)
