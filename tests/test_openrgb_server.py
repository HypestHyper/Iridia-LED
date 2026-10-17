"""Starting, supervising and restarting OpenRGB, with fake `openrgb` and `systemctl` programs.

tests/fakes/openrgb is a real process that speaks enough of the SDK protocol to report zero
devices (or stays silent, or crashes); tests/fakes/systemctl records its calls. Each test gets
its own HOME, XDG_RUNTIME_DIR and a PATH holding only those fakes and python3.
"""
import json
import os
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from iridia import daemon as daemon_mod
from iridia import diagnostics
from iridia import openrgb_server as osrv
from iridia.config import Config
from iridia.openrgb_ctl import OpenRGBController

FAKES = Path(__file__).parent / "fakes"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _kill_fakes():
    """Stop every fake OpenRGB: python3 running a script called "openrgb" (found by its command
    line too, since a fake only renames itself to "openrgb" once Python has started)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if len(argv) > 1 and os.path.basename(argv[0]).startswith("python") and argv[1].endswith("/openrgb"):
            osrv._terminate(int(pid), wait=2.0, group=False)


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


@pytest.fixture
def env(tmp_path, monkeypatch):
    home, run, bin_ = tmp_path / "home", tmp_path / "run", tmp_path / "bin"
    for d in (home / ".config" / "iridia", run, bin_):
        d.mkdir(parents=True)
    run.chmod(0o700)
    os.symlink(FAKES / "openrgb", bin_ / "openrgb")
    # a wrapper, not a symlink: a symlinked venv Python forgets the venv (and the openrgb library)
    (bin_ / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (bin_ / "python3").chmod(0o755)
    starts, calls = tmp_path / "starts.log", tmp_path / "systemctl.log"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    monkeypatch.setenv("PATH", str(bin_))
    monkeypatch.setenv("FAKE_OPENRGB_LOG", str(starts))
    monkeypatch.setenv("FAKE_SYSTEMCTL_LOG", str(calls))
    for var in ("XDG_CONFIG_HOME", "INVOCATION_ID", "FAKE_OPENRGB_MODE", "FAKE_SYSTEMD", "FAKE_GST",
                "FAKE_ENABLED", "FAKE_ACTIVE"):
        monkeypatch.delenv(var, raising=False)
    unit_dir = home / ".config" / "systemd" / "user"
    monkeypatch.setattr(osrv, "UNIT_DIR", str(unit_dir))
    monkeypatch.setattr(osrv, "UNIT_PATH", str(unit_dir / osrv.UNIT_NAME))
    monkeypatch.setattr(osrv, "LOG_PATH", str(home / ".local" / "share" / "iridia" / "openrgb.log"))
    monkeypatch.setattr("iridia.setups.CONFIG_DIR", str(home / ".config" / "iridia"))
    _kill_fakes()

    def with_systemd(gst="inactive", enabled="", active=""):
        if not (bin_ / "systemctl").exists():
            os.symlink(FAKES / "systemctl", bin_ / "systemctl")
        monkeypatch.setenv("FAKE_SYSTEMD", "1")
        monkeypatch.setenv("FAKE_GST", gst)
        monkeypatch.setenv("FAKE_ENABLED", enabled)
        monkeypatch.setenv("FAKE_ACTIVE", active)

    def config(data):
        (home / ".config" / "iridia" / "config.json").write_text(json.dumps(data))

    def starts_():
        return starts.read_text().splitlines() if starts.exists() else []

    def calls_():
        return calls.read_text() if calls.exists() else ""

    def foreign(*args):
        """An OpenRGB that Iridia didn't start."""
        p = subprocess.Popen([str(bin_ / "openrgb"), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert wait_for(lambda: any(pid == p.pid for pid, _ in osrv.processes()))
        return p

    yield SimpleNamespace(home=home, run=run, bin=bin_, port=_free_port(), with_systemd=with_systemd,
                          config=config, starts=starts_, calls=calls_, foreign=foreign)
    _kill_fakes()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _sup(clock=None):
    return osrv.Supervisor(clock=clock or Clock())


# ------------------------------------------------------------- settings

def test_start_method_migrates_from_start_server(env):
    env.config({"openrgb": {"start_server": False}})
    cfg = Config()
    assert cfg.get("openrgb.start_method") == "off"
    assert "start_server" not in cfg.get("openrgb")
    env.config({"openrgb": {"start_server": True}})
    assert Config().get("openrgb.start_method") == "daemon"
    env.config({"openrgb": {"start_method": "sometimes"}})
    assert Config().get("openrgb.start_method") == "daemon"
    assert osrv.method_of({"start_server": False}) == "off"
    assert osrv.method_of({"start_method": "systemd"}) == "systemd"


def test_command_passes_the_port_and_custom_command(env):
    assert osrv.command() == [str(env.bin / "openrgb"), "--server"]
    assert osrv.command(port=6800)[-2:] == ["--server-port", "6800"]
    assert osrv.command("/opt/OpenRGB.AppImage --server", 6800) == [
        "/opt/OpenRGB.AppImage", "--server", "--server-port", "6800"]
    os.remove(env.bin / "openrgb")
    assert osrv.command() == []


# ----------------------------------------------------- the "daemon" method

def test_waits_for_the_grace_then_starts_and_remembers_it(env):
    clock = Clock()
    sup = _sup(clock)
    sup.tick("daemon", "127.0.0.1", False, "", env.port)
    time.sleep(0.3)
    assert env.starts() == []                       # login's own startup gets a chance first
    clock.t += osrv.Supervisor.QUICK_SEC + 0.5      # nothing else starts OpenRGB: no 10 s wait
    sup.tick("daemon", "127.0.0.1", False, "", env.port)
    assert wait_for(lambda: len(env.starts()) == 1)
    assert env.starts()[0].endswith(f"--server --server-port {env.port}")
    assert osrv.read_pid() == sup.pid and sup.alive()
    assert stat.S_IMODE(os.stat(osrv.pid_path()).st_mode) == 0o600
    assert wait_for(lambda: "fake openrgb" in Path(osrv.LOG_PATH).read_text())
    sup.tick("daemon", "127.0.0.1", False, "", env.port)    # still starting up: no second one
    time.sleep(0.3)
    assert len(env.starts()) == 1


def test_a_restarted_daemon_reuses_the_running_server(env):
    clock = Clock()
    sup = _sup(clock)
    clock.t += 100
    sup.tick("daemon", "127.0.0.1", False, "", env.port)
    assert wait_for(lambda: osrv.read_pid() == sup.pid)
    again = _sup(Clock())
    assert again.pid == sup.pid
    again._clock.t += 100
    again.tick("daemon", "127.0.0.1", False, "", env.port)
    time.sleep(0.3)
    assert len(env.starts()) == 1


def test_restarts_a_crashing_server_with_backoff_then_gives_up(env, monkeypatch):
    monkeypatch.setenv("FAKE_OPENRGB_MODE", "crash")
    clock = Clock()
    sup = _sup(clock)
    clock.t += 100
    when, last = [], None
    for _ in range(200):
        sup.tick("daemon", "127.0.0.1", False, "", env.port)
        if sup._proc is not None and sup._proc.pid != last:
            last = sup._proc.pid
            when.append(clock.t)
            sup._proc.wait(5)               # the fake crashes right away
        if sup.gave_up:
            break
        clock.t += 1
    assert sup.gave_up
    assert len(env.starts()) == 1 + len(osrv.Supervisor.BACKOFF)
    gaps = [b - a for a, b in zip(when, when[1:])]
    assert gaps == [pytest.approx(w, abs=1.01) for w in osrv.Supervisor.BACKOFF]
    clock.t += 10000
    sup.tick("daemon", "127.0.0.1", False, "", env.port)
    time.sleep(0.3)
    assert len(env.starts()) == 4                   # gave up: no more tries
    assert osrv.read_pid() is None


def test_never_starts_a_second_openrgb(env):
    window = env.foreign()                          # the OpenRGB window, SDK server off
    assert osrv.window_without_server()
    clock = Clock()
    sup = _sup(clock)
    clock.t += 100
    sup.tick("daemon", "127.0.0.1", False, "", env.port)
    time.sleep(0.3)
    assert len(env.starts()) == 1 and sup.pid is None
    window.terminate()
    window.wait(5)


def test_off_and_remote_hosts_never_start_anything(env):
    clock = Clock()
    sup = _sup(clock)
    clock.t += 100
    sup.tick("off", "127.0.0.1", False, "", env.port)
    sup.tick("daemon", "192.168.1.20", False, "", env.port)
    time.sleep(0.3)
    assert env.starts() == []


def test_leaves_it_to_another_starter_until_that_is_turned_off(env):
    auto = env.home / ".config" / "autostart"
    auto.mkdir(parents=True)
    entry = auto / "OpenRGB.desktop"
    entry.write_text("[Desktop Entry]\nType=Application\nName=OpenRGB\nExec=/usr/bin/openrgb\n")
    assert osrv.others() == ["~/.config/autostart/OpenRGB.desktop"]
    clock = Clock()
    sup = _sup(clock)
    clock.t += 100
    sup.tick("daemon", "127.0.0.1", False, "", env.port)
    time.sleep(0.3)
    assert env.starts() == []
    ok, _msg = osrv.hide_xdg_entry(str(entry))
    assert ok and "Hidden=true" in entry.read_text() and entry.exists()
    assert osrv.xdg_entries() == []
    clock.t += osrv.Supervisor.OTHERS_TTL + 1        # the cached scan expires
    sup.tick("daemon", "127.0.0.1", False, "", env.port)
    assert wait_for(lambda: len(env.starts()) == 1)


def test_hide_refuses_files_outside_autostart(env, tmp_path):
    other = tmp_path / "x.desktop"
    other.write_text("[Desktop Entry]\nExec=openrgb\n")
    assert not osrv.hide_xdg_entry(str(other))[0]
    assert "Hidden" not in other.read_text()


def test_not_installed_starts_nothing(env):
    os.remove(env.bin / "openrgb")
    clock = Clock()
    sup = _sup(clock)
    clock.t += 100
    sup.tick("daemon", "127.0.0.1", False, "", env.port)
    assert sup.pid is None and "isn't installed" in sup._said


# ------------------------------------------------------------- restarts

def test_restarts_only_its_own_server(env):
    stranger = env.foreign("--server", "--server-port", str(env.port))
    sup = _sup()
    assert sup.owner("daemon") == ""
    assert sup.restart("daemon", "test", "", env.port) is False
    assert stranger.poll() is None                  # left alone
    stranger.terminate()
    stranger.wait(5)

    sup.spawn(osrv.command("", env.port), "test")
    old = sup.pid
    assert sup.owner("daemon") == "pid" and sup.owner("off") == ""
    assert sup.restart("daemon", "test", "", env.port)
    assert sup.pid != old and osrv.read_pid() == sup.pid
    assert wait_for(lambda: osrv._start_time(old) is None)


def test_an_explicit_restart_replaces_a_headless_server(env):
    stranger = env.foreign("--server", "--server-port", str(env.port))
    window = env.foreign()                          # never touched
    sup = _sup()
    assert sup.take_over("Restart requested", "", env.port)
    assert stranger.wait(5) is not None
    assert window.poll() is None
    assert sup.owner("daemon") == "pid"
    window.terminate()
    window.wait(5)


# ---------------------------------------------- zero devices (the boot bug)

def _daemon(env, monkeypatch, retry=0.1):
    from tests.test_daemon import FakeDDC
    env.config({"openrgb": {"port": env.port}, "ddc": {"enabled": False},
                "timing": {"openrgb_retry_interval_sec": retry}})
    monkeypatch.setattr(daemon_mod, "DDCController", FakeDDC)
    monkeypatch.setattr(osrv.Supervisor, "GRACE_SEC", 0.0)
    monkeypatch.setattr(daemon_mod.Daemon, "NODEV_FIRST_SEC", 0.6)
    monkeypatch.setattr(daemon_mod.Daemon, "NODEV_AGAIN_SEC", 0.6)
    monkeypatch.setattr(daemon_mod.Daemon, "RESTART_SETTLE_SEC", 0.1)
    return daemon_mod.Daemon()


def _run(d, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        d._tick()
        time.sleep(0.05)


def test_daemon_restarts_its_own_openrgb_that_sees_no_devices(env, monkeypatch):
    d = _daemon(env, monkeypatch)
    try:
        _run(d, 6)
        assert len(env.starts()) == 1 + d.NODEV_MAX     # started, then restarted twice, then stops
        assert d._nodev_restarts == d.NODEV_MAX
        assert "no devices" in (d.openrgb.last_error or "")
        assert d.handle_command({"cmd": "status"})["openrgb_ours_pid"] == osrv.read_pid()
    finally:
        d.ipc.stop()


def test_daemon_leaves_a_foreign_openrgb_with_no_devices_alone(env, monkeypatch):
    stranger = env.foreign("--server", "--server-port", str(env.port))
    d = _daemon(env, monkeypatch)
    try:
        _run(d, 3)
        assert len(env.starts()) == 1 and stranger.poll() is None
        assert d._nodev_restarts == 0
        assert "won't restart it" in d._said.get("nodev", "")
        resp = d.handle_command({"cmd": "restart_openrgb_server"})     # an explicit click may
        assert resp["ok"]
        assert stranger.wait(5) is not None
        assert wait_for(lambda: len(env.starts()) == 2)
    finally:
        d.ipc.stop()
        stranger.kill()


def test_restart_click_with_method_off_does_nothing(env, monkeypatch):
    d = _daemon(env, monkeypatch)
    try:
        d.config.set("openrgb.start_method", "off")
        assert not d.handle_command({"cmd": "restart_openrgb_server"})["ok"]
        _run(d, 1)
        assert env.starts() == []
    finally:
        d.ipc.stop()


def test_port_probe_runs_once(env, monkeypatch):
    stranger = env.foreign("--server", "--server-port", str(env.port))
    ctl = OpenRGBController()
    monkeypatch.setattr(ctl, "COMMON_PORTS", [env.port])
    probes = []
    real = ctl._detect_port
    monkeypatch.setattr(ctl, "_detect_port", lambda: probes.append(1) or real())
    for _ in range(3):
        ctl._last_connect_attempt = 0
        assert ctl.ensure_connected(retry_interval=0) is False      # zero devices: dropped
    assert probes == [1] and ctl.port == env.port
    assert ctl.no_devices_since is not None
    stranger.terminate()
    stranger.wait(5)


# ------------------------------------------------------ systemd and setup

OLD_UNIT = f"""{osrv.MARKER} (`iridia openrgb enable`); removed by `iridia openrgb disable` and on uninstall.
[Unit]
Description=OpenRGB SDK server (started by Iridia)
[Service]
ExecStart=/usr/bin/openrgb --server
[Install]
WantedBy=default.target
"""


def _write_unit(text):
    os.makedirs(osrv.UNIT_DIR, exist_ok=True)
    Path(osrv.UNIT_PATH).write_text(text)


def test_migration_removes_the_old_unit(env):
    env.with_systemd()
    _write_unit(OLD_UNIT)
    msg = osrv.migrate("daemon")
    assert "Removed" in msg and not os.path.exists(osrv.UNIT_PATH)
    assert "disable --now iridia-openrgb.service" in env.calls()


def test_migration_never_touches_a_unit_iridia_did_not_write(env):
    env.with_systemd()
    _write_unit("[Service]\nExecStart=/usr/bin/openrgb --server\n")
    assert "leaving it alone" in osrv.migrate("daemon")
    assert os.path.exists(osrv.UNIT_PATH) and "disable" not in env.calls()


def test_migration_works_without_systemd(env):
    _write_unit(OLD_UNIT)
    osrv.migrate("daemon")
    assert not os.path.exists(osrv.UNIT_PATH)


def test_migration_updates_a_chosen_systemd_unit(env):
    env.with_systemd(gst="active")
    _write_unit(OLD_UNIT)
    osrv.migrate("systemd")
    text = Path(osrv.UNIT_PATH).read_text()
    assert "WantedBy=graphical-session.target" in text and "After=graphical-session.target" in text
    assert "sleep 3" in text and "reenable iridia-openrgb.service" in env.calls()


def test_switching_to_systemd_stops_the_daemons_server(env):
    env.with_systemd(gst="inactive")
    sup = _sup()
    sup.spawn(osrv.command("", env.port), "test")
    ok, msgs = osrv.set_method("systemd", "daemon")
    assert ok and osrv.read_pid() is None
    assert "WantedBy=graphical-session.target" in Path(osrv.UNIT_PATH).read_text()
    assert any("graphical-session.target" in m for m in msgs)      # warned: never reached here
    ok, _ = osrv.set_method("daemon", "systemd")
    assert ok and not os.path.exists(osrv.UNIT_PATH)


def test_leaving_daemon_keeps_its_server_unless_asked(env):
    sup = _sup()
    sup.spawn(osrv.command("", env.port), "test")
    ok, msgs = osrv.set_method("off", "daemon", stop_running=False)
    assert ok and sup.alive() and "keeps running" in msgs[0]
    ok, _ = osrv.set_method("off", "daemon", stop_running=True)
    assert ok and wait_for(lambda: not sup.alive())


def test_systemd_method_without_systemd_is_refused(env):
    from iridia import cli
    env.config({})
    assert cli.set_start_method("systemd") == 1
    assert cli.set_start_method("off", stop=False) == 0
    assert Config().get("openrgb.start_method") == "off"


# --------------------------------------------------------------- doctor

def test_doctor_names_a_second_starter(env):
    auto = env.home / ".config" / "autostart"
    auto.mkdir(parents=True)
    (auto / "OpenRGB.desktop").write_text("[Desktop Entry]\nExec=/usr/bin/openrgb\n")
    checks = diagnostics.openrgb_login_checks({"openrgb_host": "127.0.0.1"})
    bad = [c for c in checks if c.label == "Other OpenRGB starters"]
    assert bad and bad[0].ok is False and "hide-autostart" in bad[0].hint


def test_doctor_warns_when_the_unit_can_never_start(env):
    env.with_systemd(gst="inactive")
    env.config({"openrgb": {"start_method": "systemd"}})
    _write_unit(OLD_UNIT)
    checks = diagnostics.openrgb_login_checks({"openrgb_host": "127.0.0.1"})
    assert any(c.ok is False and "graphical-session.target" in c.detail for c in checks)


def test_doctor_does_not_call_a_running_daemon_inactive(env):
    env.with_systemd(enabled="iridia-daemon.service")
    checks = diagnostics.daemon_login_checks({"started_by": "Hyprland"})
    started = [c for c in checks if c.label == "Daemon started"][0]
    assert started.ok is True and "started outside systemd" in started.detail
    assert not any("inactive" in c.detail for c in checks)



def test_a_server_stopped_by_a_method_change_is_not_a_crash(env):
    clock = Clock()
    sup = _sup(clock)
    sup.spawn(osrv.command("", env.port), "test")
    assert wait_for(lambda: len(env.starts()) == 1)
    osrv.stop_ours()
    sup.tick("off", "127.0.0.1", False, "", env.port)
    assert sup.pid is None and sup.failures == 0
    clock.t += 100
    sup.tick("daemon", "127.0.0.1", False, "", env.port)    # back to daemon: starts right away
    assert wait_for(lambda: len(env.starts()) == 2) and sup.failures == 0


@pytest.mark.parametrize("protocol", [3, 6])
def test_daemon_animates_real_devices_over_the_sdk(env, monkeypatch, tmp_path, protocol):
    """The whole path: the daemon starts a fake OpenRGB with devices, finds their zones, and streams
    animation frames to it as SDK packets: with Iridia's own client (protocol 6, OpenRGB 1.0) and
    with openrgb-python (an older OpenRGB)."""
    packets = tmp_path / "packets.log"
    monkeypatch.setenv("FAKE_OPENRGB_MODE", "devices")
    monkeypatch.setenv("FAKE_OPENRGB_PACKETS", str(packets))
    monkeypatch.setenv("FAKE_OPENRGB_PROTOCOL", str(protocol))
    d = _daemon(env, monkeypatch)
    try:
        for _ in range(100):
            d._tick()
            if d.openrgb.devices:
                break
            time.sleep(0.05)
        assert set(d.openrgb.devices) == {"Fake ARGB Controller", "Fake RAM"}
        assert d.openrgb.protocol == (6 if protocol == 6 else 0)
        assert d.handle_command({"cmd": "status"})["openrgb_protocol"] == d.openrgb.protocol
        assert d.handle_command({"cmd": "set_all", "field": "animation", "value": {"effect": "rainbow"}})["ok"]
        _run(d, 1.5)
        kinds = [ln.split()[:2] for ln in packets.read_text().splitlines()]
        whole = sum(1 for k in kinds if k == ["1050", "0"])        # one packet per device and frame
        ram = sum(1 for k in kinds if k == ["1050", "1"])
        assert whole >= 20 and ram >= 20, (whole, ram)
        first = kinds.index(["1050", "0"])
        assert not any(k[0] == "1051" for k in kinds[first:])      # never zone by zone (OpenRGB queues those)
        assert ["1101", "0"] in kinds                               # Direct mode was set first
    finally:
        d._animator.stop()
        d.ipc.stop()



def test_a_slow_controller_never_builds_a_backlog(env, monkeypatch, tmp_path):
    """OpenRGB 1.0 queues every colour update per controller and writes them one by one, telling
    only protocol 6 clients when one is written. A controller slower than the frame rate let frames
    pile up: going back to static showed up a minute late. Frames now go over a protocol 6
    connection, one written frame at a time."""
    packets = tmp_path / "packets.log"
    monkeypatch.setenv("FAKE_OPENRGB_MODE", "devices")
    monkeypatch.setenv("FAKE_OPENRGB_PACKETS", str(packets))
    monkeypatch.setenv("FAKE_OPENRGB_UPDATE_DELAY", "0.05")        # 20 colour packets a second at most
    monkeypatch.setenv("FAKE_OPENRGB_PROTOCOL", "6")                # like OpenRGB 1.0
    d = _daemon(env, monkeypatch)
    try:
        for _ in range(100):
            d._tick()
            if d.openrgb.devices:
                break
            time.sleep(0.05)
        d.handle_command({"cmd": "animations", "fps": 60})
        # only one of the controller's two channels animates: it still goes as whole-device updates
        assert d.handle_command({"cmd": "set_zone_animation", "device": "Fake ARGB Controller",
                                 "zone": "Channel 1", "animation": {"effect": "rainbow"}})["ok"]
        assert d.handle_command({"cmd": "set_zone_animation", "device": "Fake RAM", "zone": "Stick",
                                 "animation": {"effect": "rainbow"}})["ok"]
        _run(d, 3.0)
        assert d.openrgb.protocol == 6                              # Iridia's own client: every frame acknowledged
        assert d.handle_command({"cmd": "set_all", "field": "animation", "value": None})["ok"]
        stopped = time.time()
        _run(d, 1.5)
        d._animator.stop()
        times = [float(ln.split()[3]) for ln in packets.read_text().splitlines() if ln.split()[0] in ("1050", "1051")]
        assert times and max(times) - stopped < 0.6, max(times) - stopped   # caught up at once
    finally:
        d._animator.stop()
        d.ipc.stop()


def test_run_by_systemd_is_the_service_itself_not_its_children(monkeypatch):
    monkeypatch.setenv("INVOCATION_ID", "abc")
    monkeypatch.setenv("SYSTEMD_EXEC_PID", str(os.getpid()))
    assert osrv.run_by_systemd()
    monkeypatch.setenv("SYSTEMD_EXEC_PID", "1")         # a compositor under UWSM passed it on
    assert not osrv.run_by_systemd()
    monkeypatch.delenv("SYSTEMD_EXEC_PID")
    monkeypatch.delenv("INVOCATION_ID")
    assert not osrv.run_by_systemd()
