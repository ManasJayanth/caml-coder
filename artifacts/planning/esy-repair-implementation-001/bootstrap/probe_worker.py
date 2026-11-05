import json,os,socket,subprocess,sys
from pathlib import Path
s=Path(__file__).resolve().parents[1]; c=s/'candidate'; results=[]
def check(name,passed):
 results.append({'id':name,'passed':bool(passed)})
def denied(path):
 try:
  fd=os.open(path,os.O_WRONLY); os.close(fd); return False
 except PermissionError: return True
x=c/'scripts/esy-repair/probe-write.txt'; x.write_text('ok'); check('allowed-write',x.read_text()=='ok')
for name,path in [('original',s.parents[2]/'pyproject.toml'),('baseline',s/'baseline-manifest.json'),('controller',Path(__file__)),('outside',s/'bootstrap.json')]:
 check('denied-'+name,denied(path))
 code='import os;\ntry: fd=os.open('+repr(str(path))+',os.O_WRONLY); os.close(fd); raise SystemExit(2)\nexcept PermissionError: pass\n'
 check('child-denied-'+name,subprocess.run([sys.executable,'-c',code]).returncode==0)
link=c/'scripts/esy-repair/probe-escape'; link.symlink_to(s/'baseline-manifest.json'); check('symlink-denied',denied(link)); link.unlink()
try:
 sock=socket.socket(socket.AF_UNIX); sock.connect('/var/run/docker.sock'); ok=False
except PermissionError: ok=True
except OSError: ok=False
finally: sock.close()
check('docker-socket-denied',ok)
try: os.kill(os.getppid(),0); ok=False
except PermissionError: ok=True
check('parent-signal-denied',ok)
x.unlink()
print(json.dumps({'checks':results,'passed':all(r['passed'] for r in results)})); raise SystemExit(0 if all(r['passed'] for r in results) else 1)
