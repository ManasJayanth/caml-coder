#!/usr/bin/env python3
"""Sole process launcher: deadline, byte caps, process-group ownership, durable receipt.

Usage: run_bounded.py RECEIPT_JSON TIMEOUT_S CAP_BYTES CWD [--stdin FILE] -- argv...
Exit: 0 receipt published (child may still have failed), 70 launcher refused, 71 ownership/reap uncertain.
"""
import json, os, selectors, signal, subprocess, sys, time

GRACE_TERM = 3.0     # SIGTERM -> SIGKILL
GRACE_EOF = 5.0      # reaped leader but pipes still open => descendants hold them => uncertain


def main():
    a = sys.argv[1:]
    sep = a.index('--')
    receipt, timeout, cap, cwd = a[0], float(a[1]), int(a[2]), a[3]
    opts = a[4:sep]
    stdin_path = opts[1] if opts[:1] == ['--stdin'] else None
    argv = a[sep + 1:]
    start_wall, start = time.time(), time.monotonic()
    rec = {'schema': 1, 'argv_len': len(argv), 'start_wall': start_wall, 'status': 'launcher-error',
           'reaped': False, 'signal': None, 'timed_out': False,
           'overflow': {'out': False, 'err': False}, 'ownership_uncertain': False}
    out_p, err_p = receipt + '.out', receipt + '.err'
    for p in (receipt, out_p, err_p, receipt + '.tmp'):
        if os.path.lexists(p):
            print('refusing to overwrite ' + p, file=sys.stderr)
            return 70
    child = None
    bufs = {'out': bytearray(), 'err': bytearray()}
    try:
        stdin = open(stdin_path, 'rb') if stdin_path else subprocess.DEVNULL
        child = subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, close_fds=True)
        if stdin_path:
            stdin.close()
        rec['pid'] = child.pid
        sel = selectors.DefaultSelector()
        for name, pipe in (('out', child.stdout), ('err', child.stderr)):
            os.set_blocking(pipe.fileno(), False)
            sel.register(pipe, selectors.EVENT_READ, name)
        deadline = start + timeout
        term_at = None
        reaped_at = None
        reaped = False

        def send(sig, label):
            rec['signal'] = label
            try:
                os.killpg(child.pid, sig)   # only while the direct leader is owned and unreaped
            except ProcessLookupError:
                pass

        while True:
            now = time.monotonic()
            if not reaped:
                pid, st = os.waitpid(child.pid, os.WNOHANG)
                if pid:
                    reaped, reaped_at = True, now
                    rec['reaped'] = True
                    rec['exit'] = os.waitstatus_to_exitcode(st)
            if reaped and not sel.get_map():
                break
            if not reaped:
                if now >= deadline and rec['signal'] is None:
                    rec['timed_out'] = True
                    term_at = now
                    send(signal.SIGTERM, 'TERM')
                elif rec['signal'] == 'TERM' and now >= term_at + GRACE_TERM:
                    send(signal.SIGKILL, 'KILL')
                if any(rec['overflow'].values()) and rec['signal'] is None:
                    term_at = now
                    send(signal.SIGTERM, 'TERM')
            elif now > reaped_at + GRACE_EOF:
                rec['ownership_uncertain'] = True
                break
            events = sel.select(0.05) if sel.get_map() else (time.sleep(0.05) or [])
            for key, _ in events:
                data = os.read(key.fileobj.fileno(), 16384)
                if not data:
                    sel.unregister(key.fileobj)
                    continue
                b = bufs[key.data]
                room = cap - len(b)
                b.extend(data[:max(0, room)])
                if len(data) > room:
                    rec['overflow'][key.data] = True
        if rec['ownership_uncertain']:
            rec['status'] = 'uncertain'
        elif rec['timed_out']:
            rec['status'] = 'timeout'
        elif any(rec['overflow'].values()):
            rec['status'] = 'overflow'
        else:
            rec['status'] = 'ok' if rec.get('exit') == 0 else 'child-failed'
    except BaseException as e:   # protect acquisition and interrupts; never claim a clean child
        rec['error'] = type(e).__name__
        if child is not None and not rec['reaped']:
            rec['ownership_uncertain'] = True
            rec['status'] = 'uncertain'
    finally:
        rec['elapsed'] = round(time.monotonic() - start, 3)
        for p, b in ((out_p, bufs['out']), (err_p, bufs['err'])):
            with open(p, 'xb') as f:
                f.write(bytes(b)); f.flush(); os.fsync(f.fileno())
        tmp = receipt + '.tmp'
        with open(tmp, 'x') as f:
            json.dump(rec, f, sort_keys=True); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, receipt)
    return 71 if rec['ownership_uncertain'] else 0


if __name__ == '__main__':
    sys.exit(main())
