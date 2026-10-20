"""Desktop notifications, as they're sent: which app, and whether it's urgent. Nothing else is kept
(not the title, not the text).

Every desktop shows notifications the same way: apps call Notify on org.freedesktop.Notifications on
the session bus, and whoever shows them (GNOME Shell, Plasma, XFCE, mako, dunst, SwayNC, Noctalia,
...) answers there. GNOME's own apps, and Flatpak apps on GNOME, use org.gtk.Notifications
(AddNotification) instead. Both are watched as messages go by: `dbus-monitor` (the dbus tools), or
`busctl --user monitor` (systemd) where that's missing, as on Fedora without dbus-tools. Nothing runs
until something asks for notifications.

Do Not Disturb isn't on the bus: dnd_on() asks the desktops that say (GNOME, KDE, mako, dunst, SwayNC).
"""
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, List, Optional

logger = logging.getLogger("iridia")

FD, GTK = "org.freedesktop.Notifications", "org.gtk.Notifications"
OWN_APPS = {"iridia", "io.github.hypesthyper.iridia"}      # Iridia's own (update notices): never flashed
_STR = re.compile(r'^string "(.*)"$')


class MonitorParser:
    """Reads `dbus-monitor --session` output line by line; feed() returns (app, urgent) when a
    notification is complete, else None. dbus-monitor prints the message header at the line start and
    each argument indented by three spaces (what's inside an argument by more)."""

    def __init__(self):
        self._cur = None

    def feed(self, line: str):
        line = line.rstrip("\n")
        if line and not line[0].isspace():
            self._cur = None
            if line.startswith("method call") and "member=Notify" in line and FD in line:
                self._cur = {"kind": "fd", "args": 0, "app": "", "urgent": False, "key": None}
            elif line.startswith("method call") and "member=AddNotification" in line and GTK in line:
                self._cur = {"kind": "gtk", "args": 0, "app": "", "urgent": False, "key": None}
            return None
        c = self._cur
        if c is None:
            return None
        s = line.strip()
        top = line.startswith("   ") and not line.startswith("    ")
        if top and s not in ("]", ")"):
            c["args"] += 1
            if c["args"] == 1:
                m = _STR.match(s)
                c["app"] = m.group(1) if m else ""
        m = _STR.match(s)
        if m and m.group(1) in ("urgency", "priority"):
            c["key"] = m.group(1)
        elif c["key"] and s.startswith("variant"):
            if c["key"] == "urgency":
                b = re.search(r"byte (\d+)", s)
                c["urgent"] = bool(b) and int(b.group(1)) >= 2
            else:
                c["urgent"] = '"urgent"' in s or '"high"' in s
            c["key"] = None
        done = (c["kind"] == "fd" and top and s.startswith("int32") and c["args"] >= 8) or \
               (c["kind"] == "gtk" and top and s == "]" and c["args"] >= 3)
        if done:
            self._cur = None
            return c["app"], c["urgent"]
        return None


def busctl_event(line: str):
    """One line of `busctl --user monitor --json=short`: (app, urgent) for a notification, else None."""
    if not line.startswith("{"):
        return None
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    if msg.get("type") != "method_call":
        return None
    data = (msg.get("payload") or {}).get("data") or []
    member, iface = msg.get("member"), msg.get("interface")
    if member == "Notify" and iface == FD and len(data) >= 7:
        hints = data[6] if isinstance(data[6], dict) else {}
        u = hints.get("urgency") or {}
        return str(data[0] or ""), isinstance(u, dict) and isinstance(u.get("data"), int) and u["data"] >= 2
    if member == "AddNotification" and iface == GTK and len(data) >= 3:
        info = data[2] if isinstance(data[2], dict) else {}
        pr = info.get("priority") or {}
        return str(data[0] or ""), isinstance(pr, dict) and pr.get("data") in ("urgent", "high")
    return None


def monitor_command() -> Optional[List[str]]:
    if shutil.which("dbus-monitor"):
        return ["dbus-monitor", "--session",
                f"type='method_call',interface='{FD}',member='Notify'",
                f"type='method_call',interface='{GTK}',member='AddNotification'"]
    if shutil.which("busctl"):
        return ["busctl", "--user", "monitor", "--json=short", FD, GTK]
    return None


class NotifyWatcher:
    """Calls on_notify(app, urgent) for every notification while running; started and stopped with
    set_needed() (each daemon tick), so nothing runs unless notifications are wanted."""

    def __init__(self, on_notify: Callable[[str, bool], None]):
        self._on_notify = on_notify
        self._lock = threading.Lock()
        self._gen = 0
        self._proc: Optional[subprocess.Popen] = None
        self.running = False
        self.method: Optional[str] = None           # "dbus-monitor" or "busctl"; None: can't listen here

    def set_needed(self, on: bool):
        with self._lock:
            if on and not self.running:
                cmd = monitor_command()
                self.method = cmd[0] if cmd else None
                if cmd is None:
                    return
                self.running = True
                self._gen += 1
                threading.Thread(target=self._loop, args=(cmd, self._gen), daemon=True,
                                 name="notifywatch").start()
                logger.info(f"Listening for notifications ({cmd[0]})")
            elif not on and self.running:
                self.running = False
                self._gen += 1
                self._kill()

    def stop(self):
        self.set_needed(False)

    def _kill(self):
        p, self._proc = self._proc, None
        if p is not None and p.poll() is None:
            p.terminate()

    def _loop(self, cmd, gen):
        backoff = 2.0
        while gen == self._gen:
            start = time.monotonic()
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL, text=True, bufsize=1)
            except OSError:
                return
            with self._lock:
                if gen != self._gen:
                    p.terminate()
                    return
                self._proc = p
            parser = MonitorParser() if cmd[0] == "dbus-monitor" else None
            for line in p.stdout:
                if gen != self._gen:
                    break
                ev = parser.feed(line) if parser is not None else busctl_event(line)
                if ev is not None and ev[0].lower() not in OWN_APPS:
                    try:
                        self._on_notify(ev[0], ev[1])
                    except Exception as e:          # noqa: BLE001
                        logger.debug(f"Notification handler failed: {e}")
            if gen != self._gen:
                return
            backoff = 2.0 if time.monotonic() - start > 30 else min(120.0, backoff * 2)
            time.sleep(backoff)


# ---------------------------------------------------------------- Do Not Disturb
_dnd_cache = [0.0, False]


def _out(cmd: List[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def dnd_on() -> bool:
    """Do Not Disturb, where the desktop tells: GNOME, KDE (and other servers with an Inhibited
    property), mako, dunst, SwayNC. Asked at most every 2 seconds."""
    now = time.monotonic()
    if now - _dnd_cache[0] < 2.0:
        return _dnd_cache[1]
    on = False
    desk = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in desk and shutil.which("gsettings"):
        on = _out(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"]) == "false"
    if not on and shutil.which("gdbus"):
        on = "true" in _out(["gdbus", "call", "--session", "--dest", FD, "--object-path",
                             "/org/freedesktop/Notifications", "--method", "org.freedesktop.DBus.Properties.Get",
                             FD, "Inhibited"])
    if not on and shutil.which("makoctl"):
        on = "do-not-disturb" in _out(["makoctl", "mode"])
    if not on and shutil.which("dunstctl"):
        on = _out(["dunstctl", "is-paused"]) == "true"
    if not on and shutil.which("swaync-client"):
        on = _out(["swaync-client", "-D"]) == "true"
    _dnd_cache[0], _dnd_cache[1] = now, on
    return on
