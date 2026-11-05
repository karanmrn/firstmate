#!/usr/bin/env python3
"""Drive the real eventwait CLI against disposable AF_UNIX protocol peers.
Oracle: documented newline JSON events.subscribe protocol and reader exit codes.
No Herdr CLI is replaced. The optional real Herdr lab uses its guarded helper.
"""
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path.cwd()
EVIDENCE = Path(__file__).parent
READER = ROOT / 'bin/backends/herdr-eventwait.py'
TRANSCRIPT = []
RESULTS = []

def log(message):
    print(message, flush=True)
    TRANSCRIPT.append(message)

def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=12, **kwargs)

PEER = r'''
import json, socket, sys, time
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind('herdr.sock')
server.listen(1)
server.settimeout(8)
print('ready', flush=True)
connection, _ = server.accept()
connection.settimeout(8)
data = b''
while b'\n' not in data:
    chunk = connection.recv(65536)
    if not chunk:
        raise SystemExit('closed before subscription')
    data += chunk
request = json.loads(data.split(b'\n')[0])
expected = {'id': 'fm-eventwait', 'method': 'events.subscribe', 'params': {'subscriptions': [
    {'type': 'pane.agent_status_changed', 'pane_id': 'pane-1'},
    {'type': 'pane.agent_status_changed', 'pane_id': 'pane-2'}]}}
if request != expected:
    raise SystemExit('unexpected subscription: ' + repr(request))
print('received ' + json.dumps(request, sort_keys=True), flush=True)
mode = sys.argv[1]
if mode == 'bad-ack':
    connection.sendall(b'{"result":{"type":"rejected"}}\n')
else:
    # Split the acknowledgement across writes, then coalesce two events.
    connection.sendall(b'{"id":"fm-eventwait","result":')
    time.sleep(0.02)
    connection.sendall(b'{"type":"subscription_started"}}\n')
    if mode != 'eof':
        connection.sendall(b'not-json\n{"event":"unrelated","data":{}}\n'
            b'{"event":"pane.agent_status_changed","data":{"pane_id":"pane-1","workspace_id":"workspace-1","agent_status":"blocked","agent":"claude"}}\n'
            b'{"event":"pane.agent_status_changed","data":{"pane_id":"pane-2","workspace_id":"workspace-1","agent_status":"idle","agent":"codex"}}\n')
if mode not in ('eof', 'bad-ack'):
    while connection.recv(65536):
        pass
connection.close()
server.close()
print('peer closed cleanly', flush=True)
'''
EXPECTED = '@subscribed\npane-1\tworkspace-1\tblocked\tclaude\npane-2\tworkspace-1\tidle\tcodex\n'

def session(label, socket_dir, arg, cwd, mode='events', baseline=None):
    proc = subprocess.Popen([sys.executable, '-B', '-c', PEER, mode], cwd=cwd if False else socket_dir,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            if not selector.select(5):
                raise AssertionError('peer readiness timeout')
        assert proc.stdout.readline().strip() == 'ready', 'peer did not become ready'
        absolute = socket_dir / 'herdr.sock'
        path_bytes = len(os.fsencode(absolute))
        log(f'\n{label}: socket path is {path_bytes} bytes, argument={arg!r}')
        if baseline:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(str(absolute))
                raise AssertionError('absolute AF_UNIX path unexpectedly connected')
            except OSError as exc:
                log('Direct full-path AF_UNIX probe: ' + str(exc))
            finally:
                probe.close()
            old = run([sys.executable, '-B', str(baseline), str(arg), '0.5', 'pane-1', 'pane-2'], cwd=cwd)
            log(f'Base reader exit={old.returncode}, stdout={old.stdout!r}, stderr={old.stderr!r}')
            assert old.returncode == 2 and old.stdout == '', 'base did not reproduce long-path failure'
        started = time.monotonic()
        client = run([sys.executable, '-B', str(READER), str(arg), '0.5', 'pane-1', 'pane-2'], cwd=cwd)
        elapsed = time.monotonic() - started
        peer_out, peer_err = proc.communicate(timeout=5)
        log(peer_out.strip())
        log(f'Target reader exit={client.returncode}, elapsed={elapsed:.3f}s, stdout={client.stdout!r}, stderr={client.stderr!r}')
        log(f'Peer exit={proc.returncode}, stderr={peer_err!r}')
        expected_rc = {'bad-ack': 3, 'eof': 4}.get(mode, 0)
        expected_out = '' if mode == 'bad-ack' else '@subscribed\n' if mode == 'eof' else EXPECTED
        assert client.returncode == expected_rc, label
        assert client.stdout == expected_out and client.stderr == '', label
        assert elapsed < 3, 'reader exceeded bounded wait'
        assert proc.returncode == 0, peer_err
        RESULTS.append({'name': label, 'result': 'pass', 'live': True, 'socket_bytes': path_bytes,
                        'reader_exit': client.returncode, 'output': client.stdout, 'elapsed_seconds': elapsed})
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            stream.close()
        (socket_dir / 'herdr.sock').unlink(missing_ok=True)

try:
    log('Tested head: ' + run(['git', 'rev-parse', 'HEAD']).stdout.strip())
    log('Product: bin/backends/herdr-eventwait.py, launched as a subprocess without monkeypatches.')
    log('External peer: disposable real AF_UNIX listener implementing the documented subscription boundary.')
    with tempfile.TemporaryDirectory(prefix='.eventwait-live-', dir=ROOT) as tmp:
        scratch = Path(tmp)
        baseline = scratch / 'base-eventwait.py'
        base_result = run(['git', 'show', 'b77b66cb999876c4db19da36b9af5baaacdd52e5:bin/backends/herdr-eventwait.py'])
        assert base_result.returncode == 0
        baseline.write_text(base_result.stdout)
        deep = scratch / ('deep path ' + 'd' * 35) / ('unicode-\u00e9-' + 'e' * 40)
        deep.mkdir(parents=True)
        assert len(os.fsencode(deep / 'herdr.sock')) > 104
        session('Long absolute path streams status changes and ends on timeout', deep, deep / 'herdr.sock', ROOT, baseline=baseline)
        session('Descending relative path resolves from caller directory', deep, os.path.relpath(deep / 'herdr.sock', scratch), scratch)
        child = deep / 'child'
        child.mkdir()
        session('Parent-relative path resolves from child directory', deep, '../herdr.sock', child)
        session('Basename path preserves ordinary relative invocation', deep, 'herdr.sock', deep)
        session('Rejected subscription signals exit 3 without readiness', deep, deep / 'herdr.sock', ROOT, mode='bad-ack')
        session('Early stream closure signals exit 4 after readiness', deep, deep / 'herdr.sock', ROOT, mode='eof')
        missing = [scratch / 'absent-directory' / 'herdr.sock', deep / 'absent.sock', deep, deep / ('s' * 110)]
        stale = deep / 'stale.sock'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale_sock:
            # The actual bind uses a short basename in a child, just like the server.
            bind = run([sys.executable, '-B', '-c', "import socket; s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.bind('stale.sock'); s.close()"], cwd=deep)
            assert bind.returncode == 0
        missing.append(stale)
        for bad_path in missing:
            client = run([sys.executable, '-B', str(READER), str(bad_path), '0.5', 'pane-1'], cwd=ROOT)
            log(f'Unavailable socket {bad_path.name!r}: exit={client.returncode}, stdout={client.stdout!r}, stderr={client.stderr!r}')
            assert client.returncode == 2 and client.stdout == '' and client.stderr == ''
        RESULTS.append({'name': 'Unavailable directory, missing socket, directory target, overlong basename and refused socket preserve polling fallback', 'result': 'pass', 'live': True})
        assert Path.cwd() == ROOT
        log('Caller working directory remains unchanged after all reader subprocesses.')

        lab_home = scratch / 'herdr-home'
        lab_home.mkdir()
        lab_env = os.environ.copy()
        for key in list(lab_env):
            if key.startswith(('HERDR_', 'FM_')) or key in ('NO_MISTAKES_GATE', 'TMUX'):
                lab_env.pop(key, None)
        for key, suffix in [('HOME', ''), ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                            ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state'), ('TMPDIR', 'tmp')]:
            directory = lab_home / suffix
            directory.mkdir(exist_ok=True)
            lab_env[key] = str(directory)
        lab_env['FM_HERDR_LAB_STATE_DIR'] = str(lab_home / 'tripwire')
        helper = str(ROOT / 'bin/fm-herdr-lab.sh')
        named = run(['bash', helper, 'name', 'eventwait-gate'], env=lab_env)
        assert named.returncode == 0
        lab = named.stdout.strip()
        prep = run(['bash', helper, 'prepare', lab], env=lab_env)
        log(f'\nReal Herdr lab prepare {lab}: exit={prep.returncode}, stdout={prep.stdout!r}, stderr={prep.stderr!r}')
        if prep.returncode != 0:
            log('No lab server was started. Provision/run/teardown lifecycle was not entered after prepare refused.')
            RESULTS.append({'name': 'Real named Herdr lab status transition', 'result': 'untested', 'live': False,
                            'reason': 'Workspace-local HOME, XDG directories and tripwire were supplied to the real lab helper. Prepare refused because the isolated namespace has no running default session. The required tripwire cannot be satisfied through this helper, which forbids default-session lifecycle. An authorised workspace-contained Herdr environment with its running default tripwire is required. No default session or lab server was started.'})
        else:
            teardown = run(['bash', helper, 'teardown', lab], env=lab_env)
            log(f'Lab teardown exit={teardown.returncode}, stdout={teardown.stdout!r}, stderr={teardown.stderr!r}')
            assert teardown.returncode == 0
            raise AssertionError('Lab prepared unexpectedly. Drive the real integration scenario before completing.')
    log('\nCleanup: all disposable listener children were reaped and the workspace scratch directory was removed.')
except Exception as exc:
    log('DRIVER FAILURE: ' + repr(exc))
    raise
finally:
    (EVIDENCE / 'eventwait-live-transcript.txt').write_text('\n'.join(TRANSCRIPT) + '\n')
    (EVIDENCE / 'eventwait-live-results.json').write_text(json.dumps(RESULTS, indent=2) + '\n')
