"""Animated effects.

Every effect is a pure function of time:

    render(effect, params, n, t, colors, seed=0, positions=None, base=None) -> [(r, g, b), ...]

- t is seconds on a shared clock, so a dropped frame never slows an effect down.
- colors are the zone's colors as (r, g, b) tuples (wallpaper picks, saved or exact colors).
  Rainbow effects ignore them.
- seed makes random-looking effects (embers, sparkles) differ between zones while staying the
  same for a given t, so the window's preview matches the LEDs.
- positions is where each LED sits along the effect, in LEDs (default 0, 1, 2, ...). Reverse,
  mirror and "follow the layout" are all just different positions.
- base is the zone's static pattern (what it shows without an animation); breathing and fill
  use it, so a gradient zone breathes as a gradient.

The output is at full brightness. Brightness (monitor, manual, night cap) and color correction
are applied afterwards, by the daemon, to every frame.
"""

import colorsys
import math
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

RGB = Tuple[int, int, int]

# effect -> {param: (kind, default, low, high) or ("choice", default, options) or ("bool", default)}
EFFECTS: Dict[str, Dict[str, tuple]] = {
    "breathing": {
        "speed": ("float", 4.0, 0.5, 30.0),          # seconds per breath
        "min": ("int", 10, 0, 100),                  # % of the zone's brightness
        "max": ("int", 100, 0, 100),
        "easing": ("choice", "sine", ("sine", "smooth", "sharp")),
        "cycle_colors": ("bool", True),              # next color at each dark point
    },
    "comet": {
        "speed": ("float", 30.0, 1.0, 300.0),        # LEDs per second
        "tail": ("int", 12, 1, 200),                 # LEDs
        "heads": ("int", 1, 1, 10),
        "spacing": ("int", 0, 0, 500),               # LEDs between heads, 0 = spread evenly
        "bounce": ("bool", False),
        "reverse": ("bool", False),
        "background": ("choice", "off", ("off", "dim", "second")),
    },
    "fill": {
        "speed": ("float", 20.0, 1.0, 300.0),        # LEDs per second
        "pause": ("float", 1.0, 0.0, 10.0),          # seconds full and empty
        "origin": ("choice", "start", ("start", "end", "center")),
        "empty": ("choice", "reverse", ("reverse", "same", "reset")),
    },
    "embers": {
        "speed": ("float", 0.4, 0.05, 3.0),          # how fast a point changes
        "density": ("int", 35, 0, 100),              # % of points changing at once
        "softness": ("int", 50, 0, 100),             # blend with neighbours
        "flicker": ("int", 20, 0, 100),
        "palette": ("choice", "zone", ("zone", "warm")),  # the zone's colors, or fire colors
    },
    "rainbow": {
        "speed": ("float", 20.0, 0.0, 300.0),        # LEDs per second
        "width": ("int", 120, 4, 1000),              # LEDs per full rainbow
        "saturation": ("int", 100, 0, 100),
        "reverse": ("bool", False),
    },
    "rainbow_vomit": {
        "speed": ("float", 60.0, 0.0, 400.0),
        "chaos": ("int", 50, 0, 100),                # sparkle amount
        "width": ("int", 40, 4, 1000),
    },
    "color_cycle": {
        "speed": ("float", 3.0, 0.2, 120.0),         # seconds to fade to the next color
        "hold": ("float", 2.0, 0.0, 120.0),          # seconds on each color
    },
}
COMMON: Dict[str, tuple] = {
    "follow_layout": ("bool", False),                # run through 2D space on the Layout tab
    "angle": ("int", 0, 0, 359),                     # direction for follow_layout, 0 = left to right
    "sync": ("bool", True),                          # same clock as other zones with this effect
}
ORDER = ["breathing", "comet", "fill", "embers", "rainbow", "rainbow_vomit", "color_cycle"]
WARM = [(110, 8, 0), (200, 32, 0), (255, 80, 0), (255, 150, 18)]   # glowing to hot: deep red to amber
OFF: RGB = (0, 0, 0)


def clean(anim) -> Optional[dict]:
    """A zone's "animation" setting with every value valid; None when the zone is static."""
    if not isinstance(anim, dict):
        return None
    effect = anim.get("effect")
    if effect not in EFFECTS:
        return None
    out = {"effect": effect}
    for key, spec in list(EFFECTS[effect].items()) + list(COMMON.items()):
        out[key] = _value(anim.get(key), spec)
    if effect == "breathing" and out["min"] > out["max"]:
        out["min"], out["max"] = out["max"], out["min"]
    return out


def defaults(effect: str) -> dict:
    return clean({"effect": effect}) or {}


def _value(v, spec):
    kind, default = spec[0], spec[1]
    if kind == "bool":
        return v if isinstance(v, bool) else default
    if kind == "choice":
        return v if v in spec[2] else default
    lo, hi = spec[2], spec[3]
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    x = max(lo, min(hi, x))
    return int(round(x)) if kind == "int" else x


# ------------------------------------------------------------------ helpers

def _hash(a: int, b: int = 0, c: int = 0) -> float:
    """A repeatable pseudo-random number in [0, 1) for three integers."""
    h = (a * 73856093 ^ b * 19349663 ^ c * 83492791) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 3266489917) & 0xFFFFFFFF
    h ^= h >> 16
    return h / 4294967296.0


@lru_cache(maxsize=65536)
def _lattice(seed: int, i: int, k: int) -> float:
    return _hash(seed, i, k)


def _noise(seed: int, i: int, x: float) -> float:
    """Smooth 1D value noise in [0, 1] along x, different for each (seed, i). The lattice values
    are cached: for slow effects they change a few times per second, not every frame."""
    k = math.floor(x)
    f = x - k
    f = f * f * (3 - 2 * f)
    a = _lattice(seed, i, k)
    return a + (_lattice(seed, i, k + 1) - a) * f


@lru_cache(maxsize=64)
def _offsets(seed: int, n: int) -> Tuple[float, ...]:
    return tuple(_hash(seed, i, 7) * 50 for i in range(n))


@lru_cache(maxsize=64)
def _wobble(seed: int, n: int) -> Tuple[Tuple[float, float, float, float], ...]:
    """Per LED: two frequencies and phases for a cheap, irregular wobble (sums of sines)."""
    return tuple((1.3 + 2.1 * _hash(seed, i, 11), 6.283 * _hash(seed, i, 12),
                  2.9 + 3.7 * _hash(seed, i, 13), 6.283 * _hash(seed, i, 14)) for i in range(n))


def _mix_light(a: RGB, b: RGB, t: float) -> RGB:
    """Blend in light (roughly squared values), not in the numbers sent: red to green passes
    through a clear yellow instead of a dark, muddy one."""
    return (int(math.sqrt(a[0] * a[0] + (b[0] * b[0] - a[0] * a[0]) * t) + 0.5),
            int(math.sqrt(a[1] * a[1] + (b[1] * b[1] - a[1] * a[1]) * t) + 0.5),
            int(math.sqrt(a[2] * a[2] + (b[2] * b[2] - a[2] * a[2]) * t) + 0.5))


@lru_cache(maxsize=64)
def _drift(seed: int, n: int) -> Tuple[Tuple[float, float], ...]:
    """Per LED: where it starts among the colors and how fast it moves through them."""
    return tuple((_hash(seed, i, 21), 0.6 + 0.8 * _hash(seed, i, 22)) for i in range(n))


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return (int(a[0] + (b[0] - a[0]) * t + 0.5), int(a[1] + (b[1] - a[1]) * t + 0.5),
            int(a[2] + (b[2] - a[2]) * t + 0.5))


def _scale(c: RGB, k: float) -> RGB:
    return (int(c[0] * k + 0.5), int(c[1] * k + 0.5), int(c[2] * k + 0.5))


_HUES: Dict[int, List[RGB]] = {}


def hue_table(saturation: int) -> List[RGB]:
    """360 fully bright colors around the hue circle, at this saturation (0..100)."""
    tab = _HUES.get(saturation)
    if tab is None:
        s = saturation / 100.0
        tab = [tuple(int(c * 255 + 0.5) for c in colorsys.hsv_to_rgb(h / 360.0, s, 1.0)) for h in range(360)]
        _HUES[saturation] = tab
    return tab


def _positions(n: int, positions) -> Sequence[float]:
    return positions if positions is not None and len(positions) == n else range(n)


def _span(pos: Sequence[float], p: dict) -> Tuple[float, float]:
    """(start, length) the effect runs over: these LEDs, or the shared extent of every strip that
    follows the layout (so one comet or fill travels through all of them)."""
    if p.get("_extent"):
        return p["_extent"]
    lo, hi = min(pos), max(pos)
    return lo, max(1.0, hi - lo + 1)


# ------------------------------------------------------------------ effects

def _breathing(p, n, t, colors, seed, pos, base):
    phase = (t / p["speed"]) % 1.0
    tri = 1 - abs(1 - 2 * phase)                       # 0 at the dark point, 1 at the top
    if p["easing"] == "sine":
        shape = 0.5 - 0.5 * math.cos(2 * math.pi * phase)
    elif p["easing"] == "smooth":
        shape = tri * tri * (3 - 2 * tri)
    else:
        shape = tri
    # move evenly for the eye: LEDs look brighter than their numbers near the dark end, so go
    # through the range in square-root steps (the ends stay exactly min and max)
    lo, hi = math.sqrt(p["min"] / 100.0), math.sqrt(p["max"] / 100.0)
    level = (lo + (hi - lo) * shape) ** 2
    if p["cycle_colors"] and len(colors) > 1:
        c = colors[int(t // p["speed"]) % len(colors)]
        return [_scale(c, level)] * n
    return [_scale(c, level) for c in base]


def _comet(p, n, t, colors, seed, pos, base):
    lo, length = _span(pos, p)
    tail, heads = p["tail"], p["heads"]
    gap = p["spacing"] or (length + tail) / heads
    travel = p["speed"] * t
    head_cols = colors or [(255, 255, 255)]
    if p["background"] == "dim":
        bg = [_scale(head_cols[0], 0.08)] * n
    elif p["background"] == "second" and len(head_cols) > 1:
        bg = [_scale(head_cols[1], 0.35)] * n
    else:
        bg = [OFF] * n
    out = list(bg)
    level = [0.0] * n
    which = [0] * n
    for h in range(heads):
        x = travel + h * gap
        if p["bounce"]:
            period = 2 * (length - 1) if length > 1 else 1
            m = x % period
            fwd = m < length - 1
            hx = m if fwd else period - m
        else:
            hx = x % (length + tail) - tail / 2.0
            fwd = True
        if p["reverse"]:
            hx, fwd = length - 1 - hx, not fwd
        for i, px in enumerate(pos):
            d = (hx - (px - lo)) if fwd else ((px - lo) - hx)
            if -1.0 < d < tail:
                # the head lights the LED it's coming to in step with its position, so it glides
                # instead of hopping from LED to LED
                v = 1.0 + d if d < 0 else (1 - d / tail) ** 2
                if v > level[i]:
                    level[i], which[i] = v, h
    for i in range(n):
        if level[i] > 0:
            out[i] = _mix(bg[i], head_cols[which[i] % len(head_cols)], level[i])
    return out


def _fill(p, n, t, colors, seed, pos, base):
    lo, length = _span(pos, p)
    grow = length / p["speed"]
    shrink = 0.0 if p["empty"] == "reset" else grow
    pause = p["pause"]
    cycle = grow + pause + shrink + pause
    m = t % cycle
    if m < grow:
        front, emptying = m / grow, False
    elif m < grow + pause:
        front, emptying = 1.0, False
    elif m < grow + pause + shrink:
        front, emptying = 1 - (m - grow - pause) / shrink, True
    else:
        front, emptying = 0.0, False
    out = []
    for i, px in enumerate(pos):
        x = (px - lo + 0.5) / length                     # 0..1 along the strip
        if p["origin"] == "end":
            x = 1 - x
        elif p["origin"] == "center":
            x = abs(x - 0.5) * 2
        if emptying and p["empty"] == "same":
            on = x > 1 - front                           # the lit part leaves from the far end
        else:
            on = x <= front
        if on:
            out.append(base[i])
        else:
            # one LED of soft edge, so the front moves smoothly
            edge = (x - front) * length if not (emptying and p["empty"] == "same") else ((1 - front) - x) * length
            out.append(_scale(base[i], max(0.0, 1 - edge)) if 0 < edge < 1 else OFF)
    return out


def _embers(p, n, t, colors, seed, pos, base):
    """Each point glows up and dies down on its own. With the zone's colors every point drifts
    slowly through them; with fire colors a hotter point is also yellower."""
    fire = p["palette"] == "warm" or not colors
    pal = WARM if fire else colors
    lin = [(r * r, g * g, b * b) for r, g, b in pal]     # blend in light, see _mix_light
    npal = len(lin)
    rest = 0.3 if fire else 0.22                         # a resting ember still glows a little
    dens = p["density"] / 100.0
    flick = p["flicker"] / 200.0
    s = p["speed"]
    t = math.floor(t * 20) / 20.0               # slow effect: 20 steps a second are plenty
    offs = _offsets(seed, n)
    wob = _wobble(seed, n) if flick else None
    drift = _drift(seed, n) if not fire and npal > 1 else None
    ts = t * s
    floor = math.floor
    lat = _lattice
    sin = math.sin
    sqrt = math.sqrt
    top = npal - 1
    vals = []
    for i in range(n):
        x = ts + offs[i]
        k = floor(x)
        f = x - k
        f = f * f * (3 - 2 * f)
        a = lat(seed, i, k)
        a += (lat(seed, i, k + 1) - a) * f
        heat = (a - (1 - dens)) / dens if dens > 0 else 0.0
        heat = 0.0 if heat < 0 else (1.0 if heat > 1 else heat * heat * (3 - 2 * heat))
        if fire:
            c = heat * top                               # hotter: further along deep red to amber
        elif drift is not None:
            ph, rate = drift[i]
            c = (ph * npal + ts * 0.35 * rate) % npal    # wanders through the colors
        else:
            c = 0.0
        j = int(c)
        f = c - j
        r0, g0, b0 = lin[j % npal]
        r1, g1, b1 = lin[(j + 1) % npal] if not fire else lin[min(j + 1, top)]
        m = rest + (1 - rest) * heat
        if flick:
            f1, p1, f2, p2 = wob[i]
            m *= 1 - flick * (0.5 + 0.25 * (sin(t * f1 + p1) + sin(t * f2 + p2)))
        vals.append((sqrt(r0 + (r1 - r0) * f) * m, sqrt(g0 + (g1 - g0) * f) * m, sqrt(b0 + (b1 - b0) * f) * m))
    k = p["softness"] / 150.0
    if k <= 0 or n < 3:
        return [(int(r + 0.5), int(g + 0.5), int(b + 0.5)) for r, g, b in vals]
    h, out = k / 2, []
    last = n - 1
    for i in range(n):
        ar, ag, ab = vals[i - 1] if i else vals[i]
        br, bg, bb = vals[i + 1] if i < last else vals[i]
        cr, cg, cb = vals[i]
        out.append((int(cr * (1 - k) + (ar + br) * h + 0.5), int(cg * (1 - k) + (ag + bg) * h + 0.5),
                    int(cb * (1 - k) + (ab + bb) * h + 0.5)))
    return out


def _rainbow(p, n, t, colors, seed, pos, base):
    tab = hue_table(p["saturation"])
    off = p["speed"] * t * (-1 if p["reverse"] else 1)
    w = p["width"]
    return [tab[int(((px - off) / w) * 360) % 360] for px in pos]


def _rainbow_vomit(p, n, t, colors, seed, pos, base):
    tab = hue_table(100)
    w = p["width"]
    # uneven speed, so it never looks regular
    off = p["speed"] * t + 0.4 * p["speed"] * math.sin(0.7 * t) + 0.25 * p["speed"] * math.sin(1.9 * t + 1.3)
    chaos = p["chaos"] / 100.0
    jit = 40 * chaos
    rate = 6.0
    slot = math.floor(t * rate)
    fade = 1 - (t * rate - slot)
    spark_p = chaos * 0.12
    wob = _wobble(seed, n) if jit else None
    sin = math.sin
    out = []
    for i, px in enumerate(pos):
        h = ((px - off) / w) * 360
        if jit:
            f1, p1, f2, p2 = wob[i]
            h += jit * 0.25 * (sin(t * f1 + p1) + sin(t * f2 + p2))
        c = tab[int(h) % 360]
        if spark_p and _lattice(seed, i, slot) < spark_p:
            sr, sg, sb = tab[int(_lattice(seed + 3, i, slot) * 360)]
            sr, sg, sb = sr + (255 - sr) * 0.35, sg + (255 - sg) * 0.35, sb + (255 - sb) * 0.35
            c = (int(c[0] + (sr - c[0]) * fade + 0.5), int(c[1] + (sg - c[1]) * fade + 0.5),
                 int(c[2] + (sb - c[2]) * fade + 0.5))
        out.append(c)
    return out


def _color_cycle(p, n, t, colors, seed, pos, base):
    cols = colors or [(255, 255, 255)]
    if len(cols) == 1:
        return [cols[0]] * n
    step = p["hold"] + p["speed"]
    k = int(t // step)
    m = t - k * step
    a, b = cols[k % len(cols)], cols[(k + 1) % len(cols)]
    if m < p["hold"]:
        return [a] * n
    f = (m - p["hold"]) / p["speed"]
    return [_mix_light(a, b, 0.5 - 0.5 * math.cos(math.pi * f))] * n


_RENDER = {"breathing": _breathing, "comet": _comet, "fill": _fill, "embers": _embers, "rainbow": _rainbow,
           "rainbow_vomit": _rainbow_vomit, "color_cycle": _color_cycle}


def render(effect: str, params: dict, n: int, t: float, colors: Sequence[RGB], seed: int = 0,
           positions: Optional[Sequence[float]] = None, base: Optional[Sequence[RGB]] = None,
           extent: Optional[Tuple[float, float]] = None) -> List[RGB]:
    """One frame of an effect: n (r, g, b) tuples at full brightness. extent: (start, length) in
    position units when several strips share one effect (follow the layout)."""
    if n <= 0:
        return []
    p = params if params.get("effect") == effect and "speed" in params else (clean(dict(params, effect=effect))
                                                                            or defaults(effect))
    cols = [tuple(c) for c in colors] if colors else []
    if base is None or len(base) != n:
        base = [cols[0] if cols else (255, 255, 255)] * n
    if extent and extent[1] > 0:
        p = dict(p, _extent=(float(extent[0]), float(extent[1])))
    return _RENDER[effect](p, n, max(0.0, t), cols, seed, _positions(n, positions), base)


# ------------------------------------------------------------- positions

def strip_positions(n: int, reverse: bool = False, mirror: bool = False) -> List[float]:
    """Positions along one strip: reverse runs it from the other end, mirror from both ends in."""
    pos = [float(i) for i in range(n)]
    if mirror:
        pos = [float(min(i, n - 1 - i)) for i in range(n)]
    if reverse:
        top = max(pos) if pos else 0
        pos = [top - x for x in pos]
    return pos


def layout_positions(points: Sequence[Tuple[float, float]], angle_deg: float, spacing: float) -> List[float]:
    """Positions for LEDs placed on the Layout tab: each one's distance along the direction
    (0 degrees = left to right), in LEDs (spacing = distance between neighbouring LEDs)."""
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)
    sp = spacing if spacing > 0 else 1.0
    return [(x * ux + y * uy) / sp for x, y in points]


def hex_to_rgb(h: str) -> RGB:
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(c: RGB) -> str:
    return "%02x%02x%02x" % c
