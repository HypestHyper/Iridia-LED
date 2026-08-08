"""Main daemon — wallpaper watcher, color extraction, OpenRGB sync, IPC server."""

import copy
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from iridia.config import Config
from iridia.logutil import setup_logging
from iridia.wallpaper import WallpaperDetector
from iridia.colors import ColorExtractor
from iridia.palette import Palette
from iridia.patterns import PatternGenerator
from iridia.openrgb_ctl import OpenRGBController
from iridia.ddc import DDCController
from iridia.ipc import IPCServer


# ---------------------------------------------------------------------------
# File watchers
# ---------------------------------------------------------------------------

class _WallpaperHandler(FileSystemEventHandler):
    def __init__(self, daemon):
        self.daemon = daemon

    def on_modified(self, event):
        if not event.is_directory:
            self.daemon.on_wallpaper_file_changed(event.src_path)


class _ConfigHandler(FileSystemEventHandler):
    def __init__(self, daemon):
        self.daemon = daemon

    def on_modified(self, event):
        if event.src_path == self.daemon.config.path:
            self.daemon.on_config_changed()
        elif event.src_path == self.daemon.palette.path:
            self.daemon.on_palette_changed()


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------

class Daemon:
    def __init__(self):
        self.running = False
        self.config = Config()
        self.logger = setup_logging(self.config)

        # Paths
        self._socket_path = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
            f"iridia-{os.getuid()}.sock"
        )
        self._config_dir = os.path.expanduser("~/.config/iridia")

        # Components
        self.detector = WallpaperDetector(
            manual_path=self.config.get("wallpaper.manual_path"),
            watch_folder=self.config.get("wallpaper.watch_folder"),
        )
        self.extractor = ColorExtractor(backend=self.config.get("color.backend"))
        self.palette = Palette()
        self.patterns = PatternGenerator()
        port = self.config.get("openrgb.port")
        self.openrgb = OpenRGBController(
            host=self.config.get("openrgb.host"),
            port=port if port is not None else None,
        )
        self.ddc = DDCController(
            enabled=self.config.get("ddc.enabled"),
            bus_number=self.config.get("ddc.bus_number"),
            poll_interval=self.config.get("timing.ddc_poll_interval_sec"),
            fallback_brightness=self.config.get("ddc.fallback_brightness"),
        )
        if self.ddc.is_available():
            self.logger.info(f"DDC: display on I2C bus {self.ddc.bus}, brightness polling enabled")
        else:
            self.logger.info("DDC: no displays found or ddcutil not available, brightness sync disabled")
        self.ipc = IPCServer(self._socket_path, self)

        # State
        self._current_wallpaper: Optional[str] = None
        self._extracted_colors: List[str] = ["642107"]
        self._current_brightness: int = 100
        self._last_brightness_poll = 0.0
        self._last_health_check = 0.0
        self._needs_update = True
        self._force_refresh = False
        self._last_sent: Dict[str, str] = {}  # device_name -> hash of last colors

        # Watchers
        self._observer: Optional[Observer] = None
        self._last_wallpaper_event = 0.0

        # Signals
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    def _on_signal(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def run(self):
        self.running = True
        self.logger.info("Iridia daemon starting")
        self.logger.info(f"Socket: {self._socket_path}")
        self.logger.info(f"Log file: {self.config.get('logging.file_path')} (enabled={self.config.get('logging.enabled')})")

        self.ipc.start()
        self._setup_watchers()

        # Initial wallpaper read
        self._detect_wallpaper()

        while self.running:
            try:
                self._tick()
            except Exception:
                self.logger.exception("Tick error")

            time.sleep(0.5)

        self._shutdown()

    def _shutdown(self):
        self.logger.info("Shutting down")
        self.ipc.stop()
        if self._observer:
            self._observer.stop()
            self._observer.join()

    def _setup_watchers(self):
        self._observer = Observer()

        # Watch config directory
        if os.path.isdir(self._config_dir):
            self._observer.schedule(
                _ConfigHandler(self), self._config_dir, recursive=False
            )

        # Watch wallpaper file if known
        if self._current_wallpaper and os.path.exists(self._current_wallpaper):
            watch_dir = os.path.dirname(self._current_wallpaper)
            if os.path.isdir(watch_dir):
                self._observer.schedule(
                    _WallpaperHandler(self), watch_dir, recursive=False
                )

        # Watch Caelestia wallpaper path file
        caelestia_path = os.path.expanduser("~/.local/state/caelestia/wallpaper/path.txt")
        caelestia_dir = os.path.dirname(caelestia_path)
        if os.path.isdir(caelestia_dir):
            self._observer.schedule(
                _WallpaperHandler(self), caelestia_dir, recursive=False
            )

        self._observer.start()

    # -----------------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------------

    def on_wallpaper_file_changed(self, path: str):
        now = time.time()
        debounce = self.config.get("timing.wallpaper_debounce_ms", 300) / 1000.0
        if now - self._last_wallpaper_event < debounce:
            return
        self._last_wallpaper_event = now
        self.logger.debug(f"Wallpaper file changed: {path}")
        self._needs_update = True

    def on_config_changed(self):
        self.logger.info("Config changed on disk, reloading")
        if self.config.reload():
            # Re-init components that depend on config
            self.detector = WallpaperDetector(
                manual_path=self.config.get("wallpaper.manual_path"),
                watch_folder=self.config.get("wallpaper.watch_folder"),
            )
            self.ddc.poll_interval = self.config.get("timing.ddc_poll_interval_sec")
        self._needs_update = True

    def on_palette_changed(self):
        self.logger.info("Palette changed on disk, reloading")
        self.palette._load()
        self._needs_update = True

    # -----------------------------------------------------------------------
    # Main loop tick
    # -----------------------------------------------------------------------

    def _tick(self):
        # 1. Health check
        self._health_check()

        # 2. Ensure OpenRGB is connected
        retry = self.config.get("timing.openrgb_retry_interval_sec", 5.0)
        if not self.openrgb.ensure_connected(retry_interval=retry):
            return

        # 3. Re-enumerate devices periodically
        enum_interval = self.config.get("timing.device_enumeration_interval_sec", 10.0)
        self.openrgb.maybe_enumerate(interval=enum_interval)

        # 4. Detect wallpaper changes
        self._detect_wallpaper()

        # 5. Read brightness
        self._read_brightness()

        # 6. Update devices if needed
        if self._needs_update or self._force_refresh:
            self._update_all_devices()

    def _health_check(self):
        now = time.time()
        interval = self.config.get("timing.health_check_interval_sec", 30.0)
        if now - self._last_health_check < interval:
            return
        self._last_health_check = now

        # Check IPC thread
        if not self.ipc.is_alive():
            self.logger.warning("IPC thread died, restarting...")
            self.ipc = IPCServer(self._socket_path, self)
            self.ipc.start()

    def _detect_wallpaper(self):
        path = self.detector.detect()
        if path and path != self._current_wallpaper:
            self.logger.info(f"Wallpaper changed: {path}")
            self._current_wallpaper = path
            self._extract_colors(path)
            self._needs_update = True
            # Clear send cache so new colors always get pushed
            self._last_sent = {}
            # Re-setup watcher for new wallpaper directory
            self._setup_watchers()

    def _extract_colors(self, path: str):
        try:
            colors = self.extractor.extract(path)
            self._extracted_colors = colors
            self.logger.info(f"Extracted {len(colors)} colors: {colors[:4]}")
        except Exception:
            self.logger.exception("Color extraction failed")
            self._extracted_colors = ["642107"]

    def _read_brightness(self):
        brightness = self.ddc.get_brightness()
        if brightness is not None and brightness != self._current_brightness:
            self.logger.debug(f"Brightness changed: {self._current_brightness}% -> {brightness}%")
            self._current_brightness = brightness
            self._needs_update = True

    # -----------------------------------------------------------------------
    # Device update
    # -----------------------------------------------------------------------

    def _update_all_devices(self):
        devices_cfg = self.config.devices
        if not devices_cfg:
            self.logger.debug("No devices configured")
            self._needs_update = False
            return

        for name, dev_cfg in devices_cfg.items():
            if not dev_cfg.get("enabled", True):
                continue
            self._update_device(name, dev_cfg)

        self._needs_update = False
        self._force_refresh = False

    def _update_device(self, name: str, dev_cfg: Dict[str, Any]):
        # Get selected colors
        selected = dev_cfg.get("selected_colors", [0])
        colors = [
            self._extracted_colors[i]
            for i in selected
            if i < len(self._extracted_colors)
        ]
        if not colors:
            colors = [self._extracted_colors[0]] if self._extracted_colors else ["642107"]

        # Apply palette mode FIRST (lock hue before dimming)
        mode = dev_cfg.get("mode", self.config.color_mode)
        palette_mode = dev_cfg.get("palette_mode", self.config.palette_mode)
        if mode == "palette":
            if palette_mode == "interpolated":
                colors = [self.palette.nearest_interpolated(c) for c in colors]
            else:
                colors = [self.palette.nearest(c) for c in colors]

        # Apply gamma correction
        if dev_cfg.get("gamma_correction", False):
            gamma = dev_cfg.get("gamma_value", 2.2)
            colors = [self._gamma_correct(c, gamma) for c in colors]

        # Apply brightness LAST (so dimming actually works)
        brightness = self._get_device_brightness(dev_cfg)
        colors = [self._scale_brightness(c, brightness) for c in colors]

        # Generate pattern
        pattern = dev_cfg.get("pattern", "solid")
        led_count = self._get_led_count(name, dev_cfg)
        final_colors = self.patterns.generate(pattern, colors, led_count)

        if not final_colors:
            return

        # Hash to avoid redundant OpenRGB calls
        color_hash = "".join(final_colors)
        if self._last_sent.get(name) == color_hash:
            return

        zones = dev_cfg.get("zones", {})
        if self.openrgb.send(name, final_colors, zones):
            self._last_sent[name] = color_hash
            self.logger.info(
                f"Sent to '{name}' | pattern={pattern} | brightness={brightness}% | "
                f"colors={len(final_colors)} LEDs | mode={mode}"
            )
        else:
            self.logger.warning(f"Failed to send to '{name}'")

    def _get_device_brightness(self, dev_cfg: Dict[str, Any]) -> int:
        if not dev_cfg.get("brightness_sync", True):
            return dev_cfg.get("manual_brightness", 100)

        brightness = self._current_brightness
        range_min, range_max = dev_cfg.get("brightness_range", [0, 100])
        invert = dev_cfg.get("invert_brightness", False)

        if invert:
            brightness = 100 - brightness

        # Map 0-100 to range_min-range_max
        scaled = int(brightness * (range_max - range_min) / 100 + range_min)
        return max(range_min, min(range_max, scaled))

    @staticmethod
    def _scale_brightness(hex_color: str, pct: int) -> str:
        r = int(int(hex_color[0:2], 16) * pct / 100)
        g = int(int(hex_color[2:4], 16) * pct / 100)
        b = int(int(hex_color[4:6], 16) * pct / 100)
        return f"{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _gamma_correct(hex_color: str, gamma: float = 2.2) -> str:
        """Apply gamma correction to compensate for non-linear LED response."""
        r = int(pow(int(hex_color[0:2], 16) / 255.0, 1.0 / gamma) * 255)
        g = int(pow(int(hex_color[2:4], 16) / 255.0, 1.0 / gamma) * 255)
        b = int(pow(int(hex_color[4:6], 16) / 255.0, 1.0 / gamma) * 255)
        return f"{r:02x}{g:02x}{b:02x}"

    def _get_led_count(self, device_name: str, dev_cfg: Dict[str, Any]) -> int:
        zones = dev_cfg.get("zones", {})
        if zones:
            total = 0
            for zname, zcfg in zones.items():
                if zcfg.get("enabled", True):
                    total += zcfg.get("led_count", 1)
            return max(total, 1)
        # Fallback: try to get from OpenRGB device
        if device_name in self.openrgb.devices:
            dev = self.openrgb.devices[device_name]
            return sum(len(z.leds) for z in dev.zones) if dev.zones else 1
        return 48  # sensible default

    # -----------------------------------------------------------------------
    # IPC command handler
    # -----------------------------------------------------------------------

    def handle_command(self, req: Dict[str, Any]) -> Dict[str, Any]:
        cmd = req.get("cmd", "")

        if cmd == "ping":
            return {"ok": True, "version": "1.0.0"}

        if cmd == "status":
            return self._cmd_status()

        if cmd == "set_device":
            return self._cmd_set_device(req)

        if cmd == "set_pattern":
            return self._cmd_set_pattern(req)

        if cmd == "set_mode":
            return self._cmd_set_mode(req)

        if cmd == "set_led_count":
            return self._cmd_set_led_count(req)

        if cmd == "set_brightness_sync":
            return self._cmd_set_brightness_sync(req)

        if cmd == "set_manual_brightness":
            return self._cmd_set_manual_brightness(req)

        if cmd == "set_brightness_range":
            return self._cmd_set_brightness_range(req)

        if cmd == "set_invert":
            return self._cmd_set_invert(req)

        if cmd == "set_gamma":
            return self._cmd_set_gamma(req)

        if cmd == "set_selected_colors":
            return self._cmd_set_selected_colors(req)

        if cmd == "refresh_wallpaper":
            self._force_refresh = True
            self._needs_update = True
            return {"ok": True, "colors": self._extracted_colors}

        if cmd == "reload_config":
            self.on_config_changed()
            return {"ok": True}

        if cmd == "restart":
            self.logger.info("Soft restart requested via IPC")
            self._soft_restart()
            return {"ok": True}

        if cmd == "quit":
            self.running = False
            return {"ok": True}

        return {"ok": False, "error": f"unknown command: {cmd}"}

    def _cmd_status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "wallpaper": self._current_wallpaper,
            "extracted_colors": self._extracted_colors,
            "brightness": self._current_brightness,
            "ddc_available": self.ddc.is_available(),
            "openrgb_connected": self.openrgb.client is not None,
            "devices": self.openrgb.list_devices(),
            "device_configs": self.config.devices,
            "mode": self.config.color_mode,
            "palette_mode": self.config.palette_mode,
        }

    def _cmd_set_device(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        enabled = req.get("enabled")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        if enabled is not None:
            self.config.set(f"devices.{name}.enabled", enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_pattern(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        pattern = req.get("pattern")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(f"devices.{name}.pattern", pattern)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_mode(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        mode = req.get("mode")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(f"devices.{name}.mode", mode)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_led_count(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        zone = req.get("zone")
        count = req.get("count")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        if zone:
            self.config.set(f"devices.{name}.zones.{zone}.led_count", count)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_brightness_sync(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        enabled = req.get("enabled")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(f"devices.{name}.brightness_sync", enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_manual_brightness(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        value = req.get("value")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(f"devices.{name}.manual_brightness", value)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_brightness_range(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        range_min = req.get("min")
        range_max = req.get("max")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(f"devices.{name}.brightness_range", [range_min, range_max])
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_invert(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        enabled = req.get("enabled")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(f"devices.{name}.invert_brightness", enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_gamma(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        enabled = req.get("enabled")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(f"devices.{name}.gamma_correction", enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_selected_colors(self, req: dict) -> dict:
        name = req.get("device")
        indices = req.get("indices", [0])
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(f"devices.{name}.selected_colors", indices)
        self._needs_update = True
        return {"ok": True}

    def _soft_restart(self):
        """Reinitialize everything without dropping the socket."""
        self.logger.info("Performing soft restart")
        self.openrgb.client = None
        self.openrgb.devices = {}
        self._last_sent = {}
        self._detect_wallpaper()
        self._needs_update = True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    daemon = Daemon()
    daemon.run()


if __name__ == "__main__":
    main()
