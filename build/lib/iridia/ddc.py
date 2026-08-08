"""DDC/CI brightness reading with --bus targeting and error suppression."""

import re
import subprocess
import time


class DDCController:
    """Read monitor brightness via ddcutil with minimal error spam."""

    def __init__(self, enabled: bool = True, bus_number: int = None,
                 poll_interval: float = 5.0, fallback_brightness: int = 100):
        self.enabled = enabled
        self.bus = bus_number
        self.poll_interval = poll_interval
        self.fallback_brightness = fallback_brightness
        self.last_brightness = fallback_brightness
        self._last_poll = 0.0
        self._available = False
        self._warned = False
        self._detect()

    def _run(self, cmd: list, timeout: int = 5) -> str:
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return ""

    def _detect(self):
        if not self.enabled:
            return

        # Check if ddcutil is installed
        if not self._run(["ddcutil", "--version"]):
            return

        # If bus is already configured, verify it works
        if self.bus is not None:
            out = self._run([
                "ddcutil", "getvcp", "10", "--bus", str(self.bus),
                "--terse", "--syslog", "NEVER",
            ])
            if out:
                self._available = True
                return

        # Auto-detect: parse multi-line output from ddcutil detect
        out = self._run(["ddcutil", "detect", "--terse"])
        if not out:
            return

        lines = out.splitlines()
        for i, line in enumerate(lines):
            line = line.strip()
            if not line.startswith("Display"):
                continue
            # I2C bus is on the next line(s): "   I2C bus:  /dev/i2c-8"
            for j in range(i + 1, min(i + 5, len(lines))):
                bus_line = lines[j].strip()
                m = re.search(r"i2c-(\d+)", bus_line)
                if m:
                    bus = int(m.group(1))
                    test = self._run([
                        "ddcutil", "getvcp", "10", "--bus", str(bus),
                        "--terse", "--syslog", "NEVER",
                    ])
                    if test:
                        self.bus = bus
                        self._available = True
                        return
                    break  # Found bus for this display but VCP 10 failed

        # No working display found
        self._available = False

    def get_brightness(self) -> int:
        """Return current monitor brightness 0-100, or None if unavailable."""
        if not self.enabled or not self._available:
            return None

        now = time.time()
        if now - self._last_poll < self.poll_interval:
            return self.last_brightness

        self._last_poll = now

        out = self._run([
            "ddcutil", "getvcp", "10", "--bus", str(self.bus),
            "--terse", "--syslog", "NEVER",
        ])

        if not out:
            return self.last_brightness

        # Parse: "VCP 10 C 75 100" -> current=75, max=100
        parts = out.split()
        if len(parts) >= 5:
            try:
                current = int(parts[3])
                max_val = int(parts[4])
                if max_val > 0:
                    brightness = int((current / max_val) * 100)
                    self.last_brightness = brightness
                    return brightness
            except (ValueError, IndexError):
                pass

        return self.last_brightness

    def is_available(self) -> bool:
        return self._available
