#!/usr/bin/env python3
"""Workflow-loop driver. Stdlib only. Every gate fails closed; nothing 'continues anyway'."""
import argparse, hashlib, json, os, pathlib, re, shutil, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent
LIMITS = {'cap_launches': 48, 'time_ceiling': 32400.0, 'reserve': 180.0, 'code_need': 840.0,
          'review_need': 480.0, 'job_timeout': 600, 'review_timeout': 300, 'cap_bytes': 2 * 1024 * 1024,
          'max_attempts': 3, 'packet_cap': 400 * 1024, 'inputs_cap': 200 * 1024, 'receipt_cap': 16384,
          'smoke_timeout': 120}
# Workers get a fixed env, never the supervisor's full environment (mirrors bootstrap/launch_worker.py).
ENV_ALLOW = ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'SHELL', 'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS')


def base_env():
    e = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
    for k in filter(None, os.environ.get('ORCH_ENV_PASSTHROUGH', '').split(',')):   # explicit, for E2E fakes only
        if k in os.environ:
            e[k] = os.environ[k]
    return e
TERMINAL = {'ACCEPTED', 'SUPERSEDED', 'NEEDS_REPLAN', 'BLOCKED_CLEANUP_UNCERTAIN'}

RULES = """RULES (violating any rule = failure):
1. One objective. Edit ONLY files listed in ALLOWED_PATHS. Create nothing else.
2. Use only read/edit/write tools. Do not run, import, compile, test, or call providers.
3. Each single edit < 3000 characters; split larger changes into several edits.
4. Do not touch history, config/, uv.lock, adapters, or any file not in ALLOWED_PATHS.
5. Finish by printing exactly one line: CARD_DONE <card-id>. If blocked print CARD_BLOCKED <card-id>: <reason> and stop.
6. If instructions conflict, stop with CARD_BLOCKED. Never guess.
7. Never print or write credentials, tokens, or paths under private-pi.
"""


# ---------------------------------------------------------------- primitives
def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def jwrite(p, obj):
    t = str(p) + '.tmp'
    with open(t, 'w') as f:
        json.dump(obj, f, sort_keys=True, indent=1); f.flush(); os.fsync(f.fileno())
    os.replace(t, p)


def append_ledger(rec):
    rec = dict(rec, wall=time.time())
    fd = os.open(ROOT / 'ledger.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(rec, sort_keys=True) + '\n').encode()); os.fsync(fd)
    finally:
        os.close(fd)


def strict_json(b):
    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate key')
        return dict(pairs)
    return json.loads(b, object_pairs_hook=hook)


def read_bounded_json(path, limit):
    with open(path, 'rb') as f:
        b = f.read(limit + 1)          # read limit+1 BEFORE parsing
    if len(b) > limit:
        sys.exit('RECEIPT_TOO_LARGE ' + str(path))
    try:
        return strict_json(b)
    except ValueError as e:
        sys.exit('RECEIPT_INVALID %s: %s' % (path, e))


def load_env():
    env = {}
    p = ROOT / 'env.sh'
    if not p.is_file():
        sys.exit('ENV_MISSING: copy env.sh.example to env.sh')
    for line in p.read_text().splitlines():
        m = re.match(r'\s*export\s+([A-Z_]+)=(.*?)\s*(#.*)?$', line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"\'')
    return env


def load_state():
    p = ROOT / 'state.json'
    if not p.is_file():
        sys.exit('NOT_INITIALIZED')
    return read_bounded_json(p, 8 * 1024 * 1024)


def save_state(st):
    jwrite(ROOT / 'state.json', st)


class Lock:
    def __enter__(self):
        try:
            self.fd = os.open(ROOT / 'lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            sys.exit('LOCK_HELD: previous run uncertain or still active; inspect evidence')
        os.write(self.fd, str(os.getpid()).encode())
        self.keep = False
        return self

    def __exit__(self, *exc):
        os.close(self.fd)
        if not self.keep:
            os.unlink(ROOT / 'lock')
        return False


# ---------------------------------------------------------------- inventory / scope
def inventory(root):
    out = []
    for p in sorted(pathlib.Path(root).rglob('*')):
        if p.is_symlink():
            raise SystemExit('SYMLINK_IN_TREE ' + str(p))
        if p.is_dir():
            continue
        if not p.is_file():
            raise SystemExit('SPECIAL_FILE ' + str(p))
        out.append([str(p.relative_to(root)), oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
    return out


def inv_hash(inv):
    return sha_bytes(json.dumps(inv, sort_keys=True).encode())


def orch_source_inventory():
    """Inventory of the orchestration source itself: orch/*.py, orch/*.sh, env.sh.example, ../review-readonly.sb,
    ../e2e/*.py. A frozen snapshot with this exact relative layout hashes identically (see `review --subject`)."""
    rows = []
    for p in sorted(ROOT.iterdir()):
        if p.is_file() and not p.is_symlink() and p.name != 'env.sh' \
                and (p.suffix in ('.py', '.sh') or p.name == 'env.sh.example'):
            rows.append([p.name, oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
    sb = ROOT.parent / 'review-readonly.sb'
    if sb.is_file() and not sb.is_symlink():
        rows.append([sb.name, oct(sb.stat().st_mode & 0o777), sb.stat().st_size, sha(sb)])
    e2e = ROOT.parent / 'e2e'
    if e2e.is_dir():
        for p in sorted(e2e.glob('*.py')):
            if p.is_file() and not p.is_symlink():
                rows.append(['e2e/' + p.name, oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
    return sorted(rows)


def scope_verify(parent_inv, new_inv, allowed):
    p = {r[0]: r for r in parent_inv}
    n = {r[0]: r for r in new_inv}
    probs = []
    for path in sorted(set(p) | set(n)):
        if p.get(path) != n.get(path):
            if path not in allowed:
                probs.append('OUT_OF_SCOPE ' + path)
            if path not in n:
                probs.append('DELETED ' + path)
    for r in new_inv:
        if r[2] > LIMITS['cap_bytes']:
            probs.append('OVERSIZE ' + r[0])
    return (not probs, probs)


# ---------------------------------------------------------------- gates
def time_gate(st, need_total):
    avail = LIMITS['time_ceiling'] - st['active_seconds']
    if avail < need_total:
        sys.exit('TIME_GATE_FAILED avail=%.1f need=%.1f' % (avail, need_total))


def slot_gate(st):
    if st['launches_used'] >= LIMITS['cap_launches']:
        sys.exit('SLOT_CAP_REACHED')


def reserve_slot(st, card, attempt):
    st['launches_used'] += 1             # consumed BEFORE launch; never refunded
    append_ledger({'event': 'reserve', 'slot': st['launches_used'], 'card': card, 'attempt': attempt})
    save_state(st)


def check_auth_clean(env):
    d = env.get('AUTH_DIR')
    if d and (pathlib.Path(d) / 'auth.json').exists():
        return False
    return True


def guardian_bindings(env):
    """Validate the guardian-route bindings (absolute, non-symlink). Exits on any bad value."""
    for key, kind in (('PI_GUARDIAN', 'file'), ('PI_RUNTIME', 'dir'), ('BOOT_PYTHON', 'exe')):
        p = pathlib.Path(env.get(key) or '')
        if not str(p).startswith('/') or p.is_symlink() or not p.exists():
            sys.exit('%s_INVALID (absolute existing non-symlink %s required)' % (key, kind))
        if kind == 'file' and not p.is_file():
            sys.exit('PI_GUARDIAN_INVALID')
        if kind == 'dir' and not p.is_dir():
            sys.exit('PI_RUNTIME_INVALID')
        if kind == 'exe' and not (p.is_file() and os.access(p, os.X_OK)):
            sys.exit('BOOT_PYTHON_INVALID')


def worker_env(env):
    """Proven worker env (continuation-010/launch-correction.py): fixed allowlist + private runtime dirs."""
    r = pathlib.Path(env['PI_RUNTIME'])
    e = {k: os.environ[k] for k in ('PATH', 'LANG', 'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS') if k in os.environ}
    e.update(HOME=str(r / 'home'), PI_CODING_AGENT_DIR=str(r / 'private-pi'),
             PI_CODING_AGENT_SESSION_DIR=str(r / 'sessions'), PI_TELEMETRY='0', TMPDIR=str(r))
    return e


def coding_spec(env, tree, prompt, output, timeout):
    """Guardian spec whose argv is the exact worker-pi.sh vector (single source of truth for both)."""
    return {'argv': [env['SANDBOX_EXEC'], '-f', env['PI_PROFILE'], env['PI_BIN'], '--print', '--mode', 'json',
                     '--provider', env['PI_PROVIDER'], '--model', env['PI_CODING_MODEL'], '--thinking', 'high',
                     '--no-session', '--no-extensions', '--no-mcp', '--no-skills', '--no-prompt-templates',
                     '--no-context-files', '--no-themes', '--no-approve', '--offline', '--tools', 'read,edit,write',
                     '@' + str(prompt)],
            'env': worker_env(env), 'cwd': str(tree), 'output': str(output), 'timeout': int(timeout),
            'cap': LIMITS['cap_bytes'], 'auth_source': 'real'}


# ---------------------------------------------------------------- launching
def launch(lock, st, label, argv, timeout, cap, cwd, extra_env=None, stdin_pipe=False):
    """Run argv through run_bounded. Uncertainty keeps the lock and aborts; returns (receipt, out_text)."""
    d = ROOT / 'evidence' / label
    d.mkdir(parents=True, exist_ok=False)
    rc = d / 'receipt.json'
    cmd = [sys.executable, '-B', str(ROOT / 'run_bounded.py'), str(rc), str(timeout), str(cap), str(cwd)] \
        + (['--stdin-pipe'] if stdin_pipe else []) + ['--'] + argv
    env = dict(base_env(), **(extra_env or {}))
    p = subprocess.Popen(cmd, start_new_session=True, env=env)
    try:
        code = p.wait()
    except BaseException:
        lock.keep = True                   # interrupted: ownership uncertain, retain lock + evidence
        append_ledger({'event': 'interrupted', 'label': label})
        raise
    if code != 0 or not rc.exists():
        lock.keep = True
        append_ledger({'event': 'uncertain', 'label': label, 'runner_exit': code})
        return None, None
    rec = read_bounded_json(rc, LIMITS['receipt_cap'])
    st['active_seconds'] += rec['elapsed']
    save_state(st)
    append_ledger({'event': 'step', 'label': label, 'status': rec['status'], 'elapsed': rec['elapsed'],
                   'exit': rec.get('exit')})
    out = pathlib.Path(str(rc) + '.out').read_bytes().decode('utf-8', 'replace')
    return rec, out


def uncertain_stop(lock, st, card_id=None):
    lock.keep = True
    if card_id:
        st['cards'][card_id]['status'] = 'BLOCKED_CLEANUP_UNCERTAIN'
    save_state(st)
    sys.stderr.write('BLOCKED_CLEANUP_UNCERTAIN: lock and evidence retained; no automatic salvage\n')
    sys.exit(71)


# ---------------------------------------------------------------- cards
CARD_KEYS = {'id', 'objective', 'depends_on', 'allowed_paths', 'acceptance_rows', 'stop_condition', 'e2e', 'timeout'}
CARD_OPTIONAL = {'inputs_inline', 'base', 'replaces', 'max_edit_chars', 'parent_manifest', 'parent_hash'}


def validate_card(c):
    if not isinstance(c, dict):
        return 'card not an object'
    miss = CARD_KEYS - set(c)
    if miss:
        return 'missing keys %s' % sorted(miss)
    extra = set(c) - CARD_KEYS - CARD_OPTIONAL
    if extra:
        return 'unknown keys %s' % sorted(extra)
    if not isinstance(c['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', c['id']):
        return 'bad id'
    if not isinstance(c['objective'], str) or not c['objective'].strip() or '\n' in c['objective']:
        return 'objective must be one non-empty line'
    ap = c['allowed_paths']
    if not isinstance(ap, list) or not 1 <= len(ap) <= 3:
        return 'allowed_paths must list 1..3 paths'
    for x in ap:
        if not isinstance(x, str) or x.startswith('/') or '..' in pathlib.PurePosixPath(x).parts or not x:
            return 'bad allowed path %r' % (x,)
    if not isinstance(c['timeout'], int) or not 1 <= c['timeout'] <= LIMITS['job_timeout']:
        return 'timeout must be int 1..600'
    e = c['e2e']
    if not isinstance(e, dict) or not isinstance(e.get('argv'), list) or not e['argv'] \
            or not all(isinstance(x, str) for x in e['argv']) or not isinstance(e.get('expect_status'), int):
        return 'e2e needs argv list and int expect_status'
    if not isinstance(c['depends_on'], list) or not isinstance(c['acceptance_rows'], list) or not c['acceptance_rows']:
        return 'depends_on / acceptance_rows malformed'
    machine = {'id': c['id'], 'objective': c['objective'], 'allowed_paths': ap, 'depends_on': c['depends_on'],
               'argv': e['argv'], 'expect_files': e.get('expect_files', []), 'inputs_inline': c.get('inputs_inline', [])}
    if re.search(r'<[^<>\n]*>|TODO', json.dumps(machine)):      # prose rows may quote "<card-id>" legitimately
        return 'placeholder text (<...> or TODO) in a machine-consumed field'
    return None


def check_acyclic(cards):
    seen = {}

    def visit(i, stack):
        if i in stack:
            return False
        if seen.get(i):
            return True
        for d in cards[i]['depends_on']:
            if d in cards and not visit(d, stack | {i}):
                return False
        seen[i] = True
        return True
    return all(visit(i, frozenset()) for i in cards)


def load_cards():
    cards = {}
    for p in sorted((ROOT / 'cards').glob('*.json')):
        c = read_bounded_json(p, 256 * 1024)
        err = validate_card(c)
        if err:
            sys.exit('CARD_INVALID %s: %s' % (p.name, err))
        if c['id'] in cards:
            sys.exit('CARD_DUPLICATE ' + c['id'])
        cards[c['id']] = c
    if not check_acyclic(cards):
        sys.exit('CARD_CYCLE')
    return cards


def dep_satisfied(st, d):
    s = st['cards'].get(d)
    if not s:
        return False
    if s['status'] == 'ACCEPTED':
        return True
    if s['status'] == 'SUPERSEDED' and s.get('superseded_by'):
        return all(dep_satisfied(st, x) for x in s['superseded_by'])
    return False


def assemble_prompt(c, st, base_dir):
    parts = [RULES, 'CARD_ID: %s' % c['id'], 'OBJECTIVE: %s' % c['objective'],
             'PARENT_HASH: %s' % st['parent_hash'], 'ALLOWED_PATHS: %s' % ','.join(c['allowed_paths']),
             'ACCEPTANCE_ROWS:'] + ['- ' + r for r in c['acceptance_rows']]
    parts.append('STOP_CONDITION: %s' % c['stop_condition'])
    total = 0
    for rel in c.get('inputs_inline', []):
        p = pathlib.Path(base_dir) / rel
        if p.is_symlink() or not p.is_file() or rel.startswith('/') or '..' in pathlib.PurePosixPath(rel).parts:
            sys.exit('INPUT_INVALID ' + rel)
        data = p.read_bytes()
        total += len(data)
        if total > LIMITS['inputs_cap']:
            sys.exit('INPUTS_TOO_LARGE')
        parts.append('--- INPUT %s ---\n%s\n--- END INPUT ---' % (rel, data.decode('utf-8', 'replace')))
    parts.append('Finish per rule 5 now.')
    return '\n'.join(parts) + '\n'


# ---------------------------------------------------------------- commands
def cmd_init(a):
    if (ROOT / 'state.json').exists():
        sys.exit('ALREADY_INITIALIZED')
    env = load_env()
    for k in ('PI_BIN', 'SANDBOX_EXEC', 'PI_PROFILE', 'REVIEW_PROFILE'):
        v = env.get(k, '')
        if not v.startswith('/') or os.path.islink(v) or not os.path.exists(v):
            sys.exit('ENV_BAD %s=%r (absolute existing non-symlink required)' % (k, v))
    parent = pathlib.Path(a.parent).resolve()
    inv = inventory(parent)
    h = inv_hash(inv)
    if a.expected_entries is not None and len(inv) != a.expected_entries:
        sys.exit('PARENT_ENTRY_COUNT %d != %d' % (len(inv), a.expected_entries))
    if a.expected_hash and h != a.expected_hash:
        sys.exit('PARENT_HASH_MISMATCH')
    st = {'launches_used': a.launches_used, 'active_seconds': a.active_seconds, 'parent_dir': str(parent),
          'parent_hash': h, 'cards': {}, 'reviews': [], 'reviewer_backend': 'codex', 'pending_findings': [],
          'review_subjects': [], 'milestone': 'OPEN', 'review_seq': 0,
          'orch_hash': inv_hash(orch_source_inventory()), 'source_reviews': {}, 'smokes': {}}
    cards = load_cards()
    for cid in cards:
        st['cards'][cid] = {'status': 'PENDING', 'attempts': 0}
    save_state(st)
    append_ledger({'event': 'init', 'parent_hash': h, 'entries': len(inv), 'cards': sorted(cards)})
    print('INIT_OK parent_hash=%s entries=%d cards=%d' % (h, len(inv), len(cards)))


def cmd_status(a):
    print(json.dumps(load_state(), sort_keys=True, indent=1))


def cmd_rebind_orch(a):
    """After a root-authored orchestration fix: bind the new source hash. Acceptance needs a fresh source review."""
    with Lock():
        st = load_state()
        old, new = st['orch_hash'], inv_hash(orch_source_inventory())
        if old == new:
            print('ORCH_UNCHANGED ' + new)
            return
        st['orch_hash'] = new
        save_state(st)
        append_ledger({'event': 'rebind_orch', 'old': old, 'new': new})
        print('ORCH_REBOUND %s -> %s (source review required again)' % (old[:12], new[:12]))


def cmd_backfill_review(a):
    """Re-parse a retained review receipt into state.last_review (for reviews run before persistence existed)."""
    with Lock():
        st = load_state()
        rec = [r for r in st['reviews'] if r['seq'] == a.seq]
        if len(rec) != 1:
            sys.exit('REVIEW_SEQ_UNKNOWN')
        outp = ROOT / 'evidence' / ('review-%03d' % a.seq) / 'run' / 'receipt.json.out'
        if not outp.is_file() or outp.is_symlink():
            sys.exit('REVIEW_EVIDENCE_MISSING')
        out = outp.read_text()
        v = parse_verdict(out)
        if v is None or [f['id'] for f in v['findings']] != rec[0]['findings']:
            sys.exit('REVIEW_EVIDENCE_MISMATCH')
        st['last_review'] = {'seq': a.seq, 'scope': rec[0]['scope'], 'revision': v['revision'],
                             'verdict': {k: v[k] for k in ('revision', 'findings', 'missing_evidence', 'coverage',
                                                           'cleanup', 'verdict')}, 'backfilled_from': str(outp),
                             'out_sha': sha_bytes(out.encode())}
        save_state(st)
        append_ledger({'event': 'backfill_review', 'seq': a.seq, 'out_sha': st['last_review']['out_sha']})
        print('REVIEW_BACKFILLED seq=%d findings=%d' % (a.seq, len(v['findings'])))


def cmd_set_parent(a):
    """Point future cards at a newer frozen tree. Refused while any card is mid-flight."""
    with Lock():
        st = load_state()
        busy = [k for k, v in st['cards'].items() if v['status'] in ('RESERVED', 'E2E_PASS', 'REVIEW_FINDINGS')]
        if busy:
            sys.exit('SET_PARENT_BLOCKED mid-flight cards: %s' % busy)
        d = pathlib.Path(a.dir)
        if not d.is_absolute() or d.is_symlink() or not d.is_dir():
            sys.exit('PARENT_INVALID')
        new = inv_hash(inventory(d))
        append_ledger({'event': 'set_parent', 'old': st['parent_hash'], 'new': new, 'dir': str(d)})
        st['parent_dir'], st['parent_hash'] = str(d), new
        save_state(st)
        print('PARENT_SET %s' % new)


def cmd_note_interval(a):
    """Record root-authored active time that no launch receipt covers. Only ever adds time."""
    with Lock():
        st = load_state()
        if not (0 < a.seconds <= 36000):
            sys.exit('INTERVAL_INVALID')
        st['active_seconds'] += a.seconds
        save_state(st)
        append_ledger({'event': 'root_interval', 'seconds': a.seconds, 'basis': a.basis,
                       'start_wall': a.start_wall, 'end_wall': a.end_wall})
        print('INTERVAL_NOTED active=%.3f remaining=%.3f' % (st['active_seconds'],
                                                             LIMITS['time_ceiling'] - st['active_seconds']))


def cmd_read_receipt(a):
    print(json.dumps(read_bounded_json(a.file, LIMITS['receipt_cap']), sort_keys=True))


def fail_attempt(st, cid, why):
    cs = st['cards'][cid]
    cs['status'] = 'NEEDS_REPLAN' if cs['attempts'] >= LIMITS['max_attempts'] else 'FAILED'
    cs['last_failure'] = why
    save_state(st)
    append_ledger({'event': 'attempt_failed', 'card': cid, 'attempt': cs['attempts'], 'why': why})
    sys.stderr.write('ATTEMPT_FAILED %s: %s -> %s\n' % (cid, why, cs['status']))
    sys.exit(1)


def cmd_retire_card(a):
    """Root-authored retirement of a card back to NEEDS_REPLAN (e.g. planner defect found before launch)."""
    if not a.reason or not a.reason.strip():
        sys.exit('RETIRE_NEEDS_REASON')
    with Lock():
        st = load_state()
        cs = st['cards'].get(a.id)
        if not cs:
            sys.exit('UNKNOWN_CARD')
        if cs['status'] not in ('PENDING', 'FAILED'):
            sys.exit('RETIRE_BLOCKED status=' + cs['status'])
        cs['status'] = 'NEEDS_REPLAN'
        cs['retired_reason'] = a.reason
        save_state(st)
        append_ledger({'event': 'retire_card', 'card': a.id, 'reason': a.reason})
        print('CARD_RETIRED %s -> NEEDS_REPLAN (replan must replace it)' % a.id)


def cmd_run_card(a):
    env = load_env()
    with Lock() as L:
        st = load_state()
        cards = load_cards()
        if a.id not in cards:
            sys.exit('UNKNOWN_CARD')
        c = cards[a.id]
        cs = st['cards'].setdefault(a.id, {'status': 'PENDING', 'attempts': 0})
        if cs['status'] not in ('PENDING', 'FAILED'):
            sys.exit('CARD_NOT_RUNNABLE status=' + cs['status'])
        if cs['attempts'] >= LIMITS['max_attempts']:
            sys.exit('ATTEMPTS_EXHAUSTED: replan required')
        for d in c['depends_on']:
            if not dep_satisfied(st, d):
                sys.exit('DEPENDENCY_NOT_ACCEPTED ' + d)
        if env.get('PI_GUARDIAN'):
            guardian_bindings(env)
        base_id = c.get('base')
        if base_id:
            bs = st['cards'].get(base_id, {})
            if not bs.get('tree'):
                sys.exit('BASE_TREE_MISSING ' + base_id)
            base_dir, base_hash = bs['tree'], bs['tree_hash']
        else:
            base_dir, base_hash = st['parent_dir'], st['parent_hash']
        parent_inv = inventory(base_dir)
        if inv_hash(parent_inv) != base_hash:
            sys.exit('PARENT_HASH_MISMATCH')
        if not check_auth_clean(env):
            uncertain_stop(L, st)
        slot_gate(st)
        time_gate(st, LIMITS['code_need'])
        attempt = cs['attempts'] + 1
        reserve_slot(st, a.id, attempt)
        cs['attempts'] = attempt
        cs['status'] = 'RESERVED'
        save_state(st)
        job_timeout = min(c['timeout'], LIMITS['job_timeout'])
        if env.get('PI_GUARDIAN'):
            # Real-credential route: the job tree MUST live under PI_RUNTIME (the pi profile denies reads/writes
            # elsewhere under /Users/psac); the worker runs via the guardian with auth_source=real.
            job = pathlib.Path(env['PI_RUNTIME']) / 'jobs' / ('%s-%d' % (a.id, attempt))
            if job.exists():
                fail_attempt(st, a.id, 'JOB_DIR_EXISTS ' + str(job))
            job.mkdir(parents=True, mode=0o700)
            tree = job / 'tree'
            shutil.copytree(base_dir, tree)
            prompt = job / 'prompt.txt'
            prompt.write_text(assemble_prompt(dict(c), dict(st, parent_hash=base_hash), base_dir))
            append_ledger({'event': 'prompt', 'card': a.id, 'attempt': attempt, 'sha': sha(prompt)})
            spec = coding_spec(env, tree, prompt, job / 'guardian', job_timeout)
            jwrite(job / 'spec.json', spec)
            append_ledger({'event': 'guardian_spec', 'card': a.id, 'attempt': attempt, 'sha': sha(job / 'spec.json'),
                           'output': str(job / 'guardian')})
            rec, _ = launch(L, st, '%s/%d/code' % (a.id, attempt),
                            [env['BOOT_PYTHON'], '-B', env['PI_GUARDIAN'], str(job / 'spec.json')],
                            job_timeout + 30, 1 << 20, str(job), stdin_pipe=True)
            if rec is None:
                uncertain_stop(L, st, a.id)
            if rec['status'] != 'ok' or not rec.get('reaped'):
                uncertain_stop(L, st, a.id)
            gp = job / 'guardian' / 'receipt.json'
            g = None
            if gp.is_file() and not gp.is_symlink():
                try:
                    g = read_bounded_json(gp, LIMITS['receipt_cap'])
                except SystemExit:
                    g = None
            append_ledger({'event': 'guardian_receipt', 'card': a.id, 'attempt': attempt,
                           'status': None if g is None else g.get('status'),
                           'worker_reaped': None if g is None else g.get('worker_reaped'),
                           'exit_code': None if g is None else g.get('exit_code'),
                           'credential_removed': None if g is None else g.get('credential_removed'),
                           'reason': None if g is None else g.get('reason')})
            if g is None or g.get('status') != 'TERMINATED' or g.get('worker_reaped') is not True \
                    or g.get('credential_removed') is not True or g.get('exit_code') != 0:
                uncertain_stop(L, st, a.id)      # never interpret a missing/bad receipt as "zero children"
            gout = job / 'guardian' / 'stdout'
            out = gout.read_bytes()[:LIMITS['cap_bytes']].decode('utf-8', 'replace') if gout.is_file() else ''
        else:
            job = ROOT / 'jobs' / ('%s-%d' % (a.id, attempt))
            if job.exists():
                fail_attempt(st, a.id, 'JOB_DIR_EXISTS ' + str(job))
            job.mkdir(parents=True, mode=0o700)
            tree = job / 'tree'
            shutil.copytree(base_dir, tree)
            prompt = job / 'prompt.txt'
            prompt.write_text(assemble_prompt(dict(c), dict(st, parent_hash=base_hash), base_dir))
            append_ledger({'event': 'prompt', 'card': a.id, 'attempt': attempt, 'sha': sha(prompt)})
            rec, out = launch(L, st, '%s/%d/code' % (a.id, attempt),
                              ['/bin/bash', str(ROOT / 'worker-pi.sh'), 'code', str(tree), str(prompt), env['PI_PROFILE']],
                              job_timeout, LIMITS['cap_bytes'], str(tree))
            if rec is None:
                uncertain_stop(L, st, a.id)
            if rec['status'] == 'uncertain':
                uncertain_stop(L, st, a.id)
            if rec['status'] != 'ok':
                fail_attempt(st, a.id, 'worker-' + rec['status'])
        if ('CARD_BLOCKED %s' % a.id) in out:
            fail_attempt(st, a.id, 'worker reported CARD_BLOCKED')
        if ('CARD_DONE %s' % a.id) not in out:
            fail_attempt(st, a.id, 'missing CARD_DONE')
        if not check_auth_clean(env):
            uncertain_stop(L, st, a.id)
        try:
            new_inv = inventory(tree)
        except SystemExit as e:
            fail_attempt(st, a.id, str(e))
        ok, probs = scope_verify(parent_inv, new_inv, set(c['allowed_paths']))
        if not ok:
            fail_attempt(st, a.id, 'scope: ' + '; '.join(probs))
        if inv_hash(new_inv) == inv_hash(parent_inv):
            fail_attempt(st, a.id, 'no change produced')
        manifest = {'card': a.id, 'attempt': attempt, 'parent_hash': base_hash, 'inventory': new_inv,
                    'tree_hash': inv_hash(new_inv)}
        jwrite(job / 'result-manifest.json', manifest)
        e = c['e2e']
        t = int(e.get('timeout', 20))
        rec2, _ = launch(L, st, '%s/%d/e2e' % (a.id, attempt), list(e['argv']), min(t, 200), 1 << 20, str(tree))
        if rec2 is None or rec2['status'] == 'uncertain':
            uncertain_stop(L, st, a.id)
        if not rec2['reaped'] or rec2.get('exit') != e['expect_status'] or rec2['status'] in ('timeout', 'overflow'):
            fail_attempt(st, a.id, 'e2e status %s/%s' % (rec2['status'], rec2.get('exit')))
        for f in e.get('expect_files', []):
            if not (tree / f).is_file():
                fail_attempt(st, a.id, 'e2e missing file ' + f)
        cs.update(status='E2E_PASS', tree=str(tree), tree_hash=manifest['tree_hash'])
        save_state(st)
        print('E2E_PASS %s attempt=%d tree_hash=%s' % (a.id, attempt, manifest['tree_hash']))


# ---------------------------------------------------------------- review / plan
def text_candidates(raw):
    cands = [raw]

    def walk(x):
        if isinstance(x, str):
            cands.append(x)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)
    for chunk in [raw] + raw.splitlines():
        try:
            walk(json.loads(chunk))
        except ValueError:
            pass
    return cands


def extract_block(raw):
    blocks = set()
    for t in text_candidates(raw):
        for m in re.findall(r'```json\s*(\{.*?\})\s*```', t, re.S):
            blocks.add(m)
    if len(blocks) != 1:
        return None
    try:
        return strict_json(next(iter(blocks)))
    except ValueError:
        return None


UNAVAILABLE_MARKERS = ('usage limit', 'rate limit', 'quota', 'not logged in', 'unauthorized', 'authentication')


def provider_error(raw):
    """Codex emits JSONL {'type':'error'|'turn.failed'}; Claude emits one object with is_error/result."""
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get('type') in ('error', 'turn.failed'):
            err = ev.get('error') if isinstance(ev.get('error'), dict) else {}
            return str(ev.get('message') or err.get('message') or ev.get('type'))
        if ev.get('type') == 'result' and ev.get('is_error'):
            return str(ev.get('result') or 'is_error')
    return None


def provider_stop(st, label, msg):
    """Classify a provider-side failure: unavailable (75) versus other provider error (74). Never a fallback."""
    append_ledger({'event': 'provider_failed', 'label': label, 'message': msg[:300]})
    save_state(st)
    if any(m in msg.lower() for m in UNAVAILABLE_MARKERS):
        sys.stderr.write('BLOCKED_PROVIDER_UNAVAILABLE: %s\n' % msg[:300])
        sys.exit(75)
    sys.stderr.write('PROVIDER_ERROR: %s\n' % msg[:300])
    sys.exit(74)


def parse_verdict(raw):
    v = extract_block(raw)
    if v is None:
        return None
    need = {'revision', 'findings', 'missing_evidence', 'coverage', 'cleanup', 'verdict'}
    if set(v) != need or v['verdict'] not in ('ACCEPTED', 'INCOMPLETE', 'BLOCKED'):
        return None
    if not isinstance(v['findings'], list) or not isinstance(v['missing_evidence'], list) \
            or not isinstance(v['coverage'], dict):
        return None
    for f in v['findings']:
        if not isinstance(f, dict) or not isinstance(f.get('id'), str):
            return None
    if v['coverage'].get('complete') is not True or v['coverage'].get('truncated') is not False:
        v['verdict'] = 'INCOMPLETE' if v['verdict'] == 'ACCEPTED' else v['verdict']
        v['_coverage_bad'] = True
    if v['findings'] or v['missing_evidence']:
        v['verdict'] = 'INCOMPLETE' if v['verdict'] == 'ACCEPTED' else v['verdict']
    return v


def run_model(L, st, env, label, role, prompt_text, backend, timeout=None):
    """One model invocation with a private runtime (proven route: private CODEX_HOME/TMPDIR under the writable
    evidence subtree; auth.json is a SYMLINK to the real credential, created just before launch and unlinked after)."""
    d = ROOT / 'evidence' / label
    d.mkdir(parents=True, exist_ok=False)
    pf = d / 'packet.txt'
    pf.write_text(prompt_text)
    ws = d / 'ws'
    ws.mkdir(mode=0o700)
    rt = d / 'runtime'
    for sub in ('codex', 'tmp', 'claude'):
        (rt / sub).mkdir(parents=True, mode=0o700)
    extra = {'REVIEW_BACKEND': backend, 'TMPDIR': str(rt / 'tmp')}
    auth_link = None
    if backend == 'codex':
        extra['CODEX_HOME'] = str(rt / 'codex')
        real = pathlib.Path.home() / '.codex' / 'auth.json'
        if real.is_file():
            auth_link = rt / 'codex' / 'auth.json'
            os.symlink(real, auth_link)            # never a copy; the sandbox denies writes to the real file
    else:
        extra.update(DISABLE_AUTOUPDATER='1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
        # Private config dir => CLI reports "Not logged in" (observed). CLAUDE_REAL_CONFIG=1 keeps the real
        # config dir untouched; the strict review profile stays authoritative either way and already permitted
        # every write the real-config route needed (review-004/005, plan-008) - it was never widened (F7).
        if env.get('CLAUDE_REAL_CONFIG') != '1':
            extra['CLAUDE_CONFIG_DIR'] = str(rt / 'claude')
    try:
        res = launch(L, st, label + '/run',
                     ['/bin/bash', str(ROOT / 'worker-claude.sh'), role, str(ws), str(pf), env['REVIEW_PROFILE']],
                     timeout or LIMITS['review_timeout'], 1 << 20, str(ws), extra)
    finally:
        if auth_link is not None:
            try:
                os.unlink(auth_link)
            except FileNotFoundError:
                pass
            if os.path.lexists(auth_link):
                L.keep = True
                append_ledger({'event': 'credential_residue', 'label': label})
                sys.exit('CREDENTIAL_RESIDUE: %s still present; lock retained' % auth_link)
        append_ledger({'event': 'credential_lifecycle', 'label': label, 'backend': backend,
                       'symlink_used': auth_link is not None, 'removed': True})
    return pf, res


def build_packet(st, scope, subject_tree, revision, subjects):
    lines = ['ROLE: REVIEWER', 'SCOPE: %s' % scope, 'REVISION: %s' % revision,
             'NO TOOLS: you cannot read files or run commands; everything is inline. Do not emit tool calls.',
             'You are an independent reviewer. Do not edit or execute. Return exactly ONE fenced json block with keys '
             'revision, findings[{id,severity,location,evidence}], missing_evidence[], coverage{complete,truncated}, '
             'cleanup, verdict (ACCEPTED|INCOMPLETE|BLOCKED). ACCEPTED requires zero findings and zero missing evidence.',
             'ACCOUNTING: launches_used=%d/%d active_seconds=%.1f/%.0f' % (
                 st['launches_used'], LIMITS['cap_launches'], st['active_seconds'], LIMITS['time_ceiling'])]
    inv = inventory(subject_tree)
    lines.append('INVENTORY:')
    lines += ['  %s %s %d %s' % tuple(r) for r in inv]
    total = 0
    for r in inv:
        data = (pathlib.Path(subject_tree) / r[0]).read_bytes()
        total += len(data)
        if total > LIMITS['packet_cap']:
            sys.exit('PACKET_TOO_LARGE: indexed review parts are not implemented; split scope')
        lines.append('--- FILE %s ---\n%s\n--- END FILE ---' % (r[0], data.decode('utf-8', 'replace')))
    for s in subjects:
        lines.append('PRIOR_DISPOSITIONS: ' + json.dumps(s))
    return '\n'.join(lines) + '\n'


def cmd_review(a):
    env = load_env()
    with Lock() as L:
        st = load_state()
        if a.backend:
            st['reviewer_backend'] = a.backend
        if st['pending_findings']:
            sys.exit('UNDISPOSED_FINDINGS: replan must disposition %s' % st['pending_findings'])
        time_gate(st, LIMITS['review_need'])
        if a.smoke and not a.subject:
            sys.exit('SMOKE_NEEDS_SUBJECT')
        if a.subject and a.card:
            sys.exit('SUBJECT_AND_CARD_EXCLUSIVE')
        if a.subject:
            sd = pathlib.Path(a.subject)
            if not sd.is_absolute() or sd.is_symlink() or not sd.is_dir():
                sys.exit('SUBJECT_INVALID')
            name = a.name or sd.name
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}', name):
                sys.exit('SUBJECT_NAME_INVALID')
            tree, revision = str(sd), inv_hash(inventory(sd))
            scope = ('smoke:' if a.smoke else 'source:') + name
        elif a.card:
            cs = st['cards'].get(a.card)
            if not cs or cs['status'] != 'E2E_PASS':
                sys.exit('CARD_NOT_REVIEWABLE')
            tree, revision = cs['tree'], cs['tree_hash']
            scope = 'card:' + a.card
        else:
            open_cards = [k for k, v in st['cards'].items() if v['status'] not in ('ACCEPTED', 'SUPERSEDED')]
            if open_cards:
                sys.exit('FINAL_REVIEW_BLOCKED open cards: %s' % open_cards)
            tree, revision, scope = st['parent_dir'], st['parent_hash'], 'final'
        st['review_seq'] += 1
        save_state(st)
        label = 'review-%03d' % st['review_seq']
        if a.packet:
            pf = pathlib.Path(a.packet)
            if not pf.is_file() or pf.is_symlink() or sha(pf) != a.sha:
                sys.exit('PACKET_HASH_MISMATCH')
            text = pf.read_text()
        else:
            text = build_packet(st, scope, tree, revision, st['reviews'][-3:] and [
                {'id': r['seq'], 'verdict': r['verdict']} for r in st['reviews'][-3:]])
        if a.smoke:
            text += ('SMOKE: this is a transport smoke. In the "cleanup" field write the string "MODEL=<your model '
                     'name>" so provenance can be checked. Keep the response under 2000 characters.\n')
        pf, (rec, out) = run_model(L, st, env, label, 'review', text, st['reviewer_backend'],
                                   LIMITS['smoke_timeout'] if a.smoke else None)
        append_ledger({'event': 'review_packet', 'label': label, 'sha': sha(pf), 'scope': scope})
        if rec is None or rec['status'] == 'uncertain':
            uncertain_stop(L, st)
        if rec.get('exit') == 75:
            save_state(st)
            sys.stderr.write('BLOCKED_PROVIDER_UNAVAILABLE: no fallback model is permitted\n')
            sys.exit(75)
        perr = provider_error(out)
        if perr:
            provider_stop(st, label, perr)
        if rec['status'] != 'ok':
            save_state(st)
            sys.exit('REVIEW_TRANSPORT_FAILED ' + rec['status'])
        v = parse_verdict(out)
        if v is None:
            save_state(st)
            sys.exit('REVIEW_MALFORMED: no acceptance; a fresh review is required')
        if v['revision'] != revision:
            save_state(st)
            sys.exit('REVIEW_REVISION_MISMATCH')
        if a.smoke:   # transport proven; never touches acceptance state
            st['smokes'][name] = {'backend': st['reviewer_backend'], 'exit': rec.get('exit'), 'elapsed': rec['elapsed'],
                                  'out_sha': sha_bytes(out.encode()), 'verdict': v['verdict'],
                                  'cleanup': str(v.get('cleanup'))[:200], 'label': label}
            save_state(st)
            append_ledger({'event': 'smoke', 'name': name, 'backend': st['reviewer_backend'], 'label': label})
            print('SMOKE_OK %s backend=%s cleanup=%s' % (name, st['reviewer_backend'], str(v.get('cleanup'))[:200]))
            return
        accepted = (v['verdict'] == 'ACCEPTED' and not v['findings'] and not v['missing_evidence']
                    and not v.get('_coverage_bad'))
        st['last_review'] = {'seq': st['review_seq'], 'scope': scope, 'revision': revision,
                             'verdict': {k: v[k] for k in ('revision', 'findings', 'missing_evidence', 'coverage',
                                                           'cleanup', 'verdict')}}
        st['reviews'].append({'seq': st['review_seq'], 'scope': scope, 'backend': st['reviewer_backend'],
                              'verdict': 'ACCEPTED' if accepted else (v['verdict'] if v['verdict'] != 'ACCEPTED' else 'INCOMPLETE'),
                              'findings': [f['id'] for f in v['findings']], 'missing': len(v['missing_evidence']),
                              'packet_sha': sha(pf)})
        if accepted:
            if a.subject:
                st['source_reviews'][name] = revision
            elif a.card:
                cs['status'] = 'ACCEPTED'
                st['parent_dir'], st['parent_hash'] = tree, revision
            else:
                st['milestone'] = 'ACCEPTED'
            save_state(st)
            print('REVIEW_ACCEPTED ' + scope)
            return
        ids = [f['id'] for f in v['findings']] + ['M%d' % i for i in range(len(v['missing_evidence']))]
        if not ids:
            ids = ['COVERAGE']
        st['pending_findings'] = ids
        st['review_subjects'] = [a.card] if a.card else []
        if a.card:
            st['cards'][a.card]['status'] = 'REVIEW_FINDINGS'
        save_state(st)
        sys.stderr.write('REVIEW_NOT_ACCEPTED findings=%s\n' % ids)
        sys.exit(2)


def cmd_replan(a):
    env = load_env()
    with Lock() as L:
        st = load_state()
        other = 'fable' if st['reviewer_backend'] == 'codex' else 'codex'
        backend = a.backend or other
        if backend == st['reviewer_backend']:
            if not a.same_backend_approved:
                sys.exit('PLANNER_MUST_DIFFER from reviewer backend (pass --same-backend-approved "<who/when>")')
            st.setdefault('same_backend_approvals', []).append(
                {'backend': backend, 'approval': a.same_backend_approved, 'review_seq': st['review_seq'],
                 'wall': time.time()})
            append_ledger({'event': 'same_backend_approval', 'backend': backend, 'approval': a.same_backend_approved})
        time_gate(st, LIMITS['review_need'])
        subjects = [k for k, v in st['cards'].items() if v['status'] in ('REVIEW_FINDINGS', 'NEEDS_REPLAN')]
        if not st['pending_findings'] and not subjects:
            sys.exit('NOTHING_TO_REPLAN')
        existing = load_cards()
        inv = inventory(st['parent_dir'])
        e2e_src = pathlib.Path(st['parent_dir']) / 'e2e' / 'run_e2e.py'
        try:
            e2e_ids = sorted(set(re.findall(r'^def (O\d+)\b', e2e_src.read_text(), re.M))) if e2e_src.is_file() else []
        except OSError:
            e2e_ids = []
        example = {'id': 'X1', 'objective': 'one-line concern', 'depends_on': [], 'allowed_paths': ['loop.py'],
                   'acceptance_rows': ['R1 ...'], 'stop_condition': 'print CARD_BLOCKED if ...',
                   'e2e': {'argv': ['/usr/bin/python3', '-B', 'e2e/run_e2e.py', 'O01'], 'expect_status': 0,
                           'expect_files': []}, 'timeout': 600}
        prompt = '\n'.join([
            'ROLE: PLANNER',
            'NO TOOLS: you cannot read files, list directories or run commands. Everything you need is in this packet. '
            'Do not emit tool calls; answer with text only.',
            'Emit ONE fenced json block {"cards":[...],"dispositions":{...}} (<=4 cards).',
            'EXAMPLE_CARD: ' + json.dumps(example, sort_keys=True),
            'PARENT_TREE (cards edit paths relative to this tree; e2e argv runs with cwd=tree, no shell):',
            ] + ['  %s %s %d %s' % tuple(r) for r in inv] + [
            'REVIEW_JSON: ' + json.dumps(st.get('last_review'), sort_keys=True),
            'Each card keys: id,objective(one line),depends_on,allowed_paths(1-3 relative),acceptance_rows,'
            'stop_condition,e2e{argv,expect_status,expect_files},timeout(<=600); optional base,replaces. One concern per card.',
            'No placeholders. Every finding id needs a disposition: card:<id> | rejected:<why> | deferred:<why>.',
            'EXISTING_E2E_IDS: ' + ','.join(e2e_ids),
            'Any e2e scenario id a new card references (in e2e.argv or acceptance rows) must NOT be in '
            'EXISTING_E2E_IDS; pick fresh ids larger than every listed id.',
            'FINDING_IDS: ' + ','.join(st['pending_findings']), 'REPLACES: ' + ','.join(subjects),
            'EXISTING_CARD_IDS: ' + ','.join(sorted(existing)),
            'BUDGET: launches_used=%d/%d active=%.1f/%.0f' % (st['launches_used'], LIMITS['cap_launches'],
                                                             st['active_seconds'], LIMITS['time_ceiling']),
            'PARENT_HASH: ' + st['parent_hash'], RULES])
        st['review_seq'] += 1
        save_state(st)
        pf, (rec, out) = run_model(L, st, env, 'plan-%03d' % st['review_seq'], 'plan', prompt, backend)
        if rec is None or rec['status'] == 'uncertain':
            uncertain_stop(L, st)
        if rec.get('exit') == 75:
            save_state(st)
            sys.stderr.write('BLOCKED_PROVIDER_UNAVAILABLE\n')
            sys.exit(75)
        perr = provider_error(out)
        if perr:
            provider_stop(st, 'plan-%03d' % st['review_seq'], perr)
        if rec['status'] != 'ok':
            save_state(st)
            sys.exit('PLANNER_TRANSPORT_FAILED ' + rec['status'])
        plan = extract_block(out)
        if not isinstance(plan, dict) or set(plan) != {'cards', 'dispositions'} or not isinstance(plan['cards'], list) \
                or not 1 <= len(plan['cards']) <= 4 or not isinstance(plan['dispositions'], dict):
            save_state(st)
            sys.exit('PLAN_MALFORMED')
        new = {}
        for c in plan['cards']:
            err = validate_card(c)
            if err:
                save_state(st)
                sys.exit('PLAN_CARD_INVALID: ' + str(err))
            if c['id'] in existing or c['id'] in new:
                save_state(st)
                sys.exit('PLAN_CARD_DUPLICATE ' + c['id'])
            new[c['id']] = c
        allc = dict(existing, **new)
        for c in new.values():
            for d in c['depends_on'] + ([c['base']] if c.get('base') else []):
                if d not in allc:
                    sys.exit('PLAN_UNKNOWN_DEP ' + d)
        if not check_acyclic(allc):
            sys.exit('PLAN_CYCLE')
        for fid in st['pending_findings']:
            disp = plan['dispositions'].get(fid)
            if not isinstance(disp, str) or not re.fullmatch(r'(card:[A-Za-z0-9_-]+|rejected:.+|deferred:.+)', disp):
                sys.exit('PLAN_MISSING_DISPOSITION ' + fid)
            if disp.startswith('card:') and disp[5:] not in new:
                sys.exit('PLAN_DISPOSITION_UNKNOWN_CARD ' + disp)
        replaced = {}
        for c in new.values():
            if c.get('replaces'):
                replaced.setdefault(c['replaces'], []).append(c['id'])
        for s in subjects:
            if s not in replaced:
                sys.exit('PLAN_DOES_NOT_REPLACE ' + s)
        for k, ids in replaced.items():
            if k not in subjects:
                sys.exit('PLAN_REPLACES_NON_SUBJECT ' + k)
        for cid, c in new.items():
            jwrite(ROOT / 'cards' / (cid + '.json'), c)
            st['cards'][cid] = {'status': 'PENDING', 'attempts': 0}
        for k, ids in replaced.items():
            st['cards'][k].update(status='SUPERSEDED', superseded_by=ids)
        append_ledger({'event': 'replan', 'planner': backend, 'new_cards': sorted(new),
                       'dispositions': plan['dispositions']})
        st['dispositions'] = dict(st.get('dispositions', {}), **plan['dispositions'])
        st['pending_findings'] = []
        save_state(st)
        print('REPLAN_OK planner=%s new=%s' % (backend, sorted(new)))


# ---------------------------------------------------------------- handoff
REVIEW_TEMPLATE = """You are the independent final reviewer of review-worker adapter acceptance ONLY. You may not edit,
execute code, delegate, or infer runtime evidence from source closure. Read ALL inline material.
REVISION: {{revision}}
CARDS & DISPOSITIONS: {{cards}}
DISPOSITIONS: {{dispositions}}
ACCOUNTING: {{accounting}}
REVIEW HISTORY: {{reviews}}
SOURCE INVENTORY:
{{inventory}}
TASK: check correctness, regressions, provenance, process ownership, finite-failure contract, every acceptance
criterion. Zero findings with missing evidence is NOT acceptance. Return exactly ONE fenced json block with keys
revision, findings[{id,severity,location,evidence}], missing_evidence[], coverage{complete,truncated}, cleanup,
verdict (ACCEPTED|INCOMPLETE|BLOCKED). Output outside the block is ignored.
"""


def cmd_handoff(a):
    with Lock() as L:
        st = load_state()
        open_cards = [k for k, v in st['cards'].items() if v['status'] not in TERMINAL]
        if open_cards:
            sys.exit('HANDOFF_BLOCKED non-terminal cards: %s' % open_cards)
        live = inv_hash(orch_source_inventory())
        if live != st['orch_hash']:
            sys.exit('HANDOFF_BLOCKED orchestration source changed since init (%s != %s)' % (live[:12], st['orch_hash'][:12]))
        if st['orch_hash'] not in st['source_reviews'].values():
            sys.exit('HANDOFF_BLOCKED no accepted source review of the orchestration snapshot %s' % st['orch_hash'][:12])
        inv = inventory(st['parent_dir'])
        parts = [REVIEW_TEMPLATE]
        subst = {'revision': st['parent_hash'], 'cards': json.dumps(st['cards'], sort_keys=True),
                 'dispositions': json.dumps(st.get('dispositions', {}), sort_keys=True),
                 'accounting': 'launches %d/%d, active %.1f/%.0f s, remaining %.1f s' % (
                     st['launches_used'], LIMITS['cap_launches'], st['active_seconds'], LIMITS['time_ceiling'],
                     LIMITS['time_ceiling'] - st['active_seconds']),
                 'reviews': json.dumps({'reviews': st['reviews'], 'source_reviews': st['source_reviews'],
                                        'smokes': st['smokes'], 'orch_hash': st['orch_hash']}, sort_keys=True),
                 'inventory': '\n'.join('  %s %s %d %s' % tuple(r) for r in inv)}
        prompt = REVIEW_TEMPLATE
        for k, v in subst.items():
            prompt = prompt.replace('{{%s}}' % k, v)
        if '{{' in prompt:
            sys.exit('HANDOFF_UNFILLED_PLACEHOLDER')
        verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED' else (
            'BLOCKED' if any(v['status'] == 'BLOCKED_CLEANUP_UNCERTAIN' for v in st['cards'].values()) else 'INCOMPLETE')
        ledger = (ROOT / 'ledger.jsonl').read_text() if (ROOT / 'ledger.jsonl').exists() else ''
        text = '\n'.join(['HANDOFF-011', 'MILESTONE VERDICT: ' + verdict, 'REVISION: ' + st['parent_hash'],
                          'ACCOUNTING: ' + subst['accounting'], 'CARDS: ' + subst['cards'],
                          'LEDGER:', ledger, '=== FULL REVIEW PROMPT ===', prompt, '=== END ==='])
        out_dir = ROOT.parent
        (out_dir / 'HANDOFF-011.txt').write_text(text)
        jwrite(out_dir / 'RESULT-011.json', {'verdict': verdict, 'revision': st['parent_hash'],
                                              'launches_used': st['launches_used'], 'active_seconds': st['active_seconds'],
                                              'handoff_sha': sha_bytes(text.encode())})
        print(text)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('init'); p.add_argument('--parent', required=True)
    p.add_argument('--active-seconds', type=float, default=24923.746)
    p.add_argument('--launches-used', type=int, default=36)
    p.add_argument('--expected-hash'); p.add_argument('--expected-entries', type=int)
    p.set_defaults(f=cmd_init)
    sub.add_parser('status').set_defaults(f=cmd_status)
    sub.add_parser('rebind-orch').set_defaults(f=cmd_rebind_orch)
    p = sub.add_parser('note-interval'); p.add_argument('--seconds', type=float, required=True)
    p.add_argument('--basis', required=True); p.add_argument('--start-wall', type=float); p.add_argument('--end-wall', type=float)
    p.set_defaults(f=cmd_note_interval)
    p = sub.add_parser('read-receipt'); p.add_argument('file'); p.set_defaults(f=cmd_read_receipt)
    p = sub.add_parser('run-card'); p.add_argument('id'); p.set_defaults(f=cmd_run_card)
    p = sub.add_parser('retire-card'); p.add_argument('id'); p.add_argument('--reason', required=True)
    p.set_defaults(f=cmd_retire_card)
    p = sub.add_parser('review'); p.add_argument('--card'); p.add_argument('--backend', choices=['codex', 'fable'])
    p.add_argument('--packet'); p.add_argument('--sha')
    p.add_argument('--subject'); p.add_argument('--name'); p.add_argument('--smoke', action='store_true')
    p.set_defaults(f=cmd_review)
    p = sub.add_parser('replan'); p.add_argument('--backend', choices=['codex', 'fable'])
    p.add_argument('--same-backend-approved', help='explicit user approval text; required when planner == reviewer')
    p.set_defaults(f=cmd_replan)
    p = sub.add_parser('set-parent'); p.add_argument('dir'); p.set_defaults(f=cmd_set_parent)
    p = sub.add_parser('backfill-review'); p.add_argument('--seq', type=int, required=True); p.set_defaults(f=cmd_backfill_review)
    sub.add_parser('handoff').set_defaults(f=cmd_handoff)
    a = ap.parse_args()
    try:
        a.f(a)
    except KeyboardInterrupt:
        sys.stderr.write('INTERRUPTED: lock retained if a launch was in flight\n')
        sys.exit(130)


if __name__ == '__main__':
    main()
