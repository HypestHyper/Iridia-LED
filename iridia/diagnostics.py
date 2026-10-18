"""Shared health-check logic for `iridia doctor` (CLI) and the GUI's
diagnostics dialog. Kept in one place so the two can't drift apart on
what counts as healthy — each just renders the same Check list for its
own medium (plain text vs a colored dialog).
"""

import os
import time
from typing import List, NamedTuple, Optional


class Check(NamedTuple):
    label: str
    ok: Optional[bool]   # True/False, or None for "informational, not a pass/fail"
    detail: str
    hint: str = ""


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
        proto = status.get("openrgb_protocol")
        if proto == 6:
            detail += ", SDK protocol 6 (every update waits until OpenRGB has applied it)"
        elif proto is not None:
            detail += ", OpenRGB older than 1.0 (openrgb-python)"
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
            # named, so a device that isn't there at all (OpenRGB doesn't report it) is noticed too
            checks.append(Check("Configured devices visible", True,
                                f"{len(devs)} device(s), all present: {', '.join(devs)}"))

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
        err = status.get("openrgb_last_error") or "no OpenRGB SDK server answered"
        since = status.get("openrgb_no_devices_since")
        if since:
            err = f"OpenRGB is running but has reported no devices for {int(time.time() - since)}s"
        if "library is missing" in err:
            hint = "Run the installer again so the library is installed: bash install.sh"
        elif since or "no devices" in err:
            hint = ("It probably started before your session could reach the hardware, and OpenRGB never looks "
                    "again by itself. " + ("Iridia started it, so it restarts it automatically (up to twice)."
                                           if status.get("openrgb_ours_pid") else
                                           "Iridia didn't start it, so restart it yourself: iridia openrgb restart, "
                                           "or however you started it."))
        else:
            hint = ("Is OpenRGB's SDK server running? See the \"OpenRGB at login\" line below. "
                    "If you use the OpenRGB window, turn on its SDK server (SDK Server tab, Start Server).")
        checks.append(Check("OpenRGB connection", False, err, hint))

    if status.get("ddc_available"):
        bus = status.get("ddc_bus")
        name = next((d.get("name") for d in status.get("ddc_displays") or [] if d.get("bus") == bus), None)
        checks.append(Check("Monitor brightness sync (DDC)", True,
                            "Following the screen's backlight" if status.get("ddc_source") == "backlight" else
                            f"Following {name or 'a monitor'} (I2C bus {bus})"
                            + ("" if status.get("ddc_choice") is not None else ", the first that answers")))
    else:
        err = status.get("ddc_last_error")
        checks.append(Check(
            "Monitor brightness sync (DDC)", None,
            err or "Not available",
            "Optional, only needed for LED brightness to follow monitor brightness; strips that follow it use "
            "their Manual brightness meanwhile. Needs 'ddcutil' installed, and DDC/CI enabled in the monitor's "
            "own menu. Pick the monitor in Settings, Monitor brightness (or: iridia monitor)."
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

    checks += daemon_login_checks(status)
    checks += openrgb_login_checks(status)
    return checks


def daemon_login_checks(status: dict) -> List[Check]:
    """How this daemon was started, and what starts it at login. A daemon started outside systemd
    is fine; "inactive" is never shown as a problem while the daemon answers."""
    from iridia import openrgb_server as osrv
    out = []
    by = status.get("started_by") or ("systemd" if status.get("managed_by") == "systemd" else "unknown")
    starters = osrv.daemon_starters()
    en, _ac = osrv.unit_state("iridia-daemon.service")
    detail = f"started by {by}"
    if en == "enabled" and not by.startswith("systemd"):
        detail += " (running, started outside systemd; iridia-daemon.service is enabled too)"
    out.append(Check("Daemon started", True, detail))
    if en == "enabled" and osrv.graphical_session_active() is False:
        out.append(Check("iridia-daemon.service", None,
                         "enabled, but your session doesn't start graphical-session.target, so it won't start "
                         "the daemon at login",
                         "Start the daemon from your compositor instead (see: iridia autostart), and disable the "
                         "service: systemctl --user disable iridia-daemon.service"))
    if not starters:
        out.append(Check("Daemon at login", False, "nothing found that starts the daemon at login",
                         "Set one up: iridia service install, or a line from: iridia autostart"))
    elif len(starters) > 1:
        out.append(Check("Daemon at login", None, f"set up in {len(starters)} places: {', '.join(starters)}. "
                         "Harmless (only one daemon runs), but one is enough."))
    else:
        out.append(Check("Daemon at login", True, starters[0]))
    return out


def openrgb_login_checks(status: dict) -> List[Check]:
    """Who starts OpenRGB's server, per openrgb.start_method, and whether something else does too."""
    from iridia import openrgb_server as osrv
    label = "OpenRGB at login"
    host = status.get("openrgb_host") or "127.0.0.1"
    if not osrv.is_local(host):
        return [Check(label, None, f"OpenRGB runs on another machine ({host}); start it there")]
    st = osrv.status()
    method = st["method"]
    connected = bool(status.get("openrgb_connected"))
    out = []
    if st["window_without_server"] and not connected:
        out.append(Check("OpenRGB window", False, "the OpenRGB window is open, but its SDK server is off",
                         "In OpenRGB: SDK Server tab, Start Server. Or close the window and let Iridia start "
                         "the server."))
    if method != "off" and st["others"]:
        hint = ("Turn off OpenRGB's own autostart: iridia openrgb hide-autostart (or the Service tab). "
                if st["xdg_entries"] else "Turn that off, ")
        out.append(Check("Other OpenRGB starters", False,
                         f"Iridia is set to start OpenRGB ({method}), and it's also started by "
                         f"{', '.join(st['others'])}. Two OpenRGB instances fight over the hardware, and Iridia "
                         "won't start one while another is set up.",
                         hint + "Or let the other one do it: iridia openrgb start-method off"))
    if not st["command"] and method != "off":
        out.append(Check(label, False, "OpenRGB isn't installed (no openrgb command, no Flatpak)",
                         "Install OpenRGB from your distribution, or set openrgb.server_command in config.json "
                         "to the command that runs its server (for an AppImage)."))
        return out
    if method == "off":
        detail = "openrgb.start_method is off: you start OpenRGB yourself"
        if st["others"]:
            detail += f" (found: {', '.join(st['others'])})"
        out.append(Check(label, True if connected else False, detail,
                         "Start OpenRGB's server, or let Iridia do it: iridia openrgb start-method daemon"))
    elif method == "systemd":
        if not st["managed"]:
            out.append(Check(label, False, f"start method is systemd, but {osrv.UNIT_NAME} isn't installed",
                             "Run: iridia openrgb start-method systemd  (or use: iridia openrgb start-method daemon)"))
        elif st["graphical_session"] is False:
            out.append(Check(label, False, f"{osrv.UNIT_NAME} waits for graphical-session.target, which your "
                             "session never starts (Hyprland without UWSM, for example)",
                             "Let the daemon start it instead: iridia openrgb start-method daemon"))
        else:
            detail = f"{osrv.UNIT_NAME}: {st['active'] or '?'}, {st['enabled']}"
            out.append(Check(label, True if (st["active"] == "active" or connected) else False, detail,
                             f"See why: systemctl --user status {osrv.UNIT_NAME}"))
    else:
        ours = status.get("openrgb_ours_pid") or st["ours"]
        if status.get("openrgb_gave_up"):
            out.append(Check(label, False, "the OpenRGB server Iridia started kept exiting, so Iridia stopped "
                             "restarting it", f"See {st['log']}, then: iridia openrgb restart"))
        elif ours:
            out.append(Check(label, True, f"started by the Iridia daemon (pid {ours}); output in {st['log']}"))
        elif connected:
            out.append(Check(label, True, "running, not started by Iridia (so Iridia won't restart it)"))
        else:
            out.append(Check(label, None, "the Iridia daemon starts it when it can't reach it"))
    return out


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
                     "bash install.sh")
