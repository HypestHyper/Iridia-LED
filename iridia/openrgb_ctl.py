"""Resilient OpenRGB controller with lazy connection and device enumeration.

Error-handling here is written against openrgb-python's documented
behavior (https://openrgb-python.readthedocs.io, docs/pages/advanced.rst)
rather than guessed:
  - No SDK server reachable at all -> ConnectionRefusedError, raised from
    OpenRGBClient()/connect().
  - Connection lost after a successful initial connect -> OpenRGBDisconnected
    on the next call that touches the socket. Per the library's own source
    (openrgb/utils.py), OpenRGBDisconnected subclasses the builtin
    ConnectionError, so catching ConnectionError catches both this and
    ConnectionRefusedError without needing openrgb-specific imports.
  - `client.devices` is a plain cached list populated at connect/enumerate
    time, not a live property, reading it never raises and can't be used
    to detect a dropped connection. (This project used to do exactly that
    as a "liveness check"; it never actually checked anything.) Detecting
    a dead connection only works at an actual usage site (_enumerate,
    send) where real I/O happens, which is why those are what reset
    self.client here, not a synthetic health check.
"""

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger("iridia")

# OpenRGB mode colour modes (openrgb.utils.ModeColors)
_PER_LED, _MODE_SPECIFIC = 1, 2


def unique_names(names: List[str]) -> List[str]:
    """Make repeated names unique: two identical RAM sticks become 'X' and 'X (2)'.
    '|' is reserved (Iridia's "device|zone" keys), so it becomes '/'."""
    out, seen = [], {}
    for n in names:
        base = (str(n) if n is not None else "").replace("|", "/").strip() or "Unnamed"
        k = seen.get(base, 0) + 1
        seen[base] = k
        out.append(base if k == 1 else f"{base} ({k})")
    return out


def zones_of(dev) -> list:
    """[(unique zone name, zone)] for a device; zone names are made unique the same way."""
    zones = list(getattr(dev, "zones", None) or [])
    return list(zip(unique_names([getattr(z, "name", "") for z in zones]), zones))


def _rgb(hex_color: str):
    from openrgb.utils import RGBColor
    h = str(hex_color)
    try:
        return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return RGBColor(0, 0, 0)


def _fit(colors: List[str], n: int) -> List[str]:
    """Exactly n colours: cut, or repeat the last one (black if there are none)."""
    out = list(colors[:n])
    while len(out) < n:
        out.append(out[-1] if out else "000000")
    return out


class OpenRGBController:
    COMMON_PORTS = [6742, 6743, 6744]

    def __init__(self, host: str = "127.0.0.1", port: int = None):
        self.host = host or "127.0.0.1"
        try:
            port = int(port) if port not in (None, "", 0) else None
        except (TypeError, ValueError):
            port = None
        self._configured_port = port
        self.port = port or 6742
        self._color_kind: Dict[str, str] = {}      # device -> "per_led" | "single" (from ensure_direct_mode)
        self._fallback_mode: Dict[str, str] = {}   # device -> mode name we switched it to
        self._no_mode: set = set()                 # devices already warned about (no usable mode)
        self.client = None
        self.devices: Dict[str, any] = {}
        self._last_enum = 0.0
        self._last_connect_attempt = 0.0
        self._auto_detected = False
        self.connected_since: Optional[float] = None
        # set while OpenRGB answers but reports no devices: it probably started before the
        # session had access to the hardware, and OpenRGB never scans again by itself
        self.no_devices_since: Optional[float] = None
        self.last_error: Optional[str] = None
        self.last_error_time: Optional[float] = None
        self._last_inventory: Dict = {}
        self._last_warned: Optional[str] = None

    def _warn_once(self, msg: str):
        """Warn only when the message changes — send() runs on every
        change (and ~30x/sec during animation), so a persistent
        problem must not flood the log."""
        if msg != self._last_warned:
            logger.warning(msg)
            self._last_warned = msg

    def _record_error(self, msg: str):
        self.last_error = msg
        self.last_error_time = time.time()

    def _detect_port(self) -> Optional[int]:
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
        return None

    def _can_retry(self, interval: float) -> bool:
        now = time.time()
        if now - self._last_connect_attempt < interval:
            return False
        self._last_connect_attempt = now
        return True

    def ensure_connected(self, retry_interval: float = 5.0) -> bool:
        if self.client is not None:
            # Nothing to verify here — see module docstring. Liveness is
            # detected (and self.client reset) at actual usage sites.
            return True
        if not self._can_retry(retry_interval):
            return False
        if not self._auto_detected and self._configured_port is None:
            # Probe once: every probe is a raw connection that OpenRGB logs as an error
            # ("recv_select failed receiving magic"), so stop as soon as a port answered.
            detected = self._detect_port()
            if detected is not None:
                if detected != self.port:
                    logger.info(f"OpenRGB auto-detected on port {detected}")
                    self.port = detected
                self._auto_detected = True
        try:
            from openrgb import OpenRGBClient
            self.client = OpenRGBClient(self.host, self.port, "iridia", 0)
            self.connected_since = time.time()
            self._enumerate()
            return self.client is not None
        except ConnectionRefusedError:
            self._record_error(f"No SDK server responding on {self.host}:{self.port}")
            self.client = None
            self.no_devices_since = None
            return False
        except OSError as e:
            # Covers connection timeouts and similar transport-level
            # failures distinct from an active refusal.
            self._record_error(f"Couldn't reach {self.host}:{self.port}: {e}")
            logger.debug(f"OpenRGB connect attempt failed ({type(e).__name__}): {e}")
            self.client = None
            return False
        except ImportError as e:
            self._record_error(f"The openrgb-python library is missing from Iridia's environment ({e}). "
                               "Run the installer again: bash install.sh")
            self.client = None
            return False
        except Exception as e:
            self._record_error(f"Unexpected error connecting to OpenRGB: {type(e).__name__}: {e}")
            logger.debug(f"OpenRGB connect attempt failed: {type(e).__name__}: {e}")
            self.client = None
            return False

    def _enumerate(self):
        if not self.client:
            return
        try:
            devs = [d for d in (self.client.devices or []) if d is not None]
            devices = dict(zip(unique_names([d.name for d in devs]), devs))
            self.devices = devices
            self._last_enum = time.time()
            if devices:
                self.no_devices_since = None
                if (self.last_error or "").startswith("OpenRGB is running but reports no devices"):
                    self.last_error = None      # fixed now; don't show it as the last problem
            if not devices:
                # The SDK client caches the device list from connect time,
                # so a server that's still scanning USB (e.g. just
                # restarted) yields an empty list that never fills in on
                # this connection. Drop it and reconnect shortly. If it stays
                # empty, the daemon restarts OpenRGB (only one Iridia started).
                if self.no_devices_since is None:
                    self.no_devices_since = time.time()
                self._record_error("OpenRGB is running but reports no devices (it may have started before the "
                                   "hardware was accessible)")
                self._warn_once("OpenRGB connected but reports no devices yet (still scanning, or it started "
                                "before it could see the hardware), reconnecting shortly")
                try:
                    self.client.disconnect()
                except Exception:
                    pass
                self.client = None
                self.connected_since = None
                return
            self._log_inventory_if_changed()
        except ConnectionError as e:
            # OpenRGBDisconnected (a ConnectionError subclass) or a raw
            # ConnectionRefusedError/ResetError from the socket layer —
            # the connection is dead. Reset so the next ensure_connected()
            # does a genuine reconnect instead of reusing a client object
            # that will just keep raising the same error forever.
            self._record_error(f"Connection lost during device enumeration: {e}")
            logger.warning(f"OpenRGB connection lost during enumeration ({type(e).__name__}: {e}), will reconnect")
            self.client = None
            self.devices = {}
            self.connected_since = None
        except Exception as e:
            self._record_error(f"Device enumeration failed: {type(e).__name__}: {e}")
            logger.warning(f"OpenRGB device enumeration failed: {type(e).__name__}: {e}")
            self.devices = {}

    def maybe_enumerate(self, interval: float = 10.0):
        if time.time() - self._last_enum >= interval:
            self._enumerate()

    @staticmethod
    def _active_mode_name(dev) -> str:
        try:
            return dev.modes[dev.active_mode].name
        except Exception:
            return "unknown"

    def _log_inventory_if_changed(self):
        """Log what OpenRGB actually reports (devices, zone names, real
        LED counts, active mode) whenever it differs from last time.
        This is the single most useful line for "Sent but nothing
        changed": it shows the exact zone names the config must match."""
        inventory = {
            name: (self._active_mode_name(dev),
                   tuple((zn, len(z.leds)) for zn, z in zones_of(dev)))
            for name, dev in self.devices.items()
        }
        if inventory == self._last_inventory:
            return
        self._last_inventory = inventory
        if not inventory:
            logger.warning("OpenRGB reports no devices at all")
            return
        for name, (mode, zones) in inventory.items():
            zone_txt = ", ".join(f"'{zn}' ({n} LEDs)" for zn, n in zones) or "(no zones, whole device)"
            logger.info(f"OpenRGB device '{name}': mode={mode}; zones: {zone_txt}")

    @staticmethod
    def _color_mode(m) -> int:
        try:
            return int(getattr(m, "color_mode", 0))
        except (TypeError, ValueError):
            return 0

    def ensure_direct_mode(self, dev, name: str = "") -> Optional[str]:
        """Put the device in a mode that shows our colours. Returns "per_led" (every LED
        its own colour), "single" (one colour for the whole device) or None.

        Zone/LED updates only show in Direct mode: in Static/Rainbow/... OpenRGB accepts
        them and nothing changes. Devices without Direct fall back to another per-LED
        mode (some call it Custom or Static), then to a mode with its own colour."""
        name = name or dev.name
        modes = list(getattr(dev, "modes", None) or [])
        cur_i = getattr(dev, "active_mode", None)
        cur = modes[cur_i] if isinstance(cur_i, int) and 0 <= cur_i < len(modes) else None
        want = self._color_kind.get(name)
        if cur is not None and cur.name.lower() == "direct":
            self._color_kind[name] = "per_led"
            return "per_led"
        # Already in the fallback we picked earlier: nothing to switch.
        if cur is not None and want and self._fallback_mode.get(name) == cur.name:
            return want
        pick, kind = None, None
        for m in modes:
            if m.name.lower() == "direct":
                pick, kind = m, "per_led"
                break
        if pick is None:
            per_led = [m for m in modes if self._color_mode(m) == _PER_LED]
            per_led.sort(key=lambda m: 0 if m.name.lower() in ("custom", "static") else 1)
            if per_led:
                pick, kind = per_led[0], "per_led"
        if pick is None:
            single = [m for m in modes if self._color_mode(m) == _MODE_SPECIFIC
                      and getattr(m, "colors", None) is not None]
            single.sort(key=lambda m: 0 if m.name.lower() == "static" else 1)
            if single:
                pick, kind = single[0], "single"
        if pick is None:
            msg = (f"'{name}' has no mode Iridia can set colours in (modes: {[m.name for m in modes]})")
            if name not in self._no_mode:
                self._no_mode.add(name)
                logger.warning(msg)
            self._record_error(msg)
            return None
        try:
            if cur is None or cur.name != pick.name:
                note = "" if pick.name.lower() == "direct" else (
                    " (it has no Direct mode; LEDs can still have their own colours)" if kind == "per_led"
                    else " (it has no Direct mode, so the whole device shows one colour)")
                logger.info(f"'{name}' was in '{cur.name if cur else '?'}' mode; switching to "
                            f"'{pick.name}'{note}")
                dev.set_mode(pick)
            self._color_kind[name] = kind
            self._fallback_mode[name] = pick.name
            return kind
        except ConnectionError:
            raise
        except Exception as e:
            msg = f"Couldn't switch '{name}' to '{pick.name}' mode: {type(e).__name__}: {e}"
            self._warn_once(msg)
            self._record_error(msg)
            return None

    def list_devices(self) -> List[Dict]:
        result = []
        for name, dev in self.devices.items():
            zones = [{"name": zn, "led_count": len(getattr(z, "leds", None) or [])} for zn, z in zones_of(dev)]
            result.append({"name": name, "type": str(getattr(dev, "type", "unknown")),
                           "mode": self._active_mode_name(dev), "zones": zones,
                           "led_count": len(getattr(dev, "leds", None) or []),
                           "single_color": self._color_kind.get(name) == "single"})
        return result

    def resize_zone(self, device_name: str, zone_name: str, size: int) -> Optional[str]:
        """Resize an addressable zone in OpenRGB. Returns an error string or None."""
        dev = self.devices.get(device_name)
        if dev is None:
            return f"'{device_name}' isn't connected"
        for zn, z in zones_of(dev):
            if not zone_name or zn == zone_name:
                try:
                    z.resize(int(size))
                    try:
                        dev.update()
                    except Exception:
                        pass
                    return None
                except ConnectionError as e:
                    self._lost(f"Connection lost while resizing '{zn}': {e}")
                    return "OpenRGB disconnected"
                except Exception as e:
                    return f"OpenRGB couldn't resize '{zn}' ({type(e).__name__}: {e}). Only addressable headers can be resized."
        return f"zone '{zone_name}' not found on '{device_name}'"

    def _lost(self, msg: str):
        """The link is dead (not a data problem): reset for a real reconnect."""
        logger.warning(f"OpenRGB {msg}, will reconnect")
        self._record_error(msg)
        self.client = None
        self.devices = {}
        self.connected_since = None

    def disconnect(self):
        """Drop the current connection so the next ensure_connected() does
        a fresh connect + enumerate, bypassing the retry-interval
        throttle. Used for a user-triggered "Reconnect" action."""
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.devices = {}
        self.connected_since = None
        self._last_connect_attempt = 0.0

    def send(self, device_name: str, colors: List[str], zones_config: Optional[Dict] = None) -> bool:
        """Send colours to a device, or to the zones named in zones_config (only those)."""
        dev = self.devices.get(device_name)
        if dev is None:
            msg = (f"'{device_name}' isn't in the enumerated device list "
                   f"(have: {list(self.devices.keys())}), name mismatch, or it "
                   "hasn't been (re-)enumerated since it was plugged in?")
            self._warn_once(f"OpenRGB send: {msg}")
            self._record_error(msg)
            return False
        try:
            kind = self.ensure_direct_mode(dev, device_name)
            if kind is None:
                return False
            if kind == "single":
                # One colour for the whole device (its mode has a colour, not per-LED colours).
                dev.set_color(_rgb(colors[0] if colors else "000000"), fast=True)
            elif zones_config and dev.zones:
                matched = 0
                for zn, zone in zones_of(dev):
                    # Only touch zones we were actually asked to update.
                    zcfg = zones_config.get(zn)
                    if zcfg is None:
                        continue
                    matched += 1
                    if not zcfg.get("enabled", True):
                        continue            # deliberately skipped, not a mismatch
                    # Resizing makes the controller re-initialise (lights flash), so
                    # it's opt-in via "resize_zone": true; we normally use the real size.
                    if zcfg.get("resize_zone", False) and zcfg.get("led_count", len(zone.leds)) != len(zone.leds):
                        try:
                            zone.resize(int(zcfg["led_count"]))
                        except ConnectionError:
                            raise
                        except Exception as e:
                            logger.debug(f"Zone '{zn}' resize failed: {type(e).__name__}: {e}")
                    n = len(zone.leds)
                    if n == 0:
                        continue            # unsized ARGB header: nothing to address yet
                    zone.set_colors([_rgb(c) for c in _fit(colors, n)], fast=True)
                if matched == 0:
                    real = [zn for zn, _z in zones_of(dev)]
                    msg = (f"None of the configured zones {list(zones_config.keys())} exist on "
                           f"'{device_name}', OpenRGB reports zones {real}.")
                    self._warn_once(f"OpenRGB send: {msg}")
                    self._record_error(msg)
                    return False
            else:
                n = len(getattr(dev, "leds", None) or [])
                if n == 0:
                    dev.set_color(_rgb(colors[0] if colors else "000000"), fast=True)
                else:
                    dev.set_colors([_rgb(c) for c in _fit(colors, n)], fast=True)
            self.last_error = None
            self._last_warned = None
            return True
        except ConnectionError as e:
            self._lost(f"Connection lost while sending to '{device_name}': {e}")
            return False
        except Exception as e:
            msg = f"Send to '{device_name}' failed: {type(e).__name__}: {e}"
            self._warn_once(f"OpenRGB {msg}")
            self._record_error(msg)
            return False

    def send_zone(self, device_name: str, zone_name: str, colors: List[str]) -> bool:
        """Send colors to a specific zone."""
        return self.send(device_name, colors, {zone_name: {"enabled": True}} if zone_name else None)
