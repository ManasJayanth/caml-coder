"""Dedicated attempt 37. Output is inert proposal text. No candidate imports, tests or automatic patch application."""
import os, sys, json, hashlib, stat, pathlib, subprocess, time, importlib.util, base64
from pathlib import Path
D=Path(__file__).resolve().parent
C=D.parent
S=C.parent
O=C/'orch'
R=S/'continuation-008/pi-runtime-v2'
G=S/'continuation-008/guardian-v2.py'
BASE=C/'frozen/orch-011'
REV='b29c0769974448d4abc7b7aa261deaf0a9a7656213a2b88e82306e3bd81d36da'
def need(b,msg):
    if not b: raise RuntimeError(msg)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def bind(p,h):
    need(p.resolve()==p and p.is_file() and digest(p)==h,'binding mismatch: '+str(p))
def write(p,b):
    with p.open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
def main():
    need(sys.flags.isolated and not sys.flags.optimize and sys.dont_write_bytecode,'requires -I -B')
    os.umask(0o077)
    bind(O/'loop.py','51a64a8cd047d1792d29966ac7bff035b66f35ae623f4647f686bcb095e3bc2d')
    spec=importlib.util.spec_from_file_location('host_only',O/'loop.py');L=importlib.util.module_from_spec(spec);spec.loader.exec_module(L)
    with L.Lock() as lock:
        st=L.load_state(); env=L.load_env();card=L.load_cards()['C9']
        need(st['parent_hash']==REV==st['orch_hash']==L.inv_hash(L.inventory(BASE))==L.inv_hash(L.orch_source_inventory()),'revision drift')
        need(st['launches_used']==36 and st['cards']['C9']['status']=='PENDING' and st['cards']['C9']['attempts']==0,'slot/card changed')
        need(st['dispositions']['F11']=='card:C9' and not st['pending_findings'],'planning incomplete')
        need(st.get('worker_failure_streak',0)<2,'worker failure streak')
        bind(O/'cards/C9.json','d811dd64bbca151c1998d69ca49c55cdfb31e19f4fb6ee8b9ca7accc9f2f9c5c');
        for key,(target,h) in {'/opt/homebrew/Cellar/pi-coding-agent/1.4.0/bin/pi': ['/opt/homebrew/Cellar/pi-coding-agent/1.4.0/bin/pi', '1a28e7800ea03a52d27d3d830f3233790a4d174df9b2cb584cc55cfb681b192a'], '/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/bin/pi': ['/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js', '23d4af9cb96c3d01b13000c03d431b9f1b026527d68bc244467e77e35a3771a1'], '/opt/homebrew/opt/node/bin/node': ['/opt/homebrew/Cellar/node/26.13.0_2/bin/node', '64e4f47aef084a288c443ebe9a0091a34acba03ad176fb612b6e7d90784ff93d'], '/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js': ['/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js', '88158f4bf29b6d77d17258153733007f63ef5a50c223989953c498bc12038257'], '/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/index.js': ['/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/index.js', '4e30102d8ba2642ffa1615abcaa137ae03c2c74830e9a0cc771c11f98e037e82'], '/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli-runtime.js': ['/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli-runtime.js', '9e1d979f28e3b336bb15a5a1b00cf78b5e1f9d5e63f112d156810651c9114551'], '/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js': ['/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js', '23d4af9cb96c3d01b13000c03d431b9f1b026527d68bc244467e77e35a3771a1']}.items():
            need(str(Path(key).resolve())==target,'executable chain drift');bind(Path(target),h)
        L.guardian_bindings(env);L.slot_gate(st);L.time_gate(st,840)
        need(time.time()+840 < 1793966550,'November 6 wall window insufficient')
        profile=S/'continuation-008/pi-nofork-v3.sb'
        bind(G,'0168a443a677349c14d6ff32482976407b09568bbed18fe37c7d7105ef45aa6f');bind(profile,'6f5bd2ea5f14e95d4583167d7362a4a136655c1195b62b3d09448eb2c1b089c7')
        need(R.resolve()==R and not list((R/'private-pi').iterdir()),'credential runtime not clean')
        need(env['PI_PROVIDER']=='openai-codex' and env['PI_CODING_MODEL']=='gpt-6-luna' and Path(env['PI_RUNTIME'])==R and Path(env['PI_GUARDIAN'])==G and Path(env['PI_PROFILE'])==profile and env['PI_BIN']=='/opt/homebrew/Cellar/pi-coding-agent/1.4.0/bin/pi','wrong worker')
        tok=json.loads((Path.home()/'.codex/auth.json').read_text())['tokens']['access_token'].split('.')[1]
        need(json.loads(base64.urlsafe_b64decode(tok+'='*(-len(tok)%4)))['exp']-time.time()>650,'short credential lifetime')
        job=R/'author-only-037';ev=D/'attempt-037'
        ev.mkdir(mode=0o700);job.mkdir(mode=0o700);home=job/'home';home.mkdir();tmp=job/'tmp';tmp.mkdir();sessions=job/'sessions';sessions.mkdir()
        need(not any((q/'.pi'/n).exists() for q in (job,*job.parents) for n in ('SYSTEM.md','APPEND_SYSTEM.md','settings.json','extensions')),'ambient Pi config')
        text='Propose a patch, never execute anything. All tools disabled. Return JSON with edits (path,exact unique old text,new text), or blocked with reason. Do not emit large replacements or repeat source. Author-only transport supersedes the card edit tools and CARD_DONE marker. Do not apply or run tests. '+json.dumps(card)+'\nBinding safety clarification: never signal a PID or PGID after its leader was reaped or ownership uncertain. Do not infer tree cleanup from absence of one group; cover setsid, silent and TERM-ignoring survivors. If no defensible boundary within allowed paths, return blocked instead of unsafe success. An explicit blocked response is acceptable.\n'
        for name in ['run_bounded.py','e2e/run_e2e.py']:text+='\nSOURCE '+name+'\n'+(BASE/name).read_text()
        prompt=job/'card.txt';write(prompt,text.encode());write(ev/'prompt.txt',text.encode())
        cfg=L.coding_spec(env,job,prompt,ev/'guardian',600);a=cfg['argv'];i=a.index('--tools');a[i:i+2]=['--no-tools'];cfg['env'].update(HOME=str(home),TMPDIR=str(tmp),PI_CODING_AGENT_SESSION_DIR=str(sessions),PATH='/opt/homebrew/bin:/usr/bin:/bin')
        narrowed=ev/'worker.sb';write(narrowed,(profile.read_text()+'\n(deny file-write*)\n(allow file-write* (subpath '+json.dumps(str(job))+'))\n(allow file-write* (literal '+json.dumps(str(R/'private-pi/auth.json.lock'))+'))\n').encode());a[2]=str(narrowed);a[-1]=text;cfg['env']['NODE_DISABLE_COMPILE_CACHE']='1'
        probe="const f=require('fs'),c=require('child_process');const denied=fn=>{try{fn();return false}catch(e){return ['EPERM','EACCES'].includes(e.code)}};const r=c.spawnSync('/usr/bin/true');if(!r.error||!['EPERM','EACCES'].includes(r.error.code)||!denied(()=>f.openSync(process.argv[1],'r+'))||!denied(()=>f.openSync(process.argv[2],'r')))process.exit(1);"
        probe_argv=[a[0],'-f',str(narrowed),'/opt/homebrew/opt/node/bin/node','-e',probe,str(ev/'prompt.txt'),str(Path.home()/'.codex/auth.json')]
        subprocess.run(probe_argv,env={'PATH':'/usr/bin:/bin'},stdin=subprocess.DEVNULL,timeout=10,check=True)
        sp=ev/'spec.json';write(sp,json.dumps(cfg).encode())
        reserved=[r['slot'] for r in map(json.loads,(O/'ledger.jsonl').read_text().splitlines()) if r.get('event')=='reserve']
        need(not any(v>=37 for v in reserved),'prior slot reservation')
        lock.keep=True
        st['cards']['C9'].update(status='RESERVED',attempts=1);L.reserve_slot(st,'C9',1);start=time.monotonic()
        cmd=['/usr/bin/python3','-I','-B',str(G),str(sp)]
        with (ev/'guardian-out').open('xb') as so,(ev/'guardian-err').open('xb') as se:
            p=subprocess.Popen(cmd,cwd=ev,stdin=subprocess.PIPE,stdout=so,stderr=se,start_new_session=True,env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin','LANG':'C'})
            try:p.wait(timeout=620)
            finally:
                p.stdin.close()
                if p.poll() is None:p.wait(timeout=15)
        g=L.read_bounded_json(ev/'guardian/receipt.json',16384)
        need(p.returncode==0 and g['worker_reaped'] is True and g['credential_removed'] is True and g['status']=='TERMINATED' and not list((R/'private-pi').iterdir()),'uncertain guardian cleanup')
        need((ev/'guardian/stdout').stat().st_size<=2097152 and L.inv_hash(L.inventory(BASE))==REV,'evidence bound')
        st['active_seconds']+=time.monotonic()-start
        status='AUTHORED_UNREVIEWED' if g['exit_code']==0 and g['reason'] is None else 'FAILED'
        st['cards']['C9'].update(status=status,author_evidence=str(ev));L.save_state(st)
        L.append_ledger({'event':'author_only','slot':37,'card':'C9','status':status,'tests_executed':False,'stdout_sha256':digest(ev/'guardian/stdout'),'worker_reason':g['reason']});lock.keep=False
        print(status)
if __name__=='__main__':main()
