"""Main daemon — wallpaper watcher, color extraction, OpenRGB sync, IPC server."""

import copy
import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from iridia.config import Config
from iridia.logutil import setup_logging, MEMORY as LOG_MEMORY
from iridia.wallpaper import WallpaperDetector
from iridia.colors import ColorExtractor, resolve_colors, normalize_hex
from iridia.customcolors import CustomColors
from iridia.wallcache import WallpaperColorCache
from iridia.calibration import Profiles, valid_name
from iridia.palette import Palette
from iridia.patterns import PatternGenerator
from iridia import animations
from iridia import sections as zone_sections
from iridia import notifyflash
from iridia.animator import Animator, Job
from iridia.openrgb_ctl import OpenRGBController, zones_of
from iridia import openrgb_server
from iridia.ddc import DDCController
from iridia.ipc import IPCServer


def _num(v, default, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if v != v:                          # NaN
        return default
    return max(lo, min(hi, v))


class ZoneNotFound(ValueError):
    """A command named a zone the device doesn't have; answered as a normal error reply."""


STRIP_TYPES = ("addressable", "addressable12", "single", "rgbw")
COLOR_ORDERS = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")


def clean_zone_cfg(z: dict) -> dict:
    """A zone (or flat device) config with every field the renderer reads in a usable
    type and range, whatever a hand edit or an old version left in config.json."""
    out = dict(z)
    out["led_count"] = int(_num(z.get("led_count", 20), 20, 0, 4096))
    pc = z.get("pattern_colors", [0])
    pc = [e if isinstance(e, int) else normalize_hex(e) for e in (pc if isinstance(pc, list) else [])
          if not isinstance(e, bool) and ((isinstance(e, int) and 0 <= e < 64) or normalize_hex(e))]
    out["pattern_colors"] = pc[:16] or [0]
    pp = z.get("pattern_params")
    out["pattern_params"] = pp if isinstance(pp, dict) else {}
    if not isinstance(z.get("pattern", "solid"), str):
        out["pattern"] = "solid"
    if z.get("mode") is not None and z.get("mode") not in ("full", "palette", "calibrated"):
        out.pop("mode", None)
    out["manual_brightness"] = _num(z.get("manual_brightness", 100), 100, 0, 100)
    br = z.get("brightness_range", [0, 100])
    if not isinstance(br, (list, tuple)) or len(br) != 2:
        br = [0, 100]
    lo, hi = _num(br[0], 0, 0, 100), _num(br[1], 100, 0, 100)
    out["brightness_range"] = [min(lo, hi), max(lo, hi)]
    out["gamma_value"] = _num(z.get("gamma_value", 2.2), 2.2, 0.1, 10.0)
    if not isinstance(z.get("display_name", ""), str):
        out.pop("display_name", None)
    if z.get("calibration_profile") is not None and not isinstance(z.get("calibration_profile"), str):
        out.pop("calibration_profile", None)
    # what kind of strip this is (None: guess from what OpenRGB reports)
    if z.get("strip_type") not in STRIP_TYPES:
        out.pop("strip_type", None)
    co = str(z.get("color_order", "RGB")).upper()
    out["color_order"] = co if co in COLOR_ORDERS else "RGB"
    out["leds_per_pixel"] = int(_num(z.get("leds_per_pixel", 1), 1, 1, 20))
    out["power_limit"] = _num(z.get("power_limit", 0), 0, 0, 100)          # amps, 0 = no limit
    out["ma_per_led"] = _num(z.get("ma_per_led", 60), 60, 1, 500)          # mA at full white
    out["animation"] = animations.clean(z.get("animation"))               # None: a static pattern
    out["sections"] = zone_sections.clean(z.get("sections"), out["led_count"])
    out["led_overrides"] = zone_sections.clean_overrides(z.get("led_overrides"), out["led_count"])
    return out


def pack_rgbw(colors: List[str]) -> List[str]:
    """RGBW strips (SK6812 RGBW, 4 bytes per LED) on a header that sends 3 bytes per LED.

    Take the white out of every colour, lay the bytes out as the strip reads them (G R B W),
    and cut that stream into 3-byte "LEDs" for the header. The header sends each of those in
    G R B order, so a byte triple (a, b, c) goes out as the colour (r=b, g=a, b=c)."""
    stream = []
    for c in colors:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        w = min(r, g, b)
        stream += [g - w, r - w, b - w, w]
    while len(stream) % 3:
        stream.append(0)
    return ["%02x%02x%02x" % (stream[i + 1], stream[i], stream[i + 2]) for i in range(0, len(stream), 3)]


def reorder(hex_color: str, order: str) -> str:
    """Send the channels in another order, for strips wired as GRB, BRG, ..."""
    if order == "RGB":
        return hex_color
    ch = {"R": hex_color[0:2], "G": hex_color[2:4], "B": hex_color[4:6]}
    return ch[order[0]] + ch[order[1]] + ch[order[2]]


class _WallpaperHandler(FileSystemEventHandler):
    def __init__(self, daemon):
        self.daemon = daemon

    def on_modified(self, event):
        if not event.is_directory:
            self.daemon.on_wallpaper_file_changed(event.src_path)

    on_created = on_modified  # atomic-rename writers (write tmp, rename over) show up as create/move
    def on_moved(self, event):
        if not event.is_directory:
            self.daemon.on_wallpaper_file_changed(event.dest_path)


class _SettingsFileHandler(FileSystemEventHandler):
    """A desktop's own settings file (dconf, Plasma's appletsrc, ...) changed: ask the wallpaper
    backend again now. Other files in the same folder are ignored."""

    def __init__(self, daemon, files):
        self.daemon = daemon
        self.files = set(files)

    def on_any_event(self, event):
        for p in (getattr(event, "src_path", ""), getattr(event, "dest_path", "")):
            if p in self.files:
                self.daemon.detector.invalidate()
                self.daemon._wake.set()
                return


class _ConfigHandler(FileSystemEventHandler):
    def __init__(self, daemon):
        self.daemon = daemon

    def on_modified(self, event):
        self._check(event.src_path)

    def on_created(self, event):
        self._check(event.src_path)

    def on_moved(self, event):
        # Editors (and our own atomic saves) write a temp file and rename it over the real one.
        self._check(getattr(event, "dest_path", "") or "")

    def _check(self, path):
        try:
            if path == self.daemon.config.path:
                self.daemon.on_config_changed()
            elif path == self.daemon.palette.path:
                self.daemon.on_palette_changed()
        except Exception:                   # noqa: BLE001 - never kill the watcher thread
            logging.getLogger("iridia").exception("Reloading a changed file failed")


class Daemon:
    def __init__(self):
        self.running = False
        self.config = Config()
        self.started_by = openrgb_server.started_by()
        if not openrgb_server.run_by_systemd() and not self.config.is_set("logging.enabled"):
            # Started outside systemd (a compositor line, XDG autostart...): there is no
            # journal, so keep a log file unless you've turned it off yourself.
            self.config.set("logging.enabled", True)
        self.logger = setup_logging(self.config)

        self._socket_path = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
            f"iridia-{os.getuid()}.sock"
        )
        self._config_dir = os.path.expanduser("~/.config/iridia")

        self.detector = WallpaperDetector(
            manual_path=self.config.get("wallpaper.manual_path"),
            watch_folder=self.config.get("wallpaper.watch_folder"),
            cache_path="~/.config/iridia/detection_cache.json",
        )
        self.extractor = ColorExtractor(backend=self.config.get("color.backend", "auto"))
        self._reextract = False
        self.palette = Palette()
        self._snap_cache = {}
        self._preview_hex = None          # live colour-picker preview (never saved)
        self._preview_raw = False         # True: send exactly this hex (calibration tuning)
        self._preview_exact = False       # True: no correction, but brightness still applies
        self._preview_until = 0.0
        self._identify = None             # (device, zone, until): that zone white, the rest dark
        self._probe = None                # (device, zone, led index, until): one LED lit, for counting
        self._lights_off = False          # all LEDs dark (`iridia lights off`)
        # Keybind changes ("iridia zone NAME off"): temporary, never saved, cleared by running
        # the same command again or "normal". zone key -> {"power": "on"|"off", "hex": .., "bright": N}
        # (any combination: "on" + a color + a brightness in one keybind)
        self._overlays: Dict[str, dict] = {}
        self._rgbtest = None              # (device, zone, until): red / green / blue test for color order
        self._strip_info: Dict[str, dict] = {}   # zone key -> strip type, power estimate, size needs
        self._asleep = False              # PC is suspending: LEDs dark
        self._sleep_sent = threading.Event()
        self._wake = threading.Event()    # wakes the main loop early
        self._night_active = False
        self.sleepwatch = None
        self.sessionwatch = None
        self.notifywatch = None
        self._notify_events: List[tuple] = []     # (app, urgent) from the watcher thread, not handled yet
        self._notify_lock = threading.Lock()
        self._flash: Optional[notifyflash.Flash] = None   # a notification flash running now
        self._flash_sizes: Dict[str, int] = {}   # zone key -> its LED count, for the last flash's targets
        self._flash_keys: set = set()       # zones showing it through a flash job (static or paused)
        self._static_pre: Dict[str, list] = {}    # key -> the static colours before _finish, for flashes
        self._stopping = threading.Event()  # set when the daemon shuts down
        self._sessions_dir = "/run/systemd/sessions"
        self._sensor_zones = set()          # zones to redraw for a new sensor reading
        from iridia.sensors import SensorHub
        self.sensors = SensorHub()          # read only while a strip shows a sensor
        self._hooks = {"lock": False, "idle": False}     # iridia lock|idle on (hypridle, swayidle, ...)
        self._sess_test_until = 0.0                     # Settings, Try it: act as if locked until then
        self._sess_ramp = (1.0, 1.0, 0.0, 0.0)          # brightness factor (from, to, start, seconds)
        self._sess_settled = True                       # the end of the last fade has been sent
        self._sess_state = "active"
        self._frozen = bool(self.config.get("color.frozen", False))
        self.calibration = Profiles()
        self.calibration.ensure_default()
        from iridia import get_version
        from iridia.setups import Setups
        self.setups = Setups(version=get_version())
        self.wallcache = WallpaperColorCache()
        self.custom_colors = CustomColors()
        legacy = self.config.get("custom_colors", [])
        if legacy and self.custom_colors.migrate_from(legacy):
            self.config.set("custom_colors", [])
            self.logger.info(f"Moved {len(legacy)} custom colour(s) from config.json to {self.custom_colors.path}")
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
        # DDCController.__init__ already logs its own detection outcome
        # (with more accurate detail — ddcutil missing vs. present but
        # no display found vs. display found but not DDC/CI-capable —
        # than a simple is_available() check could tell apart here).
        self.ipc = IPCServer(self._socket_path, self)

        self._current_wallpaper: Optional[str] = None
        self._extracted_colors: List[str] = ["642107"]
        self._current_brightness: int = 100
        self._last_brightness_poll = 0.0
        self._last_health_check = 0.0
        self._needs_update = True
        self._force_refresh = False
        self._last_sent: Dict[str, str] = {}
        self._openrgb_epoch = 0
        self._settle_resend_at: Optional[float] = None
        self._start_time = time.time()
        self._orgb = openrgb_server.Supervisor()
        self._orgb_busy = False
        self._orgb_restarting = False
        self._nodev_restarts = 0          # restarts because OpenRGB saw no devices (max NODEV_MAX per run)
        self._nodev_last = 0.0
        self._said: Dict[str, str] = {}   # topic -> last message, for warnings logged once
        self._last_logged_connected = None
        self._device_missing_since: Dict[str, float] = {}
        self._zone_errors: Dict[tuple, str] = {}
        self._last_auto_restart = 0.0
        self._restart_attempts: Dict[str, int] = {}   # device -> automatic OpenRGB restarts tried for it

        self._observer: Optional[Observer] = None
        self._last_wallpaper_event = 0.0

        # animations (see animations.py and animator.py)
        self._animator = Animator(self.openrgb.send_frames)
        self._anim_keys: set = set()      # zones the animator sends (unless paused for a moment)
        self._anim_jobs: Dict[str, tuple] = {}    # key -> (signature, Job)
        self._static_rgb: Dict[str, list] = {}    # key -> what the static path shows on that zone
        self._anim_hold = False           # `iridia animations pause`: until resumed (not saved)
        self._run_seed = int.from_bytes(os.urandom(2), "little")
        self._glide: Dict[str, tuple] = {}        # key -> (from %, to %, start) for brightness glides
        self._glide_active = False
        self._layout = None
        self._layout_mtime = None
        self._anim_cfg = self._anim_settings()        # read once per tick, not once per frame
        self._night_cap = self._night_settings()["cap"]
        self._power_shown: Dict[str, float] = {}

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    def _on_signal(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def run(self):
        self.running = True
        from iridia import code_fingerprint, get_version
        self._code = code_fingerprint()
        self.logger.info(f"Iridia daemon starting (version {get_version()}, code {self._code})")
        self.logger.info(f"Socket: {self._socket_path}")
        self.logger.info(f"Log file: {self.config.get('logging.file_path')} (enabled={self.config.get('logging.enabled')})")

        self._migrate_patterns()
        self.logger.info(f"Started by: {self.started_by}")
        threading.Thread(target=self._migrate_openrgb_unit, daemon=True, name="openrgb-migrate").start()
        self.ipc.start()
        self._setup_watchers()
        self._detect_wallpaper()
        self._start_sleepwatch()
        self._start_sessionwatch()
        from iridia.notifywatch import NotifyWatcher
        self.notifywatch = NotifyWatcher(self._on_notification)
        threading.Thread(target=self._update_check, daemon=True, name="update-check").start()

        while self.running:
            try:
                self._tick()
            except Exception:
                self.logger.exception("Tick error")
            # Nothing animates any more, so there is never a reason to tick
            # faster than this; colours are sent only when they change.
            # brightness glides re-send static zones for a moment; otherwise nothing animates here
            self._wake.wait(0.05 if self._glide_active or self._sess_fading() else 0.5 if self._busy() else 1.0)
            self._wake.clear()

        self._shutdown()

    def _start_sleepwatch(self):
        if not self.config.get("sleep.lights_off", True):
            return
        from iridia.sleepwatch import SleepWatcher
        self.sleepwatch = SleepWatcher(self._on_sleep, self._on_wake)
        self.sleepwatch.start()

    def _busy(self) -> bool:
        """Something that needs a tick twice a second (sensor readings and blinks, identify, LED
        counting, test colors, a color preview). Otherwise once a second is plenty: commands,
        lock changes and fades wake the loop themselves."""
        return bool(self.sensors.values() or self._identify or self._probe or self._rgbtest or self._preview_hex or self._flash)

    # ------------------------------------------------------------- updates
    UPDATE_DELAY_SEC = 60           # after the daemon starts: the login has other things to do first
    UPDATE_MIN_GAP_SEC = 6 * 3600   # a daemon restarted often doesn't ask GitHub every time

    def _update_settings(self) -> dict:
        u = self.config.get("updates", {})
        u = u if isinstance(u, dict) else {}
        return {"check": u.get("check", True) is not False, "notify": u.get("notify", True) is not False,
                "prerelease": u.get("prerelease") is True, "skip": str(u.get("skip") or "")}

    def _update_check(self):
        """Once per start: look for a new version and, if there is one you haven't been told about,
        show a desktop notification. Network trouble: try again a little later, three times at most."""
        from iridia import get_version, updater
        if self._stopping.wait(self.UPDATE_DELAY_SEC):
            return
        for attempt in range(3):
            s = self._update_settings()
            if not s["check"]:
                return
            last = (updater.load_state().get("last") or {})
            if time.time() - float(last.get("checked") or 0) < self.UPDATE_MIN_GAP_SEC and not last.get("error"):
                res = last
            else:
                res = updater.check(get_version(), s["prerelease"])
            if res.get("error"):
                self.logger.info(f"Update check: {res['error']}")
                if self._stopping.wait(600 * (attempt + 1)):
                    return
                continue
            info = res.get("latest") or {}
            v = info.get("version")
            if res.get("available") and v:
                self.logger.info(f"Iridia {v} is available (this is {get_version()}); see the window's Updates tab")
                state = updater.load_state()
                if s["notify"] and v != s["skip"] and state.get("notified") != v:
                    if updater.notify(f"Iridia {v} is available",
                                      "Open Iridia, Updates, to see what's new and install it."):
                        updater.save_state(notified=v)
            return

    def _cmd_updates(self, req: dict) -> dict:
        """Update settings (check, notify, prerelease, skip) and what the last check found."""
        from iridia import get_version, updater
        new = {k: req[k] for k in ("check", "notify", "prerelease") if isinstance(req.get(k), bool)}
        if "skip" in req:
            new["skip"] = str(req["skip"] or "")
        if new:
            cur = self.config.get("updates", {})
            self.config.set("updates", dict(cur if isinstance(cur, dict) else {}, **new))
        return {"ok": True, "settings": self._update_settings(), "version": get_version(),
                "last": updater.load_state().get("last"), "previous": updater.prev_version(),
                "kind": updater.install_kind()}

    # ------------------------------------------------------------- sensors
    def _sensor_parts(self):
        """(sensor parts of enabled strips, the zones they're on), straight from the config."""
        from iridia.sensors import valid_id
        out, zones = [], set()
        devices = self.config.devices_view
        for dev, zn, zc in self._iter_zone_targets(devices):
            if not isinstance(zc, dict) or not zc.get("enabled", True) or not devices.get(dev, {}).get("enabled", True):
                continue
            for sec in zc.get("sections") or []:
                if isinstance(sec, dict) and sec.get("type") == "sensor" and valid_id(sec.get("sensor")):
                    out.append(zone_sections.clean_section(sec))
                    zones.add((dev, zn))
        return out, zones

    def _update_sensors(self):
        parts, zones = self._sensor_parts()
        self.sensors.set_wanted({p["sensor"] for p in parts})
        moved = self.sensors.update()
        if moved or (parts and zone_sections.has_flash(parts, self.sensors.value)):
            self._sensor_zones |= zones     # only these strips change: no need to redraw the others

    def _update_sensor_zones(self):
        zones, self._sensor_zones = self._sensor_zones, set()
        devices = self.config.devices_view
        for dev, zn, zc in self._iter_zone_targets(devices):
            if (dev, zn) in zones and isinstance(zc, dict):
                try:
                    self._update_zone(dev, zn, clean_zone_cfg(zc), time.time() - self._start_time)
                except Exception:           # noqa: BLE001 - the full update logs it properly
                    self._needs_update = True

    def _cmd_sensors(self, req: dict) -> dict:
        return {"ok": True, "sensors": self.sensors.listing(), "values": self.sensors.values()}

    # ------------------------------------------------------------- notifications
    def _notify_settings(self) -> dict:
        return notifyflash.clean(self.config.get("notify", {}))

    def _on_notification(self, app: str, urgent: bool):
        """Called from the watcher thread."""
        with self._notify_lock:
            if len(self._notify_events) < 20:
                self._notify_events.append((app, urgent))
        self._wake.set()

    def _update_notify(self):
        from iridia.notifywatch import dnd_on
        st = self._notify_settings()
        if self.notifywatch is not None:
            self.notifywatch.set_needed(st["enabled"] and bool(st["targets"]))
        with self._notify_lock:
            events, self._notify_events = self._notify_events, []
        for app, urgent in events:
            if app and app not in st["seen"]:
                st["seen"] = [app] + st["seen"][:notifyflash.SEEN_MAX - 1]
                cur = self.config.get("notify", {})
                self.config.set("notify", dict(cur if isinstance(cur, dict) else {}, seen=st["seen"]))
            if not st["enabled"] or not notifyflash.wanted(st, app):
                continue
            if st["night_quiet"] and self._night_active:
                continue
            if st["dnd"] and dnd_on():
                continue
            self._start_flash(st, app, urgent)
        if self._flash is not None and self._flash.done():
            self._flash = None

    def _start_flash(self, st: dict, app: str, urgent: bool) -> bool:
        now = time.monotonic()
        if self._flash is not None and now - self._flash.t0 < notifyflash.COALESCE_SEC:
            return True                     # a burst of notifications: one flash
        effect, rgb, painted = notifyflash.style_for(st, app, urgent, self._led_base_color() or "ffffff")
        ranges = self._flash_ranges(st["targets"])
        positions, spacing = {}, {}
        if st["spatial"]:
            for key, rs in ranges.items():
                n = max(hi for _lo, hi in rs)
                lp = self._layout_points(key, self._flash_sizes.get(key, n))
                positions[key] = lp[0] if lp else None
                if lp:
                    spacing[key] = lp[1]
        leds = notifyflash.led_places(ranges, positions, effect, st["path"] if st["spatial"] else None, spacing)
        if not leds:
            return False
        self.logger.debug(f"Notification from {app or 'an app'}: {effect} on {len(leds)} zone(s)")
        self._flash = notifyflash.Flash(leds, rgb, effect, st["duration"], now, direction=st["direction"],
                                        band=st["band"], repeat=st["repeat"], brightness=st["brightness"],
                                        paint=notifyflash.paint_rgb(st["paint"]) if painted else None)
        return True

    def _flash_ranges(self, targets: list) -> Dict[str, list]:
        """zone key -> the LEDs to flash on it, for the enabled strips the targets name."""
        out: Dict[str, list] = {}
        self._flash_sizes = {}
        devices = self.config.devices_view
        for t in targets:
            dev_cfg = devices.get(t["device"])
            if not isinstance(dev_cfg, dict) or not dev_cfg.get("enabled", True):
                continue
            zones = dev_cfg.get("zones")
            if t["zone"]:
                raw = zones.get(t["zone"]) if isinstance(zones, dict) else None
            else:
                raw = None if isinstance(zones, dict) and zones else dev_cfg
            if not isinstance(raw, dict) or not raw.get("enabled", True):
                continue
            zc = clean_zone_cfg(raw)
            n = zc["led_count"]
            if self._strip_type(t["device"], t["zone"], zc) == "single":
                r = (0, n) if n > 0 else None       # one colour for the whole strip
            else:
                r = notifyflash.target_range(t, n, zc["sections"], zone_sections.spans)
            if r is not None:
                key = self._zone_key(t["device"], t["zone"])
                out.setdefault(key, []).append(r)
                self._flash_sizes[key] = n
        return out

    def _flash_blocked(self, device: str, zone: str, key: str) -> bool:
        """What a flash gives way to: lights off, sleep, identify, Count LEDs, Test colors, a color
        preview, a keybind's color or power. (Animations being paused doesn't stop it.)"""
        if self._lights_off or self._asleep or self._preview_hex or self._anim_hold:
            return True
        if self._identify or self._probe:
            return True
        test = self._rgbtest
        if test and (test[0], test[1] or "") == (device, zone or ""):
            return True
        ov = self._overlays.get(key)
        return bool(ov and ("power" in ov or "hex" in ov))

    def _flash_mix(self, fl, key: str, zcfg: dict, colors: list) -> list:
        ov = self._overlays.get(key) or {}
        b = ov["bright"] if ov.get("bright") is not None else self._brightness_now(key, zcfg)
        if b <= 0:
            return colors                   # a strip that's dark (locked, brightness 0) stays dark
        return fl.mix(key, colors, max(35.0, min(100.0, b)) / 100.0)

    def _notify_status(self) -> dict:
        from iridia.notifywatch import monitor_command
        w = self.notifywatch
        return {"notify": dict(self._notify_settings(), listening=bool(w and w.running),
                               method=(w.method if w and w.running else None) or
                               ((monitor_command() or [None])[0]),
                               flashing=self._flash is not None)}

    def _cmd_notify(self, req: dict) -> dict:
        """Notification flash settings; test=True flashes now (on req's targets, or the saved ones)."""
        cur = self.config.get("notify", {})
        new = dict(cur if isinstance(cur, dict) else {})
        changed = False
        for k in ("enabled", "targets", "effect", "direction", "band", "repeat", "brightness", "color", "hex",
                  "urgent_red", "urgent_effect", "duration", "apps", "app_list", "rules", "path", "spatial", "paint",
                  "dnd", "night_quiet"):
            if k in req:
                new[k] = req[k]
                changed = True
        pick = req.get("pick_app")
        if isinstance(pick, list) and len(pick) == 2 and isinstance(pick[0], str):
            names = [a for a in new.get("app_list") or [] if isinstance(a, str) and a.lower() != pick[0].lower()]
            new["app_list"] = names + ([pick[0]] if pick[1] else [])
            changed = True
        ps = req.get("paint_set")
        if isinstance(ps, dict) and isinstance(ps.get("key"), str) and isinstance(ps.get("leds"), dict):
            # LED -> colour, or None to take its colour off; other strips and LEDs stay as they are
            paint = {k: dict(v) for k, v in notifyflash.clean_paint(new.get("paint")).items()}
            z = paint.setdefault(ps["key"], {})
            for i, h in ps["leds"].items():
                if h is None:
                    z.pop(str(i), None)
                else:
                    z[str(i)] = h
            new["paint"] = paint
            changed = True
        if req.get("paint_clear"):
            new["paint"] = {}
            changed = True
        rz = req.get("remove_zone")
        if isinstance(rz, list) and len(rz) == 2:
            new["targets"] = [t for t in new.get("targets") or [] if not isinstance(t, dict) or
                              (t.get("device"), t.get("zone") or "") != (rz[0], rz[1] or "")]
            changed = True
        rule = notifyflash.clean_rule(req.get("set_rule"))
        if rule is not None:
            new["rules"] = [r for r in new.get("rules") or [] if not isinstance(r, dict) or
                            str(r.get("app", "")).lower() != rule["app"].lower()] + [rule]
            changed = True
        if isinstance(req.get("remove_rule"), str):
            new["rules"] = [r for r in new.get("rules") or [] if not isinstance(r, dict) or
                            str(r.get("app", "")).lower() != req["remove_rule"].lower()]
            changed = True
        rm = req.get("remove_target")
        if isinstance(rm, int) and not isinstance(rm, bool):
            ts = list(new.get("targets") or [])
            if 0 <= rm < len(ts):
                del ts[rm]
            new["targets"] = ts
            changed = True
        if req.get("forget"):
            new["seen"] = []
            changed = True
        if req.get("clear_targets"):
            new["targets"] = []
            changed = True
        add = req.get("add_target")
        if isinstance(add, dict):
            # the window names the device and zone; the command line a strip's name (or
            # Device/Zone, a device, all)
            if isinstance(add.get("device"), str):
                keys, err = [self._zone_key(add["device"], add.get("zone") or "")], None
            else:
                keys, err = self._resolve_target(add.get("target"))
            if err:
                return {"ok": False, "error": err}
            which = {k: add[k] for k in ("part", "start", "end") if k in add}
            new["targets"] = list(new.get("targets") or []) + [
                dict(which, device=k.partition("|")[0], zone=k.partition("|")[2]) for k in keys]
            changed = True
        if changed:
            self.config.set("notify", notifyflash.clean(new))
        if req.get("test"):
            st = self._notify_settings()
            if "test_targets" in req:
                st["targets"] = notifyflash.clean({"targets": req["test_targets"]})["targets"]
            self._flash = None
            if not self._start_flash(st, "Iridia", bool(req.get("urgent"))):
                return dict(self._notify_status(), ok=False, error="No LEDs chosen for notifications")
            self._needs_update = True
        return dict(self._notify_status(), ok=True)

    # ------------------------------------------------------------- lock and idle
    SESSION_ACTIONS = ("keep", "dim", "off")
    FADE_OUT_SEC = 2.0
    FADE_IN_SEC = 0.5

    def _start_sessionwatch(self):
        from iridia.sessionwatch import SessionWatcher
        self.sessionwatch = SessionWatcher(self._wake.set)
        self.sessionwatch.start()

    def _session_settings(self) -> dict:
        c = self.config.get("session", {})
        c = c if isinstance(c, dict) else {}

        def pick(v):
            return v if v in self.SESSION_ACTIONS else "keep"
        return {"lock": pick(c.get("lock")), "idle": pick(c.get("idle")),
                "idle_minutes": _num(c.get("idle_minutes", 10), 10, 1, 240),
                "dim": int(_num(c.get("dim", 20), 20, 0, 100))}

    def _sess_fading(self) -> bool:
        """A lock or idle fade is running, or its last step hasn't been sent yet."""
        return not self._sess_settled or time.monotonic() - self._sess_ramp[2] < self._sess_ramp[3]

    def _session_factor(self, now: Optional[float] = None) -> float:
        frm, to, t0, dur = self._sess_ramp
        now = time.monotonic() if now is None else now
        if dur <= 0 or now - t0 >= dur:
            return to
        return frm + (to - frm) * (now - t0) / dur

    def _update_session(self):
        """Work out locked / idle and fade the LEDs to what Settings asks for."""
        s = self._session_settings()
        w = self.sessionwatch
        if w is not None:
            w.set_needs(lock=s["lock"] != "keep", idle=s["idle"] != "keep")
        test = time.monotonic() < self._sess_test_until
        locked = self._hooks["lock"] or bool(w and w.locked) or test
        idle_s = w.idle_seconds() if w is not None else None
        idle = self._hooks["idle"] or (idle_s is not None and idle_s >= s["idle_minutes"] * 60)
        lock_act = s["lock"] if not test or s["lock"] != "keep" else "off"     # a test always shows something
        target = 1.0
        for on, act in ((locked, lock_act), (idle, s["idle"])):
            if on and act != "keep":
                target = min(target, 0.0 if act == "off" else s["dim"] / 100.0)
        state = "locked" if locked else "idle" if idle else "active"
        if state != self._sess_state:
            self.logger.info(f"Screen {state}" + (f": LEDs to {int(target * 100)}% brightness"
                                                  if target != self._sess_ramp[1] else ""))
            self._sess_state = state
        now = time.monotonic()
        cur = self._session_factor(now)
        if target != self._sess_ramp[1]:
            dur = self.FADE_OUT_SEC if target < cur else self.FADE_IN_SEC
            self._sess_ramp = (cur, target, now, dur * abs(target - cur))
        if now - self._sess_ramp[2] < self._sess_ramp[3]:
            self._glide_active = True       # still fading: keep sending
            self._sess_settled = False
        elif not self._sess_settled:
            # The fade is over, but the loop may have last looked partway through it (it looks only
            # once a second when nothing else moves): send the final brightness once more, or the
            # LEDs stay at whatever step of the fade went out last.
            self._sess_settled = True
            self._needs_update = True

    def _cmd_session(self, req: dict) -> dict:
        """Hooks (lock_hook, idle_hook: true/false), a test (test: seconds), settings (lock, idle:
        keep/dim/off, idle_minutes, dim) and the current state."""
        for k in ("lock_hook", "idle_hook"):
            if k in req:
                self._hooks[k.split("_")[0]] = bool(req[k])
        if "test" in req:
            self._sess_test_until = time.monotonic() + _num(req["test"], 5, 0, 60)
        new = {}
        for k in ("lock", "idle"):
            if k in req:
                if req[k] not in self.SESSION_ACTIONS:
                    return {"ok": False, "error": f"{k} must be keep, dim or off"}
                new[k] = req[k]
        if "idle_minutes" in req:
            new["idle_minutes"] = _num(req["idle_minutes"], 10, 1, 240)
        if "dim" in req:
            new["dim"] = int(_num(req["dim"], 20, 0, 100))
        if new:
            cur = self.config.get("session", {})
            self.config.set("session", dict(cur if isinstance(cur, dict) else {}, **new))
        self._update_session()
        self._needs_update = True
        self._wake.set()
        return dict(self._session_status(), ok=True)

    def _session_status(self) -> dict:
        w = self.sessionwatch
        idle = w.idle_seconds() if w is not None else None
        return {"session": dict(self._session_settings(), state=self._sess_state,
                                factor=round(self._sess_ramp[1], 2), hooks=dict(self._hooks),
                                lock_method=w.lock_method if w else None,
                                idle_method=w.idle_method if w else None,
                                watching={"lock": bool(w and w.watching_lock), "idle": bool(w and w.want_idle),
                                          "idle_checked": bool(w and w.idle_checked)},
                                idle_seconds=None if idle is None else int(idle))}

    def _on_sleep(self):
        """Called from the watcher thread: dark LEDs, then let the PC sleep."""
        self._sleep_sent.clear()
        self._asleep = True
        self._last_sent = {}
        self._needs_update = True
        self._wake.set()
        if not self._sleep_sent.wait(3.0):
            self.logger.warning("Couldn't confirm the LEDs went dark before sleep")

    def _on_wake(self):
        def later():
            time.sleep(3.0)                 # USB controllers need a moment after resume
            self._asleep = False
            self._last_sent = {}
            self._force_refresh = True
            self._wake.set()
            time.sleep(7.0)                 # and once more, in case a controller came back late
            self._last_sent = {}
            self._force_refresh = True
            self._wake.set()
        threading.Thread(target=later, daemon=True).start()

    def _night_settings(self) -> dict:
        n = self.config.get("night", {})
        n = n if isinstance(n, dict) else {}
        return {"enabled": n.get("enabled", False) is True, "start": str(n.get("start", "23:00")),
                "end": str(n.get("end", "07:00")), "cap": int(_num(n.get("cap", 20), 20, 0, 100))}

    @staticmethod
    def _minutes(hhmm: str) -> Optional[int]:
        try:
            h, m = hhmm.split(":")
            h, m = int(h), int(m)
        except (ValueError, AttributeError):
            return None
        return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None

    def _night_now(self) -> bool:
        n = self._night_settings()
        if not n["enabled"]:
            return False
        s, e = self._minutes(n["start"]), self._minutes(n["end"])
        if s is None or e is None or s == e:
            return False
        lt = time.localtime()
        now = lt.tm_hour * 60 + lt.tm_min
        return s <= now < e if s < e else (now >= s or now < e)

    def _cmd_set_night(self, req: dict) -> dict:
        cur = self._night_settings()
        for key in ("start", "end"):
            if key in req:
                if self._minutes(str(req[key])) is None:
                    return {"ok": False, "error": f"{key} must be a time like 23:00"}
                h, m = str(req[key]).split(":")
                cur[key] = f"{int(h):02d}:{int(m):02d}"
        if "cap" in req:
            try:
                cur["cap"] = max(0, min(100, int(req["cap"])))
            except (TypeError, ValueError):
                return {"ok": False, "error": "cap must be 0 to 100"}
        if req.get("toggle"):
            cur["enabled"] = not cur["enabled"]
        elif "enabled" in req:
            cur["enabled"] = bool(req["enabled"])
        self.config.set("night", cur)
        self._needs_update = True
        self.logger.info(f"Night mode: {'on' if cur['enabled'] else 'off'}, {cur['start']} to {cur['end']}, "
                         f"brightness capped at {cur['cap']}%")
        return {"ok": True, "night": cur}

    def _shutdown(self):
        self._stopping.set()
        self._animator.stop()
        self.logger.info("Shutting down")
        if self.sleepwatch:
            self.sleepwatch.stop()
        if self.sessionwatch:
            self.sessionwatch.stop()
        if self.notifywatch:
            self.notifywatch.stop()
        self.sensors.stop()
        self.ipc.stop()
        if self._observer:
            self._observer.stop()
            self._observer.join()

    def _setup_watchers(self):
        if self._observer:
            # Called on every wallpaper change — stop the previous
            # observer so threads/inotify watches don't pile up.
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
        self._observer = Observer()
        watches = []
        if os.path.isdir(self._config_dir):
            watches.append((_ConfigHandler(self), self._config_dir))
        if self._current_wallpaper and os.path.exists(self._current_wallpaper):
            watch_dir = os.path.dirname(self._current_wallpaper)
            if os.path.isdir(watch_dir):
                watches.append((_WallpaperHandler(self), watch_dir))
        caelestia_dir = os.path.expanduser("~/.local/state/caelestia/wallpaper")
        if os.path.isdir(caelestia_dir):
            watches.append((_WallpaperHandler(self), caelestia_dir))
        state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        noctalia_dir = os.path.join(state, "noctalia")
        if os.path.isdir(noctalia_dir):
            watches.append((_WallpaperHandler(self), noctalia_dir))
        settings = self.detector.watch_files()
        folders = {}
        for f in settings:
            if os.path.isdir(os.path.dirname(f)):
                folders.setdefault(os.path.dirname(f), []).append(f)
        for folder, files in folders.items():
            watches.append((_SettingsFileHandler(self, files), folder))
        watched_settings = 0
        for handler, folder in watches:
            try:
                self._observer.schedule(handler, folder, recursive=False)
                if isinstance(handler, _SettingsFileHandler):
                    watched_settings += 1
            except OSError as e:
                # inotify watch limit reached, a folder on a network share, ...: wallpaper
                # changes are still found by the regular check, just a little later.
                self.logger.warning(f"Can't watch {folder} for changes ({e}); checking it periodically instead")
        try:
            self._observer.start()
        except OSError as e:
            watched_settings = 0
            self.logger.warning(f"File watching unavailable ({e}); wallpaper changes are found by polling")
        self.detector.set_watched(watched_settings > 0)

    def on_wallpaper_file_changed(self, path: str):
        # Noctalia's state dir also holds busy files (screen_time.json,
        # clipboard, ...); only its settings file can mean "wallpaper changed".
        if os.sep + "noctalia" + os.sep in path and os.path.basename(path) != "settings.toml":
            return
        now = time.time()
        debounce = _num(self.config.get("timing.wallpaper_debounce_ms", 300), 300, 0, 10000) / 1000.0
        if now - self._last_wallpaper_event < debounce:
            return
        self._last_wallpaper_event = now
        self.logger.debug(f"Wallpaper file changed: {path}")
        self.detector.invalidate()        # re-run the slow (subprocess) backends right away
        self._wake.set()
        try:
            if self._current_wallpaper and os.path.realpath(path) == self._current_wallpaper:
                self._reextract = True
        except OSError:
            pass
        self._needs_update = True

    def on_config_changed(self):
        """Config file changed on disk. Only the parts that actually
        changed are re-applied, and nothing is logged at INFO unless
        something did - toggling one switch in the GUI shouldn't
        re-initialise the wallpaper detector or spam the log."""
        keys = ("wallpaper.manual_path", "wallpaper.watch_folder", "color.backend",
                "logging.enabled", "logging.file_path", "logging.level", "logging.max_size_kb",
                "timing.ddc_poll_interval_sec")
        old = {k: copy.deepcopy(self.config.get(k)) for k in keys}
        if not self.config.reload():
            return
        changed = [k for k in keys if self.config.get(k) != old[k]]
        self.logger.debug(f"Config reloaded from disk (changed: {changed or 'device/zone settings only'})")

        if any(k.startswith("logging.") for k in changed):
            self.logger = setup_logging(self.config)
            self.logger.info("Logging reconfigured: file logging "
                             f"{'ON -> ' + str(self.config.get('logging.file_path')) if self.config.get('logging.enabled') else 'OFF'}")
        if "wallpaper.manual_path" in changed or "wallpaper.watch_folder" in changed:
            self.logger.info("Wallpaper settings changed; re-detecting")
            self.detector = WallpaperDetector(
                manual_path=self.config.get("wallpaper.manual_path"),
                watch_folder=self.config.get("wallpaper.watch_folder"),
                cache_path="~/.config/iridia/detection_cache.json",
            )
            self.detector.reset_cache()
            self._current_wallpaper = None
        if "timing.ddc_poll_interval_sec" in changed:
            self.ddc.poll_interval = self.config.get("timing.ddc_poll_interval_sec")
        new_backend = self.config.get("color.backend", "auto")
        if new_backend != self.extractor.backend:
            self.logger.info(f"Color backend changed: {self.extractor.backend} -> {new_backend}; re-extracting")
            self.extractor = ColorExtractor(backend=new_backend)
            self._current_wallpaper = None   # next tick re-detects and re-extracts
        self._needs_update = True
        self._wake.set()

    def on_palette_changed(self):
        self.logger.info("Palette changed on disk, reloading")
        self.palette._load()
        self._snap_cache = {}
        self._needs_update = True
        self._wake.set()

    def _tick(self) -> None:
        """Run one daemon cycle.

        Wallpaper/brightness detection and the GUI-visible status they
        feed always run here, regardless of whether OpenRGB is
        reachable — only the actual hardware send is gated on that.
        Previously the whole method returned immediately when OpenRGB
        wasn't connected, which meant wallpaper changes were never
        even noticed (let alone applied) until OpenRGB reconnected, and
        the "Refresh" button had nothing to act on since it just flips
        a flag this method alone consumes.
        """
        now = time.time()
        if self._preview_hex and now > self._preview_until:
            self._preview_hex = None
            self._preview_raw = False
            self._needs_update = True
        test = self._rgbtest
        if test:
            self._needs_update = True       # one-color strips cycle red, green, blue
            if now > test[2]:
                self._rgbtest = None
        ident, probe = self._identify, self._probe
        if ident and now > ident[2]:
            self._identify = None
            self._needs_update = True
        if probe and now > probe[3]:
            self._probe = None
            self._needs_update = True
        night = self._night_now()
        if night != self._night_active:
            self._night_active = night
            n = self._night_settings()
            self.logger.info(f"Night mode {'started' if night else 'ended'}"
                             + (f": brightness capped at {n['cap']}% until {n['end']}" if night else ""))
            self._needs_update = True
        self._health_check()
        retry = self.config.get("timing.openrgb_retry_interval_sec", 5.0)
        connected = self.openrgb.ensure_connected(retry_interval=retry)
        self._log_connection_state(connected)
        self._supervise_openrgb(connected)
        self._check_no_devices()
        if connected:
            enum_interval = self.config.get("timing.device_enumeration_interval_sec", 10.0)
            self.openrgb.maybe_enumerate(interval=enum_interval)
            self._check_openrgb_epoch()
            self._autoadd_devices()
            self._check_missing_devices()

        self._detect_wallpaper()
        self._read_brightness()

        self._update_session()
        self._update_notify()
        self._update_sensors()
        self._refresh_animations(connected)
        if self._glide_active:
            self._needs_update = True       # a brightness glide is still running
        if connected and (self._needs_update or self._force_refresh):
            self._glide_active = False
            self._sensor_zones = set()
            self._update_all_devices()
        elif connected and self._sensor_zones:
            self._update_sensor_zones()
        if self._asleep and (connected or not self.openrgb.client):
            self._sleep_sent.set()          # dark LEDs sent (or nothing to send to)

    SETTLE_RESEND_SEC = 3.0      # after (re)connecting, send everything once more after this long

    def _check_openrgb_epoch(self, now: Optional[float] = None):
        """OpenRGB (re)connected or its device list changed: its devices may be fresh ones showing their
        own colours, so send every zone again, and once more a little later (some controllers miss the
        first update right after being switched to Direct mode). Static colours are otherwise only sent
        when they change, so the strips stayed dark until a colour was nudged."""
        epoch = getattr(self.openrgb, "epoch", 0)
        now = time.monotonic() if now is None else now
        if epoch != self._openrgb_epoch:
            self._openrgb_epoch = epoch
            self._last_sent = {}
            self._needs_update = True
            self._settle_resend_at = now + self.SETTLE_RESEND_SEC
        elif self._settle_resend_at is not None and now >= self._settle_resend_at:
            self._settle_resend_at = None
            self._last_sent = {}
            self._needs_update = True

    def _reconcile_zones(self):
        """If none of a device's configured zone names exist in what
        OpenRGB reports (e.g. config says 'ARGB Header 1' but the
        controller exposes 'Channel 1'..'Channel 6'), rebuild the zone
        config from the real zones, copying the old first zone's
        settings as the template. Zones are only ever *replaced* when
        zero names match, so a user's deliberate partial config is
        never touched."""
        try:
            real_devs = {d["name"]: d for d in self.openrgb.list_devices()}
        except Exception:
            return
        for name, dev_cfg in self.config.devices_view.items():
            zones = dev_cfg.get("zones") if isinstance(dev_cfg, dict) else None
            real = real_devs.get(name)
            if not isinstance(zones, dict) or not zones or not real:
                continue
            real_zones = real.get("zones", [])
            if not any(r["led_count"] > 0 for r in real_zones) or any(r["name"] in zones for r in real_zones):
                continue
            template = next(iter(zones.values()))
            template = {k: v for k, v in template.items() if k != "display_name"} if isinstance(template, dict) else {}
            new_zones = {}
            for z in real_zones:
                zc = dict(template)
                zc["led_count"] = z["led_count"]
                if not z["led_count"]:
                    zc.update(enabled=False, unsized=True)
                new_zones[z["name"]] = zc
            self.logger.warning(
                f"Config zones {list(zones)} don't exist on '{name}'; "
                f"adopting OpenRGB's zones {list(new_zones)} with the old settings "
                "(edit ~/.config/iridia/config.json to disable any you don't use).")
            self.config.set(("devices", name, "zones"), new_zones)
            self._last_sent.clear()
            self._needs_update = True

    def _autoadd_devices(self):
        """Devices OpenRGB reports that aren't in the config yet get a
        sensible default entry, so a fresh install works with no hand-editing."""
        try:
            found = self.openrgb.list_devices()
        except Exception:
            return
        known = self.config.devices
        if not isinstance(known, dict):
            known = {}
        new = [dev for dev in found if dev["name"] not in known]
        devices = self.config.get("devices", {})
        if not isinstance(devices, dict):
            devices = {}

        def fresh(n, enabled=True):
            z = {"enabled": enabled, "led_count": n, "pattern": "solid",
                 "pattern_colors": [0], "mode": "full", "brightness_sync": False,
                 "manual_brightness": 100, "brightness_range": [0, 100],
                 "invert_brightness": False, "gamma_correction": False}
            if not n:
                z["unsized"] = True         # switched on by itself once it gets a size
            return z

        # Known devices: zones that appeared later get added; a zone that had no size
        # (and that we switched off for that reason) is switched on once it has one.
        changed = False
        for dev in found:
            cfg = devices.get(dev["name"])
            zcfgs = cfg.get("zones") if isinstance(cfg, dict) else None
            if not isinstance(zcfgs, dict) or not zcfgs:
                continue
            if not any(z["name"] in zcfgs for z in dev["zones"]):
                continue                    # nothing matches: _reconcile_zones adopts the real zones
            for z in dev["zones"]:
                zc = zcfgs.get(z["name"])
                if zc is None:
                    zcfgs[z["name"]] = fresh(z["led_count"], z["led_count"] > 0)
                    self.logger.info(f"'{dev['name']}' has a new zone '{z['name']}' ({z['led_count']} LEDs); added")
                    changed = True
                elif isinstance(zc, dict) and zc.get("unsized") and z["led_count"] > 0:
                    zc.pop("unsized", None)
                    zc.update(led_count=z["led_count"], enabled=True)
                    self.logger.info(f"'{dev['name']}/{z['name']}' now has {z['led_count']} LEDs; switched on")
                    changed = True
        if not new and not changed:
            return
        for dev in new:
            if dev["zones"]:
                # Zones OpenRGB reports with 0 LEDs (an ARGB header nobody has sized yet) are
                # added switched off, so they show up and can be sized from the window.
                zones = {z["name"]: fresh(z["led_count"], z["led_count"] > 0) for z in dev["zones"]}
                devices[dev["name"]] = {"enabled": True, "zones": zones}
                empty = sum(1 for z in dev["zones"] if z["led_count"] == 0)
                self.logger.info(f"Found new device '{dev['name']}' with {len(zones)} zone(s)"
                                 + (f", {empty} without a size yet (off)" if empty else "") + "; added to config")
            else:
                # Whole-device control (mice, some GPUs and RAM report no zones).
                devices[dev["name"]] = dict(fresh(max(1, dev.get("led_count") or 1)))
                self.logger.info(f"Found new device '{dev['name']}' (no zones, controlled as a whole); "
                                 "added to config")
        self.config.set("devices", devices)
        self._last_sent = {}
        self._needs_update = True

    def _check_missing_devices(self):
        """Track configured+enabled devices that OpenRGB is connected
        but doesn't currently report, and escalate to a full server
        restart if one stays missing too long — mirrors the watchdog
        pattern the user's own scripts used before iridia existed:
        periodic health check -> hard restart if the device doesn't
        come back on its own. Cheap re-enumeration alone (maybe_enumerate)
        doesn't fix this class of failure; see restart_server()'s
        docstring for why.
        """
        self._reconcile_zones()
        now = time.time()
        configured = [name for name, cfg in self.config.devices_view.items() if cfg.get("enabled", True)]
        for name in configured:
            if name in self.openrgb.devices:
                self._device_missing_since.pop(name, None)
                if self._restart_attempts.pop(name, None):
                    self.logger.info(f"'{name}' is back")
                continue
            self._device_missing_since.setdefault(name, now)

        # Drop tracking for devices no longer configured at all.
        for name in list(self._device_missing_since.keys()):
            if name not in configured:
                del self._device_missing_since[name]

        if not self._device_missing_since:
            return
        if not self.config.get("openrgb.auto_restart_on_missing_device", True):
            return

        threshold = self.config.get("openrgb.missing_device_restart_threshold_sec", 45.0)
        cooldown = self.config.get("openrgb.restart_cooldown_sec", 120.0)
        # A device that two restarts didn't bring back is probably unplugged, renamed by an
        # OpenRGB update, or gone for good: restarting OpenRGB every two minutes forever would
        # only make the other LEDs flicker. It's still shown as missing in the window.
        retry = {n: t for n, t in self._device_missing_since.items() if self._restart_attempts.get(n, 0) < 2}
        if not retry:
            return
        oldest_missing = min(retry.values())
        if now - oldest_missing < threshold:
            return
        if now - self._last_auto_restart < cooldown:
            return
        if not self._orgb.owner(self._orgb_settings()[0]):
            self._say_once("missing", f"Device(s) {list(retry)} missing from OpenRGB for over {threshold:.0f}s. "
                                      "OpenRGB wasn't started by Iridia, so it isn't restarted automatically: "
                                      "use Restart OpenRGB server, or restart it yourself.")
            return

        missing_names = list(retry.keys())
        for n in missing_names:
            self._restart_attempts[n] = self._restart_attempts.get(n, 0) + 1
        last = [n for n in missing_names if self._restart_attempts[n] >= 2]
        self.logger.warning(
            f"Device(s) {missing_names} missing from OpenRGB for over {threshold:.0f}s, "
            "attempting an automatic OpenRGB server restart to recover."
            + (f" Last try for {last}: if they stay missing, switch them off on the Devices tab "
               "(or remove them from config.json)." if last else "")
        )
        self._last_auto_restart = now
        self._device_missing_since = {}
        self._restart_openrgb_async(f"Device(s) {missing_names} missing")

    # ------------------------------------------------------------ OpenRGB server
    NODEV_FIRST_SEC = 30.0       # no devices this long: restart the OpenRGB we started
    NODEV_AGAIN_SEC = 120.0      # then at most once per this long
    NODEV_MAX = 2                # restarts per daemon run
    RESTART_SETTLE_SEC = 3.0     # after a restart, let OpenRGB scan before reconnecting

    def _say_once(self, topic: str, msg: str, level=logging.WARNING):
        if self._said.get(topic) != msg:
            self._said[topic] = msg
            self.logger.log(level, msg)

    def _orgb_settings(self):
        o = self.config.openrgb
        custom = o.get("server_command") or ""
        return openrgb_server.method_of(o), o.get("host"), (custom if isinstance(custom, str) else ""), o.get("port")

    def _migrate_openrgb_unit(self):
        try:
            msg = openrgb_server.migrate(self._orgb_settings()[0])
            if msg:
                self.logger.info(msg)
        except Exception as e:              # noqa: BLE001
            self.logger.warning(f"Checking iridia-openrgb.service failed: {type(e).__name__}: {e}")

    def _supervise_openrgb(self, connected: bool):
        """Start (and keep running) OpenRGB's server per openrgb.start_method; see openrgb_server.py.
        Runs off the tick thread when it may call systemctl or scan for other starters."""
        method, host, custom, port = self._orgb_settings()
        if method == "off" or self._orgb_busy or self._orgb_restarting:
            return
        if connected and not self._orgb.pid:
            return                          # nothing to start, nothing of ours to watch
        quick = bool(self._orgb.pid) and method == "daemon"     # only checks our process

        def run():
            try:
                self._orgb.tick(method, host, connected, custom, port)
            except Exception as e:          # noqa: BLE001
                self.logger.warning(f"Starting OpenRGB failed: {type(e).__name__}: {e}")
            finally:
                self._orgb_busy = False
        self._orgb_busy = True
        if quick:
            run()
        else:
            threading.Thread(target=run, daemon=True, name="openrgb-start").start()

    def _check_no_devices(self):
        """OpenRGB answers but sees no devices: at boot it can start before the session has access
        to the hardware, and it never scans again. Restart it, but only if Iridia started it."""
        since = self.openrgb.no_devices_since
        if since is None or self._orgb_restarting:
            return
        now = time.time()
        if now - since < self.NODEV_FIRST_SEC:
            return
        if self._nodev_restarts >= self.NODEV_MAX:
            self._say_once("nodev", f"OpenRGB still reports no devices after {self.NODEV_MAX} restarts. Check "
                                    "that OpenRGB itself sees them (open its window), and see "
                                    f"{openrgb_server.LOG_PATH}.")
            return
        if self._nodev_last and now - self._nodev_last < self.NODEV_AGAIN_SEC:
            return
        method = self._orgb_settings()[0]
        if not self._orgb.owner(method):
            who = ("openrgb.start_method is off" if method == "off" else
                   "it wasn't started by Iridia" + (f" (started by {', '.join(self._orgb._others[1])})"
                                                     if self._orgb._others[1] else ""))
            self._say_once("nodev", f"OpenRGB has reported no devices for {int(now - since)}s; {who}, so Iridia "
                                    "won't restart it. Restart OpenRGB yourself (it probably started before it "
                                    "could see the hardware).")
            return
        self._nodev_restarts += 1
        self._nodev_last = now
        self.openrgb.no_devices_since = None
        self._restart_openrgb_async(f"OpenRGB has reported no devices for {int(now - since)}s "
                                    f"(restart {self._nodev_restarts} of {self.NODEV_MAX})")

    def _restart_openrgb_async(self, reason: str, manual: bool = False) -> bool:
        """Restart OpenRGB off the tick thread (it takes a few seconds). Automatic restarts only
        touch the OpenRGB Iridia started; a Restart click may also replace a headless server that
        something else started (never the OpenRGB window). Returns False if nothing will happen."""
        if self._orgb_restarting:
            return True
        method, _host, custom, port = self._orgb_settings()
        if method == "off" and manual:
            self.logger.warning("Restart OpenRGB requested, but openrgb.start_method is off: Iridia doesn't "
                                "start or restart OpenRGB. Restart it yourself.")
            return False
        self._orgb_restarting = True

        def run():
            try:
                self.openrgb.disconnect()
                ok = self._orgb.restart(method, reason, custom, port)
                if not ok and manual:
                    ok = self._restart_not_ours(reason, custom, port)
                if not ok:
                    self.logger.warning(f"{reason}: nothing restarted (no OpenRGB server started by Iridia)")
                time.sleep(self.RESTART_SETTLE_SEC)     # let it scan before the next connect
            except Exception as e:          # noqa: BLE001
                self.logger.warning(f"Restarting OpenRGB failed: {type(e).__name__}: {e}")
            finally:
                self._orgb_restarting = False
                self._device_missing_since = {}
        threading.Thread(target=run, daemon=True, name="openrgb-restart").start()
        return True

    def _restart_not_ours(self, reason, custom, port) -> bool:
        """Explicit Restart of an OpenRGB server Iridia didn't start: restart its user unit if a
        known one runs it, else replace a headless `openrgb --server` with one Iridia starts."""
        for unit in openrgb_server.OTHER_USER_UNITS:
            _en, ac = openrgb_server.unit_state(unit)
            if ac in ("active", "activating"):
                r = openrgb_server._systemctl("restart", unit, timeout=20)
                if r is not None and r.returncode == 0:
                    self.logger.info(f"{reason}: restarted {unit}")
                    return True
        if self._orgb.take_over(reason, custom, port):
            return True
        self.logger.warning("No headless 'openrgb --server' to restart. If OpenRGB runs as its window, use its "
                            "Rescan Devices or restart it yourself.")
        return False

    def _log_connection_state(self, connected: bool):
        if connected == self._last_logged_connected:
            return
        self._last_logged_connected = connected
        if connected:
            self.logger.info(f"OpenRGB connected on port {self.openrgb.port}")
        else:
            ports = ([self.openrgb.port] if self.openrgb._configured_port or self.openrgb._auto_detected
                     else self.openrgb.COMMON_PORTS)
            tried = ", ".join(str(p) for p in ports)
            where = f"{self.openrgb.host} (port{'s' if len(ports) > 1 else ''} {tried})"
            method = self._orgb_settings()[0]
            if method in ("daemon", "systemd") and openrgb_server.is_local(self.openrgb.host):
                # Iridia (or its unit) brings the server up: nothing for you to do yet
                self.logger.info(f"OpenRGB isn't reachable on {where} yet; its server is started "
                                 f"{'by Iridia' if method == 'daemon' else 'by the systemd unit'}. Colors are kept "
                                 "and sent as soon as it's up.")
            else:
                self.logger.warning(
                    f"OpenRGB not reachable on {where}, is its SDK server actually running? Colors are still "
                    "being tracked and will be sent as soon as it connects."
                )

    def _health_check(self):
        now = time.time()
        interval = self.config.get("timing.health_check_interval_sec", 30.0)
        if now - self._last_health_check < interval:
            return
        self._last_health_check = now
        if not self.ipc.is_alive():
            self.logger.warning("IPC thread died, restarting...")
            self.ipc = IPCServer(self._socket_path, self)
            self.ipc.start()
        if self._session_over():
            self.logger.info("The login session this daemon was started in has ended: stopping, so the next "
                             "login's daemon can start")
            self.running = False

    def _session_over(self) -> bool:
        """Started by a compositor or a terminal (not systemd, which stops it itself) and its logind
        session is closing or gone. Otherwise it would outlive the logout and block the next login's copy.
        logind and elogind both keep /run/systemd/sessions/<id>."""
        sid = os.environ.get("XDG_SESSION_ID")
        if not sid or openrgb_server.run_by_systemd() or "/" in sid:
            return False
        path = os.path.join(self._sessions_dir, sid)
        try:
            with open(path, encoding="utf-8") as f:
                state = next((ln[6:].strip() for ln in f if ln.startswith("STATE=")), "")
            self._session_seen = True
            return state == "closing"
        except FileNotFoundError:
            return getattr(self, "_session_seen", False)
        except OSError:
            return False

    def _detect_wallpaper(self):
        if self._frozen:
            return      # colours are frozen: wallpaper changes are picked up on unfreeze
        path = self.detector.detect()
        if path and path == self._current_wallpaper and self._reextract:
            # The image file itself was rewritten in place (same name).
            self._reextract = False
            self.logger.info(f"Wallpaper file modified in place: {path}")
            self._extract_colors(path)
            self._needs_update = True
            self._last_sent = {}
        if path and path != self._current_wallpaper:
            self.logger.info(f"Wallpaper changed: {path}")
            self._current_wallpaper = path
            self._extract_colors(path)
            self._needs_update = True
            self._last_sent = {}
            self._setup_watchers()
            self._apply_remembered_choice()

    def _extract_colors(self, path: str):
        backend = self.extractor.backend
        cached = self.wallcache.get_colors(path, backend)
        if cached:
            self._extracted_colors = cached
            self.logger.info(f"Colors from cache: {cached[:4]}")
            return
        try:
            t0 = time.time()
            colors = self.extractor.extract(path, wallpaper_source=self.detector.last_backend or "")
            self._extracted_colors = colors
            self.wallcache.store_colors(path, colors, backend)
            self.logger.info(f"Extracted {len(colors)} colors via {self.extractor.last_used} "
                             f"(setting '{backend}', wallpaper from '{self.detector.last_backend}') "
                             f"in {time.time() - t0:.2f}s: {colors[:4]}")
        except Exception:
            self.logger.exception("Color extraction failed")
            self._extracted_colors = ["642107"]

    def _choice_entry(self, choice):
        """A saved per-wallpaper pick as a pattern_colors entry (index or hex)."""
        if not choice:
            return None
        if "hex" in choice:
            return choice["hex"].lower()
        idx = choice.get("index")
        return idx if isinstance(idx, int) and idx >= 0 else None

    @staticmethod
    def _zone_key(dev: str, zone: str) -> str:
        return f"{dev}|{zone or ''}"

    def _iter_zone_targets(self, devices):
        """(device, zone, config dict) for every zone; flat devices have zone ''."""
        for dev, dev_cfg in devices.items():
            zones = dev_cfg.get("zones")
            if zones:
                for zname, zcfg in zones.items():
                    yield dev, zname, zcfg
            else:
                yield dev, "", dev_cfg

    @staticmethod
    def _automatic(entries):
        """Same number of color slots, each following the wallpaper (slot i -> color i)."""
        return list(range(max(1, len(entries or []))))

    def _remember_zone_colors(self, picks: dict):
        """Save zone picks against the current wallpaper so they come back with it."""
        if self._current_wallpaper and picks:
            self.wallcache.set_zone_colors(self._current_wallpaper, picks)

    def _set_all_field(self, field: str, value, record: bool = False) -> int:
        devices = self.config.get("devices", {})
        n = 0
        picks = {}
        for dev, zname, target in self._iter_zone_targets(devices):
            target[field] = value
            picks[self._zone_key(dev, zname)] = value
            n += 1
        if record and field == "pattern_colors":
            self._remember_zone_colors(picks)
        self.config.set("devices", devices)
        self._last_sent = {}
        self._needs_update = True
        return n

    def _apply_remembered_choice(self):
        """A wallpaper change brings back what you picked for that wallpaper, zone by zone.

        Zones with a saved pick get it. Zones without one follow the new wallpaper: a custom
        color picked for another wallpaper is turned back into "color N of this wallpaper".
        """
        if not self._current_wallpaper:
            return
        saved = self.wallcache.get_zone_colors(self._current_wallpaper)
        legacy = None
        if not saved:
            legacy = self._choice_entry(self.wallcache.get_choice(self._current_wallpaper))
        devices = self.config.get("devices", {})
        restored = followed = 0
        for dev, zname, target in self._iter_zone_targets(devices):
            cur = target.get("pattern_colors") or [0]
            picked = saved.get(self._zone_key(dev, zname))
            if picked:
                target["pattern_colors"] = picked
                restored += 1
            elif legacy is not None:
                target["pattern_colors"] = [legacy]
                restored += 1
            elif any(not isinstance(e, int) or isinstance(e, bool) for e in cur):
                target["pattern_colors"] = [i if not isinstance(e, int) or isinstance(e, bool) else e
                                            for i, e in enumerate(cur)]
                followed += 1
        if restored or followed:
            self.config.set("devices", devices)
            self._last_sent = {}
            self._needs_update = True
        if restored or followed:
            self.logger.info(f"Colors for this wallpaper: {restored} zone(s) restored from your saved picks, "
                             f"{followed} zone(s) following the wallpaper")

    def _led_base_color(self) -> Optional[str]:
        """The colour the LEDs are (nominally) showing, before brightness
        scaling and animation — the GUI uses it as its accent colour."""
        try:
            col, mode, pm = None, self.config.color_mode, self.config.palette_mode
            for dev in self.config.devices_view.values():
                if not dev.get("enabled", True):
                    continue
                for z in (dev.get("zones") or {"": dev}).values():
                    if not z.get("enabled", True):
                        continue
                    mode = z.get("mode", mode)
                    pm = z.get("palette_mode", pm)
                    res = resolve_colors(z.get("pattern_colors", [0]), self._extracted_colors)
                    col = res[0] if res else None
                    break
                else:
                    continue
                break
            col = col or (self._extracted_colors[0] if self._extracted_colors else None)
            return col          # the wallpaper/chosen colour, before any correction
        except Exception:
            return None

    def _cmd_set_zone_profile(self, req: dict) -> dict:
        dev, zone, name = req.get("device"), req.get("zone"), req.get("name")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        if name not in self.calibration.list():
            return {"ok": False, "error": f"no calibration profile called {name!r}"}
        self.config.set(self._zone_config_path(dev, zone, "calibration_profile"), name)
        self._last_sent = {}
        self._needs_update = True
        return {"ok": True}

    def _cmd_preview_color(self, req: dict) -> dict:
        """Show one colour on every LED without touching the config, so a
        colour can be judged on the real strip. hex=None ends the preview."""
        raw = req.get("hex")
        if raw in (None, ""):
            self._preview_hex = None
            self._preview_raw = False
        else:
            h = normalize_hex(raw)
            if not h:
                return {"ok": False, "error": f"invalid hex color: {raw!r}"}
            self._preview_hex = h
            self._preview_raw = bool(req.get("raw", False))
            self._preview_exact = bool(req.get("exact", False))
            self._preview_until = time.time() + 300      # failsafe if the GUI vanishes
        self._needs_update = True
        self.logger.debug(f"Colour preview: {self._preview_hex or 'ended'}")
        return {"ok": True}

    def _cmd_setup(self, cmd: str, req: dict) -> dict:
        s = self.setups
        name = str(req.get("name") or "")
        if cmd == "setup_list":
            return {"ok": True, "setups": s.list(), "backups": s.list_backups()}
        if cmd == "setup_save":
            err = s.save(name, overwrite=bool(req.get("overwrite", True)))
            if not err:
                self.logger.info(f"Saved setup '{name}'")
            return {"ok": err is None, "error": err}
        if cmd in ("setup_load", "setup_restore_backup"):
            err = s.load(name) if cmd == "setup_load" else s.load_backup(str(req.get("id") or ""))
            if err:
                return {"ok": False, "error": err}
            self._after_restore()
            self.logger.info(f"Loaded setup '{name or req.get('id')}' (the previous state was backed up first)")
            return {"ok": True}
        if cmd == "setup_delete":
            err = s.delete(name)
            return {"ok": err is None, "error": err}
        if cmd == "setup_rename":
            err = s.rename(name, str(req.get("new") or ""))
            return {"ok": err is None, "error": err}
        if cmd == "setup_export":
            err = s.export_to(name, str(req.get("dest") or ""))
            return {"ok": err is None, "error": err}
        if cmd == "setup_import":
            new, err = s.import_from(str(req.get("src") or ""))
            return {"ok": err is None, "error": err, "name": new}
        return {"ok": False, "error": f"unknown command {cmd}"}

    def _after_restore(self):
        """Files were replaced by a setup: pick everything up again."""
        self.on_config_changed()
        self.wallcache = WallpaperColorCache()
        self.custom_colors = CustomColors()
        try:
            self.on_palette_changed()
        except Exception:
            pass
        self.calibration = Profiles()
        self._snap_cache = {}
        self._frozen = bool(self.config.get("color.frozen", False))
        want_sleep = bool(self.config.get("sleep.lights_off", True))
        if want_sleep and not self.sleepwatch:
            self._start_sleepwatch()
        elif not want_sleep and self.sleepwatch:
            self.sleepwatch.stop()
            self.sleepwatch = None
        self._current_wallpaper = None        # re-detect, which re-applies the restored picks
        self._last_sent = {}
        self._needs_update = True
        self._wake.set()

    def _cmd_freeze(self, req: dict) -> dict:
        on = (not self._frozen) if req.get("toggle") else bool(req.get("on", True))
        if on != self._frozen:
            self._frozen = on
            self.config.set("color.frozen", on)
            self.logger.info("Colors frozen: wallpaper changes are ignored until you unfreeze" if on
                             else "Colors unfrozen: following the wallpaper again")
            self._needs_update = True
        return {"ok": True, "frozen": self._frozen}

    def _zone_exists(self, dev, zone) -> bool:
        cfg = self.config.devices.get(dev)
        if cfg is None:
            return False
        zones = cfg.get("zones")
        return (zone in zones) if zones else not zone

    # ------------------------------------------------------------- keybinds
    def _zone_targets(self) -> List[dict]:
        """Every zone with the names you can call it by (for `iridia zone list`)."""
        out = []
        for dev, zname, zcfg in self._iter_zone_targets(self.config.devices_view):
            if not isinstance(zcfg, dict):
                continue
            out.append({"key": self._zone_key(dev, zname), "device": dev, "zone": zname,
                        "name": zcfg.get("display_name") or zname or dev,
                        "enabled": bool(zcfg.get("enabled", True))})
        return out

    def _resolve_target(self, target: str):
        """(zone keys, error). Accepts "all", a strip's name (as renamed in the window), its zone
        name, "Device/Zone", "Device|Zone" or a device name (all its zones). Case doesn't matter."""
        t = str(target or "").strip()
        if not t:
            return [], "say which strip, or 'all'"
        zones = self._zone_targets()
        if t.lower() == "all":
            return [z["key"] for z in zones], None
        low = t.lower()
        for sep in ("|", "/"):
            if sep in t:
                d, _, z = t.partition(sep)
                hit = [x["key"] for x in zones if x["device"].lower() == d.strip().lower()
                       and x["zone"].lower() == z.strip().lower()]
                if hit:
                    return hit, None
        for field in ("name", "zone"):
            hit = [x for x in zones if x[field] and x[field].lower() == low]
            if len(hit) == 1:
                return [hit[0]["key"]], None
            if len(hit) > 1:
                return [], (f"'{t}' matches {len(hit)} strips: "
                            + ", ".join(f"'{x['device']}/{x['zone']}'" for x in hit)
                            + ". Use 'Device/Zone', or give the strips their own names in the window.")
        hit = [x["key"] for x in zones if x["device"].lower() == low]
        if hit:
            return hit, None
        names = sorted({x["name"] for x in zones})
        return [], f"no strip called '{t}'. Known names: {', '.join(names) or 'none yet'} (or 'all')"

    @staticmethod
    def _overlay_text(ov: Optional[dict]) -> str:
        if not ov:
            return "back to normal"
        parts = []
        if ov.get("power"):
            parts.append(ov["power"])
        if ov.get("hex"):
            parts.append(f"#{ov['hex']}")
        if ov.get("bright") is not None:
            parts.append(f"{ov['bright']}% brightness")
        if "effect" in ov:
            parts.append(f"effect {ov['effect']['effect'] if ov['effect'] else 'static'}")
        return ", ".join(parts)

    @staticmethod
    def _parse_overlay(req: dict):
        """(overlay or None for "normal", error). Takes `actions` (a list like
        ["on", "color", "ff0000", "bright", "40"]) or the older single `action` + `value`."""
        tokens = req.get("actions")
        if tokens is None:
            tokens = [req.get("action")] + ([req.get("value")] if req.get("value") not in (None, "") else [])
        tokens = [str(t).strip() for t in tokens if t is not None and str(t).strip() != ""]
        if not tokens:
            return None, "say what to do: on, off, color HEX, bright PERCENT or normal"
        ov, i = {}, 0
        while i < len(tokens):
            t = tokens[i].lower()
            if t == "normal":
                if len(tokens) > 1:
                    return None, "'normal' can't be combined with other actions"
                return None, None
            if t == "effect":
                if i + 1 >= len(tokens):
                    return None, "'effect' needs a name: " + ", ".join(animations.ORDER) + " or static"
                name = tokens[i + 1].lower().replace("-", "_").replace(" ", "_")
                i += 2
                settings = {}
                while i < len(tokens) and "=" in tokens[i]:
                    k, _, v = tokens[i].partition("=")
                    v = v.strip()
                    settings[k.strip().lower()] = (v.lower() in ("1", "true", "yes", "on") if v.lower() in (
                        "1", "0", "true", "false", "yes", "no", "on", "off") and k.strip().lower() in (
                        "bounce", "reverse", "cycle_colors", "follow_layout", "sync") else v)
                    i += 1
                if name == "static":
                    ov["effect"] = None
                    continue
                anim = animations.clean(dict(settings, effect=name))
                if anim is None:
                    return None, f"no effect called '{name}': " + ", ".join(animations.ORDER) + " or static"
                ov["effect"] = anim
                continue
            if t in ("on", "off"):
                if ov.get("power") and ov["power"] != t:
                    return None, "use either on or off, not both"
                ov["power"] = t
                i += 1
                continue
            if t in ("color", "colour", "bright", "brightness"):
                if i + 1 >= len(tokens):
                    return None, f"'{t}' needs a value"
                v = tokens[i + 1]
                if t in ("color", "colour"):
                    h = normalize_hex(v)
                    if not h:
                        return None, f"'{v}' isn't a color, use a hex like ff0000"
                    ov["hex"] = h
                else:
                    try:
                        n = int(float(v.rstrip("%")))
                    except ValueError:
                        return None, "brightness must be 0 to 100"
                    if not 0 <= n <= 100:
                        return None, "brightness must be 0 to 100"
                    ov["bright"] = n
                i += 2
                continue
            # a bare hex or percentage is accepted too: "on ff0000 40%"
            if t.endswith("%") and t[:-1].isdigit() and "bright" not in ov:
                n = int(t[:-1])
                if n > 100:
                    return None, "brightness must be 0 to 100"
                ov["bright"] = n
                i += 1
                continue
            if normalize_hex(t) and "hex" not in ov:
                ov["hex"] = normalize_hex(t)
                i += 1
                continue
            return None, f"don't know '{tokens[i]}': use on, off, color HEX, bright PERCENT or normal"
        if "effect" in ov and ("hex" in ov or ov.get("power") == "off"):
            return None, "an effect can't be combined with a color or off"
        if ov.get("power") == "off" and ("hex" in ov or "bright" in ov):
            return None, "a strip that is off shows no color or brightness: drop 'off', or use 'on'"
        return ov, None

    def _cmd_zone_action(self, req: dict) -> dict:
        """A keybind: any mix of on/off, one color and a brightness for one or more strips, or back
        to normal. With toggle (the default) running the same thing again puts them back."""
        targets = req.get("target")
        if isinstance(targets, (list, tuple)):
            parts = [str(t) for t in targets]
        else:
            t = str(targets or "")
            keys, err = self._resolve_target(t)
            # "Desk back, Monitor": several strips (unless the whole text is one strip's name)
            parts = [t] if not err or "," not in t else [p.strip() for p in t.split(",") if p.strip()]
        keys = []
        for part in parts:
            ks, err = self._resolve_target(part)
            if err:
                return {"ok": False, "error": err}
            keys += [k for k in ks if k not in keys]
        if not keys:
            return {"ok": False, "error": "no strips to change"}
        new, err = self._parse_overlay(req)
        if err:
            return {"ok": False, "error": err}
        if req.get("save"):
            # `--save`: make the effect the zones' own setting instead of a temporary keybind change
            if not new or set(new) != {"effect"}:
                return {"ok": False, "error": "--save works with 'effect NAME' only"}
            devices = self.config.get("devices", {})
            for k in keys:
                d, z = k.split("|", 1)
                target = devices[d]["zones"][z] if z and devices[d].get("zones") else devices[d]
                target["animation"] = new["effect"]
                self._overlays.pop(k, None)
            self.config.set("devices", devices)
            self._needs_update = True
            what = new["effect"]["effect"] if new["effect"] else "static"
            self.logger.info(f"Effect {what} saved for {len(keys)} strip(s) ({targets})")
            return {"ok": True, "message": f"Effect {what} saved for {len(keys)} strip(s)."}
        if new is not None and req.get("toggle", True) and all(self._overlays.get(k) == new for k in keys):
            new = None                       # same key pressed again: back to normal
        for k in keys:
            if new is None:
                self._overlays.pop(k, None)
            else:
                self._overlays[k] = dict(new)
        what = self._overlay_text(new)
        self.logger.info(f"Keybind: {len(keys)} strip(s) {what} ({targets})")
        self._last_sent = {}
        self._needs_update = True
        self._wake.set()
        return {"ok": True, "state": "normal" if new is None else "changed", "zones": len(keys),
                "message": f"{', '.join(parts)}: {what}"}

    # ---------------------------------------------------------- strip types
    def _real_zone_type(self, device: str, zone: str) -> Optional[int]:
        """OpenRGB zone type: 0 single (one colour), 1 linear, 2 matrix; None if unknown."""
        dev = self.openrgb.devices.get(device) if self.openrgb.devices else None
        if dev is None or not zone:
            return None
        for zn, z in zones_of(dev):
            if zn == zone:
                try:
                    return int(getattr(z, "type", None))
                except (TypeError, ValueError):
                    return None
        return None

    def _strip_type(self, device: str, zone: str, zcfg: dict) -> str:
        t = zcfg.get("strip_type")
        if t in STRIP_TYPES:
            return t
        real = self._real_zone_size(device, zone)
        if self._real_zone_type(device, zone) == 0 or real == 1:
            return "single"
        return "addressable"

    @staticmethod
    def _merge_animation(current, anim: Optional[dict], given) -> Optional[dict]:
        """Keep the zone's other settings for the same effect; a new effect starts from its defaults."""
        if anim is None:
            return None
        cur = animations.clean(current)
        if cur and cur["effect"] == anim["effect"] and isinstance(given, dict):
            return animations.clean(dict(cur, **{k: v for k, v in given.items() if k != "effect"}))
        return anim

    def _cmd_set_zone_animation(self, req: dict) -> dict:
        """Set (or clear, with "static" or null) a zone's effect: {"effect": ..., settings...}."""
        dev, zone = req.get("device"), req.get("zone") or ""
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        given = req.get("animation")
        if isinstance(given, str):
            given = {"effect": given}
        anim = None if given in (None, {}) or (isinstance(given, dict) and given.get("effect") in (None, "static")) \
            else animations.clean(given)
        if given not in (None, {}) and isinstance(given, dict) and given.get("effect") not in (None, "static") \
                and anim is None:
            return {"ok": False, "error": f"unknown effect {given.get('effect')!r}; use one of: "
                                          + ", ".join(animations.ORDER) + " or static"}
        path = self._zone_config_path(dev, zone, "animation")
        merged = self._merge_animation(self.config.get(path), anim, given)
        self.config.set(path, merged)
        self.logger.info(f"Effect on {self._zone_key(dev, zone)}: {merged['effect'] if merged else 'static'}")
        self._needs_update = True
        return {"ok": True, "animation": merged}

    def _cmd_animations(self, req: dict) -> dict:
        """pause / resume / toggle (until the daemon restarts), or save settings: enabled, fps,
        night_pause, night_slow."""
        action = req.get("action")
        if action in ("pause", "resume", "toggle"):
            self._anim_hold = (not self._anim_hold) if action == "toggle" else action == "pause"
            self.logger.info("Animations paused" if self._anim_hold else "Animations resumed")
            self._needs_update = True
            return {"ok": True, "paused": self._anim_hold}
        if action:
            return {"ok": False, "error": "use pause, resume or toggle"}
        changed = {}
        if "enabled" in req:
            changed["enabled"] = bool(req["enabled"])
        if "fps" in req:
            if req["fps"] not in (15, 30, 60):
                return {"ok": False, "error": "fps must be 15, 30 or 60"}
            changed["fps"] = req["fps"]
        for k in ("night_pause", "night_slow"):
            if k in req:
                changed[k] = bool(req[k])
        for k, v in changed.items():
            self.config.set(f"animations.{k}", v)
        self._anim_cfg = self._anim_settings()
        if changed:
            self.logger.info(f"Animation settings: {changed}")
        self._needs_update = True
        return {"ok": True, "settings": self._anim_settings()}

    def _cmd_set_zone_strip(self, req: dict) -> dict:
        dev, zone = req.get("device"), req.get("zone") or ""
        if not self._zone_exists(dev, zone):
            return {"ok": False, "error": f"zone '{dev}/{zone}' not found"}
        changes = {}
        if "strip_type" in req:
            t = req["strip_type"]
            if t not in STRIP_TYPES and t not in (None, "auto"):
                return {"ok": False, "error": f"strip type must be one of {', '.join(STRIP_TYPES)} or auto"}
            changes["strip_type"] = None if t in (None, "auto") else t
        if "color_order" in req:
            co = str(req["color_order"]).upper()
            if co not in COLOR_ORDERS:
                return {"ok": False, "error": f"color order must be one of {', '.join(COLOR_ORDERS)}"}
            changes["color_order"] = co
        if "session_ignore" in req:            # stays lit when the screen locks or you're away
            changes["session_ignore"] = True if req["session_ignore"] else None
        for key, lo, hi in (("leds_per_pixel", 1, 20), ("power_limit", 0, 100), ("ma_per_led", 1, 500)):
            if key in req:
                try:
                    v = float(req[key])
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"{key} must be a number"}
                if not lo <= v <= hi:
                    return {"ok": False, "error": f"{key} must be {lo} to {hi}"}
                changes[key] = int(v) if key == "leds_per_pixel" else v
        for key, v in changes.items():
            path = self._zone_config_path(dev, zone, key)
            if v is None:
                devices = self.config.get("devices", {})
                target = devices.get(dev, {})
                target = (target.get("zones") or {}).get(zone, target) if zone else target
                target.pop(key, None)
                self.config.set("devices", devices)
            else:
                self.config.set(path, v)
        self.logger.info(f"Strip settings for {dev}/{zone or '(whole device)'}: {changes}")
        self._last_sent = {}
        self._needs_update = True
        self._wake.set()
        return {"ok": True}

    def _cmd_test_colors(self, req: dict) -> dict:
        if req.get("off"):
            self._rgbtest = None
        else:
            dev, zone = req.get("device"), req.get("zone") or ""
            if not self._zone_exists(dev, zone):
                return {"ok": False, "error": f"zone '{dev}/{zone}' not found"}
            self._rgbtest = (dev, zone, time.time() + 60)
        self._last_sent = {}
        self._needs_update = True
        return {"ok": True}

    def _finish(self, key: str, device: str, zone: str, zcfg: dict, colors: List[str]) -> List[str]:
        """Last steps before sending, whatever made the colours: power limit, channel order,
        RGBW packing. Also records what the window shows about the strip."""
        stype = self._strip_type(device, zone, zcfg)
        info = {"type": stype, "auto": "strip_type" not in zcfg}
        if stype != "single" and colors:
            per = zcfg.get("ma_per_led", 60) / 3.0 / 255.0          # mA per channel step
            want = sum(int(c[0:2], 16) + int(c[2:4], 16) + int(c[4:6], 16) for c in colors) * per / 1000.0
            info.update(amps=round(want, 2), full_amps=round(len(colors) * zcfg.get("ma_per_led", 60) / 1000.0, 2))
            limit = zcfg.get("power_limit", 0)
            if limit and want > limit:
                f = limit / want
                colors = ["%02x%02x%02x" % tuple(int(int(c[i:i + 2], 16) * f) for i in (0, 2, 4)) for c in colors]
                info.update(limited=True, amps=round(limit, 2), wanted_amps=round(want, 2))
        order = zcfg.get("color_order", "RGB")
        if order != "RGB":
            colors = [reorder(c, order) for c in colors]
        if stype == "rgbw":
            colors = pack_rgbw(colors)
            real = self._real_zone_size(device, zone)
            if real is not None and real < len(colors):
                info["needs_size"] = len(colors)
        self._strip_info[key] = info
        return colors

    def _cmd_identify(self, req: dict) -> dict:
        if req.get("off"):
            self._identify = None
        else:
            dev, zone = req.get("device"), req.get("zone") or ""
            if not self._zone_exists(dev, zone):
                return {"ok": False, "error": f"zone '{dev}/{zone}' not found"}
            secs = int(_num(req.get("seconds", 60), 60, 5, 600))
            self._identify = (dev, zone, time.time() + secs)
            self._probe = None
            self.logger.info(f"Identify: lighting only {dev}/{zone or '(whole device)'} for {secs}s")
        self._last_sent = {}
        self._needs_update = True
        return {"ok": True}

    def _cmd_led_probe(self, req: dict) -> dict:
        if req.get("off"):
            self._probe = None
        else:
            dev, zone = req.get("device"), req.get("zone") or ""
            if not self._zone_exists(dev, zone):
                return {"ok": False, "error": f"zone '{dev}/{zone}' not found"}
            try:
                idx = int(req.get("index", 0))
            except (TypeError, ValueError):
                return {"ok": False, "error": "index must be a number"}
            if not 0 <= idx < 2000:
                return {"ok": False, "error": "index out of range"}
            self._probe = (dev, zone, idx, time.time() + 120)
            self._identify = None
        self._last_sent = {}
        self._needs_update = True
        return {"ok": True, "zone_size": self._real_zone_size(req.get("device"), req.get("zone") or "")}

    def _cmd_resize_zone(self, req: dict) -> dict:
        """Change how many LEDs OpenRGB drives on an addressable header (and our count)."""
        dev, zone = req.get("device"), req.get("zone") or ""
        try:
            size = int(req.get("size"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "size must be a number"}
        if not 1 <= size <= 1000:
            return {"ok": False, "error": "size must be 1 to 1000"}
        err = self.openrgb.resize_zone(dev, zone, size)
        if err:
            return {"ok": False, "error": err}
        if self._zone_exists(dev, zone) and not req.get("keep_count"):
            self.config.set(self._zone_config_path(dev, zone, "led_count"), size)
            if self._zone_cfg(dev, zone).get("unsized"):
                # Sized at last: switch on the zone we switched off for having no size.
                self.config.set(self._zone_config_path(dev, zone, "enabled"), True)
                self.config.set(self._zone_config_path(dev, zone, "unsized"), False)
        self._last_sent = {}
        self._needs_update = True
        self.logger.info(f"Resized OpenRGB zone {dev}/{zone} to {size} LEDs")
        return {"ok": True, "zone_size": self._real_zone_size(dev, zone)}

    def _cmd_lights(self, req: dict) -> dict:
        on = self._lights_off if req.get("toggle") else bool(req.get("on", True))
        self._lights_off = not on
        self.logger.info("Lights on" if on else "Lights off")
        self._last_sent = {}
        self._needs_update = True
        return {"ok": True, "lights_off": self._lights_off}

    def _cmd_reset_detection(self) -> dict:
        self.detector.reset_cache()
        self._current_wallpaper = None     # re-detect (and re-extract from cache) next tick
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_wallpaper_color(self, req: dict) -> dict:
        if not self._current_wallpaper:
            return {"ok": False, "error": "no wallpaper detected yet"}
        if "hex" in req:
            h = str(req["hex"]).lstrip("#").lower()
            if len(h) != 6 or any(c not in "0123456789abcdef" for c in h):
                return {"ok": False, "error": f"invalid hex color: {req['hex']}"}
            choice = {"hex": h}
        elif "index" in req:
            idx = req["index"]
            if not isinstance(idx, int) or not 0 <= idx < len(self._extracted_colors):
                return {"ok": False, "error": f"color index {idx} out of range"}
            choice = {"index": idx}
        else:
            choice = None  # back to automatic
        self.wallcache.set_choice(self._current_wallpaper, choice)
        entry = self._choice_entry(choice)
        if entry is None:
            # back to automatic: forget this wallpaper's picks, every zone follows the wallpaper again
            self.wallcache.forget(self._current_wallpaper)
            devices = self.config.get("devices", {})
            for _d, _z, target in self._iter_zone_targets(devices):
                target["pattern_colors"] = self._automatic(target.get("pattern_colors"))
            self.config.set("devices", devices)
            self._last_sent = {}
            self._needs_update = True
        else:
            self._set_all_field("pattern_colors", [entry], record=True)
        self.logger.info(f"Color for {os.path.basename(self._current_wallpaper)} applied to all zones: "
                         f"{choice if choice else 'automatic'}")
        return {"ok": True}

    def _follows_monitor(self) -> bool:
        """Some switched-on zone follows the monitor (only then is ddcutil asked, every few seconds)."""
        for dev in self.config.devices_view.values():
            if not isinstance(dev, dict) or not dev.get("enabled", True):
                continue
            zones = dev.get("zones")
            for z in (zones.values() if isinstance(zones, dict) and zones else [dev]):
                if isinstance(z, dict) and z.get("enabled", True) and z.get("brightness_sync", False):
                    return True
        return False

    def _shown_brightness(self) -> int:
        """The brightness the LEDs are at (the brightest switched-on zone), for the window's header."""
        best = None
        for dev in self.config.devices_view.values():
            if not isinstance(dev, dict) or not dev.get("enabled", True):
                continue
            zones = dev.get("zones")
            for z in (zones.values() if isinstance(zones, dict) and zones else [dev]):
                if isinstance(z, dict) and z.get("enabled", True):
                    b = self._get_zone_brightness(clean_zone_cfg(z))
                    best = b if best is None else max(best, b)
        return best if best is not None else 100

    def _read_brightness(self):
        if not self._follows_monitor():
            return
        brightness = self.ddc.get_brightness()
        if brightness is not None and brightness != self._current_brightness:
            self.logger.debug(f"Brightness changed: {self._current_brightness}% -> {brightness}%")
            self._current_brightness = brightness
            self._needs_update = True

    def _update_all_devices(self):
        devices_cfg = self.config.devices_view
        if not devices_cfg:
            self.logger.debug("No devices configured")
            self._needs_update = False
            return
        t = time.time() - self._start_time
        for name, dev_cfg in devices_cfg.items():
            self._update_device(name, dev_cfg, t)
        self._needs_update = False
        self._force_refresh = False

    def _update_device(self, name: str, dev_cfg: Dict[str, Any], t: float = 0.0):
        if not isinstance(dev_cfg, dict):
            return
        dev_off = not dev_cfg.get("enabled", True)
        zones = dev_cfg.get("zones")
        targets = ([(zn, zc) for zn, zc in zones.items() if isinstance(zc, dict)]
                   if isinstance(zones, dict) and zones else [("", dev_cfg)])
        for zname, zcfg in targets:
            # One broken zone (a hand-edited config, odd hardware) must not stop the others.
            try:
                self._update_zone(name, zname, clean_zone_cfg(zcfg), t,
                                  off=dev_off or (bool(zname) and not zcfg.get("enabled", True)))
                self._zone_errors.pop((name, zname), None)
            except Exception as e:      # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                if self._zone_errors.get((name, zname)) != msg:
                    self._zone_errors[(name, zname)] = msg
                    self.logger.exception(f"Couldn't update '{name}/{zname}': {msg}")

    def _snap_one(self, hex_color: str) -> str:
        """Palette colour for an intended colour (cached)."""
        hit = self._snap_cache.get(hex_color)
        if hit is None:
            hit = self.palette.snap(hex_color)
            if len(self._snap_cache) > 4096:
                self._snap_cache.clear()
            self._snap_cache[hex_color] = hit
        return hit

    def _update_zone(self, device_name: str, zone_name: str, zcfg: Dict[str, Any], t: float = 0.0,
                     off: bool = False):
        pattern = PatternGenerator.normalize(zcfg.get("pattern", "solid"))
        params = zcfg.get("pattern_params") or {}
        led_count = zcfg.get("led_count", 20)
        key = f"{device_name}|{zone_name}"
        if not off and self._anim_owns(key, device_name, zone_name):
            return                          # the animation thread sends this zone
        if self._strip_type(device_name, zone_name, zcfg) == "single":
            pattern = "solid"                 # one colour for the whole strip: patterns mean nothing
        mode = zcfg.get("mode", self.config.color_mode)       # full (off) | palette | calibrated
        brightness = None
        exact = False                                        # send the colours untouched
        levels = None                                        # sensor parts: each LED's level, applied last

        override = self._override_colors(device_name, zone_name, led_count)
        ov = self._overlays.get(key) or {}
        power = ov.get("power")
        if override is not None:
            final_colors = override
            brightness = 100
            exact = True
        elif power == "off":
            final_colors = ["000000"] * led_count
            brightness = 0
            exact = True
        elif off and power != "on":         # only "on" lights a strip that is switched off
            final_colors = ["000000"] * led_count
            brightness = 0
            exact = True
        elif self._preview_hex and self._preview_raw:
            final_colors = [self._preview_hex] * led_count   # calibration tuning: exactly this hex
            exact = True
        elif self._preview_hex:
            final_colors = [self._preview_hex] * led_count
        elif ov.get("hex"):
            final_colors = [ov["hex"]] * led_count
        else:
            colors = resolve_colors(zcfg.get("pattern_colors", [0]), self._extracted_colors)
            if not colors:
                colors = [self._extracted_colors[0]] if self._extracted_colors else ["642107"]
            if self._zone_animation(key, zcfg) is not None:
                # animated, but animations are off or paused right now: the first color, still
                final_colors = [colors[0]] * led_count
            else:
                final_colors = self.patterns.generate(pattern, colors, led_count, params=params)
            if not final_colors:
                return
            if zcfg["sections"] or zcfg["led_overrides"]:
                if self._strip_type(device_name, zone_name, zcfg) != "single":
                    levels = [1.0] * len(final_colors)
                    final_colors = zone_sections.compose_static(
                        final_colors, zcfg["sections"], zcfg["led_overrides"],
                        lambda e: resolve_colors(e, self._extracted_colors), self.patterns,
                        self.sensors.value, time.monotonic(), levels)

        if not exact:
            brightness = int(round(self._brightness_now(key, zcfg)))
            if ov.get("bright") is not None:
                brightness = ov["bright"]
            # Colours you marked "exact" in the colour picker skip every correction: those
            # LEDs get the hex you picked, only scaled by brightness.
            keep = self.custom_colors.exact_set()
            if self._preview_hex and self._preview_exact:
                keep = keep | {self._preview_hex}
            plain = [c in keep for c in final_colors] if keep else [False] * len(final_colors)
            if mode == "palette":
                # Snapped exactly once, on the finished LEDs: blends between two
                # palette colours are not palette colours, and the palette is
                # hue-bucketed, so snapping twice would shift hues.
                final_colors = [c if p else self._snap_one(c) for c, p in zip(final_colors, plain)]
            if mode == "calibrated":
                # Brightness goes in as the colour's value so dim colours keep
                # their hue; gamma is skipped (the profile already covers it).
                prof = self.calibration.get(zcfg.get("calibration_profile"))
                final_colors = [self._scale_brightness(c, brightness) if p else prof.correct(c, brightness)
                                for c, p in zip(final_colors, plain)]
            else:
                if zcfg.get("gamma_correction", False):
                    gamma = zcfg.get("gamma_value", 2.2)
                    final_colors = [c if p else self._gamma_correct(c, gamma) for c, p in zip(final_colors, plain)]
                final_colors = [self._scale_brightness(c, brightness) for c in final_colors]
            if levels is not None and min(levels, default=1.0) < 1.0:
                # after correction: Palette snaps a dim color to a full one, gamma lifts it
                final_colors = [c if f >= 1.0 else self._scale_level(c, f) for c, f in zip(final_colors, levels)]

        self._static_pre[key] = [animations.hex_to_rgb(c) for c in final_colors]
        final_colors = self._finish(key, device_name, zone_name, zcfg, final_colors)
        # an animated zone's neighbours are sent with its frames (one packet per device)
        self._static_rgb[key] = [animations.hex_to_rgb(c) for c in final_colors]
        color_hash = "".join(final_colors)
        if self._last_sent.get(key) == color_hash:
            return

        # `enabled` is forced on in what the sender sees: turning a zone
        # off means sending black, and the sender skips disabled zones.
        send_cfg = dict(zcfg, enabled=True)
        zones_config = {zone_name: send_cfg} if zone_name else None
        if self.openrgb.send(device_name, final_colors, zones_config):
            self._last_sent[key] = color_hash
            self.logger.debug(f"Sent to '{device_name}/{zone_name}' | pattern={pattern} | mode={mode} | "
                              f"brightness={brightness}% | LEDs={len(final_colors)}{' | off' if off else ''}")
        # else: openrgb.send() already logged exactly why.

    # ------------------------------------------------------------- animations
    GLIDE_SEC = 0.3              # brightness changes glide over this long instead of jumping

    def _anim_settings(self) -> dict:
        a = self.config.get("animations", {}) or {}
        return {"enabled": bool(a.get("enabled", True)), "fps": a.get("fps", 30) if a.get("fps") in (15, 30, 60) else 30,
                "night_pause": bool(a.get("night_pause", False)), "night_slow": bool(a.get("night_slow", False))}

    def _zone_animation(self, key: str, zcfg: dict) -> Optional[dict]:
        """The zone's effect (a keybind's effect wins), or None for a static pattern."""
        ov = self._overlays.get(key) or {}
        if "effect" in ov:
            return animations.clean(ov["effect"]) if ov["effect"] else None
        a = zcfg.get("animation")
        return a if isinstance(a, dict) and a.get("effect") in animations.EFFECTS else animations.clean(a)

    def _anim_blocked(self, device: str, zone: str, key: str) -> bool:
        """Something else shows on this zone right now: lights off, sleep, identify, Count LEDs,
        Test colors, a color preview, a keybind's color/brightness/power, or animations paused."""
        if self._lights_off or self._asleep or self._preview_hex or self._anim_hold:
            return True
        if self._identify or self._probe:
            return True
        test = self._rgbtest
        if test and (test[0], test[1] or "") == (device, zone or ""):
            return True
        ov = self._overlays.get(key)
        if ov and ("power" in ov or "hex" in ov):
            return True                     # a keybind's brightness alone keeps the animation
        s = self._anim_cfg
        return not s["enabled"] or (self._night_active and s["night_pause"])

    def _anim_owns(self, key: str, device: str, zone: str) -> bool:
        if key in self._flash_keys:
            return not self._flash_blocked(device, zone, key)
        return key in self._anim_keys and not self._anim_blocked(device, zone, key)

    def _brightness_now(self, key: str, zcfg: dict) -> float:
        """The zone's brightness, faded down while the screen is locked or you're away (unless the
        zone ignores that)."""
        b = self._brightness_glide(key, zcfg)
        return b if zcfg.get("session_ignore") else b * self._session_factor()

    def _brightness_glide(self, key: str, zcfg: dict) -> float:
        """The zone's brightness (monitor or manual, range, invert, night cap), gliding to a new
        value over GLIDE_SEC instead of jumping."""
        target = float(self._get_zone_brightness(zcfg))
        now = time.monotonic()
        g = self._glide.get(key)
        if g is None:
            self._glide[key] = (target, target, now)
            return target
        frm, to, start = g
        k = min(1.0, (now - start) / self.GLIDE_SEC)
        cur = frm + (to - frm) * k
        if target != to:
            self._glide[key] = (cur, target, now)
            self._glide_active = True
            return cur
        if k < 1.0:
            self._glide_active = True
        return cur

    def _layout_points(self, key: str, n: int):
        """(points of each LED as sent, LED spacing) from the Layout tab, or None."""
        from iridia import layout as lay
        try:
            mtime = os.path.getmtime(lay.PATH)
        except OSError:
            return None
        if self._layout is None or mtime != self._layout_mtime:
            self._layout = lay.Layout(lay.PATH)
            self._layout_mtime = mtime
        strip = next((s for s in self._layout.strips if s["zone"] == key and not s["clone"]), None)
        if strip is None or n <= 0:
            return None
        return lay.led_points(strip, n), strip["segments"][0]["spacing"]

    def _refresh_animations(self, connected: bool):
        """Work out which zones animate and hand them to the animation thread. Jobs are only rebuilt
        when something they depend on changed, so per-frame caches survive."""
        s = self._anim_cfg = self._anim_settings()
        self._night_cap = self._night_settings()["cap"]
        jobs_by_dev: Dict[str, tuple] = {}
        keys, seen = set(), set()
        flash_on = set(self._flash.ranges) if self._flash is not None else set()
        flash_keys = set()
        if connected:
            real = {d["name"]: [z["name"] for z in d["zones"]] for d in self.openrgb.list_devices()}
            layout_groups: Dict[tuple, list] = {}
            plan = []
            for dev, dev_cfg in self.config.devices_view.items():
                if not isinstance(dev_cfg, dict) or not dev_cfg.get("enabled", True) or dev not in real:
                    continue
                zones = dev_cfg.get("zones")
                targets = ([(zn, zc) for zn, zc in zones.items() if isinstance(zc, dict)]
                           if isinstance(zones, dict) and zones else [("", dev_cfg)])
                for zn, raw in targets:
                    if zn and not raw.get("enabled", True):
                        continue
                    key = self._zone_key(dev, zn)
                    zc = clean_zone_cfg(raw)
                    anim = self._zone_animation(key, zc)
                    still = anim is None and not (zone_sections.has_effects(zc["sections"])
                                                  and self._strip_type(dev, zn, zc) != "single")
                    if key in flash_on and (still or (self._anim_blocked(dev, zn, key)
                                                      and not self._flash_blocked(dev, zn, key))):
                        plan.append((dev, zn, key, zc, "flash", None))   # static (or paused): flashed
                        continue
                    if still:
                        continue
                    n = zc["led_count"]
                    pts = self._layout_points(key, n) if anim and anim["follow_layout"] else None
                    plan.append((dev, zn, key, zc, anim, pts))
                    if pts:
                        layout_groups.setdefault((anim["effect"], anim["angle"]), []).append(pts)
            # one extent per (effect, direction) for every strip that follows the layout
            extents = {}
            for g, items in layout_groups.items():
                xs = [p for pts, sp in items for p in animations.layout_positions(pts, g[1], sp)]
                extents[g] = (min(xs), max(1.0, max(xs) - min(xs) + 1)) if xs else None
            for dev, zn, key, zc, anim, pts in plan:
                if anim == "flash":
                    job = self._flash_job(dev, zn, key, zc)
                    self._anim_jobs[key] = ("flash", job)
                    seen.add(key)
                    keys.add(key)
                    flash_keys.add(key)
                    jobs_by_dev.setdefault(dev, []).append(job)
                    continue
                ext = extents.get((anim["effect"], anim["angle"])) if pts and anim else None
                sig = repr((zc, anim, pts, ext, self._extracted_colors, sorted(self.custom_colors.exact_set()),
                            self.config.color_mode, self._real_zone_size(dev, zn)))
                old = self._anim_jobs.get(key)
                job = old[1] if old and old[0] == sig else self._make_job(dev, zn, key, zc, anim, pts, ext)
                self._anim_jobs[key] = (sig, job)
                seen.add(key)
                keys.add(key)
                jobs_by_dev.setdefault(dev, []).append(job)
            out = {}
            for dev, jobs in jobs_by_dev.items():
                order = real.get(dev, [])
                whole = bool(order) and all(j.zone for j in jobs)
                if whole:
                    # Always one packet for the whole device: OpenRGB queues zone updates one by
                    # one, and a controller slower than the frame rate then falls behind by
                    # minutes; whole-device updates are merged (only the latest is written). The
                    # zones that don't animate go along with what the static path shows on them.
                    have = {j.zone for j in jobs}
                    for zn in order:
                        if zn not in have:
                            jobs.append(self._static_job(dev, zn))
                jobs.sort(key=lambda j: order.index(j.zone) if j.zone in order else 999)
                out[dev] = (whole, jobs)
            jobs_by_dev = out
        for k in list(self._anim_jobs):
            if k not in seen:
                del self._anim_jobs[k]
        stopped = (self._anim_keys - keys) | (self._flash_keys - flash_keys)
        self._flash_keys = flash_keys
        if stopped:
            for k in stopped:
                self._last_sent.pop(k, None)    # back to the static pattern: send it again
            self._needs_update = True
        self._anim_keys = keys
        rate = 0.5 if (self._night_active and s["night_slow"]) else 1.0
        self._animator.set_jobs(jobs_by_dev, s["fps"], rate)

    def _static_job(self, dev: str, zn: str) -> Job:
        """A zone that doesn't animate on a device that does: its static colours, so the whole
        device can go in one packet."""
        key = self._zone_key(dev, zn)
        n = self._real_zone_size(dev, zn) or 0

        def frame(clock: float):
            cols = self._static_rgb.get(key)
            return cols if cols is not None else self.openrgb.zone_rgb(dev, zn)
        return Job(key, dev, zn, n, frame, None)

    def _flash_job(self, dev: str, zn: str, key: str, zc: dict) -> Job:
        """A zone the static path shows (or a paused animation), sent as frames while a
        notification flashes on it."""
        n = self._real_zone_size(dev, zn) or zc["led_count"]

        def frame(clock: float):
            pre = self._static_pre.get(key)
            if pre is None or self._flash_blocked(dev, zn, key):
                return None
            return self._finish_rgb(key, dev, zn, zc, pre)
        return Job(key, dev, zn, n, frame, None)

    def _make_job(self, dev: str, zn: str, key: str, zc: dict, anim: dict, pts, extent) -> Job:
        n = zc["led_count"]
        colors_hex = resolve_colors(zc.get("pattern_colors", [0]), self._extracted_colors) or \
            [self._extracted_colors[0] if self._extracted_colors else "642107"]
        colors = [animations.hex_to_rgb(c) for c in colors_hex]
        params = zc.get("pattern_params") or {}
        base_hex = self.patterns.generate(PatternGenerator.normalize(zc.get("pattern", "solid")), colors_hex, n,
                                          params=params) or [colors_hex[0]] * n
        base = [animations.hex_to_rgb(c) for c in base_hex]
        import zlib
        seed = zlib.crc32(key.encode()) ^ self._run_seed
        # parts of the strip with their own pattern or effect, and single LEDs set by hand
        parts = None
        if zc["sections"] or zc["led_overrides"]:
            parts = zone_sections.Composer(zc["sections"], zc["led_overrides"], n,
                                           lambda e: resolve_colors(e, self._extracted_colors), seed, self.patterns,
                                           self.sensors.value)
        if anim is None:
            # only parts of the strip move: the rest shows its static pattern
            correct = self._rgb_corrector(zc)
            real_n = self._real_zone_size(dev, zn) or n

            def still(clock: float):
                if self._anim_blocked(dev, zn, key):
                    return None
                ov = self._overlays.get(key) or {}
                b = ov["bright"] if ov.get("bright") is not None else self._brightness_now(key, zc)
                lv = [1.0] * n
                frame = correct(parts.frame(base, clock, lv), b)
                return self._finish_rgb(key, dev, zn, zc, self._levels_rgb(frame, lv))
            return Job(key, dev, zn, real_n, still, f"{len(parts.moving)} animated part(s)")
        if pts:
            positions = animations.layout_positions(pts[0], anim["angle"], pts[1])
        else:
            positions = animations.strip_positions(n, bool(params.get("reverse")), bool(params.get("mirror")))
        offset = 0.0 if anim["sync"] else (zlib.crc32(key.encode()) % 10000) / 100.0
        correct = self._rgb_corrector(zc)
        real_n = self._real_zone_size(dev, zn) or n
        step = 20 if anim["effect"] == "embers" else 0     # embers changes 20 times a second at most
        memo = [None, None]
        effect = anim["effect"]

        def frame(clock: float):
            if self._anim_blocked(dev, zn, key):
                return None
            t = clock + offset
            if step:
                tq = int(t * step)
                if memo[0] != tq:
                    memo[0], memo[1] = tq, animations.render(effect, anim, n, t, colors, seed, positions, base,
                                                             extent)
                raw = memo[1]
            else:
                raw = animations.render(effect, anim, n, t, colors, seed, positions, base, extent)
            lv = None
            if parts is not None:
                lv = [1.0] * n
                raw = parts.frame(raw, clock, lv)
            ov = self._overlays.get(key) or {}
            b = ov["bright"] if ov.get("bright") is not None else self._brightness_now(key, zc)
            out = correct(raw, b)
            return self._finish_rgb(key, dev, zn, zc, self._levels_rgb(out, lv) if lv else out)
        desc = ", ".join(f"{k}={v}" for k, v in anim.items())
        return Job(key, dev, zn, real_n, frame, desc)

    def _rgb_corrector(self, zc: dict):
        """A function (frame, brightness %) -> frame applying the zone's color correction the same way
        the static path does, with caches so a frame costs little: off (gamma, then brightness, from
        a 256 entry table), Palette (snap, then gamma and brightness) or Calibrated (the profile,
        which takes brightness itself). Colors marked exact only get brightness."""
        mode = zc.get("mode", self.config.color_mode)
        gamma = zc.get("gamma_value", 2.2) if zc.get("gamma_correction", False) else None
        exact = {animations.hex_to_rgb(h) for h in self.custom_colors.exact_set()}
        prof = self.calibration.get(zc.get("calibration_profile")) if mode == "calibrated" else None
        luts: Dict[tuple, list] = {}
        cache: Dict[tuple, tuple] = {}
        cache_b = [None]
        snaps: Dict[tuple, tuple] = {}      # palette snaps don't depend on brightness: kept

        def lut(b: int, g):
            key = (b, g)
            t = luts.get(key)
            if t is None:
                if len(luts) > 256:
                    luts.clear()
                t = [int((int(pow(v / 255.0, 1.0 / g) * 255) if g else v) * b / 100) for v in range(256)]
                luts[key] = t
            return t

        def correct(frame, brightness: float):
            b = int(round(brightness))
            plain = lut(b, None)
            if mode not in ("palette", "calibrated"):
                t = lut(b, gamma)
                if not exact:
                    return [(t[r], t[g], t[bb]) for r, g, bb in frame]
                return [(plain[c[0]], plain[c[1]], plain[c[2]]) if c in exact else (t[c[0]], t[c[1]], t[c[2]])
                        for c in frame]
            gt = lut(b, gamma)
            if mode == "palette":
                # The palette is coarse, so colors a step or two apart snap the same way: key the
                # cache on slightly rounded colors so fades and tails mostly hit it.
                if len(snaps) > 16384:
                    snaps.clear()
                out = []
                for c in frame:
                    if c in exact:
                        out.append((plain[c[0]], plain[c[1]], plain[c[2]]))
                        continue
                    q = (c[0] >> 2, c[1] >> 2, c[2] >> 2)
                    sn = snaps.get(q)
                    if sn is None:
                        sn = snaps[q] = animations.hex_to_rgb(self._snap_one(animations.rgb_to_hex(c)))
                    out.append((gt[sn[0]], gt[sn[1]], gt[sn[2]]))
                return out
            if cache_b[0] != b:
                cache.clear()
                cache_b[0] = b
            if len(cache) > 8192:
                cache.clear()
            out = []
            for c in frame:
                hit = cache.get(c)
                if hit is None:
                    if c in exact:
                        hit = (plain[c[0]], plain[c[1]], plain[c[2]])
                    else:
                        hit = animations.hex_to_rgb(prof.correct(animations.rgb_to_hex(c), b))
                    cache[c] = hit
                out.append(hit)
            return out
        return correct

    def _finish_rgb(self, key: str, device: str, zone: str, zcfg: dict, colors: list) -> list:
        """_finish for (r, g, b) frames: power limit, channel order, RGBW packing (and a
        notification flash, over what the zone shows)."""
        fl = self._flash
        if fl is not None and key in fl.ranges:
            colors = self._flash_mix(fl, key, zcfg, colors)
        stype = self._strip_type(device, zone, zcfg)
        limit = zcfg.get("power_limit", 0)
        now = time.monotonic()
        # the power estimate is only needed every frame when there is a limit; for the window's
        # display, once a second is plenty
        if stype != "single" and colors and (limit or now - self._power_shown.get(key, 0) >= 1.0):
            self._power_shown[key] = now
            per = zcfg.get("ma_per_led", 60) / 3.0 / 255.0
            want = sum(map(sum, colors)) * per / 1000.0
            info = {"type": stype, "auto": "strip_type" not in zcfg, "amps": round(want, 2),
                    "full_amps": round(len(colors) * zcfg.get("ma_per_led", 60) / 1000.0, 2)}
            if limit and want > limit:
                f = limit / want
                colors = [(int(r * f), int(g * f), int(b * f)) for r, g, b in colors]
                info.update(limited=True, amps=round(limit, 2), wanted_amps=round(want, 2))
            self._strip_info[key] = info
        order = zcfg.get("color_order", "RGB")
        if order != "RGB":
            idx = ["RGB".index(ch) for ch in order]
            colors = [(c[idx[0]], c[idx[1]], c[idx[2]]) for c in colors]
        if stype == "rgbw":
            colors = [animations.hex_to_rgb(h) for h in pack_rgbw([animations.rgb_to_hex(c) for c in colors])]
        return colors

    def _real_zone_size(self, device: str, zone: str) -> Optional[int]:
        """LED count OpenRGB reports for a zone (what can actually be addressed)."""
        dev = self.openrgb.devices.get(device) if self.openrgb.devices else None
        if dev is None:
            return None
        if not zone:
            return len(getattr(dev, "leds", None) or [])
        for zn, z in zones_of(dev):
            if zn == zone:
                return len(z.leds)
        return None

    def _override_colors(self, device: str, zone: str, led_count: int) -> Optional[List[str]]:
        """Colours that replace everything else: lights off, identify, LED counting."""
        if self._lights_off or self._asleep:
            return ["000000"] * led_count
        ident, probe, test = self._identify, self._probe, self._rgbtest   # IPC threads may clear them
        if test and (test[0], test[1] or "") == (device, zone or ""):
            n = max(1, led_count)
            if n < 3:
                return [("ff0000", "00ff00", "0000ff")[int(time.time()) % 3]] * n
            third = n / 3.0
            return [("ff0000", "00ff00", "0000ff")[min(2, int(i / third))] for i in range(n)]
        if not ident and not probe:
            return None
        size = max(led_count, self._real_zone_size(device, zone) or 0)
        if ident:
            d, z, _ = ident
            return ["ffffff"] * size if (d, z or "") == (device, zone or "") else ["000000"] * led_count
        if probe:
            d, z, idx, _ = probe
            if (d, z or "") != (device, zone or ""):
                return ["000000"] * led_count
            size = max(size, idx + 1)
            out = ["000000"] * size
            out[idx] = "ffffff"
            return out
        return None

    def _get_zone_brightness(self, zcfg: Dict[str, Any]) -> int:
        b = self._zone_brightness_raw(zcfg)
        if self._night_active:
            b = min(b, self._night_cap)
        return b

    def _zone_brightness_raw(self, zcfg: Dict[str, Any]) -> int:
        if not zcfg.get("brightness_sync", False) or not self.ddc.is_available():
            # nothing to follow (no ddcutil, no monitor answers, the chosen one is off): the Manual value
            return zcfg.get("manual_brightness", 100)
        brightness = self._current_brightness
        range_min, range_max = zcfg.get("brightness_range", [0, 100])
        invert = zcfg.get("invert_brightness", False)
        if invert:
            brightness = 100 - brightness
        scaled = int(brightness * (range_max - range_min) / 100 + range_min)
        return max(range_min, min(range_max, scaled))

    @staticmethod
    def _scale_level(hex_color: str, f: float) -> str:
        r, g, b = (int(int(hex_color[i:i + 2], 16) * f + 0.5) for i in (0, 2, 4))
        return f"{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _levels_rgb(frame: list, levels: list) -> list:
        if min(levels, default=1.0) >= 1.0:
            return frame
        return [c if f >= 1.0 else (int(c[0] * f + 0.5), int(c[1] * f + 0.5), int(c[2] * f + 0.5))
                for c, f in zip(frame, levels)]

    @staticmethod
    def _scale_brightness(hex_color: str, pct: int) -> str:
        r = int(int(hex_color[0:2], 16) * pct / 100)
        g = int(int(hex_color[2:4], 16) * pct / 100)
        b = int(int(hex_color[4:6], 16) * pct / 100)
        return f"{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _gamma_correct(hex_color: str, gamma: float = 2.2) -> str:
        r = int(pow(int(hex_color[0:2], 16) / 255.0, 1.0 / gamma) * 255)
        g = int(pow(int(hex_color[2:4], 16) / 255.0, 1.0 / gamma) * 255)
        b = int(pow(int(hex_color[4:6], 16) / 255.0, 1.0 / gamma) * 255)
        return f"{r:02x}{g:02x}{b:02x}"

    def handle_command(self, req: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self._dispatch(req)
        except ZoneNotFound as e:
            # A typo in a keybind or a zone OpenRGB renamed: tell the caller, not the error log.
            return {"ok": False, "error": str(e)}
        finally:
            if req.get("cmd") not in ("status", "ping"):
                self._wake.set()            # show a change now, not at the next half-second tick

    def _dispatch(self, req: Dict[str, Any]) -> Dict[str, Any]:
        cmd = req.get("cmd", "")
        if cmd == "ping":
            from iridia import get_version
            return {"ok": True, "version": get_version()}
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
        if cmd == "set_zone_enabled":
            return self._cmd_set_zone_enabled(req)
        if cmd == "set_zone_pattern":
            return self._cmd_set_zone_pattern(req)
        if cmd == "set_zone_pattern_params":
            return self._cmd_set_zone_pattern_params(req)
        if cmd == "set_zone_mode":
            return self._cmd_set_zone_mode(req)
        if cmd == "set_zone_name":
            return self._cmd_set_zone_name(req)
        if cmd == "set_zone_colors":
            return self._cmd_set_zone_colors(req)
        if cmd == "set_zone_led_count":
            return self._cmd_set_zone_led_count(req)
        if cmd == "ddc":
            return self._cmd_ddc(req)
        if cmd == "set_zone_brightness_sync":
            return self._cmd_set_zone_brightness_sync(req)
        if cmd == "set_zone_manual_brightness":
            return self._cmd_set_zone_manual_brightness(req)
        if cmd == "set_zone_brightness_range":
            return self._cmd_set_zone_brightness_range(req)
        if cmd == "set_zone_invert":
            return self._cmd_set_zone_invert(req)
        if cmd == "set_zone_gamma":
            return self._cmd_set_zone_gamma(req)
        if cmd == "set_all":
            return self._cmd_set_all(req)
        if cmd == "add_custom_color":
            return self._cmd_add_custom_color(req)
        if cmd == "remove_custom_color":
            return self._cmd_remove_custom_color(req)
        if cmd == "set_color_exact":
            h = normalize_hex(req.get("hex", ""))
            if not h:
                return {"ok": False, "error": f"invalid hex color: {req.get('hex')!r}"}
            if self.custom_colors.set_exact(h, bool(req.get("exact", True))):
                self.logger.info(f"#{h} {'is shown exactly as picked (no color correction)' if req.get('exact', True) else 'follows color correction again'}")
                self._last_sent = {}
                self._needs_update = True
            return {"ok": True, "exact_colors": self.custom_colors.exact()}
        if cmd == "get_log":
            try:
                n = max(1, min(500, int(req.get("lines", 20))))
            except (TypeError, ValueError):
                n = 20
            return {"ok": True, "lines": LOG_MEMORY.tail(n)}
        if cmd == "reload_calibration":
            self._last_sent = {}
            self._needs_update = True
            return {"ok": True}
        if cmd == "set_zone_calibration_profile":
            return self._cmd_set_zone_profile(req)
        if cmd == "preview_color":
            return self._cmd_preview_color(req)
        if cmd == "shutdown":
            self.logger.info("Shutdown requested over IPC")
            threading.Timer(0.2, lambda: self._on_signal(signal.SIGTERM, None)).start()
            return {"ok": True}
        if cmd == "freeze":
            return self._cmd_freeze(req)
        if cmd == "set_zone_strip":
            return self._cmd_set_zone_strip(req)
        if cmd == "session":
            return self._cmd_session(req)
        if cmd == "notify":
            return self._cmd_notify(req)
        if cmd == "sensors":
            return self._cmd_sensors(req)
        if cmd == "updates":
            return self._cmd_updates(req)
        if cmd == "set_zone_sections":
            return self._cmd_set_zone_sections(req)
        if cmd == "set_zone_animation":
            return self._cmd_set_zone_animation(req)
        if cmd == "animations":
            return self._cmd_animations(req)
        if cmd == "test_colors":
            return self._cmd_test_colors(req)
        if cmd == "zone_action":
            return self._cmd_zone_action(req)
        if cmd == "zone_targets":
            return {"ok": True, "targets": self._zone_targets()}
        if cmd == "identify":
            return self._cmd_identify(req)
        if cmd == "led_probe":
            return self._cmd_led_probe(req)
        if cmd == "resize_zone":
            return self._cmd_resize_zone(req)
        if cmd.startswith("setup_"):
            return self._cmd_setup(cmd, req)
        if cmd == "set_sleep":
            on = bool(req.get("lights_off", True))
            self.config.set("sleep.lights_off", on)
            if on and not self.sleepwatch:
                self._start_sleepwatch()
            elif not on and self.sleepwatch:
                self.sleepwatch.stop()
                self.sleepwatch = None
            return {"ok": True}
        if cmd == "set_night":
            return self._cmd_set_night(req)
        if cmd == "lights":
            return self._cmd_lights(req)
        if cmd == "reset_detection":
            return self._cmd_reset_detection()
        if cmd == "set_wallpaper_color":
            return self._cmd_set_wallpaper_color(req)
        if cmd == "forget_all_wallpaper_colors":
            n = self.wallcache.forget_all()
            self.logger.info(f"Forgot saved color picks for {n} wallpaper(s)")
            return {"ok": True, "wallpapers": n}
        if cmd == "clear_wallpaper_color":
            return self._cmd_set_wallpaper_color({})
        if cmd == "refresh_wallpaper":
            # Force a real re-check, not just a re-send of whatever
            # colors were already extracted — otherwise "Refresh" only
            # does something once the next tick happens to notice a
            # change on its own.
            self._current_wallpaper = None
            self._detect_wallpaper()
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
        if cmd == "reconnect_openrgb":
            self.logger.info("OpenRGB reconnect requested via IPC")
            self.openrgb.disconnect()
            self._device_missing_since = {}
            return {"ok": True}
        if cmd == "restart_openrgb_server":
            self.logger.info("OpenRGB server restart requested via IPC")
            self._device_missing_since = {}
            self._last_auto_restart = time.time()
            if not self._restart_openrgb_async("Restart requested", manual=True):
                return {"ok": False, "error": "openrgb.start_method is off: Iridia doesn't start or restart "
                                              "OpenRGB. Restart it yourself, or pick another method."}
            return {"ok": True, "status": "restarting"}
        if cmd == "quit":
            self.running = False
            return {"ok": True}
        return {"ok": False, "error": f"unknown command: {cmd}"}

    def _correction_preview(self) -> dict:
        """What the first active zone would send for each wallpaper colour
        (full brightness), so the Status tab can show the effect of the
        current colour correction."""
        zcfg = {}
        for dev in self.config.devices_view.values():
            if not dev.get("enabled", True):
                continue
            for z in (dev.get("zones") or {"": dev}).values():
                if z.get("enabled", True):
                    zcfg = z
                    break
            if zcfg:
                break
        mode = zcfg.get("mode", self.config.color_mode)
        modes = {z.get("mode", self.config.color_mode)
                 for dev in self.config.devices_view.values() if dev.get("enabled", True)
                 for z in (dev.get("zones") or {"": dev}).values() if z.get("enabled", True)}
        if len(modes) > 1:
            mode = "mixed"           # zones differ: show the colours as they are
        items = []
        prof = self.calibration.get(zcfg.get("calibration_profile")) if mode == "calibrated" else None
        for c in self._extracted_colors[:8]:
            if mode == "palette":
                to, name = self._snap_one(c), self.palette.nearest_entry(c)[1]
            elif mode == "calibrated":
                to, name = prof.correct(c, 100), ""
            else:
                to, name = c, ""
            items.append({"from": c, "to": to, "name": name})
        return {"mode": mode, "profile": zcfg.get("calibration_profile", "WS2812B"), "items": items}

    def _cmd_status(self) -> Dict[str, Any]:
        ident, probe = self._identify, self._probe
        missing = [
            name for name, cfg in self.config.devices_view.items()
            if cfg.get("enabled", True) and name in self._device_missing_since
        ]
        return {
            "ok": True,
            "wallpaper": self._current_wallpaper,
            "wallpaper_backend": self.detector.last_backend,
            "wallpaper_backend_cached": self.detector.cached_backend,
            "wallpaper_last_error": self.detector.last_error,
            "extracted_colors": self._extracted_colors,
            "wallpaper_choice": (self.wallcache.get_choice(self._current_wallpaper)
                                 if self._current_wallpaper else None),
            "frozen": self._frozen,
            "lights_off": self._lights_off,
            "asleep": self._asleep,
            "night": dict(self._night_settings(), active=self._night_active),
            **self._session_status(),
            **self._notify_status(),
            "sensors": self.sensors.values(),
            "sleep_watch": bool(self.sleepwatch and self.sleepwatch.available),
            "sleep_lights_off": bool(self.config.get("sleep.lights_off", True)),
            "identify": ({"device": ident[0], "zone": ident[1]} if ident else None),
            "probe": ({"device": probe[0], "zone": probe[1], "index": probe[2]} if probe else None),
            "wallpaper_has_picks": (self.wallcache.has_picks(self._current_wallpaper)
                                    if self._current_wallpaper else False),
            "correction": self._correction_preview(),
            "calibration_profiles": self.calibration.list(),
            "led_color": self._led_base_color(),
            "custom_colors": self.custom_colors.list(),
            "exact_colors": self.custom_colors.exact(),
            "overlays": dict(self._overlays),
            "strip_info": dict(self._strip_info),
            "rgb_test": ({"device": self._rgbtest[0], "zone": self._rgbtest[1]} if self._rgbtest else None),
            "brightness": self._shown_brightness(),
            "monitor_brightness": (self._current_brightness if self.ddc.is_available() and self._follows_monitor()
                                   else None),
            "ddc_available": self.ddc.is_available(),
            "ddc_source": getattr(self.ddc, "source", None),
            "ddc_last_error": self.ddc.last_error,
            "ddc_displays": [dict(d) for d in getattr(self.ddc, "displays", [])],
            "ddc_choice": getattr(self.ddc, "choice", None),
            "ddc_problem": getattr(self.ddc, "problem", None),
            "ddc_detecting": bool(getattr(self.ddc, "detecting", False)),
            "ddc_bus": self.ddc.bus if self.ddc.is_available() and self.ddc.source == "ddc" else None,
            "openrgb_connected": self.openrgb.client is not None,
            "openrgb_protocol": getattr(self.openrgb, "protocol", None) if self.openrgb.client is not None else None,
            "openrgb_host": self.openrgb.host,
            "openrgb_autostart": self._orgb.last_action,
            "openrgb_start_method": self._orgb_settings()[0],
            "openrgb_ours_pid": self._orgb.pid if self._orgb.alive() else None,
            "openrgb_gave_up": self._orgb.gave_up,
            "openrgb_no_devices_since": self.openrgb.no_devices_since,
            "started_by": self.started_by,
            "openrgb_connected_since": self.openrgb.connected_since,
            "openrgb_last_error": self.openrgb.last_error,
            "openrgb_missing_devices": missing,
            "devices": self.openrgb.list_devices(),
            "device_configs": {n: (dict(c, zones={zn: clean_zone_cfg(zc) for zn, zc in c["zones"].items()})
                                   if c.get("zones") else clean_zone_cfg(c))
                               for n, c in self.config.devices_view.items()},
            "mode": self.config.color_mode,
            "palette_mode": self.config.palette_mode,
            "color_backend": self.config.get("color.backend", "auto"),
            "color_backend_used": self.extractor.last_used,
            "config_path": self.config.path,
            "socket_path": self._socket_path,
            "pid": os.getpid(),
            "managed_by": "systemd" if openrgb_server.run_by_systemd() else "other",
            "animations": dict(self._anim_settings(), paused=self._anim_hold, running=self._animator.running(),
                               zones=sorted(self._anim_keys), clock=self._animator.clock, rate=self._animator.rate,
                               time=time.time(), measured=dict(self._animator.measured), seed=self._run_seed,
                               timing=dict(self._animator.timing)),
            "code": getattr(self, "_code", ""),
        }

    def _cmd_set_device(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        enabled = req.get("enabled")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        if enabled is not None:
            self.config.set(("devices", name, "enabled"), enabled)
            self._needs_update = True
        return {"ok": True}

    def _cmd_set_pattern(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        pattern = req.get("pattern")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(("devices", name, "pattern"), pattern)
        if self.config.get(("devices", name, "animation")) is not None:
            self.config.set(("devices", name, "animation"), None)     # a static pattern means static
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_mode(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        mode = req.get("mode")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(("devices", name, "mode"), mode)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_led_count(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        zone = req.get("zone")
        count = req.get("count")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        # Previously this silently did nothing when no --zone was given
        # (the common case for a flat, single-zone device from the CLI)
        # — it only ever wrote when a zone was explicitly passed. Route
        # through the same resolver the zone-scoped commands use so an
        # empty zone correctly falls back to the device-level field
        # instead of being a no-op that reports success.
        self._rescale_sections(name, zone, count)
        self.config.set(self._zone_config_path(name, zone, "led_count"), count)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_brightness_sync(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        enabled = req.get("enabled")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(("devices", name, "brightness_sync"), enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_manual_brightness(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        value = req.get("value")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(("devices", name, "manual_brightness"), value)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_brightness_range(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        range_min = req.get("min")
        range_max = req.get("max")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(("devices", name, "brightness_range"), [range_min, range_max])
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_invert(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        enabled = req.get("enabled")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(("devices", name, "invert_brightness"), enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_gamma(self, req: Dict[str, Any]) -> Dict[str, Any]:
        name = req.get("device")
        enabled = req.get("enabled")
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(("devices", name, "gamma_correction"), enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_selected_colors(self, req: dict) -> dict:
        name = req.get("device")
        indices = req.get("indices", [0])
        if name not in self.config.devices:
            return {"ok": False, "error": f"device '{name}' not found"}
        self.config.set(("devices", name, "selected_colors"), indices)
        self._needs_update = True
        return {"ok": True}

    def _zone_config_path(self, dev: str, zone: str, field: str) -> tuple:
        """Resolve the correct config path for a per-zone setting.

        Devices with a real "zones" sub-config (multi-zone controllers)
        store the setting per zone. Devices without one (a flat,
        single-zone config, which is what most simple ARGB headers use)
        store it directly on the device instead. Always writing to
        devices.<dev>.zones.<zone>.<field> would silently create a
        "zones" dict on a device that never had one, the render path
        would then only see that new, near-empty zone and every other
        flat field on the device (led_count, pattern, pattern_colors...)
        would appear to reset to defaults on the next refresh.
        """
        dev_cfg = self.config.devices.get(dev, {})
        if zone and dev_cfg.get("zones"):
            if zone not in dev_cfg["zones"]:
                raise ZoneNotFound(f"zone '{zone}' not found on '{dev}'")
            return ("devices", dev, "zones", zone, field)
        return ("devices", dev, field)

    def _cmd_set_zone_enabled(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        enabled = req.get("enabled")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        self.config.set(self._zone_config_path(dev, zone, "enabled"), enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_zone_pattern(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        pattern = req.get("pattern")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        if pattern not in PatternGenerator.PATTERNS:
            return {"ok": False, "error": f"unknown pattern {pattern!r}"}
        self.config.set(self._zone_config_path(dev, zone, "pattern"), pattern)
        # Picking a static pattern (or painting) means static: an effect would keep hiding it.
        if self.config.get(self._zone_config_path(dev, zone, "animation")) is not None:
            self.config.set(self._zone_config_path(dev, zone, "animation"), None)
        # Stop positions mean different things per pattern; start fresh.
        cur = dict(self._zone_cfg(dev, zone).get("pattern_params") or {})
        if cur.pop("stops", None) is not None:
            self.config.set(self._zone_config_path(dev, zone, "pattern_params"), cur)
        self._last_sent = {}
        self._needs_update = True
        return {"ok": True}

    def _zone_cfg(self, dev: str, zone: str) -> dict:
        cfg = self.config.devices.get(dev, {})
        zones = cfg.get("zones")
        if zones and zone in zones:
            return zones[zone]
        return cfg

    @staticmethod
    def _clean_layout_params(params):
        """Validated stops/reverse/paint dict, or an error string."""
        if not isinstance(params, dict):
            return "params must be an object"
        clean = {}
        if "stops" in params:
            try:
                clean["stops"] = [round(min(1.0, max(0.0, float(x))), 4) for x in params["stops"]]
            except (TypeError, ValueError):
                return "stops must be a list of numbers"
        if "reverse" in params:
            clean["reverse"] = bool(params["reverse"])
        if "mirror" in params:
            clean["mirror"] = bool(params["mirror"])
        if "paint" in params:
            paint = params["paint"]
            if not isinstance(paint, list) or len(paint) > 1000:
                return "paint must be a list of hex colours"
            clean["paint"] = [normalize_hex(c) or None for c in paint]
        return clean

    def _cmd_set_zone_pattern_params(self, req: dict) -> dict:
        """Merge editable layout params (stops / reverse / paint) into a zone."""
        dev = req.get("device")
        zone = req.get("zone")
        params = req.get("params")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        clean = self._clean_layout_params(params)
        if isinstance(clean, str):
            return {"ok": False, "error": clean}
        cur = dict(self._zone_cfg(dev, zone).get("pattern_params") or {})
        cur.update(clean)
        self.config.set(self._zone_config_path(dev, zone, "pattern_params"), cur)
        self._last_sent = {}
        self._needs_update = True
        return {"ok": True}

    def _migrate_patterns(self):
        """Animated patterns were removed; zones that used one become solid."""
        devices = self.config.get("devices", {})
        changed = []
        for dname, dev in devices.items():
            zones = dev.get("zones")
            for zname, target in (zones.items() if zones else [("", dev)]):
                p = target.get("pattern", "solid")
                if p not in PatternGenerator.PATTERNS:
                    target["pattern"] = "solid"
                    changed.append(f"{dname}/{zname or '-'}: {p}")
        if changed:
            self.config.set("devices", devices)
            self.logger.info(f"Animated patterns are no longer supported; switched to 'solid': {changed}")

    def _cmd_set_zone_mode(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        mode = req.get("mode")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        if mode not in ("full", "palette", "calibrated"):
            return {"ok": False, "error": f"mode must be full, palette or calibrated, not {mode!r}"}
        self.config.set(self._zone_config_path(dev, zone, "mode"), mode)
        self._last_sent = {}
        self._needs_update = True
        return {"ok": True}

    @staticmethod
    def _clean_color_entries(entries):
        """Validate a pattern_colors list: ints (extracted index) or hex strings (custom)."""
        if not isinstance(entries, list) or not entries:
            return None
        out = []
        for e in entries:
            if isinstance(e, bool):
                return None
            if isinstance(e, int):
                if e < 0:
                    return None
                out.append(e)
            else:
                h = normalize_hex(e)
                if not h:
                    return None
                out.append(h)
        return out

    def _cmd_set_zone_name(self, req: dict) -> dict:
        """Your own name for a zone ("Desk back", "Case left"), shown everywhere in the window."""
        dev, zone = req.get("device"), req.get("zone") or ""
        if not self._zone_exists(dev, zone):
            return {"ok": False, "error": f"zone '{dev}/{zone}' not found"}
        name = " ".join(str(req.get("name") or "").split())[:40]
        devices = self.config.get("devices", {})
        target = devices[dev]["zones"][zone] if zone and devices[dev].get("zones") else devices[dev]
        if name:
            target["display_name"] = name
        else:
            target.pop("display_name", None)
        self.config.set("devices", devices)
        self.logger.info(f"Zone {dev}/{zone or '(device)'} is now called '{name or zone or dev}'")
        return {"ok": True}

    def _cmd_set_zone_colors(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        entries = self._clean_color_entries(req.get("indices", [0]))
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        if entries is None:
            return {"ok": False, "error": "colors must be a non-empty list of indices or hex strings"}
        self.config.set(self._zone_config_path(dev, zone, "pattern_colors"), entries)
        self._remember_zone_colors({self._zone_key(dev, zone): entries})
        self._needs_update = True
        return {"ok": True}

    # Fields that "apply to everything" may set, and how each is validated.
    _GLOBAL_FIELDS = {
        "enabled": lambda v: isinstance(v, bool),
        "pattern": lambda v: v in PatternGenerator.PATTERNS,
        "mode": lambda v: v in ("palette", "full", "calibrated"),
        "calibration_profile": lambda v: isinstance(v, str) and valid_name(v),
        "brightness_sync": lambda v: isinstance(v, bool),
        "manual_brightness": lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100,
        "brightness_range": lambda v: (isinstance(v, list) and len(v) == 2 and
                                       all(isinstance(x, int) and 0 <= x <= 100 for x in v) and v[0] < v[1]),
        "invert_brightness": lambda v: isinstance(v, bool),
        "gamma_correction": lambda v: isinstance(v, bool),
    }

    def _cmd_set_all(self, req: dict) -> dict:
        """Set one setting on every zone of every device in one atomic write."""
        field = req.get("field")
        value = req.get("value")
        if field == "pattern_colors":
            value = self._clean_color_entries(value)
            if value is None:
                return {"ok": False, "error": "colors must be a non-empty list of indices or hex strings"}
        elif field == "animation":
            anim = None if value in (None, "static", "") else animations.clean(value)
            if value not in (None, "static", "") and anim is None:
                return {"ok": False, "error": f"unknown effect: {value!r}"}
            devices = self.config.get("devices", {})
            n = 0
            for _dev, _zn, target in self._iter_zone_targets(devices):
                target["animation"] = self._merge_animation(target.get("animation"), anim, value)
                n += 1
            self.config.set("devices", devices)
            self._needs_update = True
            self.logger.info(f"Effect for all {n} zone(s): {anim['effect'] if anim else 'static'}")
            return {"ok": True, "zones": n}
        elif field == "pattern_params":
            clean = self._clean_layout_params(value)
            if isinstance(clean, str):
                return {"ok": False, "error": clean}
            devices = self.config.get("devices", {})
            n = 0
            for dev_cfg in devices.values():
                zones = dev_cfg.get("zones")
                for target in (zones.values() if zones else [dev_cfg]):
                    cur = dict(target.get("pattern_params") or {})
                    cur.update(clean)
                    target["pattern_params"] = cur
                    n += 1
            self.config.set("devices", devices)
            self._last_sent = {}
            self._needs_update = True
            return {"ok": True, "zones": n}
        elif field not in self._GLOBAL_FIELDS:
            return {"ok": False, "error": f"can't set '{field}' globally"}
        elif not self._GLOBAL_FIELDS[field](value):
            return {"ok": False, "error": f"invalid value for '{field}': {value!r}"}
        devices = self.config.get("devices", {})
        n = 0
        picks = {}
        for dev, zname, target in self._iter_zone_targets(devices):
            target[field] = value
            picks[self._zone_key(dev, zname)] = value
            if field == "pattern" and isinstance(target.get("pattern_params"), dict):
                target["pattern_params"].pop("stops", None)
            if field == "pattern":
                target.pop("animation", None)          # a static pattern means static
            n += 1
        if field == "pattern_colors":
            self._remember_zone_colors(picks)
        self.config.set("devices", devices)
        self._last_sent = {}
        self._needs_update = True
        self.logger.info(f"Applied {field}={value!r} to all {n} zone(s)")
        return {"ok": True, "zones": n}

    def _cmd_add_custom_color(self, req: dict) -> dict:
        h = normalize_hex(req.get("hex", ""))
        if not h:
            return {"ok": False, "error": f"invalid hex color: {req.get('hex')!r}"}
        return {"ok": True, "custom_colors": self.custom_colors.add(h)}

    def _cmd_remove_custom_color(self, req: dict) -> dict:
        h = normalize_hex(req.get("hex", ""))
        colors = self.custom_colors.remove(h)
        # Zones that were using it fall back to their remaining colors.
        devices = self.config.get("devices", {})
        changed = False
        for dev_cfg in devices.values():
            zones = dev_cfg.get("zones")
            for target in (zones.values() if zones else [dev_cfg]):
                pc = target.get("pattern_colors")
                if isinstance(pc, list) and any(normalize_hex(e) == h for e in pc if isinstance(e, str)):
                    target["pattern_colors"] = [e for e in pc if not (isinstance(e, str) and normalize_hex(e) == h)] or [0]
                    changed = True
        if changed:
            self.config.set("devices", devices)
            self._last_sent = {}
            self._needs_update = True
        return {"ok": True, "custom_colors": colors}

    def _cmd_set_zone_led_count(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        count = req.get("count")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        self._rescale_sections(dev, zone, count)
        self.config.set(self._zone_config_path(dev, zone, "led_count"), count)
        self._needs_update = True
        return {"ok": True}

    def _rescale_sections(self, dev: str, zone: str, count) -> None:
        """A new LED count moves a split strip's dividers along with it."""
        zc = self._zone_cfg(dev, zone)
        if not (zc.get("sections") or zc.get("led_overrides")):
            return
        try:
            new = int(count)
        except (TypeError, ValueError):
            return
        old = clean_zone_cfg(zc)
        secs, ov = zone_sections.rescale(old["sections"], old["led_overrides"], old["led_count"], new)
        self.config.set(self._zone_config_path(dev, zone, "sections"), secs)
        self.config.set(self._zone_config_path(dev, zone, "led_overrides"), zone_sections.overrides_for_config(ov))

    def _cmd_set_zone_sections(self, req: dict) -> dict:
        """sections: the zone's parts (see iridia/sections.py), [] to join them again; led_overrides:
        {LED number: hex} replacing every single LED set, or set_led: [LED, hex or None] for one."""
        dev, zone = req.get("device"), req.get("zone")
        if req.get("target") is not None:
            keys, err = self._resolve_target(req["target"])
            if err:
                return {"ok": False, "error": err}
            if len(keys) != 1:
                return {"ok": False, "error": "pick one strip, not several"}
            dev, _sep, zone = keys[0].partition("|")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        n = clean_zone_cfg(self._zone_cfg(dev, zone))["led_count"]
        if "sections" in req:
            if not isinstance(req["sections"], list):
                return {"ok": False, "error": "sections must be a list"}
            self.config.set(self._zone_config_path(dev, zone, "sections"), zone_sections.clean(req["sections"], n))
        ov = None
        if "led_overrides" in req:
            if not isinstance(req["led_overrides"], dict):
                return {"ok": False, "error": "led_overrides must be an object"}
            ov = zone_sections.clean_overrides(req["led_overrides"], n)
        if "set_led" in req:
            try:
                i, h = int(req["set_led"][0]), req["set_led"][1]
            except (TypeError, ValueError, IndexError, KeyError):
                return {"ok": False, "error": "set_led must be [LED, color or null]"}
            if not 0 <= i < n:
                return {"ok": False, "error": f"LED {i + 1} is past the end of the strip ({n} LEDs)"}
            if h is not None and not normalize_hex(h):
                return {"ok": False, "error": f"not a color: {h!r}"}
            ov = dict(zone_sections.clean_overrides(self._zone_cfg(dev, zone).get("led_overrides"), n)
                      if ov is None else ov)
            if h is None:
                ov.pop(i, None)
            else:
                ov[i] = normalize_hex(h)
        if ov is not None:
            self.config.set(self._zone_config_path(dev, zone, "led_overrides"), zone_sections.overrides_for_config(ov))
        self._last_sent = {}
        self._needs_update = True
        now = clean_zone_cfg(self._zone_cfg(dev, zone))
        return {"ok": True, "device": dev, "zone": zone or "", "led_count": now["led_count"],
                "sections": now["sections"], "led_overrides": zone_sections.overrides_for_config(now["led_overrides"])}

    def _cmd_ddc(self, req: dict) -> dict:
        """Which monitor's brightness to follow ("bus": an I2C bus number, or null for the first that
        answers), or "rescan": look for monitors again (ddcutil installed since, a monitor plugged in)."""
        if "bus" in req:
            bus = req["bus"]
            if bus is not None and (isinstance(bus, bool) or not isinstance(bus, int) or not 0 <= bus < 1000):
                return {"ok": False, "error": "bus must be an I2C bus number or null"}
            self.config.set("ddc.bus_number", bus)
            self.ddc.redetect(bus)
        elif req.get("rescan"):
            self.ddc.redetect()
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_zone_brightness_sync(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        enabled = req.get("enabled")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        self.config.set(self._zone_config_path(dev, zone, "brightness_sync"), enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_zone_manual_brightness(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        value = req.get("value")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        self.config.set(self._zone_config_path(dev, zone, "manual_brightness"), value)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_zone_brightness_range(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        range_min = req.get("min")
        range_max = req.get("max")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        self.config.set(self._zone_config_path(dev, zone, "brightness_range"), [range_min, range_max])
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_zone_invert(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        enabled = req.get("enabled")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        self.config.set(self._zone_config_path(dev, zone, "invert_brightness"), enabled)
        self._needs_update = True
        return {"ok": True}

    def _cmd_set_zone_gamma(self, req: dict) -> dict:
        dev = req.get("device")
        zone = req.get("zone")
        enabled = req.get("enabled")
        if dev not in self.config.devices:
            return {"ok": False, "error": f"device '{dev}' not found"}
        self.config.set(self._zone_config_path(dev, zone, "gamma_correction"), enabled)
        self._needs_update = True
        return {"ok": True}

    def _soft_restart(self):
        self.logger.info("Performing soft restart")
        self.openrgb.client = None
        self.openrgb.devices = {}
        self._last_sent = {}
        self._detect_wallpaper()
        self._needs_update = True


def _acquire_single_instance_lock():
    """One daemon per user session, however many autostart methods fire
    (systemd + compositor exec-once + XDG autostart can all be enabled).
    Returns the open lock file (keep a reference!) or None if another
    instance already holds it."""
    import fcntl
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(base, f"iridia-daemon-{os.getuid()}.lock")
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.seek(0)
        owner = fh.read().strip() or "unknown"
        fh.close()
        print(f"iridia-daemon is already running (pid {owner}); not starting a second copy.", file=sys.stderr)
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def main():
    lock = _acquire_single_instance_lock()
    if lock is None:
        return 0
    daemon = Daemon()
    daemon.run()
    del lock


if __name__ == "__main__":
    main()
