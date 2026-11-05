import hashlib,json,os,socket,subprocess,sys,tempfile,time
from pathlib import Path
b=Path(__file__).resolve().parent; state=b.parent; repo=state.parents[2]
work=b/'work'; outside=b/'outside-canary'; outside.write_text('unchanged')
link=work/'escape'; link.unlink(missing_ok=True); link.symlink_to(outside)
sockdir=tempfile.TemporaryDirectory(prefix='esy-sock-',dir='/private/tmp'); sockpath=str(Path(sockdir.name)/'s'); server=socket.socket(socket.AF_UNIX); server.bind(sockpath); server.listen(1)
# An unsandboxed connect proves the target exists and accepts connections.
probe=socket.socket(socket.AF_UNIX); probe.connect(sockpath); c,_=server.accept(); c.close(); probe.close()
checks=[]
def run(name,profile,code,expected):
 r=subprocess.run(['/usr/bin/sandbox-exec','-f',str(b/profile),sys.executable,'-c',code],capture_output=True,timeout=10)
 checks.append({'id':name,'exit_code':r.returncode,'stdout':r.stdout.decode(),'stderr':r.stderr.decode(),'passed':r.returncode==expected})
run('allowed-code-write','code-002.sb',f'from pathlib import Path; Path({str(work/"allowed")!r}).write_text("ok")',0)
for name,path in [('outside',outside),('baseline',state/'baseline-manifest.json'),('original',repo/'pyproject.toml'),('symlink',link)]:
 code=f'''import os
try:
 fd=os.open({str(path)!r},os.O_WRONLY)
except PermissionError: raise SystemExit(0)
else:
 os.close(fd); raise SystemExit(3)
'''
 run('deny-'+name,'code-002.sb',code,0)
 run('deny-child-'+name,'code-002.sb','import subprocess,sys; raise SystemExit(subprocess.run([sys.executable,"-c",'+repr(code)+']).returncode)',0)
run('deny-unix-socket','code-002.sb',f'''import socket
s=socket.socket(socket.AF_UNIX)
try: s.connect({sockpath!r})
except PermissionError: raise SystemExit(0)
else: raise SystemExit(3)
''',0)
run('review-input-readonly','review-002.sb',f'''import os
try: fd=os.open({str(work/"allowed")!r},os.O_WRONLY)
except PermissionError: raise SystemExit(0)
else: os.close(fd); raise SystemExit(3)
''',0)
run('deny-signal-parent','code-002.sb',f'''import os
try: os.kill({os.getpid()},0)
except PermissionError: raise SystemExit(0)
else: raise SystemExit(3)
''',0)
server.close(); Path(sockpath).unlink(); sockdir.cleanup(); link.unlink()
report={'status':'PASSED' if all(x['passed'] for x in checks) else 'FAILED','checks':checks,'scope':'bootstrap containment probes only; not full C0/C6 acceptance'}
(b/'containment-002.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
raise SystemExit(0 if report['status']=='PASSED' else 1)
