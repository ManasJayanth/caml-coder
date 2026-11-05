import subprocess,sys,time
from pathlib import Path
D=Path(__file__).resolve().parent
p=subprocess.Popen([sys.executable,'-B',str(D/'guardian.py'),sys.argv[1]],stdin=subprocess.PIPE,start_new_session=True)
time.sleep(20)
p.stdin.close();p.wait(timeout=10)
