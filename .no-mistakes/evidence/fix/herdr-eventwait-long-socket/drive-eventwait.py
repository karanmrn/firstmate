import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

ROOT = Path.cwd()
EVIDENCE = Path('~/.no-mistakes/evidence/01M6PE3RFXZWW2J3AN8ZVSVNR2')
READER = ROOT / 'bin/backends/herdr-eventwait.py'
BASE = ROOT / '.test-eventwait/base-eventwait.py'
records = []

class Peer:
    def __init__(self, directory, name):
        self.path = directory / name
        directory.mkdir(parents=True, exist_ok=True)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        original = Path.cwd()
        try:
            os.chdir(directory)
            self.sock.bind(name)
        finally:
            os.chdir(original)
        self.sock.listen(4)
        self.sock.settimeout(0.05)
        self.stop = threading.Event()
        self.requests = []
        self.errors = []
        self.thread = threading.Thread(target=self.serve)
        self.thread.start()
    def serve(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.sock.accept()
            except socket.timeout:
                continue
            try:
                with connection:
                    connection.settimeout(3)
                    request = b''
                    while not request.endswith(b'\n'):
                        chunk = connection.recv(65536)
                        if not chunk:
                            raise AssertionError('client closed before subscription')
                        request += chunk
                    decoded = json.loads(request)
                    self.requests.append(decoded)
                    # Oracle: documented wire contract, not implementation-derived values.
                    assert decoded == {'id':'fm-eventwait','method':'events.subscribe','params':{'subscriptions':[{'type':'pane.agent_status_changed','pane_id':'pane-live'}]}}
                    connection.sendall(b'{"id":"fm-eventwait","result":{"type":"subscription_started"}}\n')
                    connection.sendall(b'{"event":"pane.agent_status_changed","data":{"pane_id":"pane-live","workspace_id":"workspace-live","agent_status":"blocked","agent":"claude"}}\n')
                    while connection.recv(65536):
                        pass
            except BaseException as exc:
                self.errors.append(repr(exc))
    def close(self):
        self.stop.set()
        self.thread.join(5)
        assert not self.thread.is_alive(), 'peer did not stop'
        self.sock.close()
        self.path.unlink()
        assert not self.errors, self.errors

def drive(label, reader, path, expected_rc, expected_stdout, cwd=ROOT):
    result = subprocess.run([sys.executable, str(reader), str(path), '0.3', 'pane-live'], cwd=cwd, text=True, capture_output=True, timeout=8)
    record = {'scenario':label, 'socket_path':str(path), 'socket_path_bytes':len(os.fsencode(path)), 'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    print(json.dumps(record), flush=True)
    records.append(record)
    assert result.returncode == expected_rc, record
    assert result.stdout == expected_stdout, record
    return result

expected = '@subscribed\npane-live\tworkspace-live\tblocked\tclaude\n'
long_dir = ROOT / '.test-eventwait' / ('deep directory ' + 'd'*45) / ('é'*30)
peer = Peer(long_dir, 'herdr.sock')
try:
    assert len(os.fsencode(peer.path)) > 104
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as control:
            control.connect(str(peer.path))
    except OSError as exc:
        print('Native full-path control rejected:', repr(exc), flush=True)
    else:
        raise AssertionError('host unexpectedly accepted the oversized full-path address')
    drive('baseline long-path failure', BASE, peer.path, 2, '')
    assert not peer.requests
    drive('target long-path subscription and event', READER, peer.path, 0, expected)
    assert len(peer.requests) == 1
    drive('baseline accepts reachable relative socket', BASE, 'herdr.sock', 0, expected, long_dir)
    before = len(peer.requests)
    result = drive('existing relative socket is refused', READER, 'herdr.sock', 2, '', long_dir)
    assert 'must be absolute' in result.stderr
    child = long_dir / 'child'
    child.mkdir()
    result = drive('relative traversal socket is refused', READER, '../herdr.sock', 2, '', child)
    assert 'must be absolute' in result.stderr
    assert len(peer.requests) == before
finally:
    peer.close()

# The worktree root permits a socket shorter than the Darwin limit.
short = Peer(ROOT, '.ew.sock')
try:
    print('Short socket bytes:', len(os.fsencode(short.path)), flush=True)
    assert len(os.fsencode(short.path)) < 104
    drive('ordinary absolute socket still streams', READER, short.path, 0, expected)
    assert len(short.requests) == 1
finally:
    short.close()

drive('missing absolute directory fails closed', READER, ROOT / '.test-eventwait/missing/herdr.sock', 2, '')
drive('missing socket in existing directory fails closed', READER, ROOT / '.test-eventwait/herdr.sock', 2, '')
assert Path.cwd() == ROOT
(EVIDENCE / 'eventwait-results.json').write_text(json.dumps(records, indent=2) + '\n')
print('All public CLI scenarios passed. Peers stopped and socket files removed.', flush=True)
