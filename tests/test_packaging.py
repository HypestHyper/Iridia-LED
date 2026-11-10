"""System packages: the layout stage.sh makes, and Iridia knowing it was installed that way."""
import configparser
import os
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
