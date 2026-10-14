"""DDC/CI brightness reading."""
import logging, re, subprocess, threading, time

logger = logging.getLogger("iridia")


class DDCController:
    def __init__(self, enabled=True, bus_number=None, poll_interval=5.0, fallback_brightness=100):
        self.enabled = enabled
        self.bus = bus_number
        self.poll_interval = poll_interval
        self.fallback_brightness = fallback_brightness
        self.last_brightness = fallback_brightness
        self._last_poll = 0.0
        self._available = False
        self._consecutive_failures = 0
        self.last_error = None
        self._busy = threading.Lock()
        # ddcutil can take seconds (more on some GPU drivers), so it never runs on the
        # daemon's main loop: detection and every poll happen on a worker thread and
        # get_brightness() answers right away with the latest reading.
        threading.Thread(target=self._detect_bg, daemon=True, name="iridia-ddc").start()

    def _detect_bg(self):
        with self._busy:
            try:
                self._detect()
            except Exception as e:          # noqa: BLE001
                logger.warning(f"DDC detection failed: {type(e).__name__}: {e}")

    def _run(self, cmd, timeout=5):
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                logger.debug(f"{' '.join(cmd)} -> exit {result.returncode}: {detail}")
            return result.stdout.strip()
        except FileNotFoundError:
            logger.debug("'ddcutil' not found on PATH")
            return ""
        except subprocess.TimeoutExpired:
            logger.debug(f"{' '.join(cmd)} timed out after {timeout}s")
            return ""
        except Exception as e:
            logger.debug(f"{' '.join(cmd)} failed: {type(e).__name__}: {e}")
            return ""

    def _detect(self):
        if not self.enabled:
            logger.debug("DDC disabled in config, skipping detection")
            return
        if not self._run(["ddcutil", "--version"]):
            logger.info("DDC: 'ddcutil' not available, install it for monitor-brightness-synced LED brightness (optional)")
            return
        if self.bus is not None:
            out = self._run(["ddcutil", "getvcp", "10", "--bus", str(self.bus), "--terse", "--syslog", "NEVER"])
            if out:
                self._available = True
                logger.info(f"DDC: using configured I2C bus {self.bus}")
                return
            logger.warning(f"DDC: configured bus {self.bus} didn't respond to getvcp, falling back to auto-detect")
        out = self._run(["ddcutil", "detect", "--terse"])
        if not out:
            logger.info("DDC: 'ddcutil detect' found no displays, brightness sync disabled")
            return
        lines = out.splitlines()
        candidates_tried = []
        for i, line in enumerate(lines):
            line = line.strip()
            if not line.startswith("Display"):
                continue
            for j in range(i + 1, min(i + 5, len(lines))):
                bus_line = lines[j].strip()
                m = re.search(r"i2c-(\d+)", bus_line)
                if m:
                    bus = int(m.group(1))
                    candidates_tried.append(bus)
                    test = self._run(["ddcutil", "getvcp", "10", "--bus", str(bus), "--terse", "--syslog", "NEVER"])
                    if test:
                        self.bus = bus
                        self._available = True
                        logger.info(f"DDC: display on I2C bus {bus}, brightness polling enabled")
                        return
                    break
        self._available = False
        logger.info(f"DDC: display(s) detected ({candidates_tried or 'none with an i2c bus'}) but none "
                    "responded to getvcp (feature 0x10, brightness), brightness sync disabled. "
                    "This is often a DDC/CI setting disabled in the monitor's own OSD menu.")

    def get_brightness(self):
        if not self.enabled or not self._available:
            return None
        now = time.time()
        try:
            interval = max(1.0, float(self.poll_interval))
        except (TypeError, ValueError):
            interval = 5.0
        if now - self._last_poll >= interval and self._busy.acquire(blocking=False):
            self._last_poll = now

            def poll():
                try:
                    self._poll()
                except Exception as e:      # noqa: BLE001
                    logger.debug(f"DDC poll failed: {type(e).__name__}: {e}")
                finally:
                    self._busy.release()
            threading.Thread(target=poll, daemon=True, name="iridia-ddc").start()
        return self.last_brightness

    def _poll(self):
        out = self._run(["ddcutil", "getvcp", "10", "--bus", str(self.bus), "--terse", "--syslog", "NEVER"])
        if not out:
            self._consecutive_failures += 1
            self.last_error = f"getvcp on bus {self.bus} returned nothing"
            # ddcutil's DDC/CI reads are documented as intermittently
            # flaky even on working setups (retries/null responses) —
            # only warn once it's a real pattern, not a one-off blip,
            # and only once per streak so this can't spam every poll.
            if self._consecutive_failures == 3:
                logger.warning(
                    f"DDC: bus {self.bus} has failed to respond {self._consecutive_failures} "
                    "polls in a row, using last known brightness meanwhile. If this "
                    "persists, the monitor's DDC/CI communication may be unreliable "
                    "(common with some Nvidia/monitor combinations)."
                )
            return self.last_brightness
        self._consecutive_failures = 0
        parts = out.split()
        if len(parts) >= 5:
            try:
                current = int(parts[3])
                max_val = int(parts[4])
                if max_val > 0:
                    brightness = int((current / max_val) * 100)
                    self.last_brightness = brightness
                    self.last_error = None
                    return brightness
            except (ValueError, IndexError) as e:
                logger.debug(f"DDC: couldn't parse getvcp output {out!r}: {e}")
        return self.last_brightness

    def is_available(self):
        return self._available
