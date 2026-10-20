"""Flashing LEDs for desktop notifications: the settings, which LEDs each target means, and the
flash itself (mixed into whatever those LEDs show, so the rest of the strip, and animations, carry
on). The daemon watches for notifications (notifywatch) and calls these."""
import colorsys
import time
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

EFFECTS = ("pulse", "flash", "sweep")
COLORS = ("accent", "app", "custom")
APPS = ("all", "only", "except")
SEEN_MAX = 40
COALESCE_SEC = 0.8              # notifications this close together are one flash
URGENT = (255, 0, 0)

DEFAULTS = {"enabled": False, "targets": [], "effect": "pulse", "color": "accent", "hex": "ffffff",
            "urgent_red": True, "duration": 1.5, "apps": "all", "app_list": [], "dnd": True,
            "night_quiet": False, "seen": []}


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
    out["targets"] = targets[:64]
    out["effect"] = raw.get("effect") if raw.get("effect") in EFFECTS else "pulse"
    out["color"] = raw.get("color") if raw.get("color") in COLORS else "accent"
    out["hex"] = _hex(raw.get("hex"))
    out["urgent_red"] = bool(raw.get("urgent_red", True))
    try:
        d = float(raw.get("duration", 1.5))
    except (TypeError, ValueError):
        d = 1.5
    out["duration"] = round(max(0.5, min(5.0, d if d == d else 1.5)), 1)
    out["apps"] = raw.get("apps") if raw.get("apps") in APPS else "all"
    out["app_list"] = sorted({str(a) for a in raw.get("app_list") or [] if isinstance(a, str) and a})[:SEEN_MAX]
    out["dnd"] = bool(raw.get("dnd", True))
    out["night_quiet"] = bool(raw.get("night_quiet", False))
    out["seen"] = [str(a) for a in raw.get("seen") or [] if isinstance(a, str) and a][:SEEN_MAX]
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


class Flash:
    """One flash: started now, over the given LEDs of each zone (key -> [(first, one past)])."""

    def __init__(self, ranges: Dict[str, List[Tuple[int, int]]], rgb: Tuple[int, int, int], effect: str,
                 duration: float, now: Optional[float] = None):
        self.ranges, self.rgb, self.effect, self.duration = ranges, rgb, effect, duration
        self.t0 = time.monotonic() if now is None else now

    def done(self, now: Optional[float] = None) -> bool:
        return (time.monotonic() if now is None else now) - self.t0 >= self.duration

    def mix(self, key: str, frame: list, scale: float = 1.0, now: Optional[float] = None) -> list:
        """frame with the flash over its LEDs at this moment; scale (0-1) dims the flash colour the
        way the strip is dimmed."""
        rs = self.ranges.get(key)
        if not rs:
            return frame
        x = ((time.monotonic() if now is None else now) - self.t0) / self.duration
        if x < 0 or x >= 1:
            return frame
        fr, fg, fb = (c * scale for c in self.rgb)
        out = list(frame)
        n = len(out)
        for lo, hi in rs:
            hi = min(hi, n)
            for i in range(lo, hi):
                a = envelope(self.effect, x, i, lo, hi)
                if a <= 0:
                    continue
                r, g, b = out[i]
                out[i] = (round(r + (fr - r) * a), round(g + (fg - g) * a), round(b + (fb - b) * a))
        return out


def envelope(effect: str, x: float, i: int, lo: int, hi: int) -> float:
    """How much of the flash colour LED i shows at x (0 to 1 through the flash)."""
    import math
    if effect == "flash":
        return 1.0 if (x * 3) % 1.0 < 0.5 else 0.0             # three blinks
    if effect == "sweep":
        length = hi - lo
        w = max(3.0, length / 4.0)
        c = lo - w / 2 + x * (length + w)                        # a band running along, in and out
        return max(0.0, 1.0 - abs(i + 0.5 - c) / (w / 2))
    return math.sin(2 * math.pi * x) ** 2                         # pulse: two soft swells
