"""CLI client for controlling the Iridia daemon."""

import argparse
import os
import shutil
import subprocess
import sys

from iridia import assets
from iridia.ipc import IPCClient

SOCKET_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
    f"iridia-{os.getuid()}.sock"
)

SERVICE_NAME = "iridia-daemon.service"
SERVICE_PATH = os.path.expanduser(f"~/.config/systemd/user/{SERVICE_NAME}")

def _client():
    return IPCClient(SOCKET_PATH)

def cmd_status(args):
    resp = _client().send({"cmd": "status"})
    if not resp.get("ok"):
        print("Daemon not running. Start with: iridia-daemon")
        print("Or install service: iridia service install")
        return 1
    print("Daemon: running")
    print(f"Wallpaper: {resp.get('wallpaper', 'N/A')}")
    print(f"Extracted colors: {', '.join(resp.get('extracted_colors', [])[:4])}")
    print(f"Brightness: {resp.get('brightness', 'N/A')}%")
    print(f"DDC available: {resp.get('ddc_available', False)}")
    print(f"OpenRGB connected: {resp.get('openrgb_connected', False)}")
    corr = resp.get("correction") or {}
    names = {"full": "off", "palette": "palette", "calibrated": f"calibrated ({corr.get('profile', 'WS2812B')})",
             "mixed": "mixed (zones differ)"}
    print(f"Color correction: {names.get(corr.get('mode', 'full'), corr.get('mode'))}")
    print(f"Color backend: {resp.get('color_backend', 'N/A')}")
    n = resp.get("night") or {}
    print(f"Night mode: {'off' if not n.get('enabled') else ('on now' if n.get('active') else 'scheduled')}"
          + (f", {n.get('start')} to {n.get('end')}, cap {n.get('cap')}%" if n.get("enabled") else ""))
    if resp.get("frozen"):
        print("Colors: FROZEN (wallpaper changes ignored, 'iridia unfreeze' to follow it again)")
    if resp.get("lights_off") or resp.get("asleep"):
        print("Lights: off" + (" (PC asleep)" if resp.get("asleep") else " ('iridia lights on')"))
    print()
    print("Devices:")
    def corr_name(c):
        m = c.get("mode", "full")
        return "off" if m == "full" else f"calibrated ({c.get('calibration_profile', 'WS2812B')})" if m == "calibrated" else m

    for name, cfg in resp.get("device_configs", {}).items():
        status = "enabled" if cfg.get("enabled", True) else "disabled"
        zones = cfg.get("zones", {})
        if not zones:
            print(f"  {name}: {status} | LEDs={cfg.get('led_count', 20)} | pattern={cfg.get('pattern', 'solid')} | "
                  f"correction={corr_name(cfg)}")
            continue
        print(f"  {name}: {status}")
        for zname, zcfg in zones.items():
            zs = "" if zcfg.get("enabled", True) else " (off)"
            shown = f"{zcfg['display_name']} ({zname})" if zcfg.get("display_name") else zname
            print(f"    {shown}{zs}: LEDs={zcfg.get('led_count', 20)} | pattern={zcfg.get('pattern', 'solid')} | "
                  f"correction={corr_name(zcfg)}")

    real_devices = resp.get("devices", [])
    if real_devices:
        print()
        print("OpenRGB-reported hardware (what's actually plugged in):")
        for dev in real_devices:
            print(f"  {dev['name']}")
            for z in dev.get("zones", []):
                print(f"    {z['name']}: {z['led_count']} LEDs")
        print()
        print("If a zone's configured LED count above doesn't match the real")
        print("count here, iridia now falls back to the real count automatically -")
        print("but updating the config to match avoids relying on that fallback.")
    elif resp.get("openrgb_connected"):
        print()
        print("OpenRGB is connected but reports no devices.")

    print()
    print(f"Socket: {SOCKET_PATH}")
    print(f"Log file: {_log_path()}")
    return 0


def _log_path() -> str:
    """The log file the config points at (logging.file_path), or the default."""
    try:
        from iridia.config import Config
        p = Config().get("logging.file_path") or "~/.local/share/iridia/iridia.log"
    except Exception:                       # noqa: BLE001
        p = "~/.local/share/iridia/iridia.log"
    return os.path.expanduser(str(p))

def cmd_doctor(args):
    from iridia import diagnostics
    resp = _client().send({"cmd": "status"})
    reachable = resp.get("ok", False)
    checks = diagnostics.run_checks(resp if reachable else {}, reachable)
    checks.append(diagnostics.gui_check())
    print(diagnostics.format_text(checks))
    print()
    log_path = _log_path()
    if os.path.exists(log_path):
        print(f"Full log: {log_path}  (tail -f it while reproducing an issue)")
    else:
        print("Log file not created yet, enable it with: iridia config edit "
              '(set "logging": {"enabled": true}), then restart the daemon.')
    return 0 if all(c.ok is not False for c in checks) else 1

def _set_start_server(on: bool):
    """Save openrgb.start_server and tell a running daemon to reload its config."""
    from iridia.config import Config
    try:
        Config().set("openrgb.start_server", on)
    except Exception as e:
        print(f"Couldn't save openrgb.start_server in config.json: {e}")
    _client().send({"cmd": "reload_config"})


def cmd_openrgb(args):
    from iridia import openrgb_server as osrv
    if args.action == "enable":
        _set_start_server(True)
        ok, msg = osrv.enable()
        print(msg)
        return 0 if ok else 1
    if args.action == "disable":
        _set_start_server(False)
        ok, msg = osrv.disable()
        print(msg)
        print("The daemon won't start OpenRGB by itself either. Undo with: iridia openrgb enable")
        return 0 if ok else 1
    if args.action == "status":
        st = osrv.status()
        cmd = " ".join(st["command"]) or "not found (install OpenRGB, or set openrgb.server_command)"
        print(f"OpenRGB command:  {cmd}")
        if st["managed"]:
            print(f"Started by Iridia: {osrv.UNIT_NAME} ({st['active'] or '?'}, {st['enabled']})")
        else:
            print(f"Started by Iridia: no ({osrv.UNIT_NAME} not installed)")
        print("Started by others: " + (", ".join(st["others"]) or "nothing found"))
        print(f"Daemon may start it when unreachable: {'yes' if st['start_server'] else 'no'} (openrgb.start_server)")
        print(f"OpenRGB process running now: {'yes' if osrv.running() else 'no'}")
        return 0
    if args.action == "reconnect":
        resp = _client().send({"cmd": "reconnect_openrgb"})
    elif args.action == "restart":
        resp = _client().send({"cmd": "restart_openrgb_server"})
    if not resp.get("ok"):
        print(f"Failed: {resp.get('error', 'unknown error')}")
        return 1
    print("OK" if args.action == "reconnect" else "Restarting, give it a few seconds, then check: iridia doctor")
    return 0

def cmd_device(args):
    try:
        return _cmd_device(args)
    except (ValueError, AttributeError):
        print(f"'{args.value}' isn't a valid value for {args.action}. See: iridia device --help", file=sys.stderr)
        return 2


def _cmd_device(args):
    if args.action == "enable":
        resp = _client().send({"cmd": "set_device", "device": args.name, "enabled": True})
    elif args.action == "disable":
        resp = _client().send({"cmd": "set_device", "device": args.name, "enabled": False})
    elif args.action == "mode":
        resp = _client().send({"cmd": "set_mode", "device": args.name, "mode": args.value})
    elif args.action == "pattern":
        resp = _client().send({"cmd": "set_pattern", "device": args.name, "pattern": args.value})
    elif args.action == "brightness-sync":
        enabled = args.value.lower() in ("on", "true", "1", "yes")
        resp = _client().send({"cmd": "set_brightness_sync", "device": args.name, "enabled": enabled})
    elif args.action == "manual-brightness":
        resp = _client().send({"cmd": "set_manual_brightness", "device": args.name, "value": int(args.value)})
    elif args.action == "brightness-range":
        parts = args.value.split(",")
        if len(parts) != 2:
            print("Usage: --value 0,100")
            return 1
        resp = _client().send({"cmd": "set_brightness_range", "device": args.name, "min": int(parts[0]), "max": int(parts[1])})
    elif args.action == "invert":
        enabled = args.value.lower() in ("on", "true", "1", "yes")
        resp = _client().send({"cmd": "set_invert", "device": args.name, "enabled": enabled})
    elif args.action == "gamma":
        enabled = args.value.lower() in ("on", "true", "1", "yes")
        resp = _client().send({"cmd": "set_gamma", "device": args.name, "enabled": enabled})
    elif args.action == "led-count":
        resp = _client().send({"cmd": "set_led_count", "device": args.name, "zone": args.zone or "", "count": int(args.value)})
    elif args.action == "zone-pattern":
        resp = _client().send({"cmd": "set_zone_pattern", "device": args.name, "zone": args.zone, "pattern": args.value})
    elif args.action == "zone-colors":
        indices = [int(x) if x.strip().isdigit() else x.strip().lstrip("#") for x in args.value.split(",") if x.strip()]
        resp = _client().send({"cmd": "set_zone_colors", "device": args.name, "zone": args.zone, "indices": indices})
    else:
        print(f"Unknown action: {args.action}")
        return 1
    if resp.get("ok"):
        print("OK")
        return 0
    print(f"Error: {resp.get('error', 'unknown')}")
    return 1

def cmd_refresh(args):
    resp = _client().send({"cmd": "refresh_wallpaper"})
    if resp.get("ok"):
        print(f"Refreshed. Colors: {resp.get('colors', [])}")
        return 0
    print(f"Error: {resp.get('error', 'unknown')}")
    return 1

def cmd_wallpaper(args):
    if args.reset_detection:
        resp = _client().send({"cmd": "reset_detection"})
        print("Wallpaper detection cache cleared." if resp.get("ok") else f"Failed: {resp.get('error')}")
        return 0
    if not args.path:
        resp = _client().send({"cmd": "status"})
        print(f"Current wallpaper: {resp.get('wallpaper', 'N/A')}")
        return 0
    from iridia.config import Config
    cfg = Config()
    cfg.set("wallpaper.source", "manual")
    cfg.set("wallpaper.manual_path", os.path.abspath(os.path.expanduser(args.path)))
    _client().send({"cmd": "reload_config"})
    print(f"Wallpaper set to: {args.path}")
    return 0

def cmd_config(args):
    config_path = os.path.expanduser("~/.config/iridia/config.json")
    if args.action == "show":
        if os.path.exists(config_path):
            with open(config_path) as f:
                print(f.read())
        else:
            print("Config not found")
            return 1
    elif args.action == "edit":
        editor = os.environ.get("EDITOR", "nano")
        subprocess.call([editor, config_path])
        _client().send({"cmd": "reload_config"})
    elif args.action == "path":
        print(config_path)
        return 0

def cmd_palette(args):
    from iridia.palette import Palette
    p = Palette()
    if args.action == "reset":
        p.reset()
        print("Palette reset to defaults")
        _client().send({"cmd": "reload_config"})
    elif args.action == "path":
        print(p.path)
    elif args.action == "list":
        for i, (h, c, n) in enumerate(p.colors):
            print(f"{i+1:2d}. {n:20s} #{c} (hue {h:.1f})")
    return 0

def cmd_restart(args):
    resp = _client().send({"cmd": "restart"})
    if resp.get("ok"):
        print("Daemon restarted")
        return 0
    print(f"Error: {resp.get('error', 'unknown')}")
    return 1

def cmd_autostart(args):
    from iridia import autostart
    if args.action == "xdg-install":
        print(f"Installed: {autostart.xdg_install()}")
        return 0
    if args.action == "xdg-remove":
        print("Removed." if autostart.xdg_remove() else "Nothing to remove.")
        return 0
    print("Ways to start iridia at login (combine freely - only one daemon ever runs):\n")
    for s in autostart.snippets():
        print(f"== {s['title']}\n   file: {s['file']}\n")
        print("   " + s["text"].replace("\n", "\n   ") + "\n")
    return 0


def cmd_log(args):
    resp = _client().send({"cmd": "get_log", "lines": args.lines})
    if not resp.get("ok"):
        print(f"Couldn't read the log: {resp.get('error')}")
        return 1
    print("\n".join(resp.get("lines", [])))
    return 0


def cmd_uninstall(args):
    """Remove Iridia: daemon, systemd unit, launcher, icons, autostart entry,
    and (unless --keep-settings) your settings, then the virtualenv itself."""
    import time
    from iridia import autostart
    purge = not args.keep_settings
    venv = os.path.dirname(_venv_bin_dir())
    own_venv = os.path.basename(venv) == "iridia-venv"
    if not args.yes:
        print("This will remove Iridia: the daemon, systemd service, launcher entry, icons"
              + (", and all your settings" if purge else "") + ".")
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1
    print("Stopping the daemon...")
    try:
        cmd_daemon(argparse.Namespace(action="stop"))
    except Exception:
        pass
    print("Removing service, launcher and icons...")
    _service_remove()
    try:
        from iridia import openrgb_server
        if openrgb_server.managed():
            print(openrgb_server.disable()[1])
    except Exception:
        pass
    try:
        if autostart.xdg_installed():
            autostart.xdg_remove()
            print("Removed the XDG autostart entry.")
    except Exception:
        pass
    if purge:
        for d in ("~/.config/iridia", "~/.cache/iridia", "~/.local/share/iridia"):
            shutil.rmtree(os.path.expanduser(d), ignore_errors=True)
        print("Removed your settings, caches and logs.")
    else:
        print("Kept your settings in ~/.config/iridia/.")
    print("")
    print("If you added an Iridia startup line to your compositor's config, remove it too.")
    if own_venv:
        time.sleep(0.2)
        shutil.rmtree(venv, ignore_errors=True)
        print("Removed the Iridia program files. Iridia is uninstalled.")
    else:
        print("Iridia was installed outside its own virtualenv; remove it with the tool you used "
              "(for example: pip uninstall iridia, or pipx uninstall iridia).")
    return 0


def cmd_preview(args):
    """Show one colour on every LED without saving it (`off` ends the preview)."""
    val = None if args.hex.lower() in ("off", "none", "clear") else args.hex
    try:
        resp = _client().send({"cmd": "preview_color", "hex": val})
    except Exception as e:
        print(f"Couldn't reach the daemon: {e}", file=sys.stderr)
        return 1
    if not resp.get("ok"):
        print(f"Failed: {resp.get('error')}", file=sys.stderr)
        return 1
    print("Preview ended." if val is None else f"Showing #{val.lstrip('#')} on all LEDs (lasts up to 5 minutes; "
          "run 'iridia preview off' to end it).")
    return 0


def _simple(req, ok_text):
    try:
        resp = _client().send(req)
    except Exception as e:
        print(f"Couldn't reach the daemon: {e}", file=sys.stderr)
        return 1
    if not resp.get("ok"):
        print(f"Failed: {resp.get('error')}", file=sys.stderr)
        return 1
    print(ok_text)
    return 0


def cmd_freeze(args):
    if getattr(args, "state", None) == "toggle":
        return _report({"cmd": "freeze", "toggle": True},
                       lambda r: "Colors frozen." if r.get("frozen") else "Colors follow the wallpaper again.")
    return _simple({"cmd": "freeze", "on": True},
                   "Colors frozen. Wallpaper changes are ignored until 'iridia unfreeze'.")


def _report(req, text):
    """Send a request and print text(response) (or the error)."""
    try:
        resp = _client().send(req)
    except Exception as e:                  # noqa: BLE001
        print(f"Couldn't reach the daemon: {e}", file=sys.stderr)
        return 1
    if not resp.get("ok"):
        print(f"Failed: {resp.get('error')}", file=sys.stderr)
        return 1
    print(text(resp))
    return 0


def cmd_zone(args):
    """Keybind commands: iridia zone "Desk back" off | on | color ff0000 | bright 30 | normal."""
    if args.target == "list" and not args.actions:
        try:
            resp = _client().send({"cmd": "zone_targets"})
        except Exception as e:              # noqa: BLE001
            print(f"Couldn't reach the daemon: {e}", file=sys.stderr)
            return 1
        if not resp.get("ok"):
            print(f"Failed: {resp.get('error')}", file=sys.stderr)
            return 1
        print("Strips you can use (the name, or Device/Zone when two share a name):")
        for t in resp.get("targets", []):
            where = f"{t['device']}/{t['zone']}" if t["zone"] else t["device"]
            print(f"  {t['name']:<28} {where}{'' if t['enabled'] else '  (switched off)'}")
        print("  all                          every strip")
        return 0
    if not args.actions:
        print("Say what to do: on, off, color HEX, bright PERCENT (any mix), or normal. "
              "'iridia zone list' shows the strip names.", file=sys.stderr)
        return 2
    return _report({"cmd": "zone_action", "target": args.target, "actions": args.actions,
                    "toggle": not args.set},
                   lambda r: r.get("message", "Done."))


def cmd_unfreeze(args):
    return _simple({"cmd": "freeze", "on": False}, "Colors follow the wallpaper again.")


def cmd_lights(args):
    if args.state == "toggle":
        return _report({"cmd": "lights", "toggle": True},
                       lambda r: "Lights off." if r.get("lights_off") else "Lights on.")
    on = args.state == "on"
    return _simple({"cmd": "lights", "on": on}, "Lights on." if on else "Lights off. 'iridia lights on' brings them back.")


def cmd_night(args):
    req = {"cmd": "set_night"}
    if args.state == "toggle":
        req["toggle"] = True
    elif args.state in ("on", "off"):
        req["enabled"] = args.state == "on"
    for k in ("start", "end", "cap"):
        v = getattr(args, k)
        if v is not None:
            req[k] = v
    try:
        resp = _client().send(req)
    except Exception as e:
        print(f"Couldn't reach the daemon: {e}", file=sys.stderr)
        return 1
    if not resp.get("ok"):
        print(f"Failed: {resp.get('error')}", file=sys.stderr)
        return 1
    n = resp["night"]
    print(f"Night mode {'on' if n['enabled'] else 'off'}: {n['start']} to {n['end']}, brightness capped at {n['cap']}%")
    return 0


def cmd_setup(args):
    req = {"cmd": f"setup_{args.action}"}
    if args.action in ("save", "load", "delete", "export"):
        if not args.name:
            print("Give the setup's name.", file=sys.stderr)
            return 2
        req["name"] = args.name
    if args.action == "export":
        req["dest"] = args.file or f"iridia-{args.name}.json"
    if args.action == "import":
        if not args.name:
            print("Give the file to import.", file=sys.stderr)
            return 2
        req["src"] = args.name
    try:
        resp = _client().send(req)
    except Exception as e:
        print(f"Couldn't reach the daemon: {e}", file=sys.stderr)
        return 1
    if not resp.get("ok"):
        print(f"Failed: {resp.get('error')}", file=sys.stderr)
        return 1
    if args.action == "list":
        for s in resp.get("setups", []):
            print(f"  {s['name']:<30} {s.get('saved', '')}")
        if not resp.get("setups"):
            print("  (no setups yet: iridia setup save NAME)")
        if resp.get("backups"):
            print("Automatic backups:")
            for b in resp["backups"]:
                print(f"  {b['saved']:<17} {b.get('reason', '')}")
    elif args.action == "import":
        print(f"Imported as '{resp.get('name')}'. Load it with: iridia setup load \"{resp.get('name')}\"")
    else:
        print({"save": "Saved.", "load": "Loaded (your previous settings were backed up first).",
               "delete": "Deleted.", "export": f"Exported to {req.get('dest')}."}[args.action])
    return 0


def cmd_identify(args):
    if args.device.lower() == "off":
        return _simple({"cmd": "identify", "off": True}, "Identify ended.")
    return _simple({"cmd": "identify", "device": args.device, "zone": args.zone or "", "seconds": args.seconds},
                   f"Lighting only {args.device}{'/' + args.zone if args.zone else ''} for {args.seconds}s "
                   "('iridia identify off' to end it).")


def cmd_service(args):
    if args.action == "install":
        return _service_install()
    elif args.action == "remove":
        return _service_remove()
    elif args.action == "status":
        return _service_status()
    elif args.action == "start":
        return _service_start()
    elif args.action == "stop":
        return _service_stop()
    elif args.action == "restart":
        return _service_restart()
    else:
        print(f"Unknown action: {args.action}")
        return 1

def _venv_bin_dir() -> str:
    """Directory containing this running interpreter's console-scripts.

    Derived from sys.executable rather than a hardcoded venv path, so
    this works correctly regardless of exactly how iridia was
    installed (the documented ~/.local/share/iridia-venv convention,
    a differently-located venv, pipx, etc.) as long as this CLI is
    itself being run through the right interpreter — which it must be,
    since that's how it got invoked at all.
    """
    return os.path.dirname(os.path.abspath(sys.executable))

def _systemctl(*args, capture=False):
    """systemctl --user ..., or None when this system has no systemd (Void, Alpine, Artix,
    Gentoo with OpenRC...) or no user session manager is reachable."""
    if not shutil.which("systemctl"):
        return None
    try:
        return subprocess.run(["systemctl", "--user", *args], check=False, timeout=20,
                              capture_output=capture, text=True)
    except (OSError, subprocess.SubprocessError):
        return None


def _has_user_systemd() -> bool:
    r = _systemctl("show-environment", capture=True)
    return bool(r) and r.returncode == 0


def _service_install():
    bin_dir = _venv_bin_dir()
    python_bin = os.path.join(bin_dir, "python3")
    gui_bin = os.path.join(bin_dir, "iridia-gui")
    if not os.path.exists(python_bin) or not os.path.exists(gui_bin):
        print(f"Expected iridia's venv binaries in {bin_dir} but didn't find them.")
        print("Run install.sh (in the Iridia folder) first, or activate the right virtualenv before running this.")
        return 1

    os.makedirs(os.path.dirname(SERVICE_PATH), exist_ok=True)
    service_content = f"""[Unit]
Description=Iridia Daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart={python_bin} -m iridia.daemon
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
Environment=\"PYTHONUNBUFFERED=1\"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical-session.target
"""
    with open(SERVICE_PATH, "w") as f:
        f.write(service_content)

    _install_icon()

    apps_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps_dir, exist_ok=True)
    desktop_path = os.path.join(apps_dir, f"{assets.APP_ID}.desktop")
    for old in assets.OLD_LAUNCHERS:
        legacy = os.path.join(apps_dir, old)
        if os.path.exists(legacy):
            os.remove(legacy)
    # Exec uses the resolved absolute path rather than the bare
    # `iridia-gui` command: a .desktop Exec= line is launched directly
    # by the desktop environment, not through a login shell, so it
    # never sees PATH additions a venv relies on — a bare command name
    # here would silently fail to launch for virtually everyone.
    desktop_content = f"""[Desktop Entry]
Name=Iridia
Comment=Sync LED colors with wallpaper via OpenRGB
Exec={gui_bin}
Type=Application
Terminal=false
Categories=System;Settings;HardwareSettings;
Keywords=led;rgb;openrgb;wallpaper;light;strip;
Icon={assets.ICON_NAME}
StartupNotify=false
StartupWMClass={assets.APP_ID}
"""
    with open(desktop_path, "w") as f:
        f.write(desktop_content)
    os.chmod(desktop_path, 0o644)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", apps_dir], check=False, capture_output=True)
    print(f"Launcher: {desktop_path}")
    if not _has_user_systemd():
        # No systemd user session: start at login through the desktop's autostart folder
        # instead (GNOME, KDE, XFCE, ... read it; tiling compositors need one line, see below).
        from iridia import autostart
        try:
            path = autostart.xdg_install()
            print(f"No systemd user session here, so the daemon starts at login via {path} instead.")
        except OSError as e:
            print(f"No systemd user session here, and the autostart entry couldn't be written: {e}")
        print("Compositors that don't read ~/.config/autostart (Hyprland, Sway, niri, river, ...) need one line")
        print(f"in their config, for example:  exec-once = {autostart.daemon_command()}")
        print("`iridia autostart` lists the line for each compositor.")
        return 0
    _systemctl("daemon-reload")
    _systemctl("enable", SERVICE_NAME)
    _systemctl("start", SERVICE_NAME)
    print("Service installed and started.")
    _openrgb_auto_setup()
    return 0


def _openrgb_auto_setup():
    """Have OpenRGB's server start at login too, unless something else already does it."""
    from iridia import openrgb_server
    try:
        msg = openrgb_server.auto_setup()
    except Exception as e:
        msg = f"Note: couldn't set up OpenRGB's server: {e}"
    if msg:
        print(msg)

def _icon_dirs():
    base = os.path.expanduser("~/.local/share/icons/hicolor")
    return base, os.path.join(base, "scalable", "apps")


def _purge_stale_icons():
    """Old installs (or other tools) may have left iridia icons in sizes
    that now take precedence over the new scalable one, so the launcher
    keeps showing the old picture."""
    base, _ = _icon_dirs()
    removed = []
    for root, _dirs, files in os.walk(base):
        for fn in files:
            if fn.split(".")[0] in (assets.ICON_NAME, f"{assets.ICON_NAME}-symbolic"):
                p = os.path.join(root, fn)
                try:
                    os.remove(p)
                    removed.append(p)
                except OSError:
                    pass
    for ext in ("png", "svg", "xpm"):
        p = os.path.expanduser(f"~/.local/share/pixmaps/{assets.ICON_NAME}.{ext}")
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    return removed


def _install_icon():
    """Install the bundled icon into the user's hicolor icon theme so
    it's found by name (Icon=iridia) regardless of where the package
    itself is installed."""
    try:
        base, icon_dir = _icon_dirs()
        _purge_stale_icons()
        os.makedirs(icon_dir, exist_ok=True)
        dest = os.path.join(icon_dir, f"{assets.ICON_NAME}.svg")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(assets.read_icon_svg())
        # Themed (currentColor) variant: panels/trays/GTK recolour *-symbolic icons.
        shutil.copyfile(assets.symbolic_svg_path(), os.path.join(icon_dir, f"{assets.ICON_NAME}-symbolic.svg"))
        # Pre-rendered sizes for launchers that don't render SVG.
        for n in assets.ICON_SIZES:
            d = os.path.join(base, f"{n}x{n}", "apps")
            os.makedirs(d, exist_ok=True)
            shutil.copyfile(assets.icon_png_for(n), os.path.join(d, f"{assets.ICON_NAME}.png"))
        if shutil.which("gtk-update-icon-cache"):
            subprocess.run(["gtk-update-icon-cache", "-f", "-t", base],
                            check=False, capture_output=True)
    except OSError as e:
        print(f"Warning: could not install icon: {e}")

def _remove_icon():
    _purge_stale_icons()

def _service_remove():
    _systemctl("stop", SERVICE_NAME)
    _systemctl("disable", SERVICE_NAME)
    if os.path.exists(SERVICE_PATH):
        os.remove(SERVICE_PATH)
    for fn in (f"{assets.APP_ID}.desktop",) + assets.OLD_LAUNCHERS:
        desktop_path = os.path.expanduser(f"~/.local/share/applications/{fn}")
        if os.path.exists(desktop_path):
            os.remove(desktop_path)
    _remove_icon()
    apps_dir = os.path.expanduser("~/.local/share/applications")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", apps_dir], check=False, capture_output=True)
    _systemctl("daemon-reload")
    print("Service removed.")
    return 0

def _lock_pid():
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    try:
        with open(os.path.join(base, f"iridia-daemon-{os.getuid()}.lock")) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _daemon_running() -> bool:
    try:
        return bool(_client().send({"cmd": "ping"}).get("ok"))
    except Exception:
        return False


def cmd_daemon(args):
    import signal
    import time
    if args.action == "status":
        try:
            st = _client().send({"cmd": "status"})
        except Exception:
            st = {}
        if st.get("ok"):
            by = "systemd" if st.get("managed_by") == "systemd" else "another method"
            print(f"Running (pid {st.get('pid')}, started by {by})")
            return 0
        print("Stopped")
        return 1
    if args.action == "start":
        if _daemon_running():
            print("Daemon is already running")
            return 0
        unit = SERVICE_PATH
        if os.path.exists(unit) and _has_user_systemd():
            _systemctl("start", SERVICE_NAME)
        else:
            from iridia import autostart
            try:
                subprocess.Popen([autostart.daemon_command()], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as e:
                print(f"Couldn't launch iridia-daemon: {e}", file=sys.stderr)
                return 1
        for _ in range(30):
            if _daemon_running():
                print("Daemon started")
                return 0
            time.sleep(0.2)
        print("Daemon did not come up; check `iridia log` or `journalctl --user -u iridia-daemon`", file=sys.stderr)
        return 1
    # stop: IPC shutdown, then systemctl, then SIGTERM
    if not _daemon_running() and _lock_pid() is None:
        print("Daemon is not running")
        return 0
    try:
        _client().send({"cmd": "shutdown"})
    except Exception:
        pass
    def gone(t):
        end = time.time() + t
        while time.time() < end:
            if not _daemon_running():
                return True
            time.sleep(0.2)
        return False
    if not gone(3):
        _systemctl("stop", SERVICE_NAME, capture=True)
        if not gone(3):
            pid = _lock_pid()
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            if not gone(3):
                print("Could not stop the daemon", file=sys.stderr)
                return 1
    print("Daemon stopped")
    return 0


def _service_status():
    result = _systemctl("is-active", SERVICE_NAME, capture=True)
    status = (result.stdout.strip() if result else "") or "unknown (no systemd user session reachable)"
    print(f"Service status: {status}")
    return 0 if status == "active" else 1

def _service_start():
    if _systemctl("start", SERVICE_NAME) is None:
        print("No systemd user session here; use `iridia daemon start`")
        return 1
    print("Service started")
    return 0

def _service_stop():
    if _systemctl("stop", SERVICE_NAME) is None:
        print("No systemd user session here; use `iridia daemon stop`")
        return 1
    print("Service stopped")
    return 0

def _service_restart():
    if _systemctl("restart", SERVICE_NAME) is None:
        print("No systemd user session here; use `iridia daemon stop`, then `iridia daemon start`")
        return 1
    print("Service restarted")
    return 0

def main():
    from iridia import get_version
    parser = argparse.ArgumentParser(prog="iridia", description="Iridia CLI")
    parser.add_argument("--version", action="version", version=f"iridia {get_version()}")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show daemon status")
    subparsers.add_parser("doctor", help="Run a full health check and explain what's wrong, if anything")
    orgb_parser = subparsers.add_parser("openrgb", help="Manage the OpenRGB connection")
    orgb_parser.add_argument("action", choices=["reconnect", "restart", "enable", "disable", "status"],
                             help="reconnect, restart the server, enable/disable starting its server at login, "
                                  "status")
    dev_parser = subparsers.add_parser("device", help="Control a device")
    dev_parser.add_argument("name", help="Device name")
    dev_parser.add_argument("action", choices=["enable", "disable", "mode", "pattern", "brightness-sync",
        "manual-brightness", "brightness-range", "invert", "gamma", "led-count", "zone-pattern", "zone-colors"])
    dev_parser.add_argument("--value", "-v", default="", help="Value for the action: mode full|palette|calibrated, "
                            "pattern name, on/off, a number, 'min,max' for brightness-range, color list like "
                            "'0,2,ff8800' for zone-colors")
    dev_parser.add_argument("--zone", "-z", default=None, help="Zone name")
    subparsers.add_parser("refresh", help="Force wallpaper refresh")
    wp_parser = subparsers.add_parser("wallpaper", help="Show or set wallpaper path")
    wp_parser.add_argument("path", nargs="?", help="Path to image")
    wp_parser.add_argument("--reset-detection", action="store_true",
                           help="Forget the cached wallpaper backend and probe all of them again")
    cfg_parser = subparsers.add_parser("config", help="Config operations")
    cfg_parser.add_argument("action", choices=["show", "edit", "path"])
    pal_parser = subparsers.add_parser("palette", help="Palette operations")
    pal_parser.add_argument("action", choices=["reset", "path", "list"])
    subparsers.add_parser("restart", help="Soft-restart the daemon")
    log_parser = subparsers.add_parser("log", help="Show the daemon's most recent log lines")
    log_parser.add_argument("-n", "--lines", type=int, default=20)
    as_parser = subparsers.add_parser("autostart", help="Show/install login-autostart methods (compositor config, XDG)")
    as_parser.add_argument("action", nargs="?", default="show", choices=["show", "xdg-install", "xdg-remove"])
    pv_parser = subparsers.add_parser("preview", help="Show one color on all LEDs without saving it")
    pv_parser.add_argument("hex", help="a hex color like 00ff88, or 'off'")
    fr_parser = subparsers.add_parser("freeze", help="Keep the current colors, ignore wallpaper changes")
    fr_parser.add_argument("state", nargs="?", choices=["on", "toggle"], default="on")
    z_parser = subparsers.add_parser(
        "zone", help="Keybind actions for strips: on, off, color HEX, bright PERCENT (any mix), normal",
        description="Change strips for a moment (nothing is saved). Running the same command again puts them "
                    "back to normal, so one key can switch both ways. Mix actions freely. Examples:  "
                    "iridia zone \"Desk back\" off   iridia zone \"Desk back,Monitor\" on color ff0000 bright 40   "
                    "iridia zone all color 00ff88 bright 20   iridia zone list")
    z_parser.add_argument("target", help="a strip name, several separated by commas, Device/Zone, a device "
                                         "name, 'all', or 'list'")
    z_parser.add_argument("actions", nargs="*", help="on | off | color HEX | bright PERCENT | normal")
    z_parser.add_argument("--set", action="store_true", help="don't switch back when it's already set")
    subparsers.add_parser("unfreeze", help="Follow the wallpaper again")
    n_parser = subparsers.add_parser("night", help="Night mode: cap brightness between two times")
    n_parser.add_argument("state", nargs="?", choices=["on", "off", "toggle", "show"], default="show")
    n_parser.add_argument("--start", help="e.g. 23:00")
    n_parser.add_argument("--end", help="e.g. 07:00")
    n_parser.add_argument("--cap", type=int, help="brightness cap in percent")
    s_parser = subparsers.add_parser("setup", help="Save, load and back up your whole setup")
    s_parser.add_argument("action", choices=["list", "save", "load", "delete", "export", "import"])
    s_parser.add_argument("name", nargs="?", help="setup name (or the file, for import)")
    s_parser.add_argument("file", nargs="?", help="destination file for export")
    l_parser = subparsers.add_parser("lights", help="Turn all LEDs off or back on")
    l_parser.add_argument("state", choices=["on", "off", "toggle"])
    id_parser = subparsers.add_parser("identify", help="Light only one zone, to see which strip it is")
    id_parser.add_argument("device", help="device name, or 'off'")
    id_parser.add_argument("-z", "--zone", help="zone name")
    id_parser.add_argument("-s", "--seconds", type=int, default=60)
    u_parser = subparsers.add_parser("uninstall", help="Remove Iridia completely")
    u_parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    u_parser.add_argument("--keep-settings", action="store_true", help="keep ~/.config/iridia")
    d_parser = subparsers.add_parser("daemon", help="Start, stop or check the background daemon")
    d_parser.add_argument("action", choices=["start", "stop", "status"])
    svc_parser = subparsers.add_parser("service", help="Manage systemd service")
    svc_parser.add_argument("action", choices=["install", "remove", "status", "start", "stop", "restart"])
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    commands = {"status": cmd_status, "doctor": cmd_doctor, "openrgb": cmd_openrgb,
                "device": cmd_device, "refresh": cmd_refresh,
                "wallpaper": cmd_wallpaper, "config": cmd_config, "palette": cmd_palette,
                "restart": cmd_restart, "service": cmd_service, "daemon": cmd_daemon, "preview": cmd_preview, "uninstall": cmd_uninstall,
                "freeze": cmd_freeze, "zone": cmd_zone, "unfreeze": cmd_unfreeze, "lights": cmd_lights, "night": cmd_night, "setup": cmd_setup, "identify": cmd_identify, "autostart": cmd_autostart, "log": cmd_log}
    return commands[args.command](args)

if __name__ == "__main__":
    sys.exit(main())
