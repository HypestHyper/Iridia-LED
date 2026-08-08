"""System tray GUI for Iridia using pystray."""

import json
import os
import subprocess
import threading
import time
import tkinter as tk

import pystray
from PIL import Image, ImageDraw

from iridia.client import Client
from iridia.config import Config
from iridia.palette import Palette
from iridia.dialogs import (
    DeviceDialog, ColorsDialog, PaletteDialog, SettingsDialog, ServiceDialog
)


# ---------------------------------------------------------------------------
# Icon generation
# ---------------------------------------------------------------------------

def _create_icon(color: str = "00aa66") -> Image.Image:
    """Generate a simple colored circle tray icon."""
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(r, g, b, 255))
    return img


# ---------------------------------------------------------------------------
# Tray App
# ---------------------------------------------------------------------------

class TrayApp:
    def __init__(self):
        self.client = Client()
        self.config = Config()
        self.palette = Palette()
        self.icon = None
        self._status = {}
        self._running = True
        self._poll_thread = None
        self._tk_root = None

    def run(self):
        """Start the tray icon and polling loop."""
        # Initialize tkinter root (hidden) for dialogs
        self._tk_root = tk.Tk()
        self._tk_root.withdraw()
        self._tk_root.configure(bg="#1e1e1e")

        # Start polling thread
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

        # Create tray icon
        self.icon = pystray.Icon(
            "iridia-tray",
            icon=_create_icon(),
            title="Iridia",
            menu=self._build_menu(),
        )
        self.icon.run()

    def _poll_loop(self):
        """Poll daemon status every 2 seconds and refresh menu."""
        while self._running:
            try:
                resp = self.client.status()
                if resp.get("ok"):
                    self._status = resp
                    # Update icon color to match dominant extracted color
                    colors = resp.get("extracted_colors", [])
                    if colors:
                        self._update_icon(colors[0])
                else:
                    self._status = {"_error": "daemon not running"}
            except Exception:
                self._status = {"_error": "connection failed"}

            # Refresh menu
            if self.icon:
                try:
                    self.icon.menu = self._build_menu()
                except Exception:
                    pass

            time.sleep(2)

    def _update_icon(self, hex_color: str):
        """Update tray icon to reflect current dominant color."""
        try:
            self.icon.icon = _create_icon(hex_color)
        except Exception:
            pass

    def _build_menu(self) -> pystray.Menu:
        """Build dynamic menu based on current status."""
        items = []

        # Status line
        if "_error" in self._status:
            items.append(pystray.MenuItem(
                f"⚠️ {self._status['_error']}", lambda: None, enabled=False
            ))
        else:
            colors = self._status.get("extracted_colors", [])
            wallpaper = self._status.get("wallpaper", "N/A")
            brightness = self._status.get("brightness", "?")
            dominant = colors[0] if colors else "N/A"
            wp_name = os.path.basename(wallpaper) if wallpaper != "N/A" else "N/A"
            items.append(pystray.MenuItem(
                f"🎨 #{dominant} | {brightness}% | {wp_name[:20]}",
                lambda: None, enabled=False
            ))

        items.append(pystray.Menu.SEPARATOR)

        # Devices submenu
        devices = self._status.get("device_configs", {})
        if devices:
            device_items = []
            for name, cfg in devices.items():
                device_items.append(self._build_device_submenu(name, cfg))
            items.append(pystray.MenuItem("Devices", pystray.Menu(*device_items)))

        # Colors from Wallpaper
        if colors:
            items.append(pystray.MenuItem(
                "Colors from Wallpaper...",
                lambda: self._open_colors_dialog(colors)
            ))

        # Palette Editor
        items.append(pystray.MenuItem(
            "Edit 48-Color Palette...",
            self._open_palette_dialog
        ))

        items.append(pystray.Menu.SEPARATOR)

        # Settings
        items.append(pystray.MenuItem(
            "Settings", pystray.Menu(
                pystray.MenuItem("Timing & Retries...", self._open_settings_dialog),
                pystray.MenuItem("Open Config Folder", self._open_config_folder),
            )
        ))

        items.append(pystray.Menu.SEPARATOR)

        # Actions
        items.append(pystray.MenuItem("Refresh Now", self._do_refresh))
        items.append(pystray.MenuItem("Restart Daemon", self._do_restart))

        # Service controls
        items.append(pystray.MenuItem(
            "Service", pystray.Menu(
                pystray.MenuItem("Start Service", self._service_start),
                pystray.MenuItem("Stop Service", self._service_stop),
                pystray.MenuItem("Manage Service...", self._open_service_dialog),
            )
        ))

        items.append(pystray.Menu.SEPARATOR)

        # Logging
        log_enabled = self.config.get("logging.enabled", False)
        log_path = os.path.expanduser(self.config.get("logging.file_path", "~/.local/share/iridia/iridia.log"))
        items.append(pystray.MenuItem(
            f"Log: {'ON' if log_enabled else 'OFF'} | {log_path}",
            lambda: None, enabled=False
        ))
        items.append(pystray.MenuItem(
            "Toggle Logging",
            self._toggle_logging,
            checked=lambda item: log_enabled
        ))
        items.append(pystray.MenuItem("Open Log Folder", self._open_log_folder))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", self._quit))

        return pystray.Menu(*items)

    def _build_device_submenu(self, name: str, cfg: dict) -> pystray.MenuItem:
        """Build submenu for a single device."""
        enabled = cfg.get("enabled", True)
        mode = cfg.get("mode", "palette")
        pattern = cfg.get("pattern", "solid")
        sync = cfg.get("brightness_sync", True)

        return pystray.MenuItem(
            f"{'✓' if enabled else '✗'} {name}",
            pystray.Menu(
                pystray.MenuItem(
                    "Enabled",
                    lambda n=name: self._toggle_device(n),
                    checked=lambda item: enabled
                ),
                pystray.MenuItem(
                    f"Mode: {mode}",
                    lambda n=name, m="full" if mode == "palette" else "palette":
                        self._set_device_mode(n, m)
                ),
                pystray.MenuItem(
                    f"Pattern: {pattern}",
                    lambda: self._open_device_dialog(name)
                ),
                pystray.MenuItem(
                    "Brightness Sync",
                    lambda n=name: self._toggle_brightness_sync(n),
                    checked=lambda item: sync
                ),
                pystray.MenuItem("Settings...", lambda n=name: self._open_device_dialog(n)),
            )
        )

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def _toggle_device(self, name: str):
        cfg = self._status.get("device_configs", {}).get(name, {})
        new_state = not cfg.get("enabled", True)
        self.client.set_device(name, new_state)

    def _set_device_mode(self, name: str, mode: str):
        self.client.set_mode(name, mode)

    def _toggle_brightness_sync(self, name: str):
        cfg = self._status.get("device_configs", {}).get(name, {})
        new_state = not cfg.get("brightness_sync", True)
        self.client.set_brightness_sync(name, new_state)

    def _open_device_dialog(self, name: str):
        cfg = self._status.get("device_configs", {}).get(name, {})
        if not cfg:
            return
        DeviceDialog(name, cfg, self.client, lambda: self.client.reload_config())

    def _open_colors_dialog(self, colors: list):
        devices = self._status.get("device_configs", {})
        selected = []
        for cfg in devices.values():
            selected.extend(cfg.get("selected_colors", [0]))
        selected = list(set(selected)) if selected else [0]
        ColorsDialog(colors, selected, self._on_colors_save)

    def _on_colors_save(self, indices: list):
        for name in self._status.get("device_configs", {}).keys():
            self.client.set_selected_colors(name, indices)
        self.client.reload_config()

    def _open_palette_dialog(self):
        PaletteDialog(self.palette, lambda: self.client.reload_config())

    def _open_settings_dialog(self):
        SettingsDialog(self.config.raw, self._on_settings_save)

    def _on_settings_save(self, new_config: dict):
        path = os.path.expanduser("~/.config/iridia/config.json")
        with open(path, "w") as f:
            json.dump(new_config, f, indent=2)
        self.client.reload_config()

    def _open_service_dialog(self):
        ServiceDialog()

    def _do_refresh(self):
        self.client.refresh()

    def _do_restart(self):
        self.client.restart()

    def _service_start(self):
        subprocess.run(["systemctl", "--user", "start", "iridia-daemon.service"], capture_output=True)

    def _service_stop(self):
        subprocess.run(["systemctl", "--user", "stop", "iridia-daemon.service"], capture_output=True)

    def _toggle_logging(self):
        enabled = self.config.get("logging.enabled", False)
        self.config.set("logging.enabled", not enabled)
        self.client.reload_config()

    def _open_config_folder(self):
        path = os.path.expanduser("~/.config/iridia")
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _open_log_folder(self):
        path = os.path.expanduser("~/.local/share/iridia")
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _quit(self):
        self._running = False
        if self.icon:
            self.icon.stop()
        if self._tk_root:
            self._tk_root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = TrayApp()
    app.run()


if __name__ == "__main__":
    main()
