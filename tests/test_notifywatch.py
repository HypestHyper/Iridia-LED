"""Notifications from the bus: real dbus-monitor and busctl output (captured from a private session bus
with gdbus sending Notify and GNOME's AddNotification), and the watcher with fake tools."""
import os
import time
from pathlib import Path

from iridia import notifywatch as N

DATA = Path(__file__).parent / "data"
EXPECT = [("Signal", True), ("Thunderbird", False), ("org.gnome.Calendar", True)]


def test_dbus_monitor_output():
    p = N.MonitorParser()
    got = [ev for line in (DATA / "dbus-monitor-notify.txt").read_text().splitlines(True)
           if (ev := p.feed(line)) is not None]
    assert got == EXPECT


def test_busctl_output():
    got = [ev for line in (DATA / "busctl-notify.jsonl").read_text().splitlines()
           if (ev := N.busctl_event(line)) is not None]
    assert got == EXPECT
    assert N.busctl_event("Monitoring bus message stream.") is None and N.busctl_event("{bad") is None


def test_the_watcher_runs_only_while_needed(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "dbus-monitor").write_text("#!/bin/sh\ncat '%s'\nsleep 30\n" % (DATA / "dbus-monitor-notify.txt"))
    (bin_dir / "dbus-monitor").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    got = []
    w = N.NotifyWatcher(lambda app, urgent: got.append((app, urgent)))
    w.set_needed(True)
    assert w.running and w.method == "dbus-monitor"
    for _ in range(100):
        if len(got) == 3:
            break
        time.sleep(0.02)
    assert got == EXPECT
    w.set_needed(False)
    assert not w.running and w._proc is None


def test_nothing_to_listen_with(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    w = N.NotifyWatcher(lambda *a: None)
    w.set_needed(True)
    assert not w.running and w.method is None


def test_iridias_own_notifications_are_skipped():
    assert "iridia" in N.OWN_APPS
