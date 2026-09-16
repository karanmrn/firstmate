#!/usr/bin/env python3
import importlib.util
import io
import os
import subprocess
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


READER_PATH = Path(__file__).parents[1] / "bin" / "backends" / "herdr-eventwait.py"
SPEC = importlib.util.spec_from_file_location("herdr_eventwait", READER_PATH)
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class FailingSocket:
    def settimeout(self, _timeout):
        pass

    def recv(self, _size):
        raise OSError("receive failed")


class ClosingStreamSocket:
    def __init__(self):
        self.chunks = [
            b'{"result":{"type":"subscription_started"}}\n',
            b"",
        ]

    def settimeout(self, _timeout):
        pass

    def connect(self, _path):
        pass

    def sendall(self, _request):
        pass

    def recv(self, _size):
        return self.chunks.pop(0)


class RejectedSubscriptionSocket(ClosingStreamSocket):
    def __init__(self):
        self.chunks = [b'{"result":{"type":"not_started"}}\n']


class EventWaitReadLineTest(unittest.TestCase):
    def test_deadline_is_clean_timeout(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)

        line, buf, outcome = READER._read_line(left, b"", time.monotonic())

        self.assertIsNone(line)
        self.assertEqual(buf, b"")
        self.assertEqual(outcome, "timeout")

    def test_peer_closure_is_runtime_failure(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        right.close()

        line, buf, outcome = READER._read_line(
            left, b"", time.monotonic() + 1
        )

        self.assertIsNone(line)
        self.assertEqual(buf, b"")
        self.assertEqual(outcome, "closed")

    def test_receive_error_is_runtime_failure(self):
        line, buf, outcome = READER._read_line(
            FailingSocket(), b"", time.monotonic() + 1
        )

        self.assertIsNone(line)
        self.assertEqual(buf, b"")
        self.assertEqual(outcome, "error")

    def test_main_rejects_a_relative_socket_path(self):
        stderr = io.StringIO()
        with mock.patch.object(READER.sys, "stderr", stderr):
            result = READER.main(["herdr-eventwait.py", "herdr.sock", "1", "pane"])

        self.assertEqual(result, 2)
        self.assertIn("must be absolute", stderr.getvalue())

    def test_connects_to_a_socket_path_beyond_the_af_unix_limit(self):
        listener_code = r'''
import json
import os
import socket
import sys

directory, name = sys.argv[1:]
os.chdir(directory)
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(name)
server.listen(1)
print("ready", flush=True)
connection, _ = server.accept()
with connection, server:
    request_bytes = b""
    while b"\n" not in request_bytes:
        chunk = connection.recv(65536)
        if not chunk:
            raise SystemExit("client closed before subscribing")
        request_bytes += chunk
    request = json.loads(request_bytes.split(b"\n", 1)[0].decode("utf-8"))
    if request.get("method") != "events.subscribe":
        raise SystemExit(f"unexpected request: {request!r}")
    connection.sendall(
        b'{"id":"fm-eventwait","result":{"type":"subscription_started"}}\n'
    )
    while connection.recv(65536):
        pass
'''

        with tempfile.TemporaryDirectory(prefix="eventwait-socket-") as base:
            socket_dir = Path(base) / ("d" * 45) / ("e" * 45)
            socket_dir.mkdir(parents=True)
            socket_name = "herdr.sock"
            socket_path = socket_dir / socket_name
            self.assertGreater(len(os.fsencode(socket_path)), 104)

            listener = subprocess.Popen(
                [sys.executable, "-c", listener_code, str(socket_dir), socket_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                ready = listener.stdout.readline().strip()
                if ready != "ready":
                    self.fail(f"listener did not start: {ready!r} {listener.stderr.read()!r}")
                client = subprocess.run(
                    [
                        sys.executable,
                        str(READER_PATH),
                        str(socket_path),
                        "1.0",
                        "pane-1",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(
                    client.returncode,
                    0,
                    f"stdout={client.stdout!r} stderr={client.stderr!r}",
                )
                self.assertEqual(client.stdout, "@subscribed\n")
                listener_rc = listener.wait(timeout=5)
                self.assertEqual(listener_rc, 0, listener.stderr.read())
            finally:
                if listener.poll() is None:
                    listener.terminate()
                    listener.wait(timeout=5)
                listener.stdout.close()
                listener.stderr.close()

    def test_main_reports_early_stream_closure(self):
        stdout = io.StringIO()
        with mock.patch.object(READER.socket, "socket", return_value=ClosingStreamSocket()):
            with mock.patch.object(READER.os, "chdir"):
                with mock.patch.object(READER.sys, "stdout", stdout):
                    result = READER.main(["herdr-eventwait.py", "/run/herdr.sock", "1", "pane"])

        self.assertEqual(result, 4)
        self.assertEqual(stdout.getvalue(), "@subscribed\n")

    def test_main_does_not_signal_readiness_before_valid_ack(self):
        stdout = io.StringIO()
        with mock.patch.object(
            READER.socket, "socket", return_value=RejectedSubscriptionSocket()
        ):
            with mock.patch.object(READER.os, "chdir"):
                with mock.patch.object(READER.sys, "stdout", stdout):
                    result = READER.main(["herdr-eventwait.py", "/run/herdr.sock", "1", "pane"])

        self.assertEqual(result, 3)
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
