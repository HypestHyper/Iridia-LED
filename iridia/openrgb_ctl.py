"""Resilient OpenRGB controller with lazy connection and device enumeration."""

import time
from typing import Dict, List, Optional


class OpenRGBController:
    """Manages OpenRGB connection, device enumeration, and color sending."""

    COMMON_PORTS = [6742, 6743, 6744]

    def __init__(self, host: str = "127.0.0.1", port: int = None):
        self.host = host
        self._configured_port = port
        self.port = port or 6743
        self.client = None
        self.devices: Dict[str, any] = {}
        self._last_enum = 0.0
        self._last_connect_attempt = 0.0
        self._auto_detected = False

    def _detect_port(self) -> int:
        """Try common OpenRGB ports and return the first that responds."""
        import socket
        for p in self.COMMON_PORTS:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect((self.host, p))
                s.close()
                return p
            except (socket.timeout, ConnectionRefusedError, OSError):
                continue
        return self._configured_port or 6743

    def _can_retry(self, interval: float) -> bool:
        now = time.time()
        if now - self._last_connect_attempt < interval:
            return False
        self._last_connect_attempt = now
        return True

    def ensure_connected(self, retry_interval: float = 5.0) -> bool:
        """Ensure OpenRGB client is connected. Returns True if ready."""
        if self.client is not None:
            try:
                _ = self.client.devices
                return True
            except Exception:
                self.client = None

        if not self._can_retry(retry_interval):
            return False

        # Auto-detect port on first connection attempt
        if not self._auto_detected and self._configured_port is None:
            detected = self._detect_port()
            if detected != self.port:
                print(f"[iridia] OpenRGB auto-detected on port {detected}")
                self.port = detected
            self._auto_detected = True

        try:
            from openrgb import OpenRGBClient
            self.client = OpenRGBClient(self.host, self.port, "iridia", 0)
            self._enumerate()
            return True
        except Exception:
            self.client = None
            return False

    def _enumerate(self):
        """Refresh device list."""
        if not self.client:
            return
        self.devices = {}
        try:
            for dev in self.client.devices:
                self.devices[dev.name] = dev
            self._last_enum = time.time()
        except Exception:
            self.devices = {}

    def maybe_enumerate(self, interval: float = 10.0):
        """Re-enumerate devices if enough time has passed."""
        if time.time() - self._last_enum >= interval:
            self._enumerate()

    def list_devices(self) -> List[Dict]:
        """Return list of device info dicts."""
        result = []
        for name, dev in self.devices.items():
            zones = []
            for z in dev.zones:
                zones.append({
                    "name": z.name,
                    "led_count": len(z.leds),
                })
            result.append({
                "name": name,
                "type": getattr(dev, "type", "unknown"),
                "zones": zones,
            })
        return result

    def send(self, device_name: str, colors: List[str], zones_config: Optional[Dict] = None) -> bool:
        """Send colors to a device. colors is a list of hex strings, one per LED."""
        if device_name not in self.devices:
            return False

        dev = self.devices[device_name]

        try:
            from openrgb.utils import RGBColor

            def to_rgb(hex_color: str) -> any:
                return RGBColor(
                    int(hex_color[0:2], 16),
                    int(hex_color[2:4], 16),
                    int(hex_color[4:6], 16),
                )

            if zones_config and dev.zones:
                # Per-zone control
                for zone in dev.zones:
                    zcfg = zones_config.get(zone.name, {})
                    if not zcfg.get("enabled", True):
                        continue

                    target_count = zcfg.get("led_count", len(zone.leds))
                    if target_count != len(zone.leds):
                        try:
                            zone.resize(target_count)
                        except Exception:
                            pass

                    # Slice or pad colors for this zone
                    zone_colors = colors[:target_count]
                    while len(zone_colors) < target_count:
                        zone_colors.append(zone_colors[-1] if zone_colors else "000000")

                    rgb_list = [to_rgb(c) for c in zone_colors]
                    zone.set_colors(rgb_list, fast=True)
            else:
                # Device-level control
                if len(colors) == 1:
                    dev.set_color(to_rgb(colors[0]), fast=True)
                else:
                    rgb_list = [to_rgb(c) for c in colors]
                    if hasattr(dev, "set_colors"):
                        dev.set_colors(rgb_list, fast=True)
                    else:
                        dev.set_color(to_rgb(colors[0]), fast=True)

            return True
        except Exception:
            return False
