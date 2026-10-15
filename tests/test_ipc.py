import os
import stat
import time

from iridia.ipc import IPCClient, IPCServer


class FakeDaemon:
    def handle_command(self, req):
        if req.get("cmd") == "boom":
            raise RuntimeError("kaboom")
        return {"ok": True, "echo": req}


def _start(path):
    server = IPCServer(path, FakeDaemon())
    server.start()
    for _ in range(100):
        if os.path.exists(path):
            break
        time.sleep(0.01)
    return server


def test_roundtrip_and_errors(tmp_path):
    path = str(tmp_path / "s.sock")
    server = _start(path)
    try:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        client = IPCClient(path)
        assert client.send({"cmd": "ping"}) == {"ok": True, "echo": {"cmd": "ping"}}
        assert client.is_alive()
        resp = client.send({"cmd": "boom"})
        assert resp["ok"] is False and "kaboom" in resp["error"]
    finally:
        server.stop()
    assert not os.path.exists(path)


def test_client_without_daemon(tmp_path):
    resp = IPCClient(str(tmp_path / "missing.sock")).send({"cmd": "ping"})
    assert resp == {"ok": False, "error": "daemon not running"}
