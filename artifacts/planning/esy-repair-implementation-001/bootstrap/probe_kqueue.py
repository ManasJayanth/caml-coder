import json,os,select,subprocess,sys,time,signal
from pathlib import Path
code='''import os,sys,time
sys.stdin.readline()
print(os.getpid(),flush=True)
p=os.fork()
if p==0:
 os.setsid()
 print(os.getpid(),flush=True)
 q=os.fork()
 if q==0:
  print(os.getpid(),flush=True)
  time.sleep(1)
  os._exit(0)
 os._exit(0)
os.waitpid(p,0)
'''
p=subprocess.Popen([sys.executable,'-B','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
k=select.kqueue(); records=[]; error=None
try:
 flags=select.KQ_NOTE_FORK|select.KQ_NOTE_EXEC|select.KQ_NOTE_EXIT|select.KQ_NOTE_TRACK
 k.control([select.kevent(p.pid,filter=select.KQ_FILTER_PROC,flags=select.KQ_EV_ADD|select.KQ_EV_ENABLE|select.KQ_EV_CLEAR,fflags=flags)],0,0)
 p.stdin.write(b'go\n'); p.stdin.flush(); p.stdin.close()
 deadline=time.monotonic()+3
 while time.monotonic()<deadline:
  for event in k.control(None,20,.1): records.append({'pid':event.ident,'flags':event.flags,'fflags':event.fflags,'data':event.data})
except Exception as e:
 error=type(e).__name__+': '+str(e)
 if not p.stdin.closed: p.stdin.write(b'go\n'); p.stdin.flush(); p.stdin.close()
finally:
 k.close(); p.wait(timeout=5)
stdout=p.stdout.read().decode(); p.stderr.close(); p.stdout.close()
pids=[int(x) for x in stdout.split()]; exits={e['pid'] for e in records if e['fflags'] & select.KQ_NOTE_EXIT}; missing=sorted(set(pids)-exits)
r={'status':'PASSED' if not error and not missing else 'FAILED','expected_pids':pids,'exit_events':sorted(exits),'missing_exit_events':missing,'error':error,'events':records,'scope':'kernel descendant tracking including setsid/double-fork; no acceptance claim beyond probe'}
Path(__file__).with_name('kqueue-probe-001.json').write_text(json.dumps(r,indent=2)+'\n'); print(json.dumps(r))
