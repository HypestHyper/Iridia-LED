"""Shared health-check logic for `iridia doctor` (CLI) and the GUI's
diagnostics dialog. Kept in one place so the two can't drift apart on
what counts as healthy — each just renders the same Check list for its
own medium (plain text vs a colored dialog).
"""

import os
import subprocess
import time
from typing import List, NamedTuple, Optional


class Check(NamedTuple):
    label: str
    ok: Optional[bool]   # True/False, or None for "informational, not a pass/fail"
    detail: str
    hint: str = ""


def systemd_unit_status(unit: str) -> Optional[str]:
    """Returns 'active'/'inactive'/'failed'/etc, or None if systemd
    --user isn't available/reachable at all (not every Linux install
    has it, and a bare `is-active` call can return nothing useful if
    the user session bus isn't reachable from here)."""
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", unit],
                           capture_output=True, text=True, timeout=3)
        out = r.stdout.strip()
        return out or None
    except Exception:
        return None


def run_checks(status: dict, socket_reachable: bool) -> List[Check]:
    checks = []

    if not socket_reachable:
        checks.append(Check(
            "Daemon reachable", False,
            "Couldn't connect to the daemon's socket.",
            "Start it: run 'iridia-daemon' in a terminal to see it live, or "
            "'systemctl --user start iridia-daemon.service' if it's installed as a service."
        ))
        return checks  # nothing else here is knowable without the daemon

    checks.append(Check("Daemon reachable", True,
                        f"pid {status.get('pid', '?')}, socket {status.get('socket_path', '?')}"))

    if status.get("openrgb_connected"):
        since = status.get("openrgb_connected_since")
        detail = f"Connected for {int(time.time() - since)}s" if since else "Connected"
        checks.append(Check("OpenRGB connection", True, detail))
        missing = status.get("openrgb_missing_devices", [])
        devs = status.get("device_configs", {})
        if missing:
            checks.append(Check(
                "Configured devices visible", False,
                f"Not seeing: {', '.join(missing)}",
                "Try Reconnect first, then Restart OpenRGB Server, from the GUI's Service "
                "tab (or: iridia openrgb reconnect / iridia openrgb restart). Auto-recovery "
                "will also attempt this on its own after a while."
            ))
        elif devs:
            checks.append(Check("Configured devices visible", True, f"{len(devs)} device(s), all present"))

        # Zone names in config must match what OpenRGB reports exactly,
        # and the device must be in Direct mode for colors to show.
        real = {d["name"]: d for d in status.get("devices", [])}
        for dname, dcfg in devs.items():
            if dname not in real or not dcfg.get("enabled", True):
                continue
            real_zones = [z["name"] for z in real[dname].get("zones", [])]
            cfg_zones = list(dcfg.get("zones", {}).keys())
            bad = [z for z in cfg_zones if z not in real_zones]
            if bad:
                checks.append(Check(
                    f"Zones of '{dname}'", False,
                    f"Config has {bad}, but OpenRGB reports {real_zones}",
                    "Rename the zone(s) in ~/.config/iridia/config.json to match the "
                    "OpenRGB names exactly, colors can't be sent to a zone that doesn't exist."))
            else:
                checks.append(Check(f"Zones of '{dname}'", True,
                                    ", ".join(f"{z['name']} ({z['led_count']} LEDs)"
                                              for z in real[dname].get("zones", []))))
            mode = real[dname].get("mode", "unknown")
            if mode.lower() not in ("direct", "unknown"):
                checks.append(Check(
                    f"Mode of '{dname}'", None,
                    f"Currently '{mode}', iridia switches it to Direct on the next send."))
        last_err = status.get("openrgb_last_error")
        if last_err:
            checks.append(Check("Last OpenRGB problem", False, last_err))
    else:
        err = status.get("openrgb_last_error") or "no server responded on any of the common ports"
        hint = ("Run the installer again so the library is installed: bash scripts/install.sh"
                if "library is missing" in err else None)
        checks.append(Check(
            "OpenRGB connection", False, err, hint or
            "Is OpenRGB's SDK server actually running? ('openrgb --server', or its systemd "
            "service if you use one, check with: systemctl --user status openrgb-server.service). "
            "Then try Reconnect from the Service tab (or: iridia openrgb reconnect)."
        ))

    if status.get("ddc_available"):
        checks.append(Check("Monitor brightness sync (DDC)", True, "Available"))
    else:
        err = status.get("ddc_last_error")
        checks.append(Check(
            "Monitor brightness sync (DDC)", None,
            err or "Not available",
            "Optional, only needed for LED brightness to follow monitor brightness. "
            "Needs 'ddcutil' installed, and DDC/CI enabled in the monitor's own OSD menu."
        ))

    wallpaper = status.get("wallpaper")
    backend = status.get("wallpaper_backend")
    if wallpaper:
        checks.append(Check("Wallpaper detection", True,
                            f"via '{backend}': {os.path.basename(wallpaper)}"))
    else:
        err = status.get("wallpaper_last_error") or "no backend matched this desktop environment"
        checks.append(Check(
            "Wallpaper detection", False, err,
            "Set wallpaper.manual_path or wallpaper.watch_folder in "
            "~/.config/iridia/config.json as a fallback."
        ))

    devs = status.get("device_configs", {})
    if not devs:
        checks.append(Check(
            "Devices configured", False, "No devices in config.json",
            'Add at least one device under "devices" in ~/.config/iridia/config.json.'
        ))

    cfg_path = status.get("config_path")
    if cfg_path:
        writable = os.access(cfg_path, os.W_OK) if os.path.exists(cfg_path) else os.access(os.path.dirname(cfg_path), os.W_OK)
        checks.append(Check("Config file writable", writable, cfg_path))

    svc = systemd_unit_status("iridia-daemon.service")
    if svc is not None:
        checks.append(Check("iridia-daemon.service", svc == "active" or None, svc))

    openrgb_svc = systemd_unit_status("openrgb-server.service")
    if openrgb_svc is not None:
        checks.append(Check("openrgb-server.service", openrgb_svc == "active" or None, openrgb_svc))

    return checks


def format_text(checks: List[Check]) -> str:
    lines = []
    for c in checks:
        symbol = "?" if c.ok is None else ("\u2713" if c.ok else "\u2717")
        lines.append(f"[{symbol}] {c.label}: {c.detail}")
        if c.ok is False and c.hint:
            lines.append(f"      -> {c.hint}")
    return "\n".join(lines)


def gui_check() -> Check:
    """Can the window open? It needs GTK 4 with PyGObject and pycairo."""
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        import cairo  # noqa: F401
        gi.require_foreign("cairo")
        v = f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}"
        if (Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 6):
            return Check("Window (GTK 4)", False, f"GTK {v} is too old", "Iridia's window needs GTK 4.6 or newer.")
        return Check("Window (GTK 4)", True, f"GTK {v}")
    except (ImportError, ValueError) as e:
        return Check("Window (GTK 4)", False, f"GTK 4 for Python isn't available ({e})",
                     "Install GTK 4, PyGObject and pycairo (the installer does this), then run it again: "
                     "bash scripts/install.sh")
