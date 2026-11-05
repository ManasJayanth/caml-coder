import json,os,signal,subprocess,sys,time
from pathlib import Path
D=Path(__file__).resolve().parent;env={k:os.environ[k] for k in ['PATH','HOME','USER','LANG'] if k in os.environ};rows=[]
for phase in ['created','active']:
 out=D/('guardian-death-'+phase);marker=D/'nofork-runtime'/('active-'+phase)
 code="import os,time;from pathlib import Path;os.setsid();os.close(1);os.close(2);Path("+repr(str(marker))+").write_text('active');time.sleep(30)"
 spec={'argv':['/usr/bin/sandbox-exec','-f',str(D/'nofork.sb'),sys.executable,'-B','-c',code],'env':env,'cwd':str(D),'output':str(out),'timeout':5,'cap':1024};path=D/('death-'+phase+'.spec.json');path.write_text(json.dumps(spec))
 p=subprocess.Popen([sys.executable,'-B',str(D/'guardian-launcher-probe.py'),str(path)],start_new_session=True)
 try:
  trigger=out/'ready.json' if phase=='created' else marker
  until=time.monotonic()+3
  while not trigger.exists() and time.monotonic()<until:time.sleep(.01)
  triggered=trigger.exists();os.kill(p.pid,signal.SIGKILL);p.wait(timeout=3)
  until=time.monotonic()+7
  while not (out/'receipt.json').exists() and time.monotonic()<until:time.sleep(.01)
  receipt=json.loads((out/'receipt.json').read_text());rows.append({'phase':phase,'triggered':triggered,'passed':triggered and receipt['worker_reaped'] and receipt['reason']=='launcher-eof' and receipt['exit_code']==-9,'receipt':receipt})
 finally:
  if p.poll() is None:p.kill();p.wait(timeout=3)
(D/'guardian-death-e2e.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows));raise SystemExit(0 if all(r['passed'] for r in rows) else 1)
