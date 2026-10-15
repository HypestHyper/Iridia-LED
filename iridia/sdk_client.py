"""Iridia's own OpenRGB SDK client, protocol 6 (OpenRGB 1.0 and newer).

Why not openrgb-python: it speaks older protocol versions, and OpenRGB 1.0 only tells protocol 6
clients when an update has been applied. Every colour update goes into a queue per controller that
is written at the controller's pace; without that answer a controller slower than the frame rate
fell minutes behind. Here every request waits for its acknowledgement (packet 10), so nothing can
pile up, and an error OpenRGB reports is seen instead of lost. OpenRGB also announces changes: a
new device list (packet 100) and a changed device (packet 1150, with its new description), so
another program switching a device's mode is seen at once.

The objects (devices, zones, modes, colours) look like openrgb-python's, so the rest of Iridia uses
either. OpenRGB before 1.0 answers the version request with less than 6: connect() raises
ProtocolTooOld and the caller uses openrgb-python instead.

Formats follow OpenRGB 1.0's RGBController.cpp and NetworkServer.cpp; tests/test_sdk_client.py
checks the parser against bytes made by OpenRGB's own encoder.
"""

import logging
import queue
import socket
import struct
import threading
from typing import List, Optional, Sequence

logger = logging.getLogger("iridia")

PROTOCOL = 6
COUNT, DATA, ACK, VERSION, CLIENT_NAME = 0, 1, 10, 40, 50
LIST_UPDATED, SIGNAL_UPDATE = 100, 1150
RESIZE_ZONE, UPDATE_LEDS, UPDATE_ZONE_LEDS, UPDATE_MODE = 1000, 1050, 1051, 1101
REASON_UPDATELEDS = 0
ZONE_SIZE_EFFECTS_ONLY = 1          # zone flag: its size is for hardware effects, one colour for per-LED
NOTIFICATIONS = {LIST_UPDATED, 101, 102, 103, SIGNAL_UPDATE, 158, 160, 304}
HEADER = struct.Struct("<4sIII")
TIMEOUT = 10.0                  # a request not answered by then: the connection is broken


class ProtocolTooOld(Exception):
    """The server is older than OpenRGB 1.0 (no protocol 6)."""


class SDKError(Exception):
    """OpenRGB refused a request (its acknowledgement carried an error status)."""


# --------------------------------------------------------------- objects

class RGB:
    __slots__ = ("red", "green", "blue")

    def __init__(self, red: int = 0, green: int = 0, blue: int = 0):
        self.red, self.green, self.blue = int(red), int(green), int(blue)

    @classmethod
    def from_int(cls, v: int) -> "RGB":
        return cls(v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)

    def pack(self) -> bytes:
        return bytes((self.red & 0xFF, self.green & 0xFF, self.blue & 0xFF, 0))

    def __eq__(self, other):
        return isinstance(other, RGB) and (self.red, self.green, self.blue) == (other.red, other.green, other.blue)

    def __repr__(self):
        return f"RGB({self.red}, {self.green}, {self.blue})"


def _color_bytes(c) -> bytes:
    """An RGB, an openrgb-python RGBColor or an (r, g, b) tuple, as 4 bytes."""
    if isinstance(c, (tuple, list)):
        return bytes((int(c[0]) & 0xFF, int(c[1]) & 0xFF, int(c[2]) & 0xFF, 0))
    return bytes((int(c.red) & 0xFF, int(c.green) & 0xFF, int(c.blue) & 0xFF, 0))


class Mode:
    FIELDS = ("flags", "speed_min", "speed_max", "brightness_min", "brightness_max", "colors_min", "colors_max",
              "speed", "brightness", "direction", "color_mode")

    def __init__(self, index: int = 0, name: str = ""):
        self.index, self.id, self.name = index, index, name
        for f in self.FIELDS:
            setattr(self, f, 0)
        self.colors: List[RGB] = []

    def pack(self) -> bytes:
        """The mode description OpenRGB reads for a mode update (protocol 6)."""
        name = self.name.encode() + b"\0"
        out = struct.pack("<H", len(name)) + name
        out += struct.pack("<11I", *(int(getattr(self, f)) & 0xFFFFFFFF for f in self.FIELDS))
        cols = list(self.colors or [])
        out += struct.pack("<H", len(cols)) + b"".join(_color_bytes(c) for c in cols)
        return out


class Zone:
    def __init__(self, client: "SDKClient", device: "Device", index: int):
        self.client, self.device, self.id = client, device, index
        self.name, self.display_name = "", ""
        self.type = self.leds_min = self.leds_max = self.leds_count = self.flags = 0
        self.start_idx = 0
        self.active_mode = -1
        self.modes: List[Mode] = []
        self.segments: List[dict] = []
        self.leds: list = []
        self.colors: List[RGB] = []

    def set_colors(self, colors: Sequence, fast: bool = True):
        n = self.leds_count
        cols = list(colors[:n])
        body = struct.pack("<IH", self.id, len(cols)) + b"".join(_color_bytes(c) for c in cols)
        self.client.request(self.device.cid, UPDATE_ZONE_LEDS, struct.pack("<I", len(body) + 4) + body)

    def set_color(self, color, fast: bool = True):
        self.set_colors([color] * self.leds_count, fast)

    def resize(self, size: int):
        self.client.request(self.device.cid, RESIZE_ZONE, struct.pack("<ii", self.id, int(size)))
        self.client.refresh_device(self.device.id)


class Device:
    def __init__(self, client: "SDKClient", index: int, cid: int):
        self.client, self.id, self.cid = client, index, cid
        self.comms = None                      # not openrgb-python: the controller asks the client
        self.name = self.vendor = self.description = self.version = self.serial = self.location = ""
        self.display_name = self.configuration = ""
        self.type = self.flags = 0
        self.active_mode = 0
        self.modes: List[Mode] = []
        self.zones: List[Zone] = []
        self.leds: list = []
        self.colors: List[RGB] = []

    def set_mode(self, mode, save: bool = False):
        if isinstance(mode, str):
            mode = next(m for m in self.modes if m.name.lower() == mode.lower())
        elif isinstance(mode, int):
            mode = self.modes[mode]
        body = struct.pack("<i", mode.index) + mode.pack()
        self.client.request(self.cid, UPDATE_MODE, struct.pack("<I", len(body) + 4) + body)
        self.active_mode = mode.index

    def set_colors(self, colors: Sequence, fast: bool = True):
        mode = self.modes[self.active_mode] if 0 <= self.active_mode < len(self.modes) else None
        if mode is not None and mode.color_mode == 2:          # the mode's own colours
            cols = list(colors[:max(1, mode.colors_max)])
            while len(cols) < mode.colors_min:
                cols.append(cols[-1])
            mode.colors = [RGB(*c) if isinstance(c, (tuple, list)) else c for c in cols]
            self.set_mode(mode)
            return
        n = len(self.leds)
        body = struct.pack("<H", min(n, len(colors))) + b"".join(_color_bytes(c) for c in list(colors)[:n])
        self.update_leds(body)

    def set_color(self, color, fast: bool = True):
        mode = self.modes[self.active_mode] if 0 <= self.active_mode < len(self.modes) else None
        if mode is not None and mode.color_mode == 2:
            self.set_colors([color] * max(1, mode.colors_max), fast)
        else:
            self.set_colors([color] * len(self.leds), fast)

    def update_leds(self, body: bytes):
        """A whole-device update (the LED count and colours, as packet 1050 carries them); returns
        once OpenRGB has applied it."""
        self.client.request(self.cid, UPDATE_LEDS, struct.pack("<I", len(body) + 4) + body)

    def update(self):
        self.client.refresh_device(self.id)


# --------------------------------------------------------------- parsing

class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def many(self, fmt: str) -> tuple:
        size = struct.calcsize("<" + fmt)
        if self.pos + size > len(self.data):
            raise ValueError("device description ends early")
        v = struct.unpack_from("<" + fmt, self.data, self.pos)
        self.pos += size
        return v

    def take(self, fmt: str):
        v = self.many(fmt)
        return v if len(v) > 1 else v[0]

    def string(self, length_fmt: str = "H") -> str:
        n = self.take(length_fmt)
        if self.pos + n > len(self.data):
            raise ValueError("device description ends early")
        s = self.data[self.pos:self.pos + n]
        self.pos += n
        return s.split(b"\0", 1)[0].decode("utf-8", "replace")

    def matrix(self):
        h, w = self.take("II")
        return {"height": h, "width": w, "map": list(self.many(f"{h * w}I"))}


def _mode(r: _Reader, index: int) -> Mode:
    m = Mode(index, r.string())
    for f, v in zip(Mode.FIELDS, r.many("11I")):
        setattr(m, f, v)
    m.colors = [RGB.from_int(c) for c in r.many(f"{r.take('H')}I")]
    return m


def parse_device(data: bytes, dev: Device) -> Device:
    """Fill dev from a protocol 6 device description (without the leading size field)."""
    r = _Reader(data)
    dev.type = r.take("i")
    dev.name = r.string()
    dev.vendor = r.string()
    dev.description = r.string()
    dev.version = r.string()
    dev.serial = r.string()
    dev.location = r.string()
    num_modes = r.take("H")
    dev.active_mode = r.take("i")
    dev.modes = [_mode(r, i) for i in range(num_modes)]
    zones = []
    for zi in range(r.take("H")):
        z = Zone(dev.client, dev, zi)
        z.name = r.string()
        z.type, z.leds_min, z.leds_max, z.leds_count = r.take("IIII")
        if r.take("H") > 0:
            r.matrix()
        for _si in range(r.take("H")):
            seg = {"name": r.string()}
            seg["type"], seg["start_idx"], seg["leds_count"] = r.take("III")
            if r.take("H") > 0:
                r.matrix()
            seg["flags"] = r.take("I")
            z.segments.append(seg)
        z.flags = r.take("I")
        z.active_mode = r.take("i")
        z.modes = [_mode(r, i) for i in range(r.take("H"))]
        z.display_name = r.string()
        zones.append(z)
    leds = [r.string() for _ in range(r.take("H"))]
    colors = [RGB.from_int(c) for c in r.many(f"{r.take('H')}I")]
    for _ in range(r.take("H")):            # LED display names
        r.string()
    dev.flags = r.take("I")
    dev.display_name = r.string()
    dev.configuration = r.string("I")
    # Colours per zone, the way OpenRGB counts them (RGBController::LEDsInZone): a zone whose size
    # only matters for hardware effects is one LED for per-LED colours. Iridia addresses colours,
    # so a zone's "leds" are its colours' LEDs, and the device's are all of those in order.
    led_at = col_at = 0
    for z in zones:
        n = 1 if (z.flags & ZONE_SIZE_EFFECTS_ONLY and z.leds_count > 1) else z.leds_count
        z.start_idx = col_at
        # sized by the counts, not by the names (a server that sends fewer names mustn't shrink zones)
        z.leds = [leds[i] if i < len(leds) else f"{z.name} LED {i - led_at + 1}" for i in range(led_at, led_at + n)]
        z.colors = colors[col_at:col_at + n]
        z.leds_count_effects = z.leds_count
        z.leds_count = n
        led_at += z.leds_count_effects
        col_at += n
    dev.leds = [name for z in zones for name in z.leds] if zones else leds
    dev.colors = colors
    dev.zones = zones
    return dev


# --------------------------------------------------------------- the client

class SDKClient:
    def __init__(self, host: str, port: int, name: str = "Iridia"):
        self.host, self.port, self.name = host, port, name
        self.sock: Optional[socket.socket] = None
        self.devices: List[Device] = []
        self.ids: List[int] = []
        self.list_changed = False
        self._inbox: "queue.Queue" = queue.Queue()
        self._send_lock = threading.Lock()
        self._request_lock = threading.RLock()
        self._reader: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self.server_protocol = 0
        self.connect()

    # ------------------------------------------------------------ connection
    def connect(self):
        s = socket.create_connection((self.host, self.port), timeout=TIMEOUT)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = s
        try:
            self._send(0, VERSION, struct.pack("<I", PROTOCOL))
            s.settimeout(3.0)
            while True:                     # the version answer first; old servers send nothing else
                _dev, pid, data = self._read_packet()
                if pid == VERSION:
                    self.server_protocol = struct.unpack("<I", data[:4])[0] if len(data) >= 4 else 0
                    break
            if self.server_protocol < PROTOCOL:
                raise ProtocolTooOld(f"the SDK server speaks protocol {self.server_protocol}")
            while True:                     # protocol 6: server name, then the version request's ACK
                _dev, pid, data = self._read_packet()
                if pid == ACK:
                    break
            s.settimeout(None)
        except (socket.timeout, struct.error) as e:
            self.disconnect()
            raise ProtocolTooOld(f"no protocol 6 answer ({e})") from e
        except BaseException:
            self.disconnect()
            raise
        self._closed.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="iridia-openrgb-reader")
        self._reader.start()
        self.request(0, CLIENT_NAME, self.name.encode() + b"\0")
        self.refresh()

    def disconnect(self):
        self._closed.set()
        s, self.sock = self.sock, None
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    @property
    def connected(self) -> bool:
        return self.sock is not None and not self._closed.is_set()

    # ------------------------------------------------------------ devices
    def refresh(self):
        """The device list from scratch (after connecting, or when OpenRGB says it changed)."""
        with self._request_lock:
            self.list_changed = False
            data = self.request(0, COUNT, b"", reply=COUNT)
            n = struct.unpack_from("<I", data)[0]
            self.ids = list(struct.unpack_from(f"<{n}I", data, 4)) if len(data) >= 4 + 4 * n else []
            devices = []
            for i, cid in enumerate(self.ids):
                devices.append(self._fetch(Device(self, i, cid)))
            self.devices = devices

    def refresh_device(self, index: int):
        with self._request_lock:
            if 0 <= index < len(self.devices):
                self._fetch(self.devices[index])

    def _fetch(self, dev: Device) -> Device:
        data = self.request(dev.cid, DATA, b"", reply=DATA)
        return parse_device(data[4:], dev)

    # ------------------------------------------------------------ requests
    def request(self, dev: int, pid: int, payload: bytes, reply: Optional[int] = None) -> Optional[bytes]:
        """Send a packet and wait for OpenRGB's acknowledgement (and its answer first, if reply is
        set). An error status raises SDKError; no answer raises ConnectionError."""
        with self._request_lock:
            if not self.connected:
                raise ConnectionError("not connected to OpenRGB")
            self._send(dev, pid, payload)
            answer = None
            while True:
                try:
                    rdev, rpid, data = self._inbox.get(timeout=TIMEOUT)
                except queue.Empty:
                    self.disconnect()
                    raise ConnectionError(f"OpenRGB didn't answer (packet {pid})") from None
                if rpid is None:
                    raise ConnectionError(data or "OpenRGB closed the connection")
                if reply is not None and rpid == reply and answer is None:
                    answer = data
                    continue
                if rpid == ACK and len(data) >= 8:
                    acked, status = struct.unpack_from("<II", data)
                    if acked != pid:
                        continue            # a late answer to something earlier
                    if status != 0:
                        raise SDKError(f"OpenRGB refused packet {pid} (status {status})")
                    return answer

    # ------------------------------------------------------------ plumbing
    def _send(self, dev: int, pid: int, payload: bytes):
        s = self.sock
        if s is None:
            raise ConnectionError("not connected to OpenRGB")
        try:
            with self._send_lock:
                s.sendall(HEADER.pack(b"ORGB", dev, pid, len(payload)) + payload)
        except OSError as e:
            self.disconnect()
            raise ConnectionError(f"sending to OpenRGB failed: {e}") from e

    def _recv(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("OpenRGB closed the connection")
            buf += chunk
        return bytes(buf)

    def _read_packet(self):
        magic, dev, pid, size = HEADER.unpack(self._recv(HEADER.size))
        if magic != b"ORGB":
            raise ConnectionError("unexpected data from the SDK server")
        return dev, pid, (self._recv(size) if size else b"")

    def _read_loop(self):
        try:
            while not self._closed.is_set():
                dev, pid, data = self._read_packet()
                if pid == LIST_UPDATED:
                    self.list_changed = True
                elif pid == SIGNAL_UPDATE:
                    self._on_signal(dev, data)
                elif pid not in NOTIFICATIONS:
                    self._inbox.put((dev, pid, data))
        except (OSError, ConnectionError, struct.error) as e:
            if not self._closed.is_set():
                logger.debug(f"OpenRGB connection closed: {e}")
            self._closed.set()
            self._inbox.put((0, None, str(e)))

    def _on_signal(self, cid: int, data: bytes):
        """A device changed. LED updates are ours (or another program's colours): nothing to do.
        Anything else carries the new description: keep ours current (another program may have
        switched its mode)."""
        if len(data) < 8:
            return
        reason = struct.unpack_from("<I", data, 4)[0]
        if reason == REASON_UPDATELEDS:
            return
        dev = next((d for d in self.devices if d.cid == cid), None)
        if dev is None:
            self.list_changed = True
            return
        try:
            fresh = parse_device(data[8:], Device(self, dev.id, cid))
        except (ValueError, struct.error) as e:
            logger.debug(f"OpenRGB sent a device update Iridia couldn't read: {e}")
            return
        for attr in ("name", "type", "active_mode", "modes", "zones", "leds", "colors", "flags", "display_name"):
            setattr(dev, attr, getattr(fresh, attr))
        for z in dev.zones:
            z.device = dev

