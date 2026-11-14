"""System packages: the layout stage.sh makes, and Iridia knowing it was installed that way."""
import configparser
import os
import types
import subprocess

import iridia
from iridia import diagnostics, updater

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_stage_lays_out_usr(tmp_path):
    subprocess.run(["sh", os.path.join(ROOT, "packaging", "stage.sh"), str(tmp_path)], check=True)
    usr = tmp_path / "usr"
    assert (usr / "lib/iridia/iridia/__init__.py").is_file()
    assert not list((usr / "lib/iridia").rglob("__pycache__"))           # made after installing
    for name, mod in (("iridia", "iridia.cli"), ("iridia-gui", "iridia.gui"), ("iridia-daemon", "iridia.daemon")):
        exe = usr / "bin" / name
        assert os.access(exe, os.X_OK)
        text = exe.read_text()
        assert text.startswith("#!/usr/bin/python3\n") and f"from {mod} import main" in text
        compile(text, str(exe), "exec")
    unit = configparser.ConfigParser(strict=False)
    unit.read(usr / "lib/systemd/user/iridia-daemon.service")
    assert unit["Service"]["ExecStart"] == "/usr/bin/iridia-daemon"
    desktop = (usr / "share/applications/io.github.HypestHyper.Iridia.desktop").read_text()
    assert "\nExec=/usr/bin/iridia-gui\n" in desktop
    for f in ("share/metainfo/io.github.HypestHyper.Iridia.metainfo.xml", "share/icons/hicolor/scalable/apps/iridia.svg",
              "share/icons/hicolor/256x256/apps/iridia.png", "share/licenses/iridia/LICENSE"):
        assert (usr / f).is_file(), f


def test_the_launchers_find_iridia_and_pass_it_on(tmp_path):
    """The launcher's sys.path and PYTHONPATH lines, run against a staged copy."""
    subprocess.run(["sh", os.path.join(ROOT, "packaging", "stage.sh"), str(tmp_path)], check=True)
    lib = str(tmp_path / "usr/lib/iridia")
    text = (tmp_path / "usr/bin/iridia").read_text().replace('"/usr/lib/iridia"', repr(lib))
    text = text.replace("from iridia.cli import main", "import iridia; print(iridia.__file__, os.environ['PYTHONPATH'])")
    text = text.replace("sys.exit(main())", "")
    out = subprocess.run(["python3", "-c", text], capture_output=True, text=True, check=True,
                         env={"PATH": os.environ["PATH"]}).stdout
    assert out.startswith(lib) and out.split()[1] == lib


def test_install_kind(monkeypatch, tmp_path):
    assert updater.install_kind() in ("venv", "source")                  # this checkout
    here = os.path.dirname(os.path.dirname(os.path.realpath(iridia.__file__)))
    monkeypatch.setattr(updater, "PACKAGE_DIR", here)
    assert updater.install_kind() == "package"


def test_package_commands(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: "/usr/bin/" + t if t == "apt" else None)
    assert updater.package_manager() == "sudo apt install ./iridia_*.deb"
    assert updater.package_remove_command() == "sudo apt remove iridia"
    monkeypatch.setattr("shutil.which", lambda t: None)
    assert updater.package_manager() == "" and updater.package_remove_command() == ""


def test_doctor_sees_two_copies(monkeypatch, tmp_path):
    venv = tmp_path / "iridia-venv"
    venv.mkdir()
    monkeypatch.setattr(updater, "install_kind", lambda: "package")
    (check,) = diagnostics.two_installs_check(str(venv))
    assert check.ok is False and "uninstall --keep-settings" in check.hint
    assert diagnostics.two_installs_check(str(tmp_path / "none")) == []
    monkeypatch.setattr(updater, "install_kind", lambda: "venv")
    assert diagnostics.two_installs_check(str(venv)) == []


def test_nfpm_config_has_what_build_fills_in():
    text = open(os.path.join(ROOT, "packaging", "nfpm.yaml")).read()
    assert '"@VERSION@"' in text and '"@STAGE@/usr/"' in text
    pkgbuild = open(os.path.join(ROOT, "packaging", "arch", "PKGBUILD")).read()
    assert f"pkgver={iridia.VERSION}" in pkgbuild


def _info(tmp_path, data=b"pkg-bytes"):
    import hashlib
    rel = {"tag_name": "v9.9.9", "body": "", "html_url": "https://x/rel", "published_at": "2026-11-12",
           "assets": [{"name": "iridia-9.9.9.tar.gz", "browser_download_url": "https://x/t", "size": 1,
                       "digest": "sha256:" + "0" * 64},
                      {"name": "iridia-9.9.9-1-any.pkg.tar.zst", "browser_download_url": "https://x/a",
                       "size": len(data), "digest": "sha256:" + hashlib.sha256(data).hexdigest()}]}
    return updater._release_info(rel)


def test_a_release_names_its_packages(tmp_path):
    info = _info(tmp_path)
    assert updater.package_file(info, "arch")["url"] == "https://x/a"
    assert updater.package_file(info, "deb") is None                    # this release has no .deb


def test_a_package_update(monkeypatch, tmp_path):
    info = _info(tmp_path)
    monkeypatch.setattr(updater, "_get", lambda url, timeout=0: b"pkg-bytes")
    ran = []
    monkeypatch.setattr(updater, "_run", lambda cmd, log, cwd=None: ran.append(cmd) or 0)
    monkeypatch.setattr(updater.os, "geteuid", lambda: 1000)
    monkeypatch.setattr("shutil.which", lambda t: "/usr/bin/" + t)
    updater.apply_package(info, folder=str(tmp_path), log=lambda m: None, fmt="arch")
    path = str(tmp_path / "iridia-9.9.9-1-any.pkg.tar.zst")
    assert open(path, "rb").read() == b"pkg-bytes"
    assert ran[0] == ["pkexec", "pacman", "-U", "--noconfirm", path]      # as root, through the password prompt
    assert ran[1][1:] == ["daemon", "stop"] and ran[2][1:] == ["daemon", "start"]


def test_a_package_update_that_cant_go_ahead(monkeypatch, tmp_path):
    import pytest
    info = _info(tmp_path)
    monkeypatch.setattr(updater.os, "geteuid", lambda: 1000)
    monkeypatch.setattr("shutil.which", lambda t: "/usr/bin/" + t)
    monkeypatch.setattr(updater, "_get", lambda url, timeout=0: b"changed on the way")
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.apply_package(info, folder=str(tmp_path), log=lambda m: None, fmt="arch")
    monkeypatch.setattr(updater, "_get", lambda url, timeout=0: b"pkg-bytes")
    monkeypatch.setattr(updater, "_run", lambda cmd, log, cwd=None: 126)  # the password prompt closed
    with pytest.raises(updater.UpdateError, match="sudo pacman -U"):
        updater.apply_package(info, folder=str(tmp_path), log=lambda m: None, fmt="arch")
    with pytest.raises(updater.UpdateError, match="no deb package"):
        updater.apply_package(info, folder=str(tmp_path), log=lambda m: None, fmt="deb")


def test_the_notifications_update_button(monkeypatch, tmp_path):
    fake = tmp_path / "gdbus"
    fake.write_text("#!/bin/sh\necho \"/org/freedesktop/Notifications: org.freedesktop.Notifications.ActionInvoked "
                    "(uint32 6, 'update')\"\necho \"/org/freedesktop/Notifications: "
                    "org.freedesktop.Notifications.ActionInvoked (uint32 7, 'update')\"\nsleep 5\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert updater.wait_for_update_button(7, timeout=4) is True               # its own, not another's
    fake.write_text("#!/bin/sh\necho \"/org/freedesktop/Notifications: org.freedesktop.Notifications."
                    "NotificationClosed (uint32 7, uint32 2)\"\nsleep 5\n")
    assert updater.wait_for_update_button(7, timeout=4) is False              # closed without updating


def test_the_update_notification_goes_away_by_itself(monkeypatch):
    """The server's own timeout, like any notification: not 0 (never) and not resident."""
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="(uint32 42,)\n", stderr="")
    monkeypatch.setattr(updater.subprocess, "run", run)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    assert updater.notify_with_update("Iridia 9.9 is available", "body") == 42
    assert seen["cmd"][-1] == "-1" and "resident" not in seen["cmd"][-2]


def test_no_release_checked_yet():
    assert updater.package_file({}, "arch") is None and updater.package_file(None, "deb") is None
