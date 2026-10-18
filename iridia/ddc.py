"""Monitor brightness: DDC/CI through ddcutil, or a laptop's own backlight.

ddcutil 1.x (Ubuntu 22.04: 1.2, Ubuntu 24.04 and Debian 12: 1.4) and 2.x take different options:
--syslog only exists since 2.0, and 1.x refuses the whole command when it sees it. Without a
monitor that answers DDC/CI, a laptop's internal screen is followed through
/sys/class/backlight (readable by everyone, no ddcutil needed)."""
import glob, logging, os, re, subprocess, threading, time

logger = logging.getLogger("iridia")
_UNSET = object()


def parse_detect(out: str) -> list:
    """`ddcutil detect --terse` -> [{"bus", "name", "connector"}] for the displays it lists (not the
    "Invalid display" ones, which have no DDC/CI), in its order."""
    displays, cur = [], None
    for raw in (out or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if not raw[0].isspace():            # a block starts: "Display 1", "Invalid display", ...
            cur = {"bus": None, "name": "", "connector": ""} if line.startswith("Display") else None
            if cur is not None:
                displays.append(cur)
            continue
        if cur is None or ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        if key == "I2C bus":
            m = re.search(r"i2c-(\d+)", value)
            cur["bus"] = int(m.group(1)) if m else None
        elif key == "Monitor":              # MFG:Model:Serial
            parts = value.split(":")
            cur["name"] = (parts[1] if len(parts) > 1 and parts[1].strip() else parts[0]).strip()
        elif key == "DRM connector":
            cur["connector"] = re.sub(r"^card\d+-", "", value)
    return [d for d in displays if d["bus"] is not None]


class DDCController:
    def __init__(self, enabled=True, bus_number=None, poll_interval=5.0, fallback_brightness=100):
        self.enabled = enabled
        self.choice = bus_number            # the monitor picked in Settings (I2C bus), or None: automatic
        self.bus = bus_number               # the one followed
        self.displays = []                  # what ddcutil detect lists: [{"bus", "name", "connector", "ok"}]
        self.detections = 0                 # finished detections (tests wait on it)
        self.detecting = False
        self.problem = None                 # why nothing is followed: no_ddcutil, no_monitor, no_answer, chosen_silent
        self.poll_interval = poll_interval
        self.fallback_brightness = fallback_brightness
        self.last_brightness = fallback_brightness
        self._last_poll = 0.0
        self._available = False
        self._consecutive_failures = 0
        self.last_error = None
        self._busy = threading.Lock()
        self._quiet = []                    # ddcutil 2.x: keep its own syslog messages out of the journal
        self.source = None                  # "ddc", "backlight" or None
        self._backlight = None              # (brightness file, max)
        # ddcutil can take seconds (more on some GPU drivers), so it never runs on the
        # daemon's main loop: detection and every poll happen on a worker thread and
        # get_brightness() answers right away with the latest reading.
        threading.Thread(target=self._detect_bg, daemon=True, name="iridia-ddc").start()

    def _detect_bg(self):
        with self._busy:
            self.detecting = True
            try:
                self._detect()
            except Exception as e:          # noqa: BLE001
                logger.warning(f"DDC detection failed: {type(e).__name__}: {e}")
            self.detecting = False
            self.detections += 1

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
        self._available, self.source, self._backlight, self.displays = False, None, None, []
        self.last_error = self.problem = None
        if not self.enabled:
            logger.debug("DDC disabled in config, skipping detection")
            return
        version = self._run(["ddcutil", "--version"])
        if not version:
            logger.info("DDC: 'ddcutil' not available, install it for monitor-brightness-synced LED brightness (optional)")
            self.last_error, self.problem = "ddcutil isn't installed", "no_ddcutil"
            self._try_backlight()
            return
        m = re.search(r"ddcutil\s+(\d+)", version)
        self._quiet = ["--syslog", "NEVER"] if m and int(m.group(1)) >= 2 else []
        self.displays = parse_detect(self._run(["ddcutil", "detect", "--terse"]))
        for d in self.displays:
            d["ok"] = bool(self._getvcp(d["bus"]))
        if self.choice is not None:
            # The monitor you picked, and no other: following another screen instead is worse than
            # following none (the Manual brightness is used then).
            known = any(d["bus"] == self.choice for d in self.displays)
            if any(d["bus"] == self.choice and d["ok"] for d in self.displays) or \
                    (not known and self._getvcp(self.choice)):
                self._use(self.choice, "the chosen monitor")
                return
            self.last_error = f"the chosen monitor (I2C bus {self.choice}) doesn't answer"
            self.problem = "chosen_silent"
            logger.warning(f"DDC: the chosen monitor on I2C bus {self.choice} doesn't answer DDC/CI; is DDC/CI on "
                           "in its own menu? Using each zone's Manual brightness meanwhile.")
            return
        first = next((d for d in self.displays if d["ok"]), None)
        if first:
            self._use(first["bus"], "the first monitor that answers")
            return
        if self.displays:
            self.last_error, self.problem = "no monitor answers DDC/CI", "no_answer"
            logger.info(f"DDC: display(s) found (I2C bus {', '.join(str(d['bus']) for d in self.displays)}) but "
                        "none answered getvcp (feature 0x10, brightness). This is often a DDC/CI setting turned off "
                        "in the monitor's own menu.")
        else:
            self.last_error, self.problem = "ddcutil found no monitor", "no_monitor"
            logger.info("DDC: 'ddcutil detect' found no displays")
        self._try_backlight()

    def _getvcp(self, bus) -> str:
        return self._run(["ddcutil", "getvcp", "10", "--bus", str(bus), "--terse"] + self._quiet)

    def _use(self, bus, why):
        self.bus = bus
        self._available = True
        self.source = "ddc"
        self.last_error = self.problem = None
        name = next((d["name"] for d in self.displays if d["bus"] == bus and d["name"]), "")
        logger.info(f"DDC: following {why}" + (f", {name}" if name else "") + f" (I2C bus {bus})")

    def redetect(self, choice=_UNSET):
        """Look for monitors again (ddcutil installed since, a monitor plugged in), optionally with a
        new choice: an I2C bus number, or None for the first monitor that answers."""
        if choice is not _UNSET:
            self.choice = choice
        self._last_poll = 0.0
        threading.Thread(target=self._detect_bg, daemon=True, name="iridia-ddc").start()

    BACKLIGHT = "/sys/class/backlight"

    def _try_backlight(self):
        """A laptop's internal screen: follow its backlight instead (firmware/platform ones first)."""
        best = None
        for d in sorted(glob.glob(os.path.join(self.BACKLIGHT, "*"))):
            try:
                with open(os.path.join(d, "max_brightness")) as f:
                    mx = int(f.read().strip())
                with open(os.path.join(d, "type")) as f:
                    kind = f.read().strip()
            except (OSError, ValueError):
                continue
            if mx <= 0:
                continue
            rank = {"firmware": 0, "platform": 1, "raw": 2}.get(kind, 3)
            if best is None or rank < best[0]:
                best = (rank, os.path.join(d, "actual_brightness"), mx)
        if best is None:
            logger.info("DDC: no monitor answers and there's no backlight to follow: brightness sync off")
            return
        self._backlight = (best[1], best[2])
        self._available = True
        self.source = "backlight"
        self.last_error = self.problem = None
        logger.info(f"Brightness: following the screen's backlight ({os.path.dirname(best[1])})")

    def _read_backlight(self):
        path, mx = self._backlight
        try:
            with open(path) as f:
                return max(0, min(100, int(int(f.read().strip()) * 100 / mx)))
        except (OSError, ValueError):
            return None

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
        if self.source == "backlight":
            b = self._read_backlight()
            if b is not None:
                self.last_brightness = b
                self.last_error = None
            return self.last_brightness
        out = self._run(["ddcutil", "getvcp", "10", "--bus", str(self.bus), "--terse"] + self._quiet)
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
