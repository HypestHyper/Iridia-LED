"""Updates against a local stand-in for GitHub: checking, the checksum, unpacking safely, installing
with the old version kept, putting it back when the install fails, and going back by hand."""
import hashlib
import http.server
import io
import json
import os
import tarfile
import threading

import pytest

from iridia import updater as U


def _tarball(version="9.9.9", install_rc=0, extra=None):
    buf = io.BytesIO()
    script = ("#!/bin/bash\n[ \"$1\" = --update ] || exit 9\necho installing\n"
              "echo new > \"$VENV_MARK\"\nexit %d\n" % install_rc)
    files = {"iridia/install.sh": script, "iridia/pyproject.toml": f'[project]\nversion = "{version}"\n'}
    files.update(extra or {})
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o755
            tar.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def github(tmp_path, monkeypatch):
    routes = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = routes.get(self.path, (404, b"{}"))
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setattr(U, "STATE", str(tmp_path / "state" / "update.json"))

    def release(version="9.9.9", data=None, digest=True, prerelease=False, path="/releases/latest"):
        data = data if data is not None else _tarball(version)
        routes[f"/dl/iridia-{version}.tar.gz"] = (200, data)
        asset = {"name": f"iridia-{version}.tar.gz", "browser_download_url": f"{base}/dl/iridia-{version}.tar.gz",
                 "size": len(data)}
        if digest:
            asset["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
        rel = {"tag_name": f"v{version}", "body": "What's new", "html_url": "page", "prerelease": prerelease,
               "published_at": "2026-10-20T10:00:00Z", "assets": [asset]}
        routes[path] = (200, json.dumps(rel if path.endswith("latest") else [rel]).encode())
        return rel
    yield base, routes, release
    srv.shutdown()


def test_versions():
    assert U.newer("1.10.0", "1.9.3") and U.newer("v1.3.0", "1.2.1") and not U.newer("1.2.1", "1.2.1")
    assert U.newer("1.3.0", "1.3.0rc1") and not U.newer("1.3.0-beta", "1.3.0")
    assert U.parse_version("junk") == (0, 0, 0, 0)


def test_checking(github):
    base, routes, release = github
    release("9.9.9")
    r = U.check("1.3.0", api=base)
    assert r["available"] and r["latest"]["version"] == "9.9.9" and r["latest"]["notes"] == "What's new"
    assert U.load_state()["last"]["latest"]["version"] == "9.9.9"
    assert not U.check("9.9.9", api=base)["available"]
    routes["/releases/latest"] = (403, b"{}")
    assert "limiting" in U.check("1.3.0", api=base)["error"]
    routes["/releases/latest"] = (200, b"not json")
    assert "didn't make sense" in U.check("1.3.0", api=base)["error"]
    assert "Couldn't reach" in U.check("1.3.0", api="http://127.0.0.1:9")["error"]
    release("10.0.0rc1", prerelease=True, path="/releases?per_page=15")
    assert U.check("9.9.9", prerelease=True, api=base)["latest"]["version"] == "10.0.0rc1"


def test_the_download_must_match_its_checksum(github, tmp_path):
    base, routes, release = github
    release("9.9.9")
    info = U.latest(api=base)
    assert os.path.exists(U.download(info, str(tmp_path / "c"), log=lambda m: None))
    routes["/dl/iridia-9.9.9.tar.gz"] = (200, _tarball("9.9.9") + b"tampered")
    with pytest.raises(U.UpdateError, match="checksum"):
        U.download(info, str(tmp_path / "c"), log=lambda m: None)
    release("9.9.8", digest=False)
    with pytest.raises(U.UpdateError, match="no checksum"):
        U.download(U.latest(api=base), str(tmp_path / "c"), log=lambda m: None)


def test_unpacking_refuses_surprises(tmp_path):
    def try_extract(data, version="9.9.9"):
        p = tmp_path / "a.tar.gz"
        p.write_bytes(data)
        return U.extract(str(p), str(tmp_path / "x"), version)
    assert try_extract(_tarball()).endswith("iridia")
    with pytest.raises(U.UpdateError, match="unexpected"):
        try_extract(_tarball(extra={"../evil": "x"}))
    with pytest.raises(U.UpdateError, match="version"):
        try_extract(_tarball("9.9.9"), version="9.9.10")


def _venv(tmp_path):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "lib" / "python3.12" / "site-packages" / "iridia-1.3.0.dist-info").mkdir(parents=True)
    log = tmp_path / "daemon.log"
    (venv / "bin" / "iridia").write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n")
    (venv / "bin" / "iridia").chmod(0o755)
    (venv / "marker").write_text("old\n")
    return venv, log


def test_installing_keeps_the_old_version_and_going_back(github, tmp_path, monkeypatch):
    base, routes, release = github
    venv, log = _venv(tmp_path)
    monkeypatch.setenv("VENV_MARK", str(venv / "marker"))
    release("9.9.9")
    U.apply(U.latest(api=base), venv=str(venv), folder=str(tmp_path / "c"), log=lambda m: None)
    assert (venv / "marker").read_text() == "new\n"                  # install.sh --update ran
    assert (tmp_path / "venv.prev" / "marker").read_text() == "old\n"  # the old one is kept
    assert U.prev_version(str(venv)) == "1.3.0" and U.load_state()["installed"] == "9.9.9"
    assert U.rollback(str(venv), log=lambda m: None) == "1.3.0"
    assert (venv / "marker").read_text() == "old\n" and (tmp_path / "venv.prev" / "marker").read_text() == "new\n"
    assert log.read_text().split("\n")[-3:-1] == ["daemon stop", "daemon start"]


def test_a_failed_install_puts_the_old_version_back(github, tmp_path, monkeypatch):
    base, routes, release = github
    venv, log = _venv(tmp_path)
    monkeypatch.setenv("VENV_MARK", str(venv / "marker"))
    release("9.9.9", data=_tarball("9.9.9", install_rc=1))
    with pytest.raises(U.UpdateError, match="previous version is back"):
        U.apply(U.latest(api=base), venv=str(venv), folder=str(tmp_path / "c"), log=lambda m: None)
    assert (venv / "marker").read_text() == "old\n"
    assert "daemon start" in log.read_text()
    with pytest.raises(U.UpdateError):
        U.rollback(str(tmp_path / "nothing"), log=lambda m: None)


def test_install_sh_update_needs_an_install(tmp_path):
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(["bash", os.path.join(repo, "install.sh"), "--update"], capture_output=True, text=True,
                       env=dict(os.environ, HOME=str(tmp_path)), timeout=30)
    assert r.returncode == 1 and "needs an existing install" in r.stdout
    r = subprocess.run(["bash", os.path.join(repo, "install.sh"), "--help"], capture_output=True, text=True,
                       timeout=30)
    assert "--update" in r.stdout
