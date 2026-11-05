import hashlib,json,os,re,selectors,signal,subprocess,time
from pathlib import Path
s=Path('/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001');b=s/'builds/N3-002';b.mkdir(parents=True,exist_ok=False);context=b/'context';context.mkdir();base='sha256:c41892ac54ffae381d3629618f07134e8191a609baec19a77584f45c5345c267'
def call(name,args,timeout=20,env=None):
 p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,start_new_session=True,env=env);sel=selectors.DefaultSelector();logs={'stdout':bytearray(),'stderr':bytearray()};end=time.monotonic()+timeout;failure=None
 for st,k in ((p.stdout,'stdout'),(p.stderr,'stderr')):sel.register(st,selectors.EVENT_READ,k)
 try:
  while sel.get_map():
   if time.monotonic()>=end:failure='timeout';break
   for key,_ in sel.select(.1):
    raw=os.read(key.fd,16384)
    if not raw:sel.unregister(key.fileobj);continue
    room=1048576-sum(map(len,logs.values()));logs[key.data].extend(raw[:room])
    if len(raw)>room:failure='output-cap';break
   if failure:break
 finally:
  if failure or p.poll() is None:
   try:os.killpg(p.pid,signal.SIGKILL)
   except ProcessLookupError:pass
  p.wait(timeout=5);sel.close()
  for st in (p.stdout,p.stderr):st.close()
 for k,raw in logs.items():(b/(name+'.'+k)).write_bytes(raw)
 rec={'argv':args,'exit_code':p.returncode,'failure':failure,'logs':{k:{'path':str(b/(name+'.'+k)),'sha256':hashlib.sha256(raw).hexdigest()} for k,raw in logs.items()}};(b/(name+'.json')).write_text(json.dumps(rec,indent=2))
 if failure or p.returncode:raise RuntimeError(name+' failed; daemon build cancellation is unverified if build began')
 return bytes(logs['stdout'])
result={'status':'INCOMPLETE','started_epoch':time.time()}
try:
 review=json.loads((s/'jobs/N3-platform-review-001/final.txt').read_text());assert review['safe_to_attempt_build'] is True
 raw=(s/'candidate/artifacts/planning/esy-reference-proposal-001/Dockerfile.esy-runtime').read_bytes();h=hashlib.sha256(raw).hexdigest();assert h in (s/'jobs/N3-review-001/prompt.txt').read_text();(context/'Dockerfile.esy-runtime').write_bytes(raw);result['dockerfile_sha256']=h
 before=json.loads(call('base-before',['docker','image','inspect',base]))[0];assert before['Id']==base and before['RootFS']['Layers'];assert not before['Config'].get('OnBuild') and not before['Config'].get('Volumes');assert 'ocaml-sft-esy-project-probe@'+base in before['RepoDigests']
 env=dict(os.environ);env['DOCKER_BUILDKIT']='0';result['builder_environment']={'DOCKER_BUILDKIT':'0'}
 call('build',['docker','build','--platform=linux/amd64','--pull=false','--network=none','--no-cache','--rm=true','--force-rm=true','--iidfile',str(b/'image-id'),'--file',str(context/'Dockerfile.esy-runtime'),str(context)],120,env)
 im=(b/'image-id').read_text().strip();assert re.fullmatch(r'sha256:[0-9a-f]{64}',im)
 derivative=json.loads(call('derivative',['docker','image','inspect',im]))[0];after=json.loads(call('base-after',['docker','image','inspect',base]))[0];assert after['Id']==base and after['RootFS']==before['RootFS'];assert derivative['Id']==im and derivative['RootFS']['Layers'][:len(before['RootFS']['Layers'])]==before['RootFS']['Layers'];result.update(status='BUILT_NOT_ACCEPTED',base_image=base,derivative_image=im,base_layer_prefix_verified=True,seed_inventory_verified=False)
except Exception as exc:result['error']=str(exc)
result['finished_epoch']=time.time();(b/'build-receipt.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));raise SystemExit(0 if result['status']=='BUILT_NOT_ACCEPTED' else 1)
