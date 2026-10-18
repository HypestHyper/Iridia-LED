"""Monitor brightness with ddcutil 1.x and 2.x (fake ones), and a laptop's backlight."""
import os
import time

import pytest

from iridia import ddc as D


@pytest.fixture
def tools(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(D.DDCController, "BACKLIGHT", str(tmp_path / "backlight"))

    def ddcutil(version):
        # 1.x refuses --syslog (it only exists since 2.0)
        (bin_dir / "ddcutil").write_text(f"""#!/bin/sh
case " $* " in *" --syslog "*) [ {version} -lt 2 ] && {{ echo "Unrecognized option --syslog" >&2; exit 1; }} ;; esac
case "$1" in
  --version) echo "ddcutil {version}.4.1" ;;
  detect) printf 'Display 1\\n   I2C bus:  /dev/i2c-6\\n   Monitor:  DEL:DELL U2720Q\\n' ;;
  getvcp) echo "VCP 10 C 42 100" ;;
esac
""")
        (bin_dir / "ddcutil").chmod(0o755)
    return tmp_path, ddcutil


def _wait(c):
    for _ in range(100):
        if c._available or not c._busy.locked() and c.source is not None:
            break
        time.sleep(0.02)
    with c._busy:
        pass


@pytest.mark.parametrize("version", [1, 2])
def test_both_ddcutil_generations(tools, version):
    tmp, ddcutil = tools
    ddcutil(version)
    c = D.DDCController(poll_interval=1)
    _wait(c)
    assert c.is_available() and c.source == "ddc" and c.bus == 6
    assert c._poll() == 42
    assert ("--syslog" in c._quiet) == (version >= 2)


def test_a_laptop_follows_its_backlight(tools):
    tmp, ddcutil = tools
    bl = tmp / "backlight" / "intel_backlight"
    bl.mkdir(parents=True)
    (bl / "max_brightness").write_text("19393\n")
    (bl / "actual_brightness").write_text("9696\n")
    (bl / "type").write_text("raw\n")
    c = D.DDCController(poll_interval=1)              # no ddcutil at all here
    _wait(c)
    assert c.is_available() and c.source == "backlight"
    assert c._poll() == 49
