import os,json,threading,errno
results={}
try:
 pid=os.fork()
 if pid==0: os._exit(0)
 os.waitpid(pid,0);results['fork_denied']=False
except OSError as e: results['fork_denied']=e.errno in (errno.EPERM,errno.EACCES)
try:
 pid=os.posix_spawn('/usr/bin/true',['/usr/bin/true'],{})
 os.waitpid(pid,0);results['posix_spawn_denied']=False
except OSError as e:results['posix_spawn_denied']=e.errno in (errno.EPERM,errno.EACCES)
def target():results['thread_works']=True
t=threading.Thread(target=target);t.start();t.join(2)
print(json.dumps(results));raise SystemExit(0 if all(results.values()) else 1)
