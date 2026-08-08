"""CLI client for controlling the Iridia daemon."""

import argparse
import json
import os
import subprocess
import sys

from iridia.ipc import IPCClient


SOCKET_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
    f"iridia-{os.getuid()}.sock"
)

SERVICE_NAME = "iridia-daemon.service"
SERVICE_PATH = os.path.expanduser(f"~/.config/systemd/user/{SERVICE_NAME}")


def _client() -> IPCClient:
    return IPCClient(SOCKET_PATH)


def cmd_status(args):
    resp = _client().send({"cmd": "status"})
    if not resp.get("ok"):
        print(f"Daemon not running. Start with: iridia-daemon")
        print(f"Or install service: iridia service install")
        return 1

    print(f"Daemon: running")
    print(f"Wallpaper: {resp.get('wallpaper', 'N/A')}")
    print(f"Extracted colors: {', '.join(resp.get('extracted_colors', [])[:4])}")
    print(f"Brightness: {resp.get('brightness', 'N/A')}%")
    print(f"DDC available: {resp.get('ddc_available', False)}")
    print(f"OpenRGB connected: {resp.get('openrgb_connected', False)}")
    print(f"Mode: {resp.get('mode', 'N/A')} / {resp.get('palette_mode', 'N/A')}")
    print()
    print("Devices:")
    for name, cfg in resp.get("device_configs", {}).items():
        status = "enabled" if cfg.get("enabled", True) else "disabled"
        print(f"  {name}: {status} | pattern={cfg.get('pattern', 'solid')} | mode={cfg.get('mode', 'palette')}")
    print()
    print(f"Socket: {SOCKET_PATH}")
    log_path = os.path.expanduser("~/.local/share/iridia/iridia.log")
    print(f"Log file: {log_path}")
    return 0


def cmd_device(args):
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
        resp = _client().send({
            "cmd": "set_brightness_range",
            "device": args.name,
            "min": int(parts[0]),
            "max": int(parts[1]),
        })
    elif args.action == "invert":
        enabled = args.value.lower() in ("on", "true", "1", "yes")
        resp = _client().send({"cmd": "set_invert", "device": args.name, "enabled": enabled})
    elif args.action == "gamma":
        enabled = args.value.lower() in ("on", "true", "1", "yes")
        resp = _client().send({"cmd": "set_gamma", "device": args.name, "enabled": enabled})
    elif args.action == "led-count":
        resp = _client().send({
            "cmd": "set_led_count",
            "device": args.name,
            "zone": args.zone or "",
            "count": int(args.value),
        })
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
    if not args.path:
        # Show current wallpaper
        resp = _client().send({"cmd": "status"})
        print(f"Current wallpaper: {resp.get('wallpaper', 'N/A')}")
        return 0
    # Set manual wallpaper path
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
            print(f"{i+1:2d}. {n:20s} #{c}  (hue {h:.1f})")
    return 0


def cmd_restart(args):
    resp = _client().send({"cmd": "restart"})
    if resp.get("ok"):
        print("Daemon restarted")
        return 0
    print(f"Error: {resp.get('error', 'unknown')}")
    return 1


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


def _service_install() -> int:
    venv = os.path.expanduser("~/.local/share/iridia-venv")
    if not os.path.exists(venv):
        print("Virtual environment not found. Run install.sh first.")
        return 1

    os.makedirs(os.path.dirname(SERVICE_PATH), exist_ok=True)

    service_content = f"""[Unit]
Description=Iridia Daemon
After=graphical-session.target network.target
Wants=graphical-session.target

[Service]
Type=simple
ExecStart={venv}/bin/python3 -m iridia.daemon
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
Environment="PYTHONUNBUFFERED=1"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    with open(SERVICE_PATH, "w") as f:
        f.write(service_content)

    # Install desktop entry
    apps_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps_dir, exist_ok=True)
    desktop_path = os.path.join(apps_dir, "iridia.desktop")
    desktop_content = """[Desktop Entry]
Name=Iridia
Comment=Sync LED colors with wallpaper via OpenRGB
Exec=iridia-gui
Type=Application
Terminal=false
Categories=System;Settings;HardwareSettings;
Keywords=led;rgb;openrgb;wallpaper;light;strip;
Icon=preferences-desktop-display-color
StartupNotify=false
StartupWMClass=iridia-gui
"""
    with open(desktop_path, "w") as f:
        f.write(desktop_content)
    os.chmod(desktop_path, 0o644)

    if subprocess.run(["which", "update-desktop-database"], capture_output=True).returncode == 0:
        subprocess.run(["update-desktop-database", apps_dir], check=False, capture_output=True)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=False)
    subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], check=False)

    print("Service installed and started.")
    print(f"  Status: systemctl --user status {SERVICE_NAME}")
    print(f"  Logs:   journalctl --user -u {SERVICE_NAME} -f")
    print(f"  App:    Search 'Iridia' in your app launcher (wofi/rofi/GNOME/KDE)")
    return 0


def _service_remove() -> int:
    subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=False)
    subprocess.run(["systemctl", "--user", "disable", SERVICE_NAME], check=False)
    if os.path.exists(SERVICE_PATH):
        os.remove(SERVICE_PATH)

    # Remove desktop entry
    desktop_path = os.path.expanduser("~/.local/share/applications/iridia.desktop")
    if os.path.exists(desktop_path):
        os.remove(desktop_path)
        apps_dir = os.path.expanduser("~/.local/share/applications")
        if subprocess.run(["which", "update-desktop-database"], capture_output=True).returncode == 0:
            subprocess.run(["update-desktop-database", apps_dir], check=False, capture_output=True)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print("Service removed.")
    print("Desktop entry removed.")
    print("Config preserved at ~/.config/iridia/")
    return 0


def _service_status() -> int:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", SERVICE_NAME],
        capture_output=True, text=True
    )
    status = result.stdout.strip()
    print(f"Service status: {status}")
    return 0 if status == "active" else 1


def _service_start() -> int:
    subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], check=False)
    print("Service started")
    return 0


def _service_stop() -> int:
    subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=False)
    print("Service stopped")
    return 0


def _service_restart() -> int:
    subprocess.run(["systemctl", "--user", "restart", SERVICE_NAME], check=False)
    print("Service restarted")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="iridia",
        description="Iridia CLI"
    )
    subparsers = parser.add_subparsers(dest="command")

    # status
    subparsers.add_parser("status", help="Show daemon status")

    # device
    dev_parser = subparsers.add_parser("device", help="Control a device")
    dev_parser.add_argument("name", help="Device name")
    dev_parser.add_argument("action", choices=[
        "enable", "disable", "mode", "pattern", "brightness-sync",
        "manual-brightness", "brightness-range", "invert", "gamma", "led-count"
    ])
    dev_parser.add_argument("--value", "-v", default="", help="Value for the action")
    dev_parser.add_argument("--zone", "-z", default=None, help="Zone name (for led-count)")

    # refresh
    subparsers.add_parser("refresh", help="Force wallpaper refresh")

    # wallpaper
    wp_parser = subparsers.add_parser("wallpaper", help="Show or set wallpaper path")
    wp_parser.add_argument("path", nargs="?", help="Path to image (omit to show current)")

    # config
    cfg_parser = subparsers.add_parser("config", help="Config operations")
    cfg_parser.add_argument("action", choices=["show", "edit", "path"])

    # palette
    pal_parser = subparsers.add_parser("palette", help="Palette operations")
    pal_parser.add_argument("action", choices=["reset", "path", "list"])

    # restart
    subparsers.add_parser("restart", help="Soft-restart the daemon")

    # service
    svc_parser = subparsers.add_parser("service", help="Manage systemd service")
    svc_parser.add_argument("action", choices=[
        "install", "remove", "status", "start", "stop", "restart"
    ])

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "status": cmd_status,
        "device": cmd_device,
        "refresh": cmd_refresh,
        "wallpaper": cmd_wallpaper,
        "config": cmd_config,
        "palette": cmd_palette,
        "restart": cmd_restart,
        "service": cmd_service,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
