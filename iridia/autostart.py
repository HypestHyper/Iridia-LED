"""Ways to start the iridia daemon at login.

systemd (user service) is the primary method; the others cover desktops and
compositors where the systemd graphical session isn't reached, or where you
simply prefer your compositor's own autostart. They are safe to combine: the
daemon takes a single-instance lock, so a second copy exits quietly.
"""

import os
import shutil
import sys
from typing import Dict, List

XDG_AUTOSTART_NAME = "iridia-daemon.desktop"


def daemon_command() -> str:
    """Absolute path of the iridia-daemon launcher for the running install."""
    cand = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "iridia-daemon")
    if os.path.exists(cand):
        return cand
    return shutil.which("iridia-daemon") or "iridia-daemon"


def xdg_autostart_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", XDG_AUTOSTART_NAME)


def xdg_desktop_entry(cmd: str = "") -> str:
    cmd = cmd or daemon_command()
    return f"""[Desktop Entry]
Type=Application
Name=Iridia daemon
Comment=Sync LED colors with the wallpaper (OpenRGB)
Exec={_desktop_exec(cmd)}
Icon=iridia
Terminal=false
X-GNOME-Autostart-enabled=true
NoDisplay=true
"""


def _desktop_exec(cmd: str) -> str:
    """A command for a desktop entry's Exec= line: quoted when it has a space or a special character,
    % doubled (the Desktop Entry spec)."""
    q = cmd.replace("%", "%%")
    if any(ch in q for ch in ' \t"\'\\$`'):
        q = '"' + q.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'
    return q


def xdg_installed() -> bool:
    return os.path.exists(xdg_autostart_path())


def xdg_install() -> str:
    path = xdg_autostart_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(xdg_desktop_entry())
    return path


def xdg_remove() -> bool:
    path = xdg_autostart_path()
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def snippets(cmd: str = "") -> List[Dict[str, str]]:
    """Copy-paste autostart lines, one entry per environment."""
    cmd = cmd or daemon_command()
    return [
        {
            "id": "systemd", "title": "systemd (all distros)",
            "file": "(managed for you)",
            "text": ("iridia service install\n"
                     "systemctl --user enable --now iridia-daemon.service\n\n"
                     "# Starts with your graphical session (graphical-session.target): GNOME, KDE Plasma\n"
                     "# 5.25 and later, COSMIC, niri started through niri-session, and compositors started\n"
                     "# through UWSM. Other sessions never reach that target: use one of the lines below."),
        },
        {
            "id": "hyprland-lua", "title": "Hyprland (Lua config)",
            "file": "~/.config/hypr/hyprland.lua",
            "text": ('hl.on("hyprland.start", function()\n'
                     f'  hl.exec_cmd("{cmd}")\n'
                     'end)'),
        },
        {
            "id": "hyprland-conf", "title": "Hyprland (hyprland.conf)",
            "file": "~/.config/hypr/hyprland.conf",
            "text": (f"exec-once = {cmd}\n\n"
                     "# If you launch Hyprland through UWSM, prefer the systemd service above, or:\n"
                     f"exec-once = uwsm app -- {cmd}"),
        },
        {
            "id": "niri", "title": "niri",
            "file": "~/.config/niri/config.kdl",
            "text": f'spawn-at-startup "{cmd}"',
        },
        {
            "id": "sway", "title": "Sway",
            "file": "~/.config/sway/config",
            "text": f"exec {cmd}",
        },
        {
            "id": "i3", "title": "i3",
            "file": "~/.config/i3/config",
            "text": f"exec --no-startup-id {cmd}",
        },
        {
            # river 0.4 and later refuse to start when the init file contains the word riverctl,
            # so a plain shell line it is (works with river-classic too)
            "id": "river", "title": "river",
            "file": "~/.config/river/init",
            "text": f"{cmd} &\n\n# Put it before the line that starts your window manager (exec ...), if there is one.",
        },
        {
            "id": "wayfire", "title": "Wayfire",
            "file": "~/.config/wayfire.ini",
            "text": f"[autostart]\niridia = {cmd}",
        },
        {
            "id": "labwc", "title": "labwc / Openbox",
            "file": "~/.config/labwc/autostart  |  ~/.config/openbox/autostart",
            "text": f"{cmd} &",
        },
        {
            "id": "bspwm", "title": "bspwm / dwm / X11 sessions",
            "file": "~/.config/bspwm/bspwmrc  |  ~/.xinitrc  |  ~/.xprofile",
            "text": f"{cmd} &",
        },
        {
            "id": "xdg", "title": "GNOME / KDE / XFCE / Cinnamon / MATE / LXQt",
            "file": xdg_autostart_path().replace(os.path.expanduser("~"), "~"),
            "text": xdg_desktop_entry(cmd).rstrip() + "\n\n# Or just use the \"Install\" button / `iridia autostart xdg-install`.",
        },
    ]


def detect_compositor() -> str:
    """The snippet id for the compositor this session runs in, or "" (desktops that read
    ~/.config/autostart, or unknown)."""
    env = os.environ
    desk = (env.get("XDG_CURRENT_DESKTOP", "") + ":" + env.get("XDG_SESSION_DESKTOP", "")).lower()
    if env.get("HYPRLAND_INSTANCE_SIGNATURE") or "hyprland" in desk:
        lua = os.path.expanduser("~/.config/hypr/hyprland.lua")
        return "hyprland-lua" if os.path.exists(lua) else "hyprland-conf"
    if env.get("NIRI_SOCKET") or "niri" in desk:
        return "niri"
    if env.get("SWAYSOCK") or "sway" in desk:
        return "sway"
    if env.get("I3SOCK") or "i3" in desk:
        return "i3"
    if "river" in desk:
        return "river"
    if "wayfire" in desk:
        return "wayfire"
    if "labwc" in desk or "openbox" in desk:
        return "labwc"
    if "bspwm" in desk or "dwm" in desk:
        return "bspwm"
    if desk.strip(":"):
        return ""                   # a desktop that says what it is (GNOME, KDE, XFCE, ...): XDG autostart
    return _compositor_from_processes()


# compositors and window managers that don't set XDG_CURRENT_DESKTOP when started from a TTY,
# greetd or startx: found by their process instead
_PROCESS_IDS = {"river": "river", "Hyprland": "hyprland-conf", "sway": "sway", "niri": "niri", "i3": "i3",
                "labwc": "labwc", "openbox": "labwc", "wayfire": "wayfire", "bspwm": "bspwm", "dwm": "bspwm"}


def _compositor_from_processes(proc: str = "/proc") -> str:
    uid = os.getuid()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return ""
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "comm"), encoding="utf-8") as f:
                name = f.read().strip()
            if name in _PROCESS_IDS and os.stat(os.path.join(proc, pid)).st_uid == uid:
                sid = _PROCESS_IDS[name]
                if sid == "hyprland-conf" and os.path.exists(os.path.expanduser("~/.config/hypr/hyprland.lua")):
                    return "hyprland-lua"
                return sid
        except OSError:
            continue
    return ""


def snippet(snip_id: str) -> Dict[str, str]:
    return next((x for x in snippets() if x["id"] == snip_id), {})
