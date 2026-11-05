import ast,difflib,hashlib,json,stat,sys
from pathlib import Path
D=Path('/Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/continuation-010');j=D/'coding-jobs'/sys.argv[1]
def strict(ps):
 o={}
 for k,v in ps:
  if k in o:raise ValueError('duplicate key')
  o[k]=v
 return o
es=[json.loads(l,object_pairs_hook=strict) for l in (j/'guardian/stdout').read_text().splitlines()]
assert es[0]['type']=='session' and es[-1]=={'type':'agent_settled','aborted':False}
ends=[e for e in es if e['type']=='agent_end'];assert len(ends)==1 and ends[0]['willRetry'] is False
ms=[e['message'] for e in es if e['type']=='message_end' and e['message'].get('role')=='assistant'];assert ms[-1]['stopReason']=='stop' and all(m['provider']=='openai-codex' and m['model']=='gpt-6-luna' and m['stopReason'] in ['toolUse','stop'] for m in ms)
a=[e for e in es if e['type']=='tool_execution_start'];b=[e for e in es if e['type']=='tool_execution_end'];assert [e['toolCallId'] for e in a]==[e['toolCallId'] for e in b] and all(e['toolName'] in ['read','edit','write'] for e in a)
parent=json.loads((j/'parent-manifest.json').read_text());result=json.loads((j/'result-manifest.json').read_text())
for manifest,root in [(parent,D/'candidate'),(result,j/'frozen')]:
 for x in manifest:
  p=root/x['path'];assert not p.is_symlink() and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==x['sha256'] and p.stat().st_size==x['size'] and stat.S_IMODE(p.stat().st_mode)==x['mode']
old={x['path']:x for x in parent};new={x['path']:x for x in result};changed=[p for p in old.keys()|new.keys() if old.get(p)!=new.get(p)];assert changed==['tests/e2e/test_review_adapter_e2e.py']
p=changed[0];source=(j/'frozen'/p).read_text();ast.parse(source)
diff=''.join(difflib.unified_diff((D/'candidate'/p).read_text().splitlines(True),source.splitlines(True),fromfile='parent/'+p,tofile='proposed/'+p));(j/'diff.patch').write_text(diff)
r=json.loads((j/'guardian/receipt.json').read_text());assert r['worker_reaped'] and r['credential_removed'] and r['exit_code']==0 and r['reason'] is None
assert not (D.parent/'continuation-008/pi-runtime-v2/private-pi/auth.json').exists()
report={'complete_provider_envelope':True,'exact_model':True,'tool_errors':[e for e in b if e['isError']],'only_allowed_tools':True,'manifests_verified':True,'changed_paths':changed,'ast_parse':True,'tests_run':False,'cleanup_verified':True,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'revision_sha256':hashlib.sha256((j/'result-manifest.json').read_bytes()).hexdigest()}
(j/'independent-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='tool_errors'}))
