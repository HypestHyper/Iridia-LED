"""Making sure OpenRGB's SDK server runs, so the user doesn't have to set it up.

Iridia only talks to OpenRGB over its SDK server. This module makes something start that server:

- With systemd: a user unit, iridia-openrgb.service, that runs `openrgb --server` at login and
  restarts it if it crashes. `iridia service install` (and so install.sh) writes it when nothing
  else starts OpenRGB; `iridia openrgb enable` / `disable` turn it on and off.
- Without systemd, or if the unit is gone: the daemon starts `openrgb --server` itself when it
  can't reach a server on this machine.

Both are skipped when something else already starts OpenRGB (another systemd unit, an autostart
entry, a line in the compositor's config) or when an OpenRGB process is already running, because
two OpenRGB instances fight over the same hardware. The setting is "openrgb.start_server" in
config.json (true by default).
"""

import glob
import logging
import os
import shlex
import shutil
import subprocess
import time

logger = logging.getLogger("iridia.openrgb_server")

UNIT_NAME = "iridia-openrgb.service"
UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
UNIT_PATH = os.path.join(UNIT_DIR, UNIT_NAME)
FLATPAK_ID = "org.openrgb.OpenRGB"
# units other people (or distro packages) use for the same job
OTHER_USER_UNITS = ("openrgb-server.service", "openrgb.service")
SYSTEM_UNITS = ("openrgb.service",)
# compositor and desktop startup files that may start OpenRGB themselves
STARTUP_FILES = ("~/.config/hypr/*.conf", "~/.config/hypr/*.lua", "~/.config/hypr/**/*.conf",
                 "~/.config/hypr/**/*.lua", "~/.config/sway/config", "~/.config/sway/config.d/*",
                 "~/.config/niri/config.kdl", "~/.config/river/init", "~/.config/labwc/autostart",
                 "~/.config/i3/config", "~/.config/bspwm/bspwmrc", "~/.xinitrc", "~/.xprofile")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "")


def is_local(host) -> bool:
    return str(host or "").strip().lower() in LOCAL_HOSTS


def command(custom: str = "") -> list:
    """The command that runs OpenRGB's server, or [] when OpenRGB isn't installed.
    custom: "openrgb.server_command" from config.json, for an AppImage or an unusual path."""
    if custom and custom.strip():
        try:
            return shlex.split(custom)
        except ValueError:
            logger.warning(f"openrgb.server_command can't be parsed: {custom!r}")
            return []
    exe = shutil.which("openrgb")
    if exe:
        return [exe, "--server"]
    if shutil.which("flatpak"):
        try:
            r = subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True, timeout=5)
            if r.returncode == 0:
                return [shutil.which("flatpak"), "run", FLATPAK_ID, "--server"]
        except (OSError, subprocess.SubprocessError):
            pass
    return []


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


def _starts_openrgb(line: str) -> bool:
    """A config line that starts OpenRGB at startup (not a comment, not a key binding that opens
    its window)."""
    s = line.strip().lower()
    if not s or s.startswith(("#", "--", "//", ";")) or "openrgb" not in s or "iridia" in s:
        return False
    if s.startswith(("bind", "hl.bind", "bindsym", "bindcode", "super", "mod")):
        return False
    return "--server" in s or s.startswith(("exec-once", "exec ", "exec=", "exec_always", "spawn-at-startup",
                                             "openrgb", "hl.exec_cmd"))


def _startup_mentions() -> list:
    """Startup files that seem to start OpenRGB already (autostart entries, compositor configs)."""
    found = []
    for path in glob.glob(os.path.expanduser("~/.config/autostart/*.desktop")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        lines = [ln.strip() for ln in text.splitlines()]
        if any(ln.lower().startswith("exec=") and "openrgb" in ln.lower() for ln in lines) and \
                not any(ln.replace(" ", "").lower() == "hidden=true" for ln in lines):
            found.append(path)
    seen = set()
    for pattern in STARTUP_FILES:
        for path in glob.glob(os.path.expanduser(pattern), recursive=True):
            if path in seen or not os.path.isfile(path):
                continue
            seen.add(path)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for ln in f:
                        if _starts_openrgb(ln):
                            found.append(path)
                            break
            except OSError:
                continue
    return found


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
    home = os.path.expanduser("~")
    out += [p.replace(home, "~", 1) for p in _startup_mentions()]
    return out


def running() -> bool:
    """An OpenRGB process (window or server, native or Flatpak) is already running."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as f:
                comm = f.read().strip().lower()
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv0 = os.path.basename(f.read().split(b"\0")[0].decode(errors="replace")).lower()
        except OSError:
            continue
        if comm == "openrgb" or argv0 == "openrgb" or (argv0.startswith("openrgb") and argv0.endswith(".appimage")):
            return True
    return False


def managed() -> bool:
    return os.path.exists(UNIT_PATH)


def status() -> dict:
    """Everything the window and `iridia doctor` show about who starts OpenRGB."""
    en, ac = unit_state(UNIT_NAME) if managed() else ("not-found", "")
    return {"managed": managed(), "enabled": en, "active": ac, "others": others(),
            "command": command(_config_value("server_command", "")), "systemd": has_systemd(),
            "start_server": bool(_config_value("start_server", True))}


def _config_value(key, default):
    try:
        import json
        with open(os.path.expanduser("~/.config/iridia/config.json"), encoding="utf-8") as f:
            v = json.load(f).get("openrgb", {}).get(key, default)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError, AttributeError):
        return default


def _unit_text(cmd: list) -> str:
    exec_line = " ".join(shlex.quote(c) for c in cmd)
    return f"""# Written by Iridia (`iridia openrgb enable`); removed by `iridia openrgb disable` and on uninstall.
[Unit]
Description=OpenRGB SDK server (started by Iridia)
Documentation=https://github.com/HypestHyper/Iridia-LED

[Service]
Type=simple
# Two OpenRGB instances fight over the same hardware: skip this one when OpenRGB already runs.
ExecCondition=/bin/sh -c '! pgrep -x openrgb >/dev/null'
ExecStart={exec_line}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def enable() -> tuple:
    """Write, enable and start iridia-openrgb.service. Returns (ok, message)."""
    cmd = command(_config_value("server_command", ""))
    if not cmd:
        return False, ("OpenRGB isn't installed (no `openrgb` command and no Flatpak). Install it first, or set "
                       "openrgb.server_command in config.json to the command that runs its server.")
    if not has_systemd():
        return True, ("No systemd user session here, so there's no unit to install. The daemon starts "
                      "`openrgb --server` by itself when it can't reach OpenRGB.")
    os.makedirs(UNIT_DIR, exist_ok=True)
    with open(UNIT_PATH, "w", encoding="utf-8") as f:
        f.write(_unit_text(cmd))
    _systemctl("daemon-reload")
    r = _systemctl("enable", "--now", UNIT_NAME, timeout=20)
    if r is None or r.returncode != 0:
        return False, f"Couldn't enable {UNIT_NAME}: {(r.stderr if r else '').strip() or 'systemctl failed'}"
    logger.info(f"Installed and started {UNIT_NAME}: {' '.join(cmd)}")
    return True, f"OpenRGB's server now starts at login ({UNIT_NAME})."


def disable() -> tuple:
    """Stop, disable and delete iridia-openrgb.service. Returns (ok, message)."""
    if not managed():
        return True, f"{UNIT_NAME} isn't installed."
    _systemctl("disable", "--now", UNIT_NAME, timeout=20)
    try:
        os.remove(UNIT_PATH)
    except OSError as e:
        return False, f"Couldn't delete {UNIT_PATH}: {e}"
    _systemctl("daemon-reload")
    logger.info(f"Removed {UNIT_NAME}")
    return True, f"Removed {UNIT_NAME}. OpenRGB's server no longer starts at login."


def auto_setup() -> str:
    """Called by `iridia service install`: set up the unit when nothing else starts OpenRGB.
    Returns a line to print (or "")."""
    if not _config_value("start_server", True):
        return ""
    if managed():
        ok, msg = enable()             # rewrite it: the openrgb path may have changed
        return msg if ok else f"Note: {msg}"
    other = others()
    if other:
        return f"OpenRGB is already started by: {', '.join(other)}. Leaving that alone."
    if not has_systemd():
        return ""
    ok, msg = enable()
    return msg if ok else f"Note: {msg}"


class Starter:
    """Used by the daemon: start OpenRGB when it can't be reached on this machine.
    Waits a little after the daemon starts (so the login's own startup can do it first),
    then tries at most once a minute."""

    GRACE_SEC = 10.0
    INTERVAL_SEC = 60.0

    def __init__(self):
        self._born = time.monotonic()
        self._last = 0.0
        self.last_action = ""

    def maybe_start(self, host, enabled: bool, custom_cmd: str = "") -> bool:
        now = time.monotonic()
        if not enabled or not is_local(host):
            return False
        if now - self._born < self.GRACE_SEC or (self._last and now - self._last < self.INTERVAL_SEC):
            return False
        self._last = now
        if managed():
            en, ac = unit_state(UNIT_NAME)
            if ac not in ("active", "activating"):
                r = _systemctl("start", UNIT_NAME, timeout=20)
                ok = bool(r) and r.returncode == 0
                self.last_action = f"started {UNIT_NAME}" if ok else f"couldn't start {UNIT_NAME}"
                logger.info(f"OpenRGB not reachable: {self.last_action}"
                            + ("" if ok else f" ({(r.stderr if r else '').strip()})"))
                return ok
            return False
        if running():
            logger.debug("OpenRGB not reachable, but an OpenRGB process runs (its SDK server may be off)")
            return False
        if others():
            logger.debug("OpenRGB not reachable; something else is set to start it, not starting another")
            return False
        cmd = command(custom_cmd)
        if not cmd:
            logger.debug("OpenRGB not reachable and not installed, nothing to start")
            return False
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as e:
            self.last_action = f"couldn't run {cmd[0]}: {e}"
            logger.warning(f"OpenRGB not reachable and {self.last_action}")
            return False
        self.last_action = "started " + " ".join(cmd)
        logger.info(f"OpenRGB not reachable: {self.last_action}")
        return True
