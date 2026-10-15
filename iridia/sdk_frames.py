"""A second OpenRGB SDK connection, only for animation frames, that waits for each frame to be written.

OpenRGB 1.0 puts every colour update in a queue per controller and writes them one by one, at the
controller's pace. It tells a client when an update has been written only from SDK protocol 6 on,
with an acknowledgement (packet 10); Iridia's main connection (openrgb-python, protocol 0) gets no
such answer, so a controller slower than the frame rate fell minutes behind. On this connection
Iridia sends one whole-device frame, waits for its acknowledgement and only then sends the next:
the frame takes as long as the controller needs, and the animation thread lowers the rate by itself.

OpenRGB before 1.0 answers the protocol request with a lower version; then this connection isn't
used and frames go over the main connection as before.

Protocol 6 differences that matter here: the controller count lists each controller's ID, colour
packets name the controller by that ID (not its position), and every packet is acknowledged. The
server also pushes notifications (device updated, list changed, ...); they're read and dropped.
"""

import logging
import socket
import struct
import time
from typing import List, Optional

logger = logging.getLogger("iridia")

PROTOCOL = 6
_COUNT, _ACK, _VERSION, _NAME, _LIST_UPDATED, _UPDATE_LEDS = 0, 10, 40, 50, 100, 1050
_HEADER = struct.Struct("4sIII")
ACK_TIMEOUT = 2.0               # a frame not written by then: something's wrong, give up on this connection


class FrameLink:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.sock: Optional[socket.socket] = None
        self.ids: List[int] = []
        self.list_changed = False

    # ------------------------------------------------------------ connection
    def open(self) -> bool:
        """Connect and agree on protocol 6. False when the server is older (or not there)."""
        self.close()
        try:
            s = socket.create_connection((self.host, self.port), timeout=ACK_TIMEOUT)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock = s
            self._send(0, _VERSION, struct.pack("I", PROTOCOL))
            body = self._wait(lambda dev, pid, data: pid == _VERSION)
            server = struct.unpack("I", body[:4])[0] if body and len(body) >= 4 else 0
            if server < PROTOCOL:
                self.close()
                return False
            name = b"Iridia (animation frames)\0"
            self._send(0, _NAME, name)
            self.refresh_ids()
            return True
        except (OSError, struct.error, ConnectionError):
            self.close()
            return False

    def refresh_ids(self):
        """The controllers' IDs, in the order of their positions (what the main connection uses)."""
        self._send(0, _COUNT, b"")
        body = self._wait(lambda dev, pid, data: pid == _COUNT)
        n = struct.unpack("I", body[:4])[0]
        self.ids = list(struct.unpack(f"{n}I", body[4:4 + 4 * n])) if len(body) >= 4 + 4 * n else []
        self.list_changed = False

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.ids = []

    @property
    def ok(self) -> bool:
        return self.sock is not None

    # ------------------------------------------------------------ frames
    def send_leds(self, index: int, body: bytes) -> bool:
        """One whole-device update (body: the LED count and colours, as for packet 1050) for the
        controller at this position; returns once OpenRGB has written it. False if this connection
        can't be used for it (the caller then sends it over the main connection)."""
        if self.sock is None:
            return False
        if self.list_changed:
            self.refresh_ids()
        if not 0 <= index < len(self.ids):
            return False
        cid = self.ids[index]
        self._send(cid, _UPDATE_LEDS, struct.pack("I", len(body) + 4) + body)
        self._wait(lambda dev, pid, data: pid == _ACK and dev == cid and len(data) >= 4
                   and struct.unpack("I", data[:4])[0] == _UPDATE_LEDS)
        return True

    # ------------------------------------------------------------ plumbing
    def _send(self, dev: int, pid: int, payload: bytes):
        if self.sock is None:
            raise ConnectionError("not connected")
        self.sock.sendall(_HEADER.pack(b"ORGB", dev, pid, len(payload)) + payload)

    def _recv(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("OpenRGB closed the frame connection")
            buf += chunk
        return bytes(buf)

    def _wait(self, want) -> bytes:
        """Read packets until want(dev, packet id, data) is true; return that packet's data. Other
        packets (acknowledgements of other requests, notifications) are dropped."""
        end = time.monotonic() + ACK_TIMEOUT
        while True:
            left = end - time.monotonic()
            if left <= 0:
                raise ConnectionError("OpenRGB didn't answer on the frame connection")
            self.sock.settimeout(left)
            magic, dev, pid, size = _HEADER.unpack(self._recv(_HEADER.size))
            if magic != b"ORGB":
                raise ConnectionError("unexpected data on the frame connection")
            data = self._recv(size) if size else b""
            if pid == _LIST_UPDATED:
                self.list_changed = True
            if want(dev, pid, data):
                return data
