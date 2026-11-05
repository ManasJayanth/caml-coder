#!/usr/bin/env python3
"""Workflow-loop driver. Stdlib only. Every gate fails closed; nothing 'continues anyway'."""
import argparse, hashlib, json, os, pathlib, re, shutil, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent
LIMITS = {'cap_launches': 48, 'time_ceiling': 32400.0, 'reserve': 180.0,
          'review_need': 780.0, 'job_timeout': 600, 'review_timeout': 600, 'cap_bytes': 2 * 1024 * 1024,
          'max_attempts': 3, 'packet_cap': 400 * 1024, 'inputs_cap': 200 * 1024, 'receipt_cap': 16384,
          'smoke_timeout': 120, 'e2e_timeout': 120, 'e2e_cap': 200, 'suite_timeout': 300,
          'max_worker_streak': 2, 'handoff_cap': 1 << 20}
# review_timeout 300->600 and review_need 480->780: PLAN 013 Decision 2 (review-012 ran 299.8/300 s on a 119 KB packet).
# Workers get a fixed env, never the supervisor's full environment (mirrors bootstrap/launch_worker.py).
ENV_ALLOW = ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'SHELL', 'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS')


def base_env():
    e = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
    for k in filter(None, os.environ.get('ORCH_ENV_PASSTHROUGH', '').split(',')):   # explicit, for E2E fakes only
        if k in os.environ:
            e[k] = os.environ[k]
    return e
TERMINAL = {'ACCEPTED', 'SUPERSEDED', 'NEEDS_REPLAN', 'BLOCKED_CLEANUP_UNCERTAIN'}


def ceiling(st):
    """Active-time ceiling in force: LIMITS default unless an operator allocation (allocate-time) raised it."""
    return float(st.get('time_ceiling', LIMITS['time_ceiling']))

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
    ../e2e/*.py, external/* (byte copies of out-of-tree review material). A frozen snapshot with this exact relative
    layout hashes identically (see `review --subject`)."""
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
    ext = ROOT / 'external'
    if ext.is_dir() and not ext.is_symlink():
        for p in sorted(ext.iterdir()):
            if p.is_symlink():
                raise SystemExit('SYMLINK_IN_TREE ' + str(p))
            if p.is_file():
                rows.append(['external/' + p.name, oct(p.stat().st_mode & 0o777), p.stat().st_size, sha(p)])
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
    avail = ceiling(st) - st['active_seconds']
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
    """Validate EVERY binding the guardian spec will carry (absolute, existing, non-symlink) before a slot is consumed."""
    for key, kind in (('PI_GUARDIAN', 'file'), ('PI_RUNTIME', 'dir'), ('BOOT_PYTHON', 'exe'), ('PI_BIN', 'exe'),
                      ('SANDBOX_EXEC', 'exe'), ('PI_PROFILE', 'file')):
        p = pathlib.Path(env.get(key) or '')
        if not str(p).startswith('/') or p.is_symlink() or not p.exists():
            sys.exit('%s_INVALID (absolute existing non-symlink %s required)' % (key, kind))
        if (kind == 'file' and not p.is_file()) or (kind == 'dir' and not p.is_dir()) \
                or (kind == 'exe' and not (p.is_file() and os.access(p, os.X_OK))):
            sys.exit('%s_INVALID' % key)


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


ID_RE = re.compile(r'\bO\d+[a-z]?(?:_O\d+[a-z]?)*\b')     # O55, O03a, O20_O21


def ids_of(text):
    """Scenario ids mentioned in text; a joined name like O20_O21 claims both parts."""
    return {part for m in ID_RE.findall(text) for part in m.split('_')}


def suite_e2e_ids(parent_dir):
    """Ids already defined by the parent tree's suite (def names, split on '_')."""
    p = pathlib.Path(parent_dir) / 'e2e' / 'run_e2e.py'
    out = set()
    try:
        names = re.findall(r'^def (O[0-9A-Za-z_]+)\s*\(', p.read_text(), re.M) if p.is_file() else []
    except OSError:
        names = []
    for n in names:
        out.add(n)
        out.update(ids_of(n))
    return out


def claimed_e2e_ids(st, cards):
    """Ids referenced by e2e.argv of every card that is not retired/superseded -> {id: [card ids]}."""
    out = {}
    for cid, c in cards.items():
        if st['cards'].get(cid, {}).get('status') in ('SUPERSEDED', 'NEEDS_REPLAN'):
            continue
        for i in sorted(ids_of(' '.join(c['e2e']['argv']))):
            out.setdefault(i, []).append(cid)
    return out


def e2e_id_collisions(c, suite_ids, claimed):
    mine = ids_of(' '.join(c['e2e']['argv']))
    return sorted(i for i in mine if i in suite_ids or (i in claimed and claimed[i] != [c['id']]))


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
    for k in ('PI_BIN', 'SANDBOX_EXEC', 'PI_PROFILE', 'REVIEW_PROFILE', 'BOOT_PYTHON'):
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
    claimed = claimed_e2e_ids(st, cards)
    dup = {i: v for i, v in claimed.items() if len(v) > 1}
    taken = sorted(i for i in claimed if i in suite_e2e_ids(parent))
    if dup or taken:
        sys.exit('CARD_E2E_ID_COLLISION claimed_twice=%s already_in_suite=%s' % (dup, taken))
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
                                                             ceiling(st) - st['active_seconds']))




def cmd_allocate_time(a):
    """Operator-recorded raise of the active-time ceiling. Only ever raises; never silent; ledgered with the approval text."""
    if not (a.approval or '').strip():
        sys.exit('ALLOCATION_NEEDS_APPROVAL (who/when/words)')
    with Lock():
        st = load_state()
        cur = ceiling(st)
        if not (cur < a.ceiling <= cur + 86400):
            sys.exit('ALLOCATION_INVALID: ceiling must be > %.1f and at most %.1f (one step <= 86400 s)' % (cur, cur + 86400))
        st['time_ceiling'] = float(a.ceiling)
        st.setdefault('allocations', []).append({'old': cur, 'new': float(a.ceiling), 'approval': a.approval,
                                                 'active_at_allocation': st['active_seconds'], 'wall': time.time()})
        save_state(st)
        append_ledger({'event': 'allocate_time', 'old': cur, 'new': float(a.ceiling), 'approval': a.approval})
        print('ALLOCATED ceiling=%.1f active=%.3f remaining=%.3f' % (a.ceiling, st['active_seconds'],
                                                                     a.ceiling - st['active_seconds']))


def cmd_read_receipt(a):
    print(json.dumps(read_bounded_json(a.file, LIMITS['receipt_cap']), sort_keys=True))




def cmd_clear_lock(a):
    """Root-authored release of a lock retained by an uncertainty stop, AFTER manual inspection. Refuses while the
    locking process is alive or a credential is still present. Cards stay BLOCKED_CLEANUP_UNCERTAIN until retired."""
    if not a.reason.strip():
        sys.exit('CLEAR_LOCK_NEEDS_REASON')
    env = load_env()
    lp = ROOT / 'lock'
    if not lp.exists():
        sys.exit('LOCK_NOT_HELD')
    if not check_auth_clean(env):
        sys.exit('CLEAR_LOCK_BLOCKED credential residue in AUTH_DIR; remove it by hand and record why')
    pid = lp.read_text().strip()
    try:
        os.kill(int(pid), 0)
        sys.exit('CLEAR_LOCK_BLOCKED process %s still alive' % pid)
    except (ProcessLookupError, ValueError):
        pass
    except PermissionError:
        sys.exit('CLEAR_LOCK_BLOCKED process %s exists (permission denied)' % pid)
    append_ledger({'event': 'clear_lock', 'reason': a.reason, 'lock_pid': pid})
    os.unlink(lp)
    print('LOCK_CLEARED (was pid %s); uncertain cards stay BLOCKED_CLEANUP_UNCERTAIN until retire-card' % pid)


def fail_attempt(st, cid, why):
    cs = st['cards'][cid]
    cs['status'] = 'NEEDS_REPLAN' if cs['attempts'] >= LIMITS['max_attempts'] else 'FAILED'
    cs['last_failure'] = why
    save_state(st)
    append_ledger({'event': 'attempt_failed', 'card': cid, 'attempt': cs['attempts'], 'why': why})
    sys.stderr.write('ATTEMPT_FAILED %s: %s -> %s\n' % (cid, why, cs['status']))
    sys.exit(1)


def redirect_dispositions(st, old, new):
    for k, v in list(st.get('dispositions', {}).items()):
        if v == 'card:' + old:
            st['dispositions'][k] = 'card:' + new
            append_ledger({'event': 'disposition_redirect', 'finding': k, 'old': v, 'new': 'card:' + new})


def cmd_retire_card(a):
    """Root-authored retirement: -> NEEDS_REPLAN (a replan must replace it) or, with --superseded-by, -> SUPERSEDED by an
    existing live card (dispositions card:<retired> follow)."""
    if not a.reason or not a.reason.strip():
        sys.exit('RETIRE_NEEDS_REASON')
    with Lock():
        st = load_state()
        cs = st['cards'].get(a.id)
        if not cs:
            sys.exit('UNKNOWN_CARD')
        if cs['status'] not in ('PENDING', 'FAILED', 'BLOCKED_CLEANUP_UNCERTAIN'):
            sys.exit('RETIRE_BLOCKED status=' + cs['status'])
        cs['retired_reason'] = a.reason
        if a.superseded_by:
            ts = st['cards'].get(a.superseded_by)
            if a.superseded_by == a.id or not ts or ts['status'] in ('SUPERSEDED', 'NEEDS_REPLAN', 'BLOCKED_CLEANUP_UNCERTAIN'):
                sys.exit('RETIRE_SUPERSEDER_INVALID ' + str(a.superseded_by))
            cs['status'] = 'SUPERSEDED'
            cs['superseded_by'] = [a.superseded_by]
            redirect_dispositions(st, a.id, a.superseded_by)
        else:
            cs['status'] = 'NEEDS_REPLAN'
        save_state(st)
        append_ledger({'event': 'retire_card', 'card': a.id, 'reason': a.reason, 'superseded_by': a.superseded_by})
        print('CARD_RETIRED %s -> %s' % (a.id, cs['status'] + (' by ' + a.superseded_by if a.superseded_by else
                                                                ' (replan must replace it)')))


def cmd_add_card(a):
    """Root-authored card from a frontier plan file: validated exactly like a planner card, collision-checked, ledgered."""
    if not a.reason.strip() or not a.approval.strip():
        sys.exit('ADD_CARD_NEEDS_REASON_AND_APPROVAL')
    with Lock():
        st = load_state()
        existing = load_cards()
        p = pathlib.Path(a.file)
        if not p.is_file() or p.is_symlink():
            sys.exit('ADD_CARD_FILE_INVALID')
        c = read_bounded_json(p, 256 * 1024)
        err = validate_card(c)
        if err:
            sys.exit('CARD_INVALID: ' + err)
        if c['id'] in existing or c['id'] in st['cards']:
            sys.exit('CARD_DUPLICATE ' + c['id'])
        allc = dict(existing)
        allc[c['id']] = c
        for d in c['depends_on'] + ([c['base']] if c.get('base') else []):
            if d not in allc:
                sys.exit('CARD_UNKNOWN_DEP ' + d)
        if not check_acyclic(allc):
            sys.exit('CARD_CYCLE')
        coll = e2e_id_collisions(c, suite_e2e_ids(st['parent_dir']), claimed_e2e_ids(st, existing))
        if coll:
            sys.exit('CARD_E2E_ID_COLLISION %s' % coll)
        rep = c.get('replaces')
        if rep:
            rs = st['cards'].get(rep)
            if not rs or rs['status'] != 'NEEDS_REPLAN':
                sys.exit('ADD_CARD_REPLACES_INVALID %s (subject must be a retired NEEDS_REPLAN card)' % rep)
        dest = ROOT / 'cards' / (c['id'] + '.json')
        jwrite(dest, c)
        st['cards'][c['id']] = {'status': 'PENDING', 'attempts': 0, 'root_added': True}
        if rep:
            st['cards'][rep].update(status='SUPERSEDED', superseded_by=[c['id']])
            redirect_dispositions(st, rep, c['id'])
        append_ledger({'event': 'add_card', 'card': c['id'], 'sha': sha(dest), 'reason': a.reason, 'approval': a.approval,
                       'replaces': rep})
        save_state(st)
        print('CARD_ADDED %s' % c['id'])


def cmd_set_disposition(a):
    """Root-authored disposition. Only an absent or deferred: entry may change; values card:<live id> | root:<why> |
    deferred:<why> (deferred only for an absent key). Ledgered with the reason."""
    if not a.reason.strip():
        sys.exit('SET_DISPOSITION_NEEDS_REASON')
    with Lock():
        st = load_state()
        cur = st.get('dispositions', {}).get(a.key)
        if cur is not None and not cur.startswith('deferred:'):
            sys.exit('DISPOSITION_LOCKED %s=%s (only absent or deferred: values may be changed)' % (a.key, cur))
        if not re.fullmatch(r'(card:[A-Za-z0-9_-]+|root:.+|deferred:.+)', a.value, re.S) \
                or (a.value.startswith('deferred:') and cur is not None):
            sys.exit('DISPOSITION_VALUE_INVALID (card:<id> | root:<why> | deferred:<why> for a new key)')
        if a.value.startswith('card:'):
            cs = st['cards'].get(a.value[5:])
            if not cs or cs['status'] in ('SUPERSEDED', 'NEEDS_REPLAN', 'BLOCKED_CLEANUP_UNCERTAIN'):
                sys.exit('DISPOSITION_UNKNOWN_CARD ' + a.value)
        st.setdefault('dispositions', {})[a.key] = a.value
        save_state(st)
        append_ledger({'event': 'set_disposition', 'finding': a.key, 'old': cur, 'new': a.value, 'reason': a.reason})
        print('DISPOSITION_SET %s %s -> %s' % (a.key, cur, a.value))


def card_need(c):
    """Worst-case active seconds one run-card may consume: coding (+30 s guardian grace) + card e2e + full suite + reserve."""
    e2e_t = min(int(c['e2e'].get('timeout', LIMITS['e2e_timeout'])), LIMITS['e2e_cap'])
    return min(c['timeout'], LIMITS['job_timeout']) + 30 + e2e_t + LIMITS['suite_timeout'] + LIMITS['reserve']


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
        if st.get('worker_failure_streak', 0) >= LIMITS['max_worker_streak']:
            if not (a.acknowledge_streak or '').strip():
                sys.exit('WORKER_FAILURE_STREAK %d: inspect the last guardian/stdout and receipts for a provider outage; '
                         'pass --acknowledge-streak "<what you checked>" to continue' % st['worker_failure_streak'])
            append_ledger({'event': 'streak_acknowledged', 'streak': st['worker_failure_streak'], 'note': a.acknowledge_streak})
            st['worker_failure_streak'] = 0
            save_state(st)
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
        time_gate(st, card_need(c))
        attempt = cs['attempts'] + 1
        reserve_slot(st, a.id, attempt)
        cs['attempts'] = attempt
        cs['status'] = 'RESERVED'
        save_state(st)
        job_timeout = min(c['timeout'], LIMITS['job_timeout'])
        ev = ROOT / 'evidence' / a.id / str(attempt)
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
                    or g.get('credential_removed') is not True:
                uncertain_stop(L, st, a.id)      # cleanup unverified: never interpret a missing/bad receipt as "zero children"
            gout = job / 'guardian' / 'stdout'
            out = gout.read_bytes()[:LIMITS['cap_bytes']].decode('utf-8', 'replace') if gout.is_file() else ''
            if g.get('exit_code') != 0:          # cleanup verified, worker failed: an attempt failure, not uncertainty
                st['worker_failure_streak'] = st.get('worker_failure_streak', 0) + 1
                perr = provider_error(out)
                if perr:
                    append_ledger({'event': 'provider_failed', 'label': '%s/%d/code' % (a.id, attempt), 'message': perr[:300]})
                fail_attempt(st, a.id, 'worker-exit-%s%s' % (g.get('exit_code'), (': ' + perr[:120]) if perr else ''))
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
        st['worker_failure_streak'] = 0
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
        t = min(int(e.get('timeout', LIMITS['e2e_timeout'])), LIMITS['e2e_cap'])
        rec2, _ = launch(L, st, '%s/%d/e2e' % (a.id, attempt), list(e['argv']), t, 1 << 20, str(tree),
                         {'E2E_SUMMARY_DIR': str(ev / 'e2e-summary')})
        if rec2 is None or rec2['status'] == 'uncertain':
            uncertain_stop(L, st, a.id)
        if not rec2['reaped'] or rec2.get('exit') != e['expect_status'] or rec2['status'] in ('timeout', 'overflow'):
            fail_attempt(st, a.id, 'e2e status %s/%s' % (rec2['status'], rec2.get('exit')))
        for f in e.get('expect_files', []):
            if not (tree / f).is_file():
                fail_attempt(st, a.id, 'e2e missing file ' + f)
        suite = tree / 'e2e' / 'run_e2e.py'
        if suite.is_file() and not suite.is_symlink():   # the tree carries its own E2E suite: the WHOLE suite must stay green
            rec3, _ = launch(L, st, '%s/%d/suite' % (a.id, attempt), [env['BOOT_PYTHON'], '-B', 'e2e/run_e2e.py'],
                             LIMITS['suite_timeout'], 1 << 20, str(tree), {'E2E_SUMMARY_DIR': str(ev / 'suite-summary')})
            if rec3 is None or rec3['status'] == 'uncertain':
                uncertain_stop(L, st, a.id)
            if not rec3['reaped'] or rec3.get('exit') != 0 or rec3['status'] != 'ok':
                fail_attempt(st, a.id, 'suite status %s/%s' % (rec3['status'], rec3.get('exit')))
            try:
                post = inv_hash(inventory(tree))
            except SystemExit as e2:
                fail_attempt(st, a.id, str(e2))
            if post != manifest['tree_hash']:
                fail_attempt(st, a.id, 'SUITE_TREE_MUTATED')
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
                 st['launches_used'], LIMITS['cap_launches'], st['active_seconds'], ceiling(st))]
    inv = inventory(subject_tree)
    lines.append('INVENTORY:')
    lines += ['  %s %s %d %s' % tuple(r) for r in inv]
    lines.append('DISPOSITIONS: ' + json.dumps(st.get('dispositions', {}), sort_keys=True) +
                 ' (standing dispositions for prior findings; re-raise a finding only if the disposition no '
                 'longer holds, and say what changed)')
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
        ids = [f['id'] for f in v['findings']]
        for i in range(len(v['missing_evidence'])):
            mid = 'M%d' % i
            while mid in ids:                       # never collide with reviewer-authored M-ids
                mid += 'x'
            ids.append(mid)
        if not ids:
            ids = ['COVERAGE']
        undispositioned = [i for i in ids if i not in st.get('dispositions', {})]
        st['pending_findings'] = undispositioned    # a finding WITH a standing disposition does not block (§8)
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
        suite = suite_e2e_ids(st['parent_dir'])
        e2e_ids = sorted(suite)
        claimed = claimed_e2e_ids(st, existing)
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
            'stop_condition,e2e{argv,expect_status,expect_files},timeout(<=600); optional base,replaces - both are '
            'CARD IDS only, never hashes: base = build on that accepted card\'s tree instead of the parent tree, '
            'replaces = the subject card id this new card supersedes. One concern per card.',
            'No placeholders. Dispositions are required ONLY for the ids in FINDING_IDS (often none) as '
            'card:<id> | rejected:<why> | deferred:<why>; existing dispositions stand unchanged - do not '
            're-disposition already-dispositioned findings.',
            'EXISTING_DISPOSITIONS: ' + json.dumps(st.get('dispositions', {}), sort_keys=True),
            'EXISTING_E2E_IDS: ' + ','.join(e2e_ids),
            'CLAIMED_E2E_IDS: ' + ','.join('%s=%s' % (i, '+'.join(v)) for i, v in sorted(claimed.items())),
            'Any e2e scenario id a new card references (in e2e.argv or acceptance rows) must be in NEITHER '
            'EXISTING_E2E_IDS NOR CLAIMED_E2E_IDS (ids pending cards already own); pick fresh ids larger than every '
            'listed id. A card that replaces a retired card may NOT reuse the retired card\'s id either.',
            'FINDING_IDS: ' + ','.join(st['pending_findings']), 'REPLACES: ' + ','.join(subjects),
            'EXISTING_CARD_IDS: ' + ','.join(sorted(existing)),
            'BUDGET: launches_used=%d/%d active=%.1f/%.0f' % (st['launches_used'], LIMITS['cap_launches'],
                                                             st['active_seconds'], ceiling(st)),
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
                or not 0 <= len(plan['cards']) <= 4 or not isinstance(plan['dispositions'], dict):
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
            coll = e2e_id_collisions(c, suite, claimed)
            if coll:
                save_state(st)
                sys.exit('PLAN_E2E_ID_COLLISION %s claims %s' % (c['id'], coll))
            for i in ids_of(' '.join(c['e2e']['argv'])):
                claimed.setdefault(i, []).append(c['id'])
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
REVIEW_TEMPLATE = """You are the independent final reviewer of the continuation-011 orchestration layer and its card program ONLY.
You may not edit, execute code, delegate, or infer runtime evidence from source closure. Read ALL inline material.
NO TOOLS: everything you need is inline below. Do not emit tool calls.
REVISION (parent tree in force): {{revision}}
ORCH_HASH (orchestration snapshot in force, source-reviewed): {{orch_hash}}
ACCOUNTING: {{accounting}}
ALLOCATIONS (operator-recorded ceiling changes): {{allocations}}
CARD STATE: {{cards}}
CARD FILES (objective, allowed paths, acceptance rows, e2e, stop condition): {{card_files}}
DISPOSITIONS (every finding ever raised -> card:/rejected:/deferred:/root:): {{dispositions}}
REVIEW HISTORY (reviews, source_reviews, smokes, same_backend_approvals, last_review): {{reviews}}
E2E-ORCH RESULTS (per scenario; bound to the live source hashes): {{e2e_summary}}
PRESERVATION / CLEANUP:
{{preservation}}
SOURCE INVENTORY (relpath mode size sha256):
{{inventory}}
SOURCE CONTENTS (the parent tree in force, every file inline):
{{sources}}
LEDGER (append-only: every reservation, launch, interval, review, replan, allocation, retirement, disposition):
{{ledger}}
TASK: check correctness, regressions, provenance, process ownership, finite-failure contract, credential lifecycle,
every card's acceptance rows against its tree, every finding's disposition, scenario-id uniqueness, and the accounting
(no cap raised without a ledgered allocation/approval). Zero findings with missing evidence is NOT acceptance.
Return exactly ONE fenced json block with keys revision, findings[{id,severity,location,evidence}], missing_evidence[],
coverage{complete,truncated}, cleanup, verdict (ACCEPTED|INCOMPLETE|BLOCKED). ACCEPTED requires zero findings and zero
missing evidence. Output outside the block is ignored.
"""


def e2e_summary_check():
    """The live suite summary must exist, be all-pass and be bound to the live orchestration sources (run_e2e.py D8)."""
    p = ROOT.parent / 'evidence-e2e-orch' / 'summary.json'
    if not p.is_file() or p.is_symlink():
        sys.exit('HANDOFF_BLOCKED no e2e summary at %s (run e2e/run_e2e.py)' % p)
    s = read_bounded_json(p, 1 << 20)
    if not isinstance(s, dict) or not isinstance(s.get('results'), list) or not isinstance(s.get('sources'), dict):
        sys.exit('HANDOFF_BLOCKED e2e summary malformed (re-run e2e/run_e2e.py on the live source)')
    failed = [r.get('id') for r in s['results'] if not r.get('pass')]
    if not s['results'] or failed:
        sys.exit('HANDOFF_BLOCKED e2e summary has failures %s' % failed)
    live = {r[0]: r[3] for r in orch_source_inventory() if r[0].endswith(('.py', '.sh'))}
    stale = sorted(n for n, h in live.items() if s['sources'].get(n) != h)
    if stale:
        sys.exit('HANDOFF_BLOCKED e2e summary stale for %s (re-run the suite on the live source)' % stale)
    return s


def preservation_report(env, st):
    rows = []
    d = env.get('AUTH_DIR')
    if d:
        p = pathlib.Path(d)
        rows.append('AUTH_DIR %s entries=%s' % (d, sorted(x.name for x in p.iterdir()) if p.is_dir() else 'MISSING'))
    else:
        rows.append('AUTH_DIR unset')
    rt = env.get('PI_RUNTIME')
    jobs = pathlib.Path(rt) / 'jobs' if rt else None
    if jobs and jobs.is_dir():
        for j in sorted(jobs.iterdir()):
            r = j / 'guardian' / 'receipt.json'
            if r.is_file() and not r.is_symlink():
                try:
                    g = read_bounded_json(r, LIMITS['receipt_cap'])
                    rows.append('JOB %s status=%s worker_reaped=%s credential_removed=%s exit=%s reason=%s' % (
                        j.name, g.get('status'), g.get('worker_reaped'), g.get('credential_removed'), g.get('exit_code'),
                        g.get('reason')))
                except SystemExit:
                    rows.append('JOB %s receipt INVALID' % j.name)
            else:
                rows.append('JOB %s receipt MISSING' % j.name)
    rows.append('UNCERTAIN_CARDS %s' % sorted(k for k, v in st['cards'].items() if v['status'] == 'BLOCKED_CLEANUP_UNCERTAIN'))
    rows.append('WORKER_FAILURE_STREAK %s' % st.get('worker_failure_streak', 0))
    rows.append('LOCK held by this handoff process only (pid %d)' % os.getpid())
    rows.append('ORCH_HASH live=%s state=%s' % (inv_hash(orch_source_inventory()), st['orch_hash']))
    return '\n'.join(rows)


def inline_tree(tree, cap):
    inv = inventory(tree)
    lines, total = [], 0
    for r in inv:
        data = (pathlib.Path(tree) / r[0]).read_bytes()
        total += len(data)
        if total > cap:
            sys.exit('HANDOFF_TOO_LARGE: parent tree exceeds %d bytes inline; slim the subject' % cap)
        lines.append('--- FILE %s ---\n%s\n--- END FILE ---' % (r[0], data.decode('utf-8', 'replace')))
    return inv, '\n'.join(lines)


def cmd_handoff(a):
    env = load_env()
    with Lock():
        st = load_state()
        hp = ROOT.parent / ('HANDOFF-%03d.txt' % a.seq)
        rp = ROOT.parent / ('RESULT-%03d.json' % a.seq)
        if hp.exists() or rp.exists():
            sys.exit('HANDOFF_OUTPUT_EXISTS %s / %s (pass a fresh --seq)' % (hp.name, rp.name))
        open_cards = [k for k, v in st['cards'].items() if v['status'] not in TERMINAL]
        if open_cards:
            sys.exit('HANDOFF_BLOCKED non-terminal cards: %s' % open_cards)
        live = inv_hash(orch_source_inventory())
        if live != st['orch_hash']:
            sys.exit('HANDOFF_BLOCKED orchestration source changed since init (%s != %s)' % (live[:12], st['orch_hash'][:12]))
        if st['orch_hash'] not in st['source_reviews'].values():
            sys.exit('HANDOFF_BLOCKED no accepted source review of the orchestration snapshot %s' % st['orch_hash'][:12])
        summary = e2e_summary_check()
        inv, sources = inline_tree(st['parent_dir'], LIMITS['handoff_cap'])
        card_files = {p.stem: read_bounded_json(p, 256 * 1024) for p in sorted((ROOT / 'cards').glob('*.json'))}
        ledger = (ROOT / 'ledger.jsonl').read_text() if (ROOT / 'ledger.jsonl').exists() else ''
        accounting = 'launches %d/%d, active %.1f/%.0f s, remaining %.1f s' % (
            st['launches_used'], LIMITS['cap_launches'], st['active_seconds'], ceiling(st), ceiling(st) - st['active_seconds'])
        subst = {'revision': st['parent_hash'], 'orch_hash': st['orch_hash'], 'accounting': accounting,
                 'allocations': json.dumps(st.get('allocations', []), sort_keys=True),
                 'cards': json.dumps(st['cards'], sort_keys=True), 'card_files': json.dumps(card_files, sort_keys=True),
                 'dispositions': json.dumps(st.get('dispositions', {}), sort_keys=True),
                 'reviews': json.dumps({'reviews': st['reviews'], 'source_reviews': st['source_reviews'],
                                        'smokes': st['smokes'], 'same_backend_approvals': st.get('same_backend_approvals', []),
                                        'last_review': st.get('last_review')}, sort_keys=True),
                 'e2e_summary': json.dumps(summary, sort_keys=True), 'preservation': preservation_report(env, st),
                 'inventory': '\n'.join('  %s %s %d %s' % tuple(r) for r in inv), 'sources': sources, 'ledger': ledger}
        prompt = REVIEW_TEMPLATE
        for k, v in subst.items():
            prompt = prompt.replace('{{%s}}' % k, v)
        if '{{' in prompt:
            sys.exit('HANDOFF_UNFILLED_PLACEHOLDER')
        verdict = 'ACCEPTED' if st['milestone'] == 'ACCEPTED' else (
            'BLOCKED' if any(v['status'] == 'BLOCKED_CLEANUP_UNCERTAIN' for v in st['cards'].values()) else 'INCOMPLETE')
        text = '\n'.join(['HANDOFF-%03d' % a.seq, 'MILESTONE VERDICT: ' + verdict, 'REVISION: ' + st['parent_hash'],
                          'ACCOUNTING: ' + accounting, 'CARDS: ' + subst['cards'],
                          '=== FULL REVIEW PROMPT ===', prompt, '=== END ==='])
        hp.write_text(text)
        jwrite(rp, {'verdict': verdict, 'revision': st['parent_hash'], 'orch_hash': st['orch_hash'],
                    'launches_used': st['launches_used'], 'active_seconds': st['active_seconds'], 'time_ceiling': ceiling(st),
                    'handoff_sha': sha_bytes(text.encode())})
        print(text)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('init'); p.add_argument('--parent', required=True)
    p.add_argument('--active-seconds', type=float, required=True)
    p.add_argument('--launches-used', type=int, required=True)
    p.add_argument('--expected-hash'); p.add_argument('--expected-entries', type=int)
    p.set_defaults(f=cmd_init)
    sub.add_parser('status').set_defaults(f=cmd_status)
    sub.add_parser('rebind-orch').set_defaults(f=cmd_rebind_orch)
    p = sub.add_parser('note-interval'); p.add_argument('--seconds', type=float, required=True)
    p.add_argument('--basis', required=True); p.add_argument('--start-wall', type=float); p.add_argument('--end-wall', type=float)
    p.set_defaults(f=cmd_note_interval)
    p = sub.add_parser('allocate-time'); p.add_argument('--ceiling', type=float, required=True)
    p.add_argument('--approval', required=True); p.set_defaults(f=cmd_allocate_time)
    p = sub.add_parser('read-receipt'); p.add_argument('file'); p.set_defaults(f=cmd_read_receipt)
    p = sub.add_parser('clear-lock'); p.add_argument('--reason', required=True); p.set_defaults(f=cmd_clear_lock)
    p = sub.add_parser('run-card'); p.add_argument('id'); p.add_argument('--acknowledge-streak')
    p.set_defaults(f=cmd_run_card)
    p = sub.add_parser('retire-card'); p.add_argument('id'); p.add_argument('--reason', required=True)
    p.add_argument('--superseded-by')
    p.set_defaults(f=cmd_retire_card)
    p = sub.add_parser('add-card'); p.add_argument('file'); p.add_argument('--reason', required=True); p.add_argument('--approval', required=True); p.set_defaults(f=cmd_add_card)
    p = sub.add_parser('set-disposition'); p.add_argument('key'); p.add_argument('value'); p.add_argument('--reason', required=True); p.set_defaults(f=cmd_set_disposition)
    p = sub.add_parser('review'); p.add_argument('--card'); p.add_argument('--backend', choices=['codex', 'fable'])
    p.add_argument('--packet'); p.add_argument('--sha')
    p.add_argument('--subject'); p.add_argument('--name'); p.add_argument('--smoke', action='store_true')
    p.set_defaults(f=cmd_review)
    p = sub.add_parser('replan'); p.add_argument('--backend', choices=['codex', 'fable'])
    p.add_argument('--same-backend-approved', help='explicit user approval text; required when planner == reviewer')
    p.set_defaults(f=cmd_replan)
    p = sub.add_parser('set-parent'); p.add_argument('dir'); p.set_defaults(f=cmd_set_parent)
    p = sub.add_parser('backfill-review'); p.add_argument('--seq', type=int, required=True); p.set_defaults(f=cmd_backfill_review)
    p = sub.add_parser('handoff'); p.add_argument('--seq', type=int, default=11); p.set_defaults(f=cmd_handoff)
    a = ap.parse_args()
    try:
        a.f(a)
    except KeyboardInterrupt:
        sys.stderr.write('INTERRUPTED: lock retained if a launch was in flight\n')
        sys.exit(130)


if __name__ == '__main__':
    main()
