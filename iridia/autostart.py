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
Exec={cmd}
Icon=iridia
Terminal=false
X-GNOME-Autostart-enabled=true
NoDisplay=true
"""


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
                     "# Starts with your graphical session (graphical-session.target).\n"
                     "# Works out of the box on GNOME, KDE, Hyprland/Sway/niri started via UWSM or a display\n"
                     "# manager that activates the target. If your compositor does not, add one of the lines\n"
                     "# below as well - the daemon only ever runs once."),
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
            "id": "sway", "title": "Sway / i3",
            "file": "~/.config/sway/config  |  ~/.config/i3/config",
            "text": (f"# Sway\nexec {cmd}\n\n"
                     f"# i3\nexec --no-startup-id {cmd}"),
        },
        {
            "id": "river", "title": "river",
            "file": "~/.config/river/init",
            "text": f'riverctl spawn "{cmd}"',
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
