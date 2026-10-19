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


def _wait(c, done=1):
    for _ in range(250):
        if c.detections >= done:
            return
        time.sleep(0.02)
    raise AssertionError("detection didn't finish")


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


DETECT_2X = """Display 1
   I2C bus:  /dev/i2c-4
   DRM connector:  card1-DP-1
   Monitor:  DEL:DELL U2720Q:ABC123

Display 2
   I2C bus:  /dev/i2c-6
   DRM connector:  card1-HDMI-A-1
   Monitor:  GSM:LG ULTRAGEAR:

Invalid display
   I2C bus:  /dev/i2c-9
   DRM connector:  card1-eDP-1
   Monitor:  BOE::
"""


def test_detect_output_is_read():
    assert D.parse_detect(DETECT_2X) == [
        {"bus": 4, "name": "DELL U2720Q", "connector": "DP-1"},
        {"bus": 6, "name": "LG ULTRAGEAR", "connector": "HDMI-A-1"},
    ]
    assert D.parse_detect("") == []


@pytest.fixture
def two_monitors(tools):
    tmp, _ = tools
    # bus 4 answers only when ANSWER4 is set (DDC/CI switched off in its menu otherwise)
    detect = DETECT_2X.replace("\n", "\\n")
    (tmp / "bin" / "ddcutil").write_text(f"""#!/bin/sh
case "$1" in
  --version) echo "ddcutil 2.1.4" ;;
  detect) printf '{detect}' ;;
  getvcp) case " $* " in *" 4 "*) [ -n "$ANSWER4" ] && echo "VCP 10 C 70 100" ;; *) echo "VCP 10 C 25 100" ;; esac ;;
esac
""")
    (tmp / "bin" / "ddcutil").chmod(0o755)
    return tmp


def test_the_chosen_monitor_and_no_other(two_monitors, monkeypatch):
    monkeypatch.setenv("ANSWER4", "1")
    c = D.DDCController(poll_interval=1)
    _wait(c)
    assert c.bus == 4 and c._poll() == 70                   # automatic: the first that answers
    assert [(d["bus"], d["ok"]) for d in c.displays] == [(4, True), (6, True)]
    c.redetect(6)
    _wait(c, 2)
    assert c.bus == 6 and c._poll() == 25 and c.choice == 6
    # the first one's DDC/CI is off: automatic takes the next, a chosen one isn't swapped for another
    monkeypatch.delenv("ANSWER4")
    c = D.DDCController(poll_interval=1)
    _wait(c)
    assert c.bus == 6
    c = D.DDCController(bus_number=4, poll_interval=1)
    _wait(c)
    assert not c.is_available() and c.get_brightness() is None and "chosen monitor" in c.last_error


def test_no_ddcutil_says_so(tools):
    c = D.DDCController(poll_interval=1)
    _wait(c)
    assert not c.is_available() and c.last_error == "ddcutil isn't installed"


@pytest.mark.parametrize("release, tool, expect", [
    ('NAME="Fedora Linux"\nID=fedora\n', "dnf", ["dnf", "install", "-y", "ddcutil"]),
    ('ID=cachyos\nID_LIKE=arch\n', "pacman", ["pacman", "-S", "--needed", "--noconfirm", "ddcutil"]),
    ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', "apt-get", ["apt-get", "install", "-y", "ddcutil"]),
    ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "zypper",
     ["zypper", "--non-interactive", "install", "ddcutil"]),
])
def test_the_command_that_installs_ddcutil(tools, monkeypatch, release, tool, expect):
    tmp, _ = tools
    (tmp / "os-release").write_text(release)
    monkeypatch.setattr(D, "OS_RELEASE", str(tmp / "os-release"))
    monkeypatch.setenv("PATH", str(tmp / "bin"))
    assert D.install_command() is None                  # its package manager isn't there
    (tmp / "bin" / tool).write_text("#!/bin/sh\n")
    (tmp / "bin" / tool).chmod(0o755)
    assert D.install_command() == expect
    script = D.install_script(expect)
    assert script.startswith(" ".join(expect) + " && ") and "modprobe i2c-dev" in script
