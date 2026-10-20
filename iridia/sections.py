"""Sections: one strip split into parts, each showing something of its own, plus single LEDs set by hand.

Stored per zone in config.json:

    "sections": [{"start": 0, "type": "same"},
                 {"start": 27, "type": "pattern", "pattern": "gradient", "colors": [0, "ff0000"],
                  "params": {"stops": [...], "reverse": false, "mirror": false}},
                 {"start": 54, "type": "effect", "animation": {"effect": "comet", ...}, "colors": [1]},
                 {"start": 70, "type": "off"},
                 {"start": 75, "type": "sensor", "sensor": "cpu_temp", "show": "level", "min": 30, "max": 90,
                  "palette": "heat", "colors": [0], "background": "dim", "flash_above": 85}]
    "led_overrides": {"26": "ffffff", "53": "000000"}

`start` is the first LED of the part (0 based); a part runs to the next one's start. Types:
    same     what the whole strip shows there (its pattern or effect)
    pattern  a static pattern of its own, drawn over just that part
    effect   an animated effect of its own, over just that part
    off      dark
    sensor   a system reading (iridia/sensors.py) as a color, a level bar, or a bar in the reading's
             color; min/max default to 30-90 °C or 0-100 %
`colors` are entries like a zone's pattern_colors (a wallpaper color's index or a hex).
led_overrides set single LEDs to one color over everything else ("000000" is off).

Everything here is pure: the daemon and the window share it, so the preview is what the strip shows.
"""

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from iridia import animations, sensors
from iridia.colors import normalize_hex
from iridia.patterns import PatternGenerator

TYPES = ("same", "pattern", "effect", "off", "sensor")
SHOWS = ("color", "level", "both")
HEAT = ["2060ff", "20d070", "ffb000", "ff2020"]          # cool to hot
MAX_SECTIONS = 32
MAX_OVERRIDES = 512
OFF = "000000"


def _colors(raw) -> list:
    out = []
    for e in raw if isinstance(raw, list) else []:
        if isinstance(e, bool):
            continue
        if isinstance(e, int) and 0 <= e < 64:
            out.append(e)
        elif isinstance(e, str) and normalize_hex(e):
            out.append(normalize_hex(e))
    return out[:16] or [0]


def _params(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    stops = raw.get("stops")
    if isinstance(stops, list):
        try:
            out["stops"] = [min(1.0, max(0.0, float(x))) for x in stops][:16]
        except (TypeError, ValueError):
            pass
    for k in ("reverse", "mirror"):
        if raw.get(k):
            out[k] = True
    return out


def clean_section(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    kind = raw.get("type") if raw.get("type") in TYPES else "same"
    out = {"start": raw.get("start", 0), "type": kind}
    if kind == "pattern":
        out["pattern"] = PatternGenerator.normalize(raw.get("pattern", "solid"))
        if out["pattern"] == "paint":
            out["pattern"] = "solid"
        out["colors"] = _colors(raw.get("colors"))
        out["params"] = _params(raw.get("params"))
    elif kind == "effect":
        out["animation"] = animations.clean(raw.get("animation")) or animations.defaults("breathing")
        out["colors"] = _colors(raw.get("colors"))
        out["params"] = _params(raw.get("params"))
    elif kind == "sensor":
        sid = raw.get("sensor")
        out["sensor"] = sid if sensors.valid_id(sid) else "cpu_temp"
        out["show"] = raw.get("show") if raw.get("show") in SHOWS else "level"
        lo, hi = sensors.default_range(out["sensor"])
        out["min"], out["max"] = _num(raw.get("min"), lo), _num(raw.get("max"), hi)
        if out["max"] == out["min"]:
            out["max"] = out["min"] + 1
        out["palette"] = "colors" if raw.get("palette") == "colors" else "heat"
        out["colors"] = _colors(raw.get("colors"))
        out["background"] = "dim" if raw.get("background") == "dim" else "off"
        fa = raw.get("flash_above")
        out["flash_above"] = None if fa is None or isinstance(fa, bool) else _num(fa, None)
        rp = raw.get("params") or {}
        out["params"] = {"middle": True} if rp.get("middle") else {"reverse": True} if rp.get("reverse") else {}
    return out


def _num(v, default):
    if isinstance(v, bool):
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v if v == v and abs(v) < 1e6 else default


def clean(raw, led_count: int) -> List[dict]:
    """The zone's sections, valid and in order; [] when the strip isn't split."""
    if not isinstance(raw, list) or led_count < 1:
        return []
    by_start: Dict[int, dict] = {}
    for item in raw[:MAX_SECTIONS]:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item.get("start", 0))
        except (TypeError, ValueError):
            continue
        if not 0 <= start < led_count:
            continue
        by_start[start] = dict(clean_section(item), start=start)
    if not by_start:
        return []
    out = [by_start[k] for k in sorted(by_start)]
    if out[0]["start"] != 0:
        out.insert(0, {"start": 0, "type": "same"})
    if len(out) == 1 and out[0]["type"] == "same":
        return []
    return out


def clean_overrides(raw, led_count: int) -> Dict[int, str]:
    out: Dict[int, str] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in list(raw.items())[:MAX_OVERRIDES]:
        try:
            i = int(k)
        except (TypeError, ValueError):
            continue
        h = normalize_hex(v) if isinstance(v, str) else None
        if h and 0 <= i < led_count:
            out[i] = h
    return out


def overrides_for_config(ov: Dict[int, str]) -> Dict[str, str]:
    return {str(k): v for k, v in sorted(ov.items())}


def spans(sections: Sequence[dict], n: int) -> List[Tuple[int, int, dict]]:
    """(first LED, one past the last, section) for each part."""
    out = []
    for k, sec in enumerate(sections):
        end = sections[k + 1]["start"] if k + 1 < len(sections) else n
        a, b = min(sec["start"], n), min(end, n)
        if b > a:
            out.append((a, b, sec))
    return out


def has_effects(sections: Sequence[dict]) -> bool:
    return any(s["type"] == "effect" for s in sections)


def sensor_ids(sections: Sequence[dict]) -> List[str]:
    return sorted({s["sensor"] for s in sections if s["type"] == "sensor"})


def has_flash(sections: Sequence[dict], sensor: Callable[[str], Optional[float]]) -> bool:
    """A sensor part is over its flash level right now (it blinks, so it needs redrawing)."""
    for s in sections:
        if s["type"] == "sensor" and s.get("flash_above") is not None:
            v = sensor(s["sensor"])
            if v is not None and v >= s["flash_above"]:
                return True
    return False


def rescale(sections: Sequence[dict], overrides: Dict[int, str], old_n: int, new_n: int):
    """Keep parts where they were, in proportion, when the strip's LED count changes. Single LEDs keep
    their number (they mark a real LED) and are dropped past the new end."""
    if old_n < 1 or new_n < 1:
        return [], {}
    secs = []
    for s in sections:
        start = 0 if s["start"] == 0 else max(1, min(new_n - 1, round(s["start"] * new_n / old_n)))
        secs.append(dict(s, start=start))
    return clean(secs, new_n), {i: h for i, h in overrides.items() if i < new_n}


def even_starts(parts: int, n: int) -> List[int]:
    """Where each part starts when n LEDs are split as evenly as whole LEDs allow (the first parts take
    the leftover LEDs: 80 in 3 is 27 + 27 + 26)."""
    parts = max(1, min(parts, n))
    base, extra = divmod(n, parts)
    out, at = [], 0
    for k in range(parts):
        out.append(at)
        at += base + (1 if k < extra else 0)
    return out


def sizes(sections: Sequence[dict], n: int) -> List[int]:
    return [b - a for a, b, _s in spans(sections, n)]


def split_note(sz: Sequence[int], n: int) -> Optional[Tuple[str, int]]:
    """("uneven", leftover) when an even split can't be exact, ("near", spread) when the parts are
    1 or 2 LEDs apart but could match; None otherwise."""
    if len(sz) < 2:
        return None
    k = len(sz)
    even = [n // k + (1 if i < n % k else 0) for i in range(k)]
    if sorted(sz, reverse=True) == even:
        return ("uneven", n % k) if n % k else None
    spread = max(sz) - min(sz)
    return ("near", spread) if 0 < spread <= 2 else None


# ------------------------------------------------------------- drawing

Resolve = Callable[[list], List[str]]


def _section_colors(sec: dict, resolve: Resolve) -> List[str]:
    return resolve(sec.get("colors", [0])) or ["642107"]


Sensor = Callable[[str], Optional[float]]


def _ramp(cols: List[str], x: float) -> Tuple[int, int, int]:
    rgb = [animations.hex_to_rgb(c) for c in cols] or [(255, 255, 255)]
    if len(rgb) == 1:
        return rgb[0]
    x = min(1.0, max(0.0, x)) * (len(rgb) - 1)
    i = min(int(x), len(rgb) - 2)
    f = x - i
    a, b = rgb[i], rgb[i + 1]
    return (int(a[0] + (b[0] - a[0]) * f), int(a[1] + (b[1] - a[1]) * f), int(a[2] + (b[2] - a[2]) * f))


def _scale(c, k):
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


def sensor_level(sec: dict, value: Optional[float]) -> Optional[float]:
    """How full the part is, 0 to 1, or None without a reading."""
    if value is None:
        return None
    return min(1.0, max(0.0, (value - sec["min"]) / (sec["max"] - sec["min"])))


DIM_REST = 0.12          # "the rest of the bar dim": this much of the color


def sensor_part(sec: dict, length: int, value: Optional[float], resolve: Resolve, t: float = 0.0,
                levels: Optional[list] = None) -> List[tuple]:
    """A sensor part as (r, g, b): the reading's color, a level bar, or a bar in the reading's color.
    Over flash_above the LEDs blink once a second. No reading: one dim LED, so the part isn't
    mistaken for "0".

    With levels (a list as long as the part), the colors come back at full strength and how lit each
    LED is (0 to 1: the bar's tip partly, the dimmed rest) goes into levels instead, so color
    correction sees the real color: Palette snaps by hue, and snapped a dim LED to a full one."""
    if length <= 0:
        return []
    out, lv = _sensor_leds(sec, length, value, resolve, t)
    if levels is not None:
        levels[:] = lv
        return out
    return [c if f >= 1 else _scale(c, f) for c, f in zip(out, lv)]


def _sensor_leds(sec, length, value, resolve, t):
    level = sensor_level(sec, value)
    cols = HEAT if sec.get("palette") != "colors" else _section_colors(sec, resolve)
    spans_, total = _fill_spans(length, sec)
    if level is None:
        lv = [0.0] * length
        for i, (lo, _hi) in enumerate(spans_):
            if lo == 0:
                lv[i] = 0.15                        # where the bar starts (both middle LEDs, if even)
        return [_ramp(cols, 0.0)] * length, lv
    now_col = _ramp(cols, level)
    flash = sec.get("flash_above") is not None and value >= sec["flash_above"] and int(t * 2) % 2 == 1
    show = sec.get("show", "level")
    if show == "color":
        out, lv = [now_col] * length, [1.0] * length
    else:
        lit = level * total
        dim = DIM_REST if sec.get("background") == "dim" else 0.0
        out, lv = [], []
        for lo, hi in spans_:
            out.append(now_col if show == "both" else _ramp(cols, (lo + hi) / 2 / total))
            if hi <= lit:
                lv.append(1.0)
            elif lo < lit:
                lv.append(max(dim, (lit - lo) / (hi - lo)))   # the LED at the tip, partly on: smooth movement
            else:
                lv.append(dim)
    if flash:
        lv = [f * 0.15 for f in lv]
    return out, lv


def _fill_spans(n: int, sec: dict):
    """Which stretch of the bar each LED shows, measured from where the bar starts: ([(lo, hi)], the
    bar's whole length). From the start (or the other end): LED i is i to i+1 of n. From the middle the
    bar grows both ways at once, so the length is half the part: with an even number of LEDs the two in
    the middle share 0 to 1 and light together, with an odd number the middle one is half a step each
    way (0 to 0.5) and fills first."""
    p = sec.get("params") or {}
    if p.get("middle"):
        c = n / 2.0
        out = []
        for i in range(n):
            if i + 1 <= c:
                out.append((c - i - 1, c - i))
            elif i >= c:
                out.append((i - c, i + 1 - c))
            else:
                out.append((0.0, 0.5))
        return out, c
    out = [(float(i), float(i + 1)) for i in range(n)]
    if p.get("reverse"):
        out.reverse()
    return out, float(n)


def static_part(sec: dict, length: int, resolve: Resolve, patterns: Optional[PatternGenerator] = None,
                sensor: Optional[Sensor] = None, t: float = 0.0) -> Optional[List[str]]:
    """A part's hex colors when it doesn't move (an effect shows its first color, as a paused zone
    does); None for "same"."""
    kind = sec["type"]
    if kind == "same":
        return None
    if kind == "off":
        return [OFF] * length
    if kind == "sensor":
        v = sensor(sec["sensor"]) if sensor is not None else None
        return [animations.rgb_to_hex(c) for c in sensor_part(sec, length, v, resolve, t)]
    cols = _section_colors(sec, resolve)
    if kind == "effect":
        return [cols[0]] * length
    return (patterns or PatternGenerator()).generate(sec.get("pattern", "solid"), cols, length,
                                                    params=sec.get("params") or {}) or [cols[0]] * length


def compose_static(base: List[str], sections: Sequence[dict], overrides: Dict[int, str], resolve: Resolve,
                   patterns: Optional[PatternGenerator] = None, sensor: Optional[Sensor] = None,
                   t: float = 0.0, levels: Optional[list] = None) -> List[str]:
    """The whole strip's hex colors: base (what the strip shows) with each part and single LED on top.
    With levels (one 1.0 per LED), sensor parts come at full strength and their LEDs' levels go there
    (see sensor_part): the caller scales them after color correction."""
    out = list(base)
    n = len(out)
    for a, b, sec in spans(sections, n):
        if levels is not None and sec["type"] == "sensor":
            lv = []
            v = sensor(sec["sensor"]) if sensor is not None else None
            out[a:b] = [animations.rgb_to_hex(c) for c in sensor_part(sec, b - a, v, resolve, t, lv)]
            levels[a:b] = lv
            continue
        part = static_part(sec, b - a, resolve, patterns, sensor, t)
        if part is not None:
            out[a:b] = part
    for i, h in overrides.items():
        if 0 <= i < n:
            out[i] = h
            if levels is not None:
                levels[i] = 1.0
    return out


class Composer:
    """Per-frame drawing for an animated strip: static parts and single LEDs are worked out once,
    effect parts are drawn every frame over their own length. Works on (r, g, b) tuples."""

    def __init__(self, sections: Sequence[dict], overrides: Dict[int, str], n: int, resolve: Resolve,
                 seed: int = 0, patterns: Optional[PatternGenerator] = None, sensor: Optional[Sensor] = None):
        self.n = n
        self.fixed: List[Tuple[int, int, list]] = []
        self.moving = []
        self.readings = []                  # sensor parts: drawn every frame from the latest value
        self._sensor = sensor
        self._resolve = resolve
        for k, (a, b, sec) in enumerate(spans(sections, n)):
            if sec["type"] == "sensor":
                self.readings.append((a, b, sec))
            elif sec["type"] == "effect":
                p = sec.get("params") or {}
                cols = [animations.hex_to_rgb(c) for c in _section_colors(sec, resolve)]
                pos = animations.strip_positions(b - a, bool(p.get("reverse")), bool(p.get("mirror")))
                self.moving.append((a, b, sec["animation"], cols, pos, seed ^ (0x9E3779B1 * (k + 1) & 0xFFFFFFFF)))
            else:
                part = static_part(sec, b - a, resolve, patterns)
                if part is not None:
                    self.fixed.append((a, b, [animations.hex_to_rgb(c) for c in part]))
        self.single = [(i, animations.hex_to_rgb(h)) for i, h in sorted(overrides.items()) if 0 <= i < n]

    def frame(self, base: List[tuple], t: float, levels: Optional[list] = None) -> List[tuple]:
        """levels: as in compose_static (sensor parts at full strength, their LEDs' levels there)."""
        out = list(base)
        for a, b, part in self.fixed:
            out[a:b] = part
        for a, b, anim, cols, pos, seed in self.moving:
            out[a:b] = animations.render(anim["effect"], anim, b - a, t, cols, seed, pos)
        for a, b, sec in self.readings:
            v = self._sensor(sec["sensor"]) if self._sensor is not None else None
            if levels is None:
                out[a:b] = sensor_part(sec, b - a, v, self._resolve, t)
            else:
                lv = []
                out[a:b] = sensor_part(sec, b - a, v, self._resolve, t, lv)
                levels[a:b] = lv
        for i, c in self.single:
            out[i] = c
            if levels is not None:
                levels[i] = 1.0
        return out
