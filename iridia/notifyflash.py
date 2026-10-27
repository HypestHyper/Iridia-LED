"""Flashing LEDs for desktop notifications: the settings, which LEDs each target means, and the
flash itself (mixed into whatever those LEDs show, so the rest of the strip, and animations, carry
on). The daemon watches for notifications (notifywatch) and calls these; the window's Layout tab uses
the same code for its preview.

Every LED a flash lights gets a place t from 0 to 1 along it. With two points A and B set on the
Layout tab, a moving effect runs through the room: t is where the LED lies between A and B, and LEDs
outside that stretch stay out of it. Without them, t goes along each strip's LEDs. The direction then
says how the band travels over t: A to B, B to A, A to B and back, or from the middle out.

Each LED also carries how many LEDs long its stretch is, so the band (and the comet's tail, the
ripple's ring) is a number of LEDs, whatever the stretch's length, with about one LED of soft edge."""
import colorsys
import math
import time
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

EFFECTS = ("pulse", "flash", "sweep", "comet", "fill", "ripple")
MOVING = ("sweep", "comet", "fill", "ripple")       # these use the direction, the band and A/B
DIRECTIONS = ("ab", "ba", "abba", "out")
COLORS = ("accent", "app", "custom", "painted")
PAINT_MAX = 8192                # painted LEDs kept, in all
APPS = ("all", "only", "except")
SEEN_MAX = 40
RULES_MAX = 20
COALESCE_SEC = 0.8              # notifications this close together are one flash
URGENT = (255, 0, 0)

BAND_MAX = 30
DEFAULTS = {"enabled": False, "targets": [], "effect": "pulse", "direction": "ab", "band": 3,
            "repeat": 1, "brightness": 100, "color": "accent", "hex": "ffffff", "urgent_red": True,
            "urgent_effect": "same", "duration": 1.5, "apps": "all", "app_list": [], "rules": [],
            "path": None, "spatial": False, "paint": {}, "dnd": True, "night_quiet": False, "seen": []}


def _hex(v, default="ffffff") -> str:
    s = str(v or "").strip().lstrip("#").lower()
    return s if len(s) == 6 and all(ch in "0123456789abcdef" for ch in s) else default


def _int(v) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if 0 <= v < 100000 else None


def _num(v, default: float, lo: float, hi: float) -> float:
    if isinstance(v, bool):
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return default if v != v else max(lo, min(hi, v))


def clean_target(raw) -> Optional[dict]:
    """{"device", "zone", and which LEDs: "part" (0-based part number), or "start"/"end" (1-based,
    inclusive), or none of them for the whole strip}."""
    if not isinstance(raw, dict) or not isinstance(raw.get("device"), str) or not raw["device"]:
        return None
    out = {"device": raw["device"], "zone": raw.get("zone") if isinstance(raw.get("zone"), str) else ""}
    part = _int(raw.get("part"))
    a, b = _int(raw.get("start")), _int(raw.get("end"))
    if part is not None:
        out["part"] = part
    elif a is not None and b is not None and a >= 1 and b >= 1:
        out["start"], out["end"] = min(a, b), max(a, b)
    return out


def _clean_point(p) -> Optional[List[float]]:
    if isinstance(p, (list, tuple)) and len(p) == 2:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError):
            return None
        if x == x and y == y and abs(x) < 1e6 and abs(y) < 1e6:
            return [round(x, 1), round(y, 1)]
    return None


def clean_rule(raw) -> Optional[dict]:
    """One app's own look: {"app", "effect" ("default" or an effect), "color" ("default", "accent",
    "app" or "custom"), "hex"}."""
    if not isinstance(raw, dict) or not isinstance(raw.get("app"), str) or not raw["app"].strip():
        return None
    eff = raw.get("effect") if raw.get("effect") in EFFECTS else "default"
    col = raw.get("color") if raw.get("color") in COLORS else "default"
    return {"app": raw["app"].strip()[:80], "effect": eff, "color": col, "hex": _hex(raw.get("hex"))}


def clean(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    out["enabled"] = bool(raw.get("enabled", False))
    targets, seen_t = [], set()
    for t in raw.get("targets") or []:
        t = clean_target(t)
        if t is not None and repr(sorted(t.items())) not in seen_t:
            seen_t.add(repr(sorted(t.items())))
            targets.append(t)
    out["targets"] = targets[:256]
    out["effect"] = raw.get("effect") if raw.get("effect") in EFFECTS else "pulse"
    out["direction"] = raw.get("direction") if raw.get("direction") in DIRECTIONS else "ab"
    out["band"] = int(_num(raw.get("band"), 3, 1, BAND_MAX))
    out["repeat"] = int(_num(raw.get("repeat"), 1, 1, 5))
    out["brightness"] = int(_num(raw.get("brightness"), 100, 10, 100))
    out["color"] = raw.get("color") if raw.get("color") in COLORS else "accent"
    out["hex"] = _hex(raw.get("hex"))
    out["urgent_red"] = bool(raw.get("urgent_red", True))
    ue = raw.get("urgent_effect")
    out["urgent_effect"] = ue if ue in EFFECTS else "same"
    out["duration"] = round(_num(raw.get("duration"), 1.5, 0.5, 5.0), 1)
    out["apps"] = raw.get("apps") if raw.get("apps") in APPS else "all"
    out["app_list"] = sorted({str(a) for a in raw.get("app_list") or [] if isinstance(a, str) and a})[:SEEN_MAX]
    rules, names = [], set()
    for r in raw.get("rules") or []:
        r = clean_rule(r)
        if r is not None and r["app"].lower() not in names:
            names.add(r["app"].lower())
            rules.append(r)
    out["rules"] = rules[:RULES_MAX]
    path = raw.get("path") if isinstance(raw.get("path"), dict) else {}
    a, b = _clean_point(path.get("a")), _clean_point(path.get("b"))
    out["path"] = {"a": a, "b": b} if a and b else None
    out["spatial"] = bool(raw.get("spatial", False)) and out["path"] is not None
    out["paint"] = clean_paint(raw.get("paint"))
    out["dnd"] = bool(raw.get("dnd", True))
    out["night_quiet"] = bool(raw.get("night_quiet", False))
    out["seen"] = [str(a) for a in raw.get("seen") or [] if isinstance(a, str) and a][:SEEN_MAX]
    return out


def clean_paint(raw) -> Dict[str, Dict[str, str]]:
    """Colours painted on single LEDs for the flash: {"device|zone": {"LED (0-based)": "rrggbb"}}."""
    out: Dict[str, Dict[str, str]] = {}
    total = 0
    if not isinstance(raw, dict):
        return out
    for key, leds in raw.items():
        if not isinstance(key, str) or "|" not in key or not isinstance(leds, dict):
            continue
        z = {}
        for i, h in leds.items():
            n = _int(i)
            h = _hex(h, "")
            if n is not None and h and total < PAINT_MAX:
                z[str(n)] = h
                total += 1
        if z:
            out[key] = z
    return out


def wanted(settings: dict, app: str) -> bool:
    """Whether this app's notifications flash, by the apps setting (names match ignoring case)."""
    names = {a.lower() for a in settings["app_list"]}
    if settings["apps"] == "only":
        return app.lower() in names
    if settings["apps"] == "except":
        return app.lower() not in names
    return True


def app_color(app: str) -> Tuple[int, int, int]:
    """A colour of its own for each app (the same every time)."""
    hue = (zlib.crc32(app.lower().encode()) % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def _rgb(hex6: str) -> Tuple[int, int, int]:
    return int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)


def style_for(settings: dict, app: str, urgent: bool, accent: str) -> Tuple[str, Tuple[int, int, int], bool]:
    """(effect, colour, painted) for a notification from app: an urgent one's own effect and red come
    first, then the app's rule, then the defaults. accent is the wallpaper colour (hex). painted: LEDs
    with a painted colour use it, the others the colour given (the wallpaper's)."""
    rule = next((r for r in settings["rules"] if r["app"].lower() == app.lower()), None)
    effect = settings["effect"]
    if rule and rule["effect"] != "default":
        effect = rule["effect"]
    if urgent and settings["urgent_effect"] != "same":
        effect = settings["urgent_effect"]
    if urgent and settings["urgent_red"]:
        return effect, URGENT, False
    color, hex6 = settings["color"], settings["hex"]
    if rule and rule["color"] != "default":
        color, hex6 = rule["color"], rule["hex"]
    if color == "app":
        return effect, app_color(app), False
    if color == "custom":
        return effect, _rgb(hex6), False
    return effect, _rgb(_hex(accent, "ffffff")), color == "painted"


def paint_rgb(paint: Dict[str, Dict[str, str]]) -> Dict[str, Dict[int, Tuple[int, int, int]]]:
    """The painted colours as the flash uses them: key -> {LED: (r, g, b)}."""
    return {k: {int(i): _rgb(h) for i, h in leds.items()} for k, leds in paint.items()}


def target_range(t: dict, n: int, sections: Sequence[dict], spans) -> Optional[Tuple[int, int]]:
    """The LEDs a target means on a strip of n: (first, one past the last), 0-based, or None when
    there are none (a part that isn't there any more, a range past the end)."""
    if n <= 0:
        return None
    if "part" in t:
        sp = spans(sections, n) if sections else [(0, n, None)]
        if t["part"] >= len(sp):
            return None
        return sp[t["part"]][0], sp[t["part"]][1]
    if "start" in t:
        a, b = t["start"] - 1, min(t["end"], n)
        return (a, b) if a < b else None
    return 0, n


def targets_for(device: str, zone: str, leds) -> List[dict]:
    """Targets covering exactly these LEDs (0-based) of one strip, as few ranges as possible."""
    out, run = [], None
    for i in sorted(set(leds)):
        if run and i == run[1] + 1:
            run[1] = i
        else:
            if run:
                out.append(run)
            run = [i, i]
    if run:
        out.append(run)
    return [{"device": device, "zone": zone, "start": a + 1, "end": b + 1} for a, b in out]


def led_places(ranges: Dict[str, List[Tuple[int, int]]], positions: Dict[str, Optional[list]],
               effect: str, path: Optional[dict], spacing: Optional[Dict[str, float]] = None
               ) -> Dict[str, List[Tuple[int, float, float]]]:
    """key -> [(LED, t, span)]: where each LED of the flash lies along it, 0 to 1, and how many LEDs
    long its stretch is (so a band can be a number of LEDs).

    path ({"a": [x, y], "b": [x, y]}, layout units) and positions (key -> each LED's [x, y] on the
    Layout tab, or None) make a moving effect run through the room: t is the LED's place between A
    and B (the ripple: its distance from A, with B on the edge), and LEDs outside that stretch are
    left out (spacing: key -> the distance between two of its LEDs there, for the span). Otherwise,
    and for strips not on the Layout tab, t goes along each range's LEDs (the ripple: out from its
    middle)."""
    out: Dict[str, List[Tuple[int, float]]] = {}
    a = b = None
    if path and effect in MOVING:
        a, b = path.get("a"), path.get("b")
        if not a or not b or math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-6:
            a = b = None
    for key, rs in ranges.items():
        pts = positions.get(key) if a else None
        if pts is not None:
            gap = (spacing or {}).get(key) or 16.6
            span = max(1.0, math.hypot(b[0] - a[0], b[1] - a[1]) / gap)
        leds, seen = [], set()
        for lo, hi in rs:
            for i in range(lo, hi):
                if i in seen:                   # targets that overlap: once is enough
                    continue
                seen.add(i)
                if pts is not None and i < len(pts):
                    x, y = pts[i]
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    if effect == "ripple":
                        t = math.hypot(x - a[0], y - a[1]) / math.hypot(dx, dy)
                    else:
                        t = ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)
                    if -1e-9 <= t <= 1 + 1e-9:
                        leds.append((i, min(1.0, max(0.0, t)), span))
                else:
                    t = (i - lo + 0.5) / (hi - lo)
                    if effect == "ripple":
                        leds.append((i, abs(2 * t - 1), max(1.0, (hi - lo) / 2)))
                    else:
                        leds.append((i, t, float(hi - lo)))
        if leds:
            out[key] = leds
    return out


class Flash:
    """One flash, started now: leds is key -> [(LED, t, span)] from led_places(); band is in LEDs."""

    def __init__(self, leds: Dict[str, List[Tuple[int, float, float]]], rgb: Tuple[int, int, int], effect: str,
                 duration: float, now: Optional[float] = None, direction: str = "ab", band: int = 3,
                 repeat: int = 1, brightness: int = 100,
                 paint: Optional[Dict[str, Dict[int, Tuple[int, int, int]]]] = None):
        self.leds, self.rgb, self.effect, self.duration = leds, rgb, effect, duration
        self.paint = paint or {}                 # key -> {LED: colour}: painted LEDs use theirs
        self.direction, self.band, self.repeat = direction, band, max(1, repeat)
        self.brightness = brightness / 100.0
        self.t0 = time.monotonic() if now is None else now

    @property
    def ranges(self) -> Dict[str, list]:
        return self.leds

    @property
    def length(self) -> float:
        return self.duration * self.repeat

    def done(self, now: Optional[float] = None) -> bool:
        return (time.monotonic() if now is None else now) - self.t0 >= self.length

    def mix(self, key: str, frame: list, scale: float = 1.0, now: Optional[float] = None) -> list:
        """frame with the flash over its LEDs at this moment; scale (0-1) dims the flash colour the
        way the strip is dimmed."""
        leds = self.leds.get(key)
        if not leds:
            return frame
        el = (time.monotonic() if now is None else now) - self.t0
        if el < 0 or el >= self.length:
            return frame
        x = (el / self.duration) % 1.0
        s = scale * self.brightness
        fr, fg, fb = (c * s for c in self.rgb)
        own = self.paint.get(key) or {}
        out = list(frame)
        n = len(out)
        for i, t, span in leds:
            if i >= n:
                continue
            a = envelope(self.effect, x, t, self.direction, self.band / span, 1.0 / span)
            if a <= 0:
                continue
            if i in own:
                fr, fg, fb = (c * s for c in own[i])
            elif own:
                fr, fg, fb = (c * s for c in self.rgb)
            r, g, b = out[i]
            out[i] = (round(r + (fr - r) * a), round(g + (fg - g) * a), round(b + (fb - b) * a))
        return out


def _soft(v: float) -> float:
    return max(0.0, min(1.0, v))


def envelope(effect: str, x: float, t: float, direction: str = "ab", band: float = 0.25,
             edge: float = 0.05) -> float:
    """How much of the flash colour an LED at t (0 to 1 along the flash) shows at x (0 to 1 through
    one play). band and edge are parts of the way: the band's length and its soft edge (an LED)."""
    if effect == "flash":
        return 1.0 if (x * 3) % 1.0 < 0.5 else 0.0              # three blinks
    if effect == "pulse":
        return math.sin(2 * math.pi * x) ** 2                     # two soft swells
    w, e = max(1e-3, band), max(1e-3, edge)
    if effect == "ripple":                                       # a ring spreading out
        head = -w / 2 - e + x * (1 + w + 2 * e)
        return _soft((w / 2 + e / 2 - abs(t - head)) / e)
    if direction == "out":
        t = abs(2 * t - 1)                                       # from the middle out to both ends
    if direction == "ba":
        t = 1 - t
    back = direction == "abba" and x >= 0.5                      # A to B, then back to A
    c = (2 * x if x < 0.5 else 2 - 2 * x) if direction == "abba" else x
    if effect == "fill":
        if direction == "abba":
            edge_at, fade = -e + c * (1 + 2 * e), 1.0             # fills to B, then empties back to A
        else:
            edge_at = -e + min(1.0, x / 0.6) * (1 + 2 * e)       # fills, then fades out
            fade = 1.0 if x < 0.6 else max(0.0, (1 - x) / 0.4)
        return fade * _soft((edge_at - t) / e + 0.5)
    if effect == "comet":                                        # a bright head with a tail behind it
        head = -e + c * (1 + w + 2 * e)
        d = (t - head) if back else (head - t)                   # how far behind the head
        if d < 0:
            return _soft(1.0 + d / e)
        return max(0.0, 1.0 - d / w) ** 2
    head = -w / 2 - e + c * (1 + w + 2 * e)                       # sweep: a band running along
    return _soft((w / 2 + e / 2 - abs(t - head)) / e)
