"""Making sure exactly one OpenRGB SDK server runs, and that it can see the hardware.

Iridia only talks to OpenRGB over its SDK server. "openrgb.start_method" in config.json says what
starts that server:

- "daemon" (default): the Iridia daemon starts `openrgb --server` itself and restarts it if it
  exits. The daemon runs inside the graphical session, so OpenRGB starts late enough to see the
  hardware (at boot, device access is only granted once the session is up). Works with or
  without systemd, however the daemon itself is started.
- "systemd": a user unit, iridia-openrgb.service, ordered after graphical-session.target.
- "off": Iridia never starts, stops or restarts OpenRGB.

Two OpenRGB instances fight over the same hardware, so nothing is started while another OpenRGB
process runs or while something else is set up to start it (another unit, an autostart entry, a
compositor line). Iridia only ever restarts an OpenRGB it started itself: the one in its PID file
($XDG_RUNTIME_DIR/iridia-openrgb.pid), or its own systemd unit.
"""

import glob
import logging
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from typing import List, Optional, Tuple

logger = logging.getLogger("iridia.openrgb_server")

METHODS = ("daemon", "systemd", "off")
DEFAULT_METHOD = "daemon"
MARKER = "# Written by Iridia"
UNIT_NAME = "iridia-openrgb.service"
UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
UNIT_PATH = os.path.join(UNIT_DIR, UNIT_NAME)
LOG_PATH = os.path.expanduser("~/.local/share/iridia/openrgb.log")
LOG_MAX_BYTES = 1024 * 1024
FLATPAK_ID = "org.openrgb.OpenRGB"
# units other people (or distro packages) use for the same job
OTHER_USER_UNITS = ("openrgb-server.service", "openrgb.service")
SYSTEM_UNITS = ("openrgb.service",)
# compositor and desktop startup files that may start OpenRGB (or the Iridia daemon) themselves
# compositor and X11 startup files that can hold a line starting the daemon or OpenRGB ("@" is the
# config folder: $XDG_CONFIG_HOME or ~/.config)
STARTUP_FILES = ("@/hypr/*.conf", "@/hypr/*.lua", "@/hypr/**/*.conf", "@/hypr/**/*.lua", "@/sway/config",
                 "@/sway/config.d/*", "@/niri/config.kdl", "@/river/init", "@/labwc/autostart",
                 "@/openbox/autostart", "@/wayfire.ini", "@/i3/config", "@/i3/config.d/*", "~/.i3/config",
                 "@/bspwm/bspwmrc", "~/.xinitrc", "~/.xprofile")


def _config_home() -> str:
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def run_by_systemd() -> bool:
    """This process is a systemd service itself, not a child of something systemd runs (compositors
    started through UWSM or niri-session pass INVOCATION_ID on to everything they start)."""
    pid = os.environ.get("SYSTEMD_EXEC_PID")             # systemd 248+
    if pid:
        return pid == str(os.getpid())
    if not os.environ.get("INVOCATION_ID"):
        return False
    try:
        with open(f"/proc/{os.getppid()}/comm", encoding="utf-8") as f:
            return f.read().strip() == "systemd"
    except OSError:
        return False
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "")


def is_local(host) -> bool:
    return str(host or "").strip().lower() in LOCAL_HOSTS


# ----------------------------------------------------------------- settings

def method_of(openrgb_cfg) -> str:
    """The start method from the "openrgb" section of config.json (old keys included)."""
    cfg = openrgb_cfg if isinstance(openrgb_cfg, dict) else {}
    m = cfg.get("start_method")
    if m in METHODS:
        return m
    if cfg.get("start_server") is False:        # 1.1.0: "start_server": false
        return "off"
    return DEFAULT_METHOD


def _openrgb_cfg() -> dict:
    try:
        from iridia.config import Config
        return Config().openrgb
    except Exception:                       # noqa: BLE001
        return {}


def start_method() -> str:
    return method_of(_openrgb_cfg())


def command(custom: str = "", port=None) -> list:
    """The command that runs OpenRGB's server, or [] when OpenRGB isn't installed.
    custom: "openrgb.server_command" from config.json, for an AppImage or an unusual path.
    port: "openrgb.port", passed on as --server-port (OpenRGB listens on 6742 otherwise)."""
    if custom and custom.strip():
        try:
            cmd = shlex.split(custom)
        except ValueError:
            logger.warning(f"openrgb.server_command can't be parsed: {custom!r}")
            return []
    else:
        exe = shutil.which("openrgb")
        cmd = [exe, "--server"] if exe else []
        if not cmd and shutil.which("flatpak"):
            try:
                r = subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True, timeout=5)
                if r.returncode == 0:
                    cmd = [shutil.which("flatpak"), "run", FLATPAK_ID, "--server"]
            except (OSError, subprocess.SubprocessError):
                pass
    if cmd and port not in (None, "", 0) and "--server-port" not in cmd:
        try:
            cmd = cmd + ["--server-port", str(int(port))]
        except (TypeError, ValueError):
            pass
    return cmd


# ------------------------------------------------------------------ systemd

def _systemctl(*args, system=False, timeout=10):
    if not shutil.which("systemctl"):
        return None
    try:
        return subprocess.run(["systemctl", *([] if system else ["--user"]), *args],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def has_systemd() -> bool:
    r = _systemctl("show-environment", timeout=3)
    return bool(r) and r.returncode == 0


def unit_state(name: str, system=False) -> tuple:
    """(enabled, active) for a unit. enabled is "enabled", "disabled", "static"... or "not-found";
    active is "active", "inactive", "failed"... Both are "" when systemd can't be asked."""
    r = _systemctl("is-enabled", name, system=system, timeout=3)
    if r is None:
        return "", ""
    enabled = (r.stdout or "").strip().split("\n")[0]
    if not enabled or "not-found" in (r.stdout + r.stderr) or "No such file" in r.stderr:
        enabled = "not-found"
    a = _systemctl("is-active", name, system=system, timeout=3)
    active = (a.stdout or "").strip().split("\n")[0] if a else ""
    return enabled, active


def graphical_session_active() -> Optional[bool]:
    """Whether the session reached graphical-session.target (None: no systemd user session).
    Hyprland started without UWSM, and many other compositors, never activate it."""
    r = _systemctl("is-active", "graphical-session.target", timeout=3)
    if r is None or not has_systemd():
        return None
    return (r.stdout or "").strip() == "active"


def managed() -> bool:
    """Our unit file exists."""
    return os.path.exists(UNIT_PATH)


def _unit_text_of(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def unit_is_ours(path: str = "") -> bool:
    return MARKER in _unit_text_of(path or UNIT_PATH)


def _unit_text(cmd: list) -> str:
    exec_line = " ".join(shlex.quote(c) for c in cmd)
    return f"""{MARKER} (openrgb.start_method = systemd). Removed when you pick another method, and on uninstall.
[Unit]
Description=OpenRGB SDK server (started by Iridia)
Documentation=https://github.com/HypestHyper/Iridia-LED
# Start inside the graphical session: earlier, OpenRGB can't open the USB and I2C devices yet,
# finds nothing, and never looks again.
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
# Two OpenRGB instances fight over the same hardware: skip this one when OpenRGB already runs.
ExecCondition=/bin/sh -c '! pgrep -x openrgb >/dev/null'
ExecStartPre=/bin/sh -c 'sleep 3'
ExecStart={exec_line}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
"""


def enable_unit(custom: str = "", port=None) -> Tuple[bool, str]:
    """Write, enable and start iridia-openrgb.service."""
    cmd = command(custom, port)
    if not cmd:
        return False, ("OpenRGB isn't installed (no `openrgb` command and no Flatpak). Install it first, or set "
                       "openrgb.server_command in config.json to the command that runs its server.")
    if not has_systemd():
        return False, "There's no systemd user session here. Use the 'daemon' method instead."
    if os.path.exists(UNIT_PATH) and not unit_is_ours():
        return False, f"{UNIT_PATH} exists and wasn't written by Iridia; leaving it alone."
    os.makedirs(UNIT_DIR, exist_ok=True)
    with open(UNIT_PATH, "w", encoding="utf-8") as f:
        f.write(_unit_text(cmd))
    _systemctl("daemon-reload")
    # reenable, not enable: an older copy was wanted by default.target, and only reenable
    # moves the link to graphical-session.target.
    r = _systemctl("reenable", UNIT_NAME, timeout=20)
    if r is None or r.returncode != 0:
        return False, f"Couldn't enable {UNIT_NAME}: {(r.stderr if r else '').strip() or 'systemctl failed'}"
    _systemctl("start", UNIT_NAME, timeout=20)
    logger.info(f"Installed and started {UNIT_NAME}: {' '.join(cmd)}")
    msg = f"OpenRGB's server now starts with your graphical session ({UNIT_NAME})."
    if graphical_session_active() is False:
        msg += (" Warning: your session doesn't start graphical-session.target (Hyprland without UWSM, for "
                "example), so this unit won't start at login. Use the 'daemon' method instead.")
    return True, msg


def disable_unit() -> Tuple[bool, str]:
    """Stop, disable and delete iridia-openrgb.service (only if Iridia wrote it)."""
    if not managed():
        return True, f"{UNIT_NAME} isn't installed."
    if not unit_is_ours():
        return False, f"{UNIT_PATH} wasn't written by Iridia; leaving it alone."
    _systemctl("disable", "--now", UNIT_NAME, timeout=20)
    try:
        os.remove(UNIT_PATH)
    except OSError as e:
        return False, f"Couldn't delete {UNIT_PATH}: {e}"
    _systemctl("daemon-reload")
    logger.info(f"Removed {UNIT_NAME}")
    return True, f"Removed {UNIT_NAME}."


def migrate(method: str) -> str:
    """Clean up after 1.1.0, which installed iridia-openrgb.service wanted by default.target:
    that starts OpenRGB before the session has device access, so it finds no devices. Unless
    "systemd" was picked on purpose, remove it (only when Iridia wrote it). Returns a line to log."""
    if not managed():
        return ""
    if not unit_is_ours():
        return f"{UNIT_PATH} wasn't written by Iridia; leaving it alone."
    if method == "systemd":
        if "WantedBy=default.target" in _unit_text_of(UNIT_PATH):
            ok, msg = enable_unit(**_cmd_settings())
            return "Updated iridia-openrgb.service to start with the graphical session. " + ("" if ok else msg)
        return ""
    ok, msg = disable_unit()
    if ok:
        return (f"Removed the old {UNIT_NAME}: it started OpenRGB too early at boot, before it could see the "
                "hardware. " + ("The Iridia daemon starts OpenRGB now." if method == "daemon" else ""))
    return msg


def _cmd_settings() -> dict:
    cfg = _openrgb_cfg()
    custom = cfg.get("server_command") or ""
    return {"custom": custom if isinstance(custom, str) else "", "port": cfg.get("port")}


# ---------------------------------------------------------------- processes

def processes() -> List[Tuple[int, List[str]]]:
    """Running OpenRGB processes (window or server, native, Flatpak or AppImage): (pid, argv)."""
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as f:
                comm = f.read().strip().lower()
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        argv0 = os.path.basename(argv[0]).lower() if argv else ""
        if not argv or _start_time(int(pid)) is None:
            continue                        # exited (a zombie waiting to be reaped)
        if comm == "openrgb" or argv0 == "openrgb" or (argv0.startswith("openrgb") and argv0.endswith(".appimage")):
            out.append((int(pid), argv))
    return out


def running(exclude=()) -> bool:
    """An OpenRGB process (other than the pids in exclude) is running."""
    return any(pid not in exclude for pid, _ in processes())


def window_without_server() -> bool:
    """The OpenRGB window is open, without --server (its SDK server may be switched off)."""
    return any("--server" not in argv for _, argv in processes())


def _start_time(pid: int) -> Optional[str]:
    """Process start time (field 22 of /proc/PID/stat), to tell a PID apart from a reused one."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as f:
            stat = f.read()
        fields = stat[stat.rindex(")") + 2:].split()
        if fields[0] == "Z":
            return None                     # exited, waiting to be reaped
        return fields[19]
    except (OSError, ValueError, IndexError):
        return None


def pid_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR")
    return os.path.join(base, "iridia-openrgb.pid") if base else f"/tmp/iridia-openrgb-{os.getuid()}.pid"


def read_pid() -> Optional[int]:
    """The OpenRGB Iridia started, if it still runs."""
    try:
        with open(pid_path(), encoding="utf-8") as f:
            pid_s, started = f.read().split()[:2]
        pid = int(pid_s)
    except (OSError, ValueError):
        return None
    return pid if _start_time(pid) == started else None


def _write_pid(pid: int):
    path = pid_path()
    tmp = path + ".tmp"
    old = os.umask(0o077)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(f"{pid} {_start_time(pid) or 0}\n")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"Couldn't write {path}: {e}")
    finally:
        os.umask(old)


def _clear_pid():
    try:
        os.remove(pid_path())
    except OSError:
        pass


def _terminate(pid: int, wait: float = 5.0, group: bool = True) -> bool:
    """SIGTERM a process, SIGKILL if it hangs. group: the whole process group, for servers Iridia
    started in their own session (`flatpak run` has children); never for someone else's."""
    started = _start_time(pid)
    if started is None:
        return True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            if group and os.getpgid(pid) == pid:
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)
        except ProcessLookupError:
            return True
        except OSError as e:
            logger.warning(f"Couldn't stop OpenRGB (pid {pid}): {e}")
            return False
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                os.waitpid(pid, os.WNOHANG)     # reap it if it's our child
            except ChildProcessError:
                pass
            if _start_time(pid) != started:
                return True
            time.sleep(0.1)
    return _start_time(pid) != started


def stop_ours() -> Tuple[bool, str]:
    """Stop the OpenRGB Iridia started (never anything else)."""
    pid = read_pid()
    if pid is None:
        return True, "Iridia isn't running an OpenRGB server."
    ok = _terminate(pid)
    if ok:
        _clear_pid()
        logger.info(f"Stopped the OpenRGB server Iridia started (pid {pid})")
        return True, f"Stopped the OpenRGB server Iridia started (pid {pid})."
    return False, f"Couldn't stop OpenRGB (pid {pid})."


def _open_log():
    """OpenRGB's own output, so problems can be diagnosed. Rotated at about 1 MB."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        f = open(LOG_PATH, "ab")
        f.write(time.strftime("\n===== %Y-%m-%d %H:%M:%S  started by Iridia =====\n").encode())
        f.flush()
        return f
    except OSError as e:
        logger.warning(f"Couldn't open {LOG_PATH} for OpenRGB's output: {e}")
        return None


# ---------------------------------------------------------- other starters

def _starts_openrgb(line: str) -> bool:
    """A config line that starts OpenRGB at startup (not a comment, not a key binding that opens
    its window)."""
    s = line.strip().lower()
    if not s or s.startswith(("#", "--", "//", ";", "/-")) or "openrgb" not in s or "iridia" in s:
        return False
    if s.startswith(("bind", "hl.bind", "bindsym", "bindcode", "super", "mod")):
        return False
    return "--server" in s or s.startswith(("exec-once", "exec ", "exec=", "exec_always", "spawn-at-startup",
                                             "openrgb", "hl.exec_cmd"))


def _autostart_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart")


def _hidden(lines) -> bool:
    return any(ln.replace(" ", "").lower() == "hidden=true" for ln in lines)


def xdg_entries() -> List[str]:
    """Autostart entries (~/.config/autostart/*.desktop) that start OpenRGB and aren't hidden."""
    found = []
    for path in sorted(glob.glob(os.path.join(_autostart_dir(), "*.desktop"))):
        lines = [ln.strip() for ln in _unit_text_of(path).splitlines()]
        if any(ln.lower().startswith("exec=") and "openrgb" in ln.lower() for ln in lines) and not _hidden(lines):
            found.append(path)
    return found


def hide_xdg_entry(path: str) -> Tuple[bool, str]:
    """Turn off an autostart entry by adding Hidden=true (the file stays, nothing is deleted)."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.dirname(path) != os.path.abspath(_autostart_dir()) or not path.endswith(".desktop"):
        return False, f"{path} isn't an autostart entry."
    text = _unit_text_of(path)
    if not text:
        return False, f"Couldn't read {path}."
    lines = text.splitlines()
    if _hidden([ln.strip() for ln in lines]):
        return True, f"{path} is already turned off."
    out, done = [], False
    for ln in lines:
        if ln.strip().lower().startswith("hidden="):
            continue
        out.append(ln)
        if not done and ln.strip() == "[Desktop Entry]":
            out.append("Hidden=true")
            done = True
    if not done:
        return False, f"{path} has no [Desktop Entry] section."
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    except OSError as e:
        return False, f"Couldn't change {path}: {e}"
    logger.info(f"Turned off the autostart entry {path} (Hidden=true)")
    return True, f"Turned off {path} (added Hidden=true; delete that line to undo)."


def _startup_mentions(pred=_starts_openrgb) -> list:
    """Compositor and session startup files with a line matching pred."""
    found, seen = [], set()
    for pattern in STARTUP_FILES:
        pattern = _config_home() + pattern[1:] if pattern.startswith("@") else os.path.expanduser(pattern)
        for path in glob.glob(pattern, recursive=True):
            if path in seen or not os.path.isfile(path):
                continue
            seen.add(path)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    if any(pred(ln) for ln in f):
                        found.append(path)
            except OSError:
                continue
    return found


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    return path.replace(home, "~", 1) if path.startswith(home) else path


def others() -> list:
    """What else starts OpenRGB on this machine, as short descriptions."""
    out = []
    for u in OTHER_USER_UNITS:
        en, ac = unit_state(u)
        if en == "enabled" or ac in ("active", "activating"):
            out.append(f"{u} (user)")
    for u in SYSTEM_UNITS:
        en, ac = unit_state(u, system=True)
        if en == "enabled" or ac in ("active", "activating"):
            out.append(f"{u} (system)")
    out += [_short(p) for p in xdg_entries()]
    out += [_short(p) for p in _startup_mentions()]
    return out


def _starts_daemon(line: str) -> bool:
    s = line.strip().lower()
    return bool(s) and not s.startswith(("#", "--", "//", ";", "/-")) and "iridia-daemon" in s \
        and not s.startswith(("bind", "hl.bind", "bindsym", "bindcode"))


def daemon_starters() -> list:
    """Everything set up to start the Iridia daemon at login, as short descriptions."""
    out = []
    en, _ac = unit_state("iridia-daemon.service")
    # an enabled unit only starts at login when the session reaches graphical-session.target
    if en == "enabled" and graphical_session_active() is not False:
        out.append("iridia-daemon.service (systemd)")
    xdg = os.path.join(_autostart_dir(), "iridia-daemon.desktop")
    if os.path.exists(xdg) and not _hidden([ln.strip() for ln in _unit_text_of(xdg).splitlines()]):
        out.append(_short(xdg))
    out += [_short(p) for p in _startup_mentions(_starts_daemon)]
    return out


def started_by() -> str:
    """How this process was started: "systemd (UNIT)", "XDG autostart", or the parent's name."""
    if run_by_systemd():
        unit = ""
        try:
            with open("/proc/self/cgroup", encoding="utf-8") as f:
                unit = f.read().strip().rsplit("/", 1)[-1]
        except OSError:
            pass
        if "autostart" in unit:
            return "XDG autostart"
        return f"systemd ({unit})" if unit.endswith(".service") else "systemd"
    try:
        with open(f"/proc/{os.getppid()}/comm", encoding="utf-8") as f:
            parent = f.read().strip()
    except OSError:
        parent = ""
    return parent or "unknown"


# ------------------------------------------------------------------- status

def status() -> dict:
    """Everything the window and `iridia doctor` show about who starts OpenRGB."""
    cfg = _openrgb_cfg()
    custom = cfg.get("server_command") or ""
    en, ac = unit_state(UNIT_NAME) if managed() else ("not-found", "")
    procs = processes()
    return {"method": method_of(cfg), "managed": managed(), "enabled": en, "active": ac, "others": others(),
            "xdg_entries": [_short(p) for p in xdg_entries()],
            "command": command(custom if isinstance(custom, str) else "", cfg.get("port")),
            "systemd": has_systemd(), "graphical_session": graphical_session_active(),
            "running": bool(procs), "window_without_server": any("--server" not in a for _, a in procs),
            "ours": read_pid(), "pid_file": pid_path(), "log": LOG_PATH,
            "host": cfg.get("host") or "127.0.0.1"}


def set_method(new: str, old: str, stop_running: bool = False) -> Tuple[bool, List[str]]:
    """Clean up after the old method and set up the new one (config.json is saved by the caller).
    stop_running: also stop the OpenRGB the daemon started when leaving "daemon"."""
    if new not in METHODS:
        return False, [f"Unknown method {new!r}; use one of: {', '.join(METHODS)}"]
    msgs, ok = [], True
    if new != "systemd" and managed() and unit_is_ours():
        good, m = disable_unit()
        ok &= good
        msgs.append(m)
    if new == "systemd":
        if read_pid() is not None:          # its own OpenRGB would make the unit skip itself
            good, m = stop_ours()
            msgs.append(m)
        good, m = enable_unit(**_cmd_settings())
        ok &= good
        msgs.append(m)
    elif old == "daemon" and new == "off" and read_pid() is not None:
        if stop_running:
            good, m = stop_ours()
            ok &= good
            msgs.append(m)
        else:
            msgs.append("The OpenRGB server Iridia started keeps running until you log out. "
                        "Stop it now with: iridia openrgb start-method off --stop")
    return ok, msgs


# --------------------------------------------------------------- supervisor

class Supervisor:
    """Used by the daemon ("daemon" method): start OpenRGB when it can't be reached on this machine,
    remember it as ours, restart it if it exits (after 5 s, 15 s, 60 s, then give up and say so).

    tick() runs on the daemon's tick (off the main thread when it might block). After the daemon
    starts it waits QUICK_SEC, or GRACE_SEC when something else is set up to start OpenRGB, so the
    login's own startup can win; it never starts a second OpenRGB, and leaves OpenRGB alone when
    something else is set up to start it."""

    GRACE_SEC = 10.0
    QUICK_SEC = 2.0             # nothing else starts OpenRGB: no reason to keep the LEDs waiting
    BACKOFF = (5.0, 15.0, 60.0)
    STABLE_SEC = 120.0          # alive this long: earlier crashes are forgiven
    OTHERS_TTL = 60.0           # how long the (slow-ish) other-starter scan is trusted
    UNIT_RETRY_SEC = 60.0

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._born = clock()
        self._lock = threading.RLock()
        self._proc = None                   # Popen of the server we started in this run
        self.pid = read_pid()               # adopt one started before a daemon restart
        self._started_at = self._born if self.pid else 0.0
        self.failures = 0
        self._next_try = 0.0
        self.gave_up = False
        self._others = (None, [])           # (checked at, result)
        self._said = ""
        self._unit_tried = 0.0
        self.last_action = ""
        if self.pid:
            self.last_action = f"reusing OpenRGB pid {self.pid}"
            logger.info(f"Reusing the OpenRGB server started earlier (pid {self.pid})")

    # helpers ---------------------------------------------------------------
    def _say(self, msg: str, level=logging.INFO):
        """Log a skip/wait decision once (until it changes), so a retry loop can't flood the log."""
        if msg != self._said:
            self._said = msg
            logger.log(level, msg)

    def alive(self) -> bool:
        with self._lock:
            if not self.pid:
                return False
            if self._proc is not None and self._proc.pid == self.pid:
                return self._proc.poll() is None
            return read_pid() == self.pid

    def _others_now(self, now) -> list:
        at, found = self._others
        if at is None or now - at > self.OTHERS_TTL:
            found = others()
            self._others = (now, found)
        return found

    # the tick --------------------------------------------------------------
    def tick(self, method: str, host, reachable: bool, custom: str = "", port=None):
        if not is_local(host):
            if method != "off":
                self._say(f"OpenRGB is on another machine ({host}); not starting anything here", logging.DEBUG)
            return
        now = self._clock()
        with self._lock:
            if self.pid and not self.alive():
                if method != "daemon":
                    self._forget()          # stopped on purpose (method changed)
                else:
                    self._died(now)
            elif self.pid and self.failures and now - self._started_at > self.STABLE_SEC:
                self.failures = 0
        if method == "systemd":
            return self._tick_unit(now, reachable)
        if method != "daemon":
            return
        if self.pid or reachable:
            return
        if now - self._born < self.QUICK_SEC:
            return
        if now - self._born < self.GRACE_SEC and (self._others_now(now) or running()):
            return
        if self.gave_up:
            return
        if now < self._next_try:
            return
        if running(exclude=(self.pid,) if self.pid else ()):
            self._say("OpenRGB isn't reachable, but an OpenRGB process runs: not starting another. If it's the "
                      "window, turn on its SDK server (SDK Server tab, Start Server).")
            return
        found = self._others_now(now)
        if found:
            self._say(f"OpenRGB isn't reachable; it's set to be started by {', '.join(found)}: not starting "
                      "another (two OpenRGB instances fight over the hardware)", logging.WARNING)
            return
        cmd = command(custom, port)
        if not cmd:
            self._say("OpenRGB isn't reachable and isn't installed (no openrgb command, no Flatpak); "
                      "nothing to start", logging.WARNING)
            return
        self.spawn(cmd, "OpenRGB isn't reachable")

    def _tick_unit(self, now, reachable):
        if reachable or not managed() or now - self._born < self.GRACE_SEC:
            return
        if self._unit_tried and now - self._unit_tried < self.UNIT_RETRY_SEC:
            return
        self._unit_tried = now
        _en, ac = unit_state(UNIT_NAME)
        if ac in ("active", "activating"):
            return
        r = _systemctl("start", UNIT_NAME, timeout=20)
        ok = bool(r) and r.returncode == 0
        self.last_action = f"started {UNIT_NAME}" if ok else f"couldn't start {UNIT_NAME}"
        logger.info(f"OpenRGB isn't reachable: {self.last_action}"
                    + ("" if ok else f" ({(r.stderr if r else '').strip()})"))

    def _forget(self):
        self.pid, self._proc = None, None
        _clear_pid()

    def _died(self, now):
        code = self._proc.returncode if self._proc is not None else None
        self._forget()
        self.failures += 1
        if self.failures > len(self.BACKOFF):
            self.gave_up = True
            self.last_action = f"OpenRGB exited {self.failures} times; gave up"
            logger.warning(f"The OpenRGB server Iridia started exited again (code {code}); it has failed "
                           f"{self.failures} times, so Iridia stops restarting it. See {LOG_PATH}, then use "
                           "Restart OpenRGB server (or restart the daemon) to try again.")
            return
        wait = self.BACKOFF[self.failures - 1]
        self._next_try = now + wait
        logger.warning(f"The OpenRGB server Iridia started exited (code {code}); starting it again in "
                       f"{wait:.0f}s (attempt {self.failures} of {len(self.BACKOFF)}). Its output: {LOG_PATH}")

    def spawn(self, cmd: list, reason: str) -> bool:
        with self._lock:
            log = _open_log()
            try:
                # restore_signals=False: OpenRGB inherits Python's ignored SIGPIPE (as systemd's
                # IgnoreSIGPIPE does for services). OpenRGB before 1.0 doesn't ignore it itself, so a
                # client hanging up just before OpenRGB writes to it (announcing a device it found)
                # killed the whole server (exit code -13); now that write just fails.
                self._proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                              stdout=log or subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                              start_new_session=True, restore_signals=False)
            except OSError as e:
                self.last_action = f"couldn't run {cmd[0]}: {e}"
                self._next_try = self._clock() + self.BACKOFF[-1]
                logger.warning(f"{reason}, and {self.last_action}")
                return False
            finally:
                if log:
                    log.close()
            self.pid = self._proc.pid
            self._started_at = self._clock()
            _write_pid(self.pid)
            self._said = ""
            self.last_action = "started " + " ".join(cmd)
            logger.info(f"{reason}: started {' '.join(cmd)} (pid {self.pid}, output in {LOG_PATH})")
            return True

    # restarts --------------------------------------------------------------
    def owner(self, method: str) -> str:
        """Who may restart OpenRGB automatically: "pid" (ours), "unit" (our systemd unit) or ""."""
        if method == "daemon" and self.alive():
            return "pid"
        if method == "systemd" and managed() and unit_is_ours():
            return "unit"
        return ""

    def restart(self, method: str, reason: str, custom: str = "", port=None) -> bool:
        """Restart the OpenRGB Iridia started (never another one). Blocks a few seconds."""
        who = self.owner(method)
        if who == "unit":
            r = _systemctl("restart", UNIT_NAME, timeout=20)
            ok = bool(r) and r.returncode == 0
            self.last_action = f"restarted {UNIT_NAME}" if ok else f"couldn't restart {UNIT_NAME}"
            logger.warning(f"{reason}: {self.last_action}")
            return ok
        if who != "pid":
            return False
        with self._lock:
            old = self.pid
            logger.warning(f"{reason}: restarting the OpenRGB server Iridia started (pid {old})")
            _terminate(old)
            self._forget()
            self.gave_up = False
            cmd = command(custom, port)
            return bool(cmd) and self.spawn(cmd, f"Restarted OpenRGB ({reason})")

    def take_over(self, reason: str, custom: str = "", port=None) -> bool:
        """For an explicit Restart click when the running server isn't ours: stop headless
        `openrgb --server` processes (never the OpenRGB window) and start ours instead."""
        with self._lock:
            headless = [pid for pid, argv in processes() if "--server" in argv and pid != self.pid]
            if not headless and not self.alive():
                return False
            for pid in headless:
                logger.warning(f"{reason}: stopping the OpenRGB server pid {pid} (not started by Iridia)")
                _terminate(pid, group=False)
            if self.alive():
                _terminate(self.pid)
            self._forget()
            self.gave_up = False
            self.failures = 0
            cmd = command(custom, port)
            return bool(cmd) and self.spawn(cmd, reason)
