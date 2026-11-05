import hashlib,json,os,re,secrets,selectors,signal,subprocess,time
from pathlib import Path
s=Path('/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001');d=s/'probes/seed-compile-002';d.mkdir(parents=True,exist_ok=False)
def call(name,args,timeout=15):
 p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,start_new_session=True);sel=selectors.DefaultSelector();logs={'stdout':bytearray(),'stderr':bytearray()};end=time.monotonic()+timeout;failure=None
 for st,k in ((p.stdout,'stdout'),(p.stderr,'stderr')):sel.register(st,selectors.EVENT_READ,k)
 try:
  while sel.get_map():
   if time.monotonic()>=end:failure='timeout';break
   for key,_ in sel.select(.1):
    raw=os.read(key.fd,16384)
    if not raw:sel.unregister(key.fileobj);continue
    room=65536-sum(map(len,logs.values()));logs[key.data].extend(raw[:room])
    if len(raw)>room:failure='output-cap';break
   if failure:break
 finally:
  if failure:
   try:os.killpg(p.pid,signal.SIGKILL)
   except ProcessLookupError:pass
  try:p.wait(timeout=2)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=2);failure='exit-timeout'
  sel.close()
  for st in (p.stdout,p.stderr):st.close()
 for k,raw in logs.items():(d/(name+'.'+k)).write_bytes(raw)
 r={'argv':args,'exit_code':p.returncode,'failure':failure,'logs':{k:{'path':str(d/(name+'.'+k)),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for k,raw in logs.items()}};(d/(name+'.json')).write_text(json.dumps(r,indent=2));return r,bytes(logs['stdout'])
review=json.loads((s/'jobs/seed-compile-tmp-review-001/final.txt').read_text());assert review['safe_to_execute'] is True
script=(s/'bootstrap/seed-compile-probe.sh').read_text();assert script in (s/'jobs/seed-compile-review-001/prompt.txt').read_text();image='sha256:06095e22e6fb4cedaaff8fa57e7951338bb7a80e2ac8b6d1d4d6bcc0b9727459';owner=secrets.token_hex(12);cid=None;verified=False;report={'status':'FAILED','image':image,'script_sha256':hashlib.sha256(script.encode()).hexdigest(),'runner_acceptance':False,'started_epoch':time.time()}
tmpfs={'/work':'rw,nosuid,nodev,exec,size=128m,uid=1000,gid=1000,mode=700','/home/opam/esy-reference/_esy':'rw,nosuid,nodev,exec,size=32m,uid=1000,gid=1000,mode=700','/home/opam/esy-reference/node_modules/.cache':'rw,nosuid,nodev,exec,size=32m,uid=1000,gid=1000,mode=700'}
try:
 args=['docker','create','--name','esy-compile-probe-'+owner,'--label','esy-reference.owner='+owner,'--platform','linux/amd64','--pull=never','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','128','--memory','2g','--cpus','2','--env','TMPDIR=/work','--user','1000:1000','--workdir','/home/opam/esy-reference','--entrypoint','/usr/bin/timeout']
 for dest,opts in tmpfs.items():args+=['--tmpfs',dest+':'+opts]
 args +=[image,'--signal=KILL','30','/bin/sh','-c',script];r,out=call('create',args);assert r['exit_code']==0 and not r['failure'];cid=out.decode().strip();assert re.fullmatch('[0-9a-f]{64}',cid);report['container_id']=cid
 r,out=call('inspect',['docker','inspect',cid]);assert r['exit_code']==0 and not r['failure'];obj=json.loads(out)[0];c=obj['Config'];h=obj['HostConfig'];assert obj['Id']==cid and c['Labels']['esy-reference.owner']==owner;verified=True
 assert obj['Image']==image and c['User']=='1000:1000' and c['WorkingDir']=='/home/opam/esy-reference' and not c.get('Volumes');assert h['Tmpfs']==tmpfs and not obj['Mounts'];assert h['ReadonlyRootfs'] and h['NetworkMode']=='none' and h['Memory']==2147483648 and h['NanoCpus']==2000000000 and h['PidsLimit']==128;assert h['CapDrop']==['ALL'] and h['SecurityOpt']==['no-new-privileges:true'] and not h['Privileged'] and not h['CapAdd'] and not h['Devices'] and not h['DeviceRequests'];assert [e for e in c['Env'] if e.startswith('TMPDIR=')]==['TMPDIR=/work'];report['actual_configuration_verified']=True
 r,out=call('compile-run',['docker','start','-a',cid],40);report.update(command_exit=r['exit_code'],command_failure=r['failure'],stdout=out.decode(errors='replace'));report['status']='DIAGNOSTIC_PASS' if r['exit_code']==0 and not r['failure'] and out==b'esy-cache-probe:passed\n' else 'FAILED'
except Exception as exc:report['error']=repr(exc)
finally:
 if cid and verified:
  r,_=call('remove',['docker','rm','-f',cid]);q,out=call('absence',['docker','ps','-aq','--no-trunc','--filter','id='+cid]);report['cleanup_verified']=r['exit_code']==0 and not r['failure'] and q['exit_code']==0 and not q['failure'] and cid not in out.decode().splitlines()
 else:report['cleanup_verified']=False
 if not report['cleanup_verified']:report['status']='FAILED'
 report['finished_epoch']=time.time();(d/'receipt.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
raise SystemExit(0 if report['status']=='DIAGNOSTIC_PASS' else 1)
