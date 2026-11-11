"""Lights on the network: Philips WiZ and Govee, found and driven over the local network, no account,
no cloud and nothing to pair. They keep working in their own apps and in Google Home (Matter) as
before: these are their own local protocols, next to Matter.

WiZ    JSON over UDP port 38899. A broadcast getSystemConfig is answered by every WiZ light with
       its MAC; setPilot sets the colour and brightness (10 to 100), setState switches it off.
Govee  The LAN API (each light: Govee app, the light's settings, LAN Control). A scan sent to
       239.255.255.250:4001 is answered on port 4002 with the light's IP, model and id; commands
       (turn, brightness, colorwc) go to the light's port 4003.

Each light is one colour (a Govee strip too: its segments are another protocol). Colours go out at
most every MIN_GAP seconds per light, the latest one winning, and only when they change, so a fade
or an animation doesn't flood the light.
"""
import ipaddress
import json
import logging
import socket
import threading
import time

logger = logging.getLogger("iridia")

WIZ_PORT = 38899
GOVEE_SCAN = ("239.255.255.250", 4001)
GOVEE_LISTEN = 4002
GOVEE_CMD = 4003
BROADCAST = "255.255.255.255"
SCAN_EVERY = 60.0               # seconds between searches (and right away when asked)
FORGET_AFTER = 600.0            # a light not seen for this long drops off the list
MIN_GAP = {"wiz": 0.1, "govee": 0.2}     # seconds between two colours to one light
MAX_HOSTS = 1024                # addresses asked directly per search (a /22 at most)


def clean_hosts(raw) -> list[str]:
    """Addresses or networks to ask directly ("192.168.20.31", "192.168.20.0/24"): for lights the
    broadcast and multicast don't reach, on another VLAN or subnet. Bad entries are dropped."""
    out = []
    for h in raw if isinstance(raw, (list, tuple)) else []:
        try:
            net = ipaddress.ip_network(str(h).strip(), strict=False)
        except ValueError:
            continue
        if net.version != 4 or net.num_addresses > MAX_HOSTS:
            continue
        text = str(net.network_address) if net.num_addresses == 1 else str(net)
        if text not in out:
            out.append(text)
    return out


def expand(hosts) -> list[str]:
    """Every address to ask: a network's hosts (not its network and broadcast address)."""
    out = []
    for h in clean_hosts(hosts):
        net = ipaddress.ip_network(h, strict=False)
        addrs = [net.network_address] if net.num_addresses == 1 else list(net.hosts())
        out += [str(a) for a in addrs]
        if len(out) >= MAX_HOSTS:
            return out[:MAX_HOSTS]
    return out


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = (h or "000000").lstrip("#")
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 0, 0, 0


def split_brightness(rgb) -> tuple[tuple[int, int, int], int]:
    """A colour Iridia already scaled by brightness -> (full colour, brightness 0-100), the way these
    lights take it: (40, 20, 0) is (255, 127, 0) at 16%."""
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    top = max(r, g, b)
    if top == 0:
        return (0, 0, 0), 0
    f = 255.0 / top
    return (round(r * f), round(g * f), round(b * f)), max(1, round(top * 100 / 255))


def average(colors) -> tuple[int, int, int]:
    """One colour for a light from what a zone would show on its LEDs."""
    cols = [_hex_rgb(c) if isinstance(c, str) else tuple(c) for c in colors] or [(0, 0, 0)]
    n = len(cols)
    return tuple(int(round(sum(c[i] for c in cols) / n)) for i in range(3))


def wiz_command(rgb) -> dict:
    full, bright = split_brightness(rgb)
    if bright == 0:
        return {"method": "setState", "params": {"state": False}}
    return {"method": "setPilot", "params": {"state": True, "r": full[0], "g": full[1], "b": full[2],
                                             "dimming": max(10, bright)}}


def wiz_brightness(rgb) -> dict:
    """Brightness and on/off only: the colour stays what the WiZ app set."""
    _full, bright = split_brightness(rgb)
    if bright == 0:
        return {"method": "setState", "params": {"state": False}}
    return {"method": "setPilot", "params": {"state": True, "dimming": max(10, bright)}}


def on_demand_commands(kind: str, rgb) -> list[dict]:
    """A colour asked for on the card of an "only when I change it" light: colour and brightness, never
    on or off (that stays with its own app and automations); nothing for black."""
    full, bright = split_brightness(rgb)
    if bright == 0:
        return []
    if kind == "wiz":
        return [{"method": "setPilot", "params": {"r": full[0], "g": full[1], "b": full[2],
                                                  "dimming": max(10, bright)}}]
    return [{"msg": {"cmd": "colorwc", "data": {"color": {"r": full[0], "g": full[1], "b": full[2]},
                                                "colorTemInKelvin": 0}}},
            {"msg": {"cmd": "brightness", "data": {"value": bright}}}]


def govee_commands(rgb, was_on: bool | None, keep_color: bool = False) -> list[dict]:
    full, bright = split_brightness(rgb)
    if bright == 0:
        return [] if was_on is False else [{"msg": {"cmd": "turn", "data": {"value": 0}}}]
    out = [] if was_on else [{"msg": {"cmd": "turn", "data": {"value": 1}}}]
    if not keep_color:
        out.append({"msg": {"cmd": "colorwc", "data": {"color": {"r": full[0], "g": full[1], "b": full[2]},
                                                       "colorTemInKelvin": 0}}})
    out.append({"msg": {"cmd": "brightness", "data": {"value": bright}}})
    return out


def local_firewall() -> str | None:
    """This PC's own firewall, when one is on: it can drop Govee's answers (to UDP 4002) before
    Iridia sees them. None when there's none (or it can't be told without root)."""
    import shutil
    import subprocess

    def out(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    if shutil.which("firewall-cmd") and out(["firewall-cmd", "--state"]) == "running":
        return "firewalld"
    if shutil.which("systemctl"):
        for unit, name in (("ufw", "ufw"), ("firewalld", "firewalld"), ("nftables", "nftables"),
                           ("iptables", "iptables")):
            if out(["systemctl", "is-active", unit]) == "active":
                return name
    return None


class Light:
    def __init__(self, kind: str, ident: str, ip: str, model: str = "", manual: bool = False):
        self.kind, self.ident, self.ip, self.model = kind, ident, ip, model
        self.manual = manual            # added by address: driven without ever hearing from it
        self.seen = time.monotonic()
        self.sent: tuple[int, int, int] | None = None
        self.sent_at = 0.0
        self.pending: tuple[int, int, int] | None = None
        self.on: bool | None = None

    @property
    def name(self) -> str:
        """The name it gets in Iridia (renamed on its card like any strip): brand, model, end of its id."""
        if self.manual:
            return f"{'WiZ' if self.kind == 'wiz' else 'Govee'} {self.ip}"
        tail = self.ident.replace(":", "")[-6:].upper()
        if self.kind == "wiz":
            return f"WiZ {tail}"
        return f"Govee {self.model} {tail}".replace("  ", " ")


class NetLights:
    """Finds WiZ and Govee lights while enabled, and sends them colours."""

    def __init__(self):
        self.enabled = False
        self.lights: dict[str, Light] = {}          # Iridia name -> light
        self.error: str | None = None            # why Govee can't be heard (port 4002 taken, ...)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None          # WiZ, and commands to Govee
        self._govee: socket.socket | None = None         # Govee's answers to a scan (port 4002)
        # never searched: due at once (not "60 s after time 0": the monotonic clock starts at boot, so a
        # daemon started right at login would wait for a minute)
        self._last_scan = float("-inf")
        self.hosts: list[str] = []                  # also asked directly (other VLANs, subnets)
        self.keep_color: set = set()                # lights whose own colour stays: brightness and on/off only
        self.on_demand: set = set()                 # "only when I change it": never on/off, never re-sent
        self.heard: dict[str, list[str]] = {}       # address -> what came back from it lately (for a test)
        self._manual: list[tuple[str, str]] = []    # (kind, ip) added by address
        self.targets = {"wiz": (BROADCAST, WIZ_PORT), "govee": GOVEE_SCAN, "govee_cmd": GOVEE_CMD,
                        "govee_listen": GOVEE_LISTEN}       # tests point these at localhost

    # ---------------------------------------------------------------- on and off
    def set_enabled(self, on: bool):
        if on == self.enabled:
            return
        self.enabled = on
        if on:
            self._open()
            self._thread = threading.Thread(target=self._run, daemon=True, name="netlights")
            self._thread.start()
            self.scan()
        else:
            self._wake.set()
            self._close()

    def stop(self):
        self.set_enabled(False)

    def _open(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", 0))
        s.settimeout(0.2)
        self._sock = s
        self.error = None
        try:
            g = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            g.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            g.bind(("", self.targets["govee_listen"]))
            g.settimeout(0.2)
            self._govee = g
        except OSError as e:
            self._govee = None
            self.error = f"Govee lights can't answer: port {self.targets['govee_listen']} is in use ({e.strerror})"
            logger.warning(self.error)

    def _close(self):
        for s in (self._sock, self._govee):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self._sock = self._govee = None

    # ---------------------------------------------------------------- finding them
    def scan(self):
        """Look for lights now (they answer within a second)."""
        self._last_scan = float("-inf")
        self._wake.set()

    def _send_scan(self):
        s = self._sock
        if s is None:
            return
        try:
            s.sendto(json.dumps({"method": "getSystemConfig", "params": {}}).encode(), self.targets["wiz"])
        except OSError as e:
            logger.debug(f"WiZ search failed: {e}")
        govee_scan = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
        if self._govee is not None:
            try:
                s.sendto(govee_scan, self.targets["govee"])
            except OSError as e:
                logger.debug(f"Govee search failed: {e}")
        # Broadcast and multicast stay on this network: lights on another VLAN or subnet are asked
        # one by one (routers pass that on like any other traffic)
        wiz_ask = json.dumps({"method": "getSystemConfig", "params": {}}).encode()
        for ip in expand(self.hosts):
            for msg, port in ((wiz_ask, self.targets["wiz"][1]), (govee_scan, self.targets["govee"][1])):
                try:
                    s.sendto(msg, (ip, port))
                except OSError:
                    pass                        # no route to it: nothing there

    def _found(self, kind: str, ident: str, ip: str, model: str = ""):
        if not ident:
            return
        with self._lock:
            for light in self.lights.values():
                if light.kind == kind and light.ident == ident:
                    if light.ip != ip:
                        logger.info(f"{light.name} moved to {ip}")
                    light.ip, light.seen = ip, time.monotonic()
                    if model:
                        light.model = model
                    return
            light = Light(kind, ident, ip, model)
            self.lights[light.name] = light
            logger.info(f"Found {light.name} at {ip}")

    def _read(self, sock, kind_hint: str):
        try:
            data, (ip, _port) = sock.recvfrom(4096)
        except (TimeoutError, OSError):
            return False
        try:
            msg = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            return True
        if not isinstance(msg, dict):
            return True
        what = (msg.get("msg") or {}).get("cmd") if isinstance(msg.get("msg"), dict) else msg.get("method")
        heard = self.heard.setdefault(ip, [])
        heard.append(f"{'Govee' if kind_hint == 'govee' else 'WiZ'} {what or '?'}")
        del heard[:-10]
        if kind_hint == "govee" or "msg" in msg:
            d = (msg.get("msg") or {}).get("data") or {}
            if (msg.get("msg") or {}).get("cmd") == "scan" and isinstance(d, dict):
                self._found("govee", str(d.get("device") or ""), str(d.get("ip") or ip), str(d.get("sku") or ""))
            return True
        res = msg.get("result")
        if msg.get("method") == "getSystemConfig" and isinstance(res, dict):
            self._found("wiz", str(res.get("mac") or ""), ip, str(res.get("moduleName") or ""))
        return True

    def _run(self):
        while self.enabled:
            now = time.monotonic()
            if now - self._last_scan >= SCAN_EVERY:
                self._last_scan = now
                self._send_scan()
                self.resend()                   # a light switched off at the wall shows its colour again
                with self._lock:
                    for name in [n for n, light in self.lights.items()
                                 if not light.manual and now - light.seen > FORGET_AFTER]:
                        logger.info(f"{name} hasn't answered for a while; dropped from the list")
                        del self.lights[name]
            busy = False
            for sock, kind in ((self._sock, "wiz"), (self._govee, "govee")):
                if sock is not None and self._read(sock, kind):
                    busy = True
            self._flush()
            if not busy:
                self._wake.wait(0.05)
                self._wake.clear()

    # ---------------------------------------------------------------- by address
    def set_manual(self, lights):
        """Lights added by address [(kind, ip)]: driven without ever hearing from them, for a network
        whose firewall doesn't let their answers back."""
        lights = [(k, ip) for k, ip in lights if k in ("wiz", "govee")]
        if lights == self._manual:
            return
        self._manual = lights
        with self._lock:
            for n in [n for n, light in self.lights.items() if light.manual and (light.kind, light.ip) not in lights]:
                del self.lights[n]
            for kind, ip in lights:
                light = Light(kind, "ip:" + ip, ip, manual=True)
                self.lights.setdefault(light.name, light)

    def probe(self, ip: str, wait: float = 2.5) -> dict:
        """Ask one address directly, as WiZ and as Govee, and say what came back: tells "nothing there"
        from "the answers don't get back" (WiZ answers from the port it was asked on, Govee to 4002)."""
        if self._sock is None:
            return {"ok": False, "error": "Looking for network lights is off"}
        self.heard.pop(ip, None)
        msgs = ((json.dumps({"method": "getSystemConfig", "params": {}}), self.targets["wiz"][1]),
                (json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}), self.targets["govee"][1]),
                (json.dumps({"msg": {"cmd": "devStatus", "data": {}}}), self.targets["govee_cmd"]))
        errors = []
        for text, port in msgs:
            try:
                self._sock.sendto(text.encode(), (ip, port))
            except OSError as e:
                errors.append(f"port {port}: {e.strerror or e}")
        end = time.monotonic() + wait
        while time.monotonic() < end and not self.heard.get(ip):
            time.sleep(0.05)
        time.sleep(0.2)                         # the other answers, if any
        heard = list(self.heard.get(ip, []))
        return {"ok": True, "ip": ip, "heard": heard, "send_errors": errors,
                "wiz": any(h.startswith("WiZ") for h in heard), "govee": any(h.startswith("Govee") for h in heard),
                "govee_listening": self._govee is not None}

    # ---------------------------------------------------------------- what the daemon uses
    def has(self, name: str) -> bool:
        return name in self.lights

    def list_devices(self) -> list[dict]:
        """Like OpenRGB's list: one zone-less, one-colour device per light."""
        with self._lock:
            return [{"name": n, "type": f"{light.kind} light", "mode": "network", "zones": [], "led_count": 1,
                     "single_color": True, "net": {"kind": light.kind, "ip": light.ip, "id": light.ident,
                                                   "model": light.model, "manual": light.manual}}
                    for n, light in sorted(self.lights.items())]

    def send(self, name: str, colors, zones_config=None) -> bool:
        """The colour a light should show (averaged from the zone's LEDs); sent within MIN_GAP."""
        light = self.lights.get(name)
        if light is None or self._sock is None:
            return False
        rgb = average(colors)
        with self._lock:
            light.pending = rgb
        self._flush()
        return True

    def send_frames(self, name: str, frames) -> bool | None:
        """An animation frame: the light shows the average of its zone's frame."""
        cols = [c for f in frames.values() for c in f]
        return self.send(name, cols) if name in self.lights else None

    def _flush(self):
        now = time.monotonic()
        todo = []
        with self._lock:
            for light in self.lights.values():
                rgb = light.pending
                if rgb is None:
                    continue
                if rgb == light.sent:
                    light.pending = None
                    continue
                if now - light.sent_at < MIN_GAP.get(light.kind, 0.2):
                    continue                    # the next pass sends the latest one
                light.pending, light.sent, light.sent_at = None, rgb, now
                todo.append((light, rgb))
        for light, rgb in todo:
            self._transmit(light, rgb)

    def _transmit(self, light: Light, rgb):
        s = self._sock
        if s is None:
            return
        try:
            name = self._name_of(light)
            if name in self.on_demand:
                port = self.targets["wiz"][1] if light.kind == "wiz" else self.targets["govee_cmd"]
                for cmd in on_demand_commands(light.kind, rgb):
                    s.sendto(json.dumps(cmd).encode(), (light.ip, port))
                return
            keep = name in self.keep_color
            if light.kind == "wiz":
                cmd = wiz_brightness(rgb) if keep else wiz_command(rgb)
                s.sendto(json.dumps(cmd).encode(), (light.ip, self.targets["wiz"][1]))
            else:
                for cmd in govee_commands(rgb, light.on, keep_color=keep):
                    s.sendto(json.dumps(cmd).encode(), (light.ip, self.targets["govee_cmd"]))
                light.on = split_brightness(rgb)[1] > 0
        except OSError as e:
            logger.debug(f"Couldn't send to {light.name} at {light.ip}: {e}")

    def _name_of(self, light: Light) -> str:
        return next((n for n, x in self.lights.items() if x is light), light.name)

    def set_keep_color(self, names):
        """Lights whose colour stays as their own app set it; a change sends them their state again."""
        names = set(names)
        if names != self.keep_color:
            changed = names ^ self.keep_color
            self.keep_color = names
            for n in changed:
                self.resend(n)

    def power(self, name: str, on: bool):
        """Switch a light on or off, now (its power button, for one Iridia otherwise never switches)."""
        light = self.lights.get(name)
        s = self._sock
        if light is None or s is None:
            return
        try:
            if light.kind == "wiz":
                s.sendto(json.dumps({"method": "setState", "params": {"state": bool(on)}}).encode(),
                         (light.ip, self.targets["wiz"][1]))
            else:
                s.sendto(json.dumps({"msg": {"cmd": "turn", "data": {"value": 1 if on else 0}}}).encode(),
                         (light.ip, self.targets["govee_cmd"]))
            light.on = bool(on)
        except OSError as e:
            logger.debug(f"Couldn't switch {light.name} at {light.ip}: {e}")

    def resend(self, name: str | None = None):
        """Send every light (or the one named) its colour again: after a light came back, after it was
        set in its own app meanwhile, or after Iridia restarted."""
        with self._lock:
            for n, light in self.lights.items():
                if name is not None and n != name:
                    continue
                if name is None and n in self.on_demand:
                    continue                    # only when changed on its card: not again by itself
                if light.sent is not None:
                    light.pending, light.sent = light.sent, None
                light.on = None
