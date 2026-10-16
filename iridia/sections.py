"""Sections: one strip split into parts, each showing something of its own, plus single LEDs set by hand.

Stored per zone in config.json:

    "sections": [{"start": 0, "type": "same"},
                 {"start": 27, "type": "pattern", "pattern": "gradient", "colors": [0, "ff0000"],
                  "params": {"stops": [...], "reverse": false, "mirror": false}},
                 {"start": 54, "type": "effect", "animation": {"effect": "comet", ...}, "colors": [1]},
                 {"start": 70, "type": "off"}]
    "led_overrides": {"26": "ffffff", "53": "000000"}

`start` is the first LED of the part (0 based); a part runs to the next one's start. Types:
    same     what the whole strip shows there (its pattern or effect)
    pattern  a static pattern of its own, drawn over just that part
    effect   an animated effect of its own, over just that part
    off      dark
`colors` are entries like a zone's pattern_colors (a wallpaper color's index or a hex).
led_overrides set single LEDs to one color over everything else ("000000" is off).

Everything here is pure: the daemon and the window share it, so the preview is what the strip shows.
"""

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from iridia import animations
from iridia.colors import normalize_hex
from iridia.patterns import PatternGenerator

TYPES = ("same", "pattern", "effect", "off")
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
    return out


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


def static_part(sec: dict, length: int, resolve: Resolve, patterns: Optional[PatternGenerator] = None) -> \
        Optional[List[str]]:
    """A part's hex colors when it doesn't move (an effect shows its first color, as a paused zone
    does); None for "same"."""
    kind = sec["type"]
    if kind == "same":
        return None
    if kind == "off":
        return [OFF] * length
    cols = _section_colors(sec, resolve)
    if kind == "effect":
        return [cols[0]] * length
    return (patterns or PatternGenerator()).generate(sec.get("pattern", "solid"), cols, length,
                                                    params=sec.get("params") or {}) or [cols[0]] * length


def compose_static(base: List[str], sections: Sequence[dict], overrides: Dict[int, str], resolve: Resolve,
                   patterns: Optional[PatternGenerator] = None) -> List[str]:
    """The whole strip's hex colors: base (what the strip shows) with each part and single LED on top."""
    out = list(base)
    n = len(out)
    for a, b, sec in spans(sections, n):
        part = static_part(sec, b - a, resolve, patterns)
        if part is not None:
            out[a:b] = part
    for i, h in overrides.items():
        if 0 <= i < n:
            out[i] = h
    return out


class Composer:
    """Per-frame drawing for an animated strip: static parts and single LEDs are worked out once,
    effect parts are drawn every frame over their own length. Works on (r, g, b) tuples."""

    def __init__(self, sections: Sequence[dict], overrides: Dict[int, str], n: int, resolve: Resolve,
                 seed: int = 0, patterns: Optional[PatternGenerator] = None):
        self.n = n
        self.fixed: List[Tuple[int, int, list]] = []
        self.moving = []
        for k, (a, b, sec) in enumerate(spans(sections, n)):
            if sec["type"] == "effect":
                p = sec.get("params") or {}
                cols = [animations.hex_to_rgb(c) for c in _section_colors(sec, resolve)]
                pos = animations.strip_positions(b - a, bool(p.get("reverse")), bool(p.get("mirror")))
                self.moving.append((a, b, sec["animation"], cols, pos, seed ^ (0x9E3779B1 * (k + 1) & 0xFFFFFFFF)))
            else:
                part = static_part(sec, b - a, resolve, patterns)
                if part is not None:
                    self.fixed.append((a, b, [animations.hex_to_rgb(c) for c in part]))
        self.single = [(i, animations.hex_to_rgb(h)) for i, h in sorted(overrides.items()) if 0 <= i < n]

    def frame(self, base: List[tuple], t: float) -> List[tuple]:
        out = list(base)
        for a, b, part in self.fixed:
            out[a:b] = part
        for a, b, anim, cols, pos, seed in self.moving:
            out[a:b] = animations.render(anim["effect"], anim, b - a, t, cols, seed, pos)
        for i, c in self.single:
            out[i] = c
        return out
