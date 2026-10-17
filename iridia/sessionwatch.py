"""Is the screen locked, and how long since the last key press or mouse move?

Locking, from whatever the desktop offers (all through `gdbus`/`dbus-monitor`, no extra Python
dependency):
    logind       the session's LockedHint (GNOME, KDE, ...)
    ScreenSaver  ActiveChanged on the session bus (org.freedesktop.ScreenSaver, org.gnome.ScreenSaver)
    lockers      a screen locker that tells nobody (hyprlock, swaylock, gtklock, ...) running, seen in
                 /proc every 2 seconds, and at once when logind asks for a lock

Idle time, the first that answers:
    GNOME        org.gnome.Mutter.IdleMonitor GetIdletime
    KDE & co.    org.freedesktop.ScreenSaver GetSessionIdleTime
    X11          xprintidle
    logind       IdleHint and IdleSinceHint, for desktops that set them
Compositors that offer none of these (Hyprland, Sway, ...) can tell the daemon with
`iridia idle on|off` from hypridle or swayidle (and `iridia lock on|off` for an unknown locker).
"""

import logging
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger("iridia")

LOGIND = "org.freedesktop.login1"


# ------------------------------------------------------------- parsing (pure, tested)

def parse_bool(out: str) -> Optional[bool]:
    """gdbus's answer to a boolean property or method: "(<true>,)" or "(true,)"."""
    m = re.search(r"\b(true|false)\b", out or "")
    return None if m is None else m.group(1) == "true"


def parse_number(out: str) -> Optional[int]:
    """gdbus's answer holding one number: "(uint64 12345,)", "(<uint64 1700000000000000>,)", "(12,)"."""
    m = re.search(r"(?:u?int(?:16|32|64)\s+)?(-?\d+)", out or "")
    return int(m.group(1)) if m else None


def parse_object_path(out: str) -> Optional[str]:
    m = re.search(r"objectpath\s+'([^']+)'", out or "") or re.search(r"'(/org/freedesktop/login1/session/[^']+)'",
                                                                     out or "")
    return m.group(1) if m else None


def lock_event(line: str, pending: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """(event or None, what to look for on the next line) for one line of monitor output. Events:
    "locked"/"unlocked" (the desktop says so: LockedHint, ScreenSaver), "lock"/"unlock" (logind's
    requests, from loginctl lock-session: hyprlock and swaylock never answer them, so the screen
    locker's process tells when it ends).

    gdbus prints a whole signal on one line; dbus-monitor puts the argument on the next line,
    so a ScreenSaver ActiveChanged there returns pending="active"."""
    if pending == "active":
        if "boolean" in line:
            return ("locked" if "true" in line else "unlocked"), None
        return None, pending
    if "LockedHint" in line and "PropertiesChanged" in line:
        m = re.search(r"'LockedHint':\s*<(true|false)>", line)
        if m:
            return ("locked" if m.group(1) == "true" else "unlocked"), None
    if re.search(r"login1\.Session\.Lock\b", line):
        return "lock", None
    if re.search(r"login1\.Session\.Unlock\b", line):
        return "unlock", None
    if "ActiveChanged" in line:
        b = parse_bool(line.split("ActiveChanged", 1)[1])
        if b is not None:
            return ("locked" if b else "unlocked"), None
        return None, "active"
    return None, None


# For idle daemons Iridia can't see: what to add to their config.
HOOK_LINES = """# hypridle (~/.config/hypr/hypridle.conf)
listener {
    timeout = 300
    on-timeout = iridia idle on
    on-resume = iridia idle off
}

# swayidle (Sway config)
exec swayidle -w timeout 300 'iridia idle on' resume 'iridia idle off'"""

LOCKERS = ("hyprlock", "swaylock", "gtklock", "waylock", "i3lock", "xsecurelock", "slock", "physlock",
           "betterlockscreen", "light-locker")


def find_locker(proc: str, uid: int) -> Optional[str]:
    """The name of a running screen locker of this user, from /proc (no process started for it)."""
    import os
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return None
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "comm")) as f:
                name = f.read().strip()
            if name in LOCKERS and os.stat(os.path.join(proc, pid)).st_uid == uid:
                return name
        except OSError:
            continue
    return None


# ------------------------------------------------------------- the watcher

def _run(cmd: List[str], timeout: float = 2.0) -> Optional[str]:
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _gdbus_call(bus: str, dest: str, path: str, method: str, *args) -> Optional[str]:
    if not shutil.which("gdbus"):
        return None
    return _run(["gdbus", "call", f"--{bus}", "--dest", dest, "--object-path", path, "--method", method, *args])


def _prop(path: str, iface: str, name: str) -> Optional[str]:
    return _gdbus_call("system", LOGIND, path, "org.freedesktop.DBus.Properties.Get", iface, name)


class SessionWatcher:
    """Follows lock state in the background; idle_seconds() asks for the idle time when needed."""

    POLL_SEC = 5.0

    def __init__(self, on_change: Callable[[], None]):
        self._on_change = on_change
        self._stop = False
        self._procs: List[subprocess.Popen] = []
        self.session_path: Optional[str] = None
        self._said_locked = False                    # the desktop says the screen is locked
        self._locker_running = False                 # a screen locker (hyprlock, swaylock, ...) runs
        self._poke = threading.Event()
        self.lock_method: Optional[str] = None       # what reported the lock state, for the window
        self.idle_method: Optional[str] = None
        self.want_idle = False                       # only ask for the idle time when it's used
        self.idle: Optional[float] = None            # seconds without input, POLL_SEC old at most

    @property
    def locked(self) -> bool:
        return self._said_locked or self._locker_running

    # ---- start / stop
    def start(self):
        threading.Thread(target=self._setup, daemon=True, name="sessionwatch").start()

    def stop(self):
        self._stop = True
        for p in self._procs:
            if p.poll() is None:
                p.terminate()

    def _setup(self):
        self.session_path = self._find_session()
        if self.session_path:
            hint = parse_bool(_prop(self.session_path, "org.freedesktop.login1.Session", "LockedHint") or "")
            if hint is not None:
                self._said_locked = hint
                if hint:
                    self.lock_method = "logind"
            if shutil.which("gdbus"):
                self._watch(["gdbus", "monitor", "--system", "--dest", LOGIND, "--object-path", self.session_path],
                            "logind")
        if shutil.which("dbus-monitor"):
            self._watch(["dbus-monitor", "--session", "type='signal',member='ActiveChanged'"], "screensaver")
        threading.Thread(target=self._watch_lockers, daemon=True, name="sessionwatch-lockers").start()
        self.idle_method = self._find_idle_method()
        if self.idle_method:
            threading.Thread(target=self._poll_idle, daemon=True, name="sessionwatch-idle").start()
        logger.info(f"Lock detection: {self.lock_method or 'logind/ScreenSaver signals, or iridia lock on|off'}; "
                    f"idle time: {self.idle_method or 'not available (use iridia idle on|off)'}")

    @staticmethod
    def _find_session() -> Optional[str]:
        out = _prop("/org/freedesktop/login1/user/self", "org.freedesktop.login1.User", "Display")
        path = parse_object_path(out or "")
        if path and not path.endswith("/"):
            return path
        out = _gdbus_call("system", LOGIND, "/org/freedesktop/login1", "org.freedesktop.login1.Manager.GetSession",
                          "auto")
        return parse_object_path(out or "")

    def _watch(self, cmd, name):
        def loop():
            backoff = 2.0
            while not self._stop:
                start = time.monotonic()
                try:
                    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL, text=True, bufsize=1)
                except OSError:
                    return
                self._procs.append(p)
                pending = None
                for line in p.stdout:
                    if self._stop:
                        break
                    ev, pending = lock_event(line, pending)
                    if ev in ("locked", "unlocked"):
                        self.lock_method = name
                        if (ev == "locked") != self._said_locked:
                            self._said_locked = ev == "locked"
                            self._on_change()
                    elif ev in ("lock", "unlock"):
                        self._poke.set()            # look for the screen locker now
                if self._stop:
                    return
                backoff = 2.0 if time.monotonic() - start > 30 else min(120.0, backoff * 2)
                time.sleep(backoff)
        threading.Thread(target=loop, daemon=True, name=f"sessionwatch-{name}").start()

    def _watch_lockers(self):
        """Screen lockers that tell nobody (hyprlock, swaylock, ...): the screen is locked while one runs."""
        import os
        uid = os.getuid()
        while not self._stop:
            running = find_locker("/proc", uid) is not None
            if running != self._locker_running:
                self._locker_running = running
                if running:
                    self.lock_method = self.lock_method or "screen locker"
                self._on_change()
            self._poke.wait(2.0)
            self._poke.clear()

    # ---- idle time
    def _poll_idle(self):
        while not self._stop:
            if self.want_idle:
                self.idle = self._idle_now(self.idle_method)
            time.sleep(self.POLL_SEC)

    def _idle_now(self, method: str) -> Optional[float]:
        if method == "gnome":
            ms = parse_number(_gdbus_call("session", "org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
                                          "org.gnome.Mutter.IdleMonitor.GetIdletime") or "")
            return None if ms is None else ms / 1000.0
        if method == "screensaver":
            s = parse_number(_gdbus_call("session", "org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
                                         "org.freedesktop.ScreenSaver.GetSessionIdleTime") or "")
            return None if s is None else float(s)
        if method == "xprintidle":
            ms = parse_number(_run(["xprintidle"]) or "")
            return None if ms is None else ms / 1000.0
        if method == "logind" and self.session_path:
            idle = parse_bool(_prop(self.session_path, "org.freedesktop.login1.Session", "IdleHint") or "")
            if not idle:
                return None if idle is None else 0.0
            since = parse_number(_prop(self.session_path, "org.freedesktop.login1.Session", "IdleSinceHint") or "")
            return max(0.0, time.time() - since / 1e6) if since else 0.0
        return None

    def _find_idle_method(self) -> Optional[str]:
        for m in ("gnome", "screensaver", "xprintidle", "logind"):
            if m == "xprintidle" and not shutil.which("xprintidle"):
                continue
            v = self._idle_now(m)
            if v is None:
                continue
            if m == "logind" and v == 0.0:
                # IdleHint false: it may just not be set by this desktop. Use it, but say it's a guess.
                return "logind"
            return m
        return None

    def idle_seconds(self) -> Optional[float]:
        """Seconds without input, POLL_SEC old at most; None when nothing here can tell."""
        return self.idle if self.idle_method and self.want_idle else None
