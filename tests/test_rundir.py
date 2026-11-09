"""The runtime folder: never the shared /tmp."""
import os

from iridia import rundir


def test_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    assert rundir.runtime_dir() == str(tmp_path / "xdg")
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(rundir, "_private", lambda p: False)       # no /run/user/UID
    d = rundir.runtime_dir()
    assert d == str(tmp_path / "home" / ".cache" / "iridia" / "run")
    assert os.stat(d).st_mode & 0o777 == 0o700
    assert rundir.runtime_path("x.sock") == os.path.join(d, "x.sock")


def test_private(tmp_path):
    ok = tmp_path / "ok"
    ok.mkdir(mode=0o700)
    assert rundir._private(str(ok))
    open_ = tmp_path / "open"
    open_.mkdir()
    open_.chmod(0o777)
    assert not rundir._private(str(open_))
    link = tmp_path / "link"
    link.symlink_to(ok)
    assert not rundir._private(str(link))
    assert not rundir._private(str(tmp_path / "missing"))
