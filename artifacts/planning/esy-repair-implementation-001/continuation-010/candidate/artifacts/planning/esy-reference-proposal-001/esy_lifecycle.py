#!/usr/bin/env python3
"""Bounded, single-child Astra lifecycle probe supervisor."""
import argparse
import errno
import hashlib
import json
import os
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time

LIMIT = 65536
PROFILE = b'(version 1)\n(allow default)\n(deny process-fork)\n(deny file-write*)\n'
DOCKER = '/usr/local/bin/docker'
SANDBOX = '/usr/bin/sandbox-exec'
SCENARIOS = ('docker-metadata', 'fork-denial', 'timeout', 'caller-eof', 'output-overflow')
FORK_FIXTURE = ("import errno,os,sys\n"
                "try: pid=os.fork()\n"
                "except OSError as e:\n"
                " if e.errno in (errno.EPERM,errno.EACCES): print('FORK_DENIED:'+str(e.errno)); sys.exit(0)\n"
                " raise\n"
                "if pid == 0: os._exit(0)\n"
                "os.waitpid(pid,0)\nprint('FORK_POLICY_FAILURE')\nsys.exit(71)\n")
OVERFLOW_FIXTURE = "import os\ndata=b'X'*65537\noffset=0\nwhile offset < len(data):\n try: written=os.write(1,data[offset:])\n except InterruptedError: continue\n if written <= 0: raise OSError('short write made no progress')\n offset += written\n"
FIXTURES = {
    'fork-denial': FORK_FIXTURE,
    'timeout': 'import time; time.sleep(30)',
    'caller-eof': 'import time; time.sleep(30)',
    'output-overflow': OVERFLOW_FIXTURE,
}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(131072), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(prog='esy_lifecycle.py', allow_abbrev=False)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('probe', allow_abbrev=False)
    q.add_argument('--scenario', required=True, choices=SCENARIOS)
    q.add_argument('--state-directory', required=True)
    a = p.parse_args()
    if not os.path.isabs(a.state_directory) or os.path.lexists(a.state_directory):
        p.error('state directory must be an unused absolute path')
    parent = os.path.dirname(a.state_directory)
    if not os.path.isdir(parent):
        p.error('state parent must exist')
    os.mkdir(a.state_directory, 0o700)
    os.chmod(a.state_directory, 0o700)
    state = os.path.realpath(a.state_directory)
    started = time.monotonic()
    report = {
        'scenario': a.scenario, 'argv': None, 'environment': None,
        'resolved_executables': None, 'profile_sha256': hashlib.sha256(PROFILE).hexdigest(),
        'socket': None, 'socket_identity': None, 'launch_identity': None, 'ready': None,
        'started_monotonic': started, 'finished_monotonic': None,
        'first_terminal_cause': None, 'cleanup_status': 'not-required',
        'child_pid': None, 'child_owned': False, 'reaped': False,
        'wait_receipt': None, 'streams': {
            n: {'observed_bytes': 0, 'retained_bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest(), 'eof': False}
            for n in ('stdout', 'stderr')},
        'probe_exit': 1,
    }
    before = {'sandbox': None, 'command': None}
    after = {'sandbox': None, 'command': None}
    child = None
    sel = selectors.DefaultSelector()
    streams = {n: bytearray() for n in ('stdout', 'stderr')}
    observed = {'stdout': 0, 'stderr': 0}
    eof = {'stdout': False, 'stderr': False}
    reaped = False
    wait_status = None
    terminal = None
    cleanup_deadline = None
    launch_time = None
    registered_liveness = False

    def cause(value):
        nonlocal terminal, cleanup_deadline
        if terminal is None:
            terminal = value
            cleanup_deadline = time.monotonic() + 5.0 if child is not None else None

    def drain(timeout):
        for key, _ in sel.select(max(0.0, timeout)):
            if key.data == 'liveness':
                try:
                    data = os.read(key.fd, 4096)
                except BlockingIOError:
                    continue
                if not data:
                    sel.unregister(key.fileobj)
                    cause('caller-eof')
                continue
            name = key.data
            try:
                data = os.read(key.fd, 8192)
            except BlockingIOError:
                continue
            if not data:
                eof[name] = True
                sel.unregister(key.fileobj)
                continue
            observed[name] += len(data)
            streams[name].extend(data[:max(0, LIMIT - len(streams[name]))])
            if observed[name] > LIMIT:
                cause('output-overflow')

    def reap_once():
        nonlocal reaped, wait_status
        if child is None or reaped:
            return
        got, status = os.waitpid(child.pid, os.WNOHANG)
        if got:
            wait_status = status
            reaped = True
            child.returncode = os.waitstatus_to_exitcode(status)
            report['wait_receipt'] = {'pid': got, 'raw_status': status, 'exit_code': child.returncode}
            report['reaped'] = True

    try:
        home = os.path.join(state, 'home')
        config = os.path.join(state, 'docker-config')
        os.mkdir(home, 0o700)
        os.mkdir(config, 0o700)
        env = {'HOME': home, 'DOCKER_CONFIG': config, 'PATH': '/usr/bin:/bin', 'LANG': 'C'}
        report['environment'] = env
        if a.scenario == 'docker-metadata':
            sock = os.path.realpath('/var/run/docker.sock')
            info = os.stat(sock) if os.path.exists(sock) else None
            if not os.path.isabs(sock) or info is None or not stat.S_ISSOCK(info.st_mode):
                raise RuntimeError('unsupported-docker-socket')
            report['socket'] = sock
            report['socket_identity'] = {'device': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode}
            argv = [SANDBOX, '-p', PROFILE.decode(), DOCKER, '--host', 'unix://' + sock, 'version', '--format', '{{json .Server}}']
            exe = DOCKER
        else:
            exe = os.path.realpath(sys.executable)
            argv = [SANDBOX, '-p', PROFILE.decode(), exe, '-c', FIXTURES[a.scenario]]
        report['argv'] = argv
        report['resolved_executables'] = {'sandbox': os.path.realpath(SANDBOX), 'command': os.path.realpath(exe)}
        for key, path in (('sandbox', SANDBOX), ('command', exe)):
            try: before[key] = digest(path)
            except Exception as e: cause('hash-before-failure:' + type(e).__name__)
        launch_time = time.monotonic()
        if terminal is None:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     close_fds=True, env=env)
            report['child_pid'] = child.pid
            report['child_owned'] = True
            ident = hashlib.sha256((str(os.getpid()) + ':' + str(child.pid) + ':' + str(launch_time)).encode()).hexdigest()
            report['launch_identity'] = ident
            for name, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
                os.set_blocking(pipe.fileno(), False)
                sel.register(pipe, selectors.EVENT_READ, name)
            os.set_blocking(0, False)
            sel.register(0, selectors.EVENT_READ, 'liveness')
            registered_liveness = True
            ready = {'scenario': a.scenario, 'supervisor_pid': os.getpid(), 'child_pid': child.pid, 'launch_identity': ident}
            with open(os.path.join(state, 'ready.json'), 'x') as f:
                json.dump(ready, f); f.flush(); os.fsync(f.fileno())
            report['ready'] = ready
            deadline = launch_time + 3.0
            while terminal is None and not (reaped and eof['stdout'] and eof['stderr']):
                if time.monotonic() >= deadline:
                    cause('timeout')
                    break
                drain(min(.05, max(0.0, deadline - time.monotonic())))
                reap_once()
            if terminal is None and reaped and eof['stdout'] and eof['stderr']:
                report['cleanup_status'] = 'verified'
    except Exception as e:
        cause(terminal or ('supervisor-error:' + type(e).__name__))
    finally:
        if child is not None and not (reaped and eof['stdout'] and eof['stderr']):
            if terminal is None:
                cause('supervisor-error:incomplete-lifecycle')
            if not reaped:
                try: os.kill(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                except Exception as e: cause(terminal or ('supervisor-error:' + type(e).__name__))
            while time.monotonic() < cleanup_deadline and not (reaped and eof['stdout'] and eof['stderr']):
                try:
                    drain(min(.05, max(0.0, cleanup_deadline - time.monotonic())))
                    reap_once()
                except Exception as e:
                    cause('supervisor-error:' + type(e).__name__)
                    time.sleep(min(.01, max(0.0, cleanup_deadline-time.monotonic())))
            report['cleanup_status'] = 'verified' if reaped and eof['stdout'] and eof['stderr'] else 'cleanup-unverified'
        sel.close()

    for key, path in (('sandbox', SANDBOX), ('command', report['resolved_executables']['command'] if report['resolved_executables'] else None)):
        if path is not None:
            try: after[key] = digest(path)
            except Exception as e: cause('hash-after-failure:' + type(e).__name__)
    hash_comparison = {key: before[key] is not None and after[key] is not None and before[key] == after[key]
                       for key in ('sandbox', 'command')}
    report['executable_sha256_before'] = before
    report['executable_sha256_after'] = after
    report['hash_comparison'] = hash_comparison
    if not all(hash_comparison.values()):
        cause('executable-integrity-failure')

    metadata_valid = False
    policy_valid = False
    decoded_exit = child.returncode if child is not None and reaped else None
    if a.scenario == 'docker-metadata' and reaped and eof['stdout'] and eof['stderr'] and decoded_exit == 0 and terminal is None:
        try:
            metadata = json.loads(bytes(streams['stdout']).decode('utf-8'))
            metadata_valid = (isinstance(metadata, dict) and isinstance(metadata.get('Version'), str)
                              and bool(metadata['Version']) and isinstance(metadata.get('ApiVersion'), str)
                              and bool(metadata['ApiVersion']))
        except (ValueError, UnicodeDecodeError):
            metadata_valid = False
        if not metadata_valid:
            cause('invalid-metadata')
    elif a.scenario == 'fork-denial' and reaped and eof['stdout'] and eof['stderr'] and decoded_exit == 0 and terminal is None:
        output = bytes(streams['stdout'])
        policy_valid = any(output == ('FORK_DENIED:%d\n' % number).encode()
                           for number in (errno.EPERM, errno.EACCES)) and not streams['stderr']
        if not policy_valid:
            cause('policy-failure')
    if child is not None and reaped and decoded_exit != 0 and terminal is None:
        cause('child-failure')

    results = {}
    for name in ('stdout', 'stderr'):
        raw = bytes(streams[name])
        results[name] = {'observed_bytes': observed[name], 'retained_bytes': len(raw),
                         'sha256': hashlib.sha256(raw).hexdigest(), 'eof': eof[name]}
        with open(os.path.join(state, name + '.bin'), 'xb') as f:
            f.write(raw)
    report['streams'] = results
    report['decoded_child_exit'] = decoded_exit
    report['first_terminal_cause'] = terminal
    report['cleanup_status'] = report['cleanup_status'] if child is not None else 'not-required'
    report['cleanup_missing'] = {'reap': child is not None and not reaped,
                                 'stdout_eof': child is not None and not eof['stdout'],
                                 'stderr_eof': child is not None and not eof['stderr']}
    success = (terminal is None and child is not None and reaped and eof['stdout'] and eof['stderr']
               and decoded_exit == 0 and all(hash_comparison.values())
               and (metadata_valid if a.scenario == 'docker-metadata' else
                    policy_valid if a.scenario == 'fork-denial' else True))
    report['probe_exit'] = 0 if success else 1
    report['reason'] = 'success' if success else (terminal or ('child-failure' if decoded_exit not in (None, 0) else 'incomplete-lifecycle'))
    report['finished_monotonic'] = time.monotonic()
    report['timings'] = {'launch_monotonic': launch_time, 'execution_deadline_seconds': 3.0,
                         'cleanup_allowance_seconds': 5.0}
    path = os.path.join(state, 'report.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, 'w') as f:
        json.dump(report, f, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path, 0o400)
    return report['probe_exit']


if __name__ == '__main__':
    raise SystemExit(main())
