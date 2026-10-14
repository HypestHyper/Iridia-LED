"""Material 3 dark colour scheme derived from one seed colour (the LED colour).

Pure functions only: the GTK window turns the palette into CSS (iridia/ui/style.py).
"""

import colorsys

DEFAULT_SEED = "53dbb0"


def _hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#%02x%02x%02x" % (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def clean_seed(seed_hex: str) -> str:
    h = (seed_hex or DEFAULT_SEED).lstrip("#").lower()
    if len(h) != 6 or any(c not in "0123456789abcdef" for c in h):
        return DEFAULT_SEED
    return h


def palette_for(seed_hex: str) -> dict:
    """Every colour role, as '#rrggbb'. Hue comes from the seed; saturation is
    clamped so grey or near-white seeds still give a usable accent."""
    h = clean_seed(seed_hex)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, _light, sat = colorsys.rgb_to_hls(r, g, b)
    sat = max(0.45, min(0.85, sat))
    ns = 0.14  # neutral tint strength
    return {
        "SURFACE_DIM": _hsl(hue, ns, 0.065),
        "SURFACE_CONTAINER_LOWEST": _hsl(hue, ns, 0.05),
        "SURFACE_CONTAINER_LOW": _hsl(hue, ns, 0.095),
        "SURFACE_CONTAINER": _hsl(hue, ns, 0.115),
        "SURFACE_CONTAINER_HIGH": _hsl(hue, ns, 0.15),
        "SURFACE_CONTAINER_HIGHEST": _hsl(hue, ns, 0.19),
        "SURFACE_BRIGHT": _hsl(hue, ns, 0.23),
        "PRIMARY": _hsl(hue, sat, 0.66),
        "ON_PRIMARY": _hsl(hue, sat, 0.12),
        "PRIMARY_HOVER": _hsl(hue, sat, 0.74),
        "PRIMARY_CONTAINER": _hsl(hue, sat * 0.8, 0.24),
        "ON_PRIMARY_CONTAINER": _hsl(hue, sat, 0.84),
        "SECONDARY_CONTAINER": _hsl(hue, 0.20, 0.26),
        "SECONDARY_CONTAINER_HOVER": _hsl(hue, 0.22, 0.31),
        "ON_SECONDARY_CONTAINER": _hsl(hue, 0.25, 0.88),
        "TERTIARY": _hsl(hue + 0.17, 0.45, 0.72),
        "TERTIARY_CONTAINER": _hsl(hue + 0.17, 0.25, 0.28),
        "ON_TERTIARY_CONTAINER": _hsl(hue + 0.17, 0.35, 0.88),
        "ERROR": "#ffb4ab",
        "ERROR_CONTAINER": "#93000a",
        "ERROR_HOVER": "#b3261e",
        "ON_ERROR_CONTAINER": "#ffdad6",
        "ON_SURFACE": _hsl(hue, 0.10, 0.90),
        "ON_SURFACE_VARIANT": _hsl(hue, 0.08, 0.76),
        "OUTLINE": _hsl(hue, 0.07, 0.57),
        "OUTLINE_VARIANT": _hsl(hue, 0.09, 0.27),
        "GRID": _hsl(hue, 0.10, 0.17),
        "INVERSE_SURFACE": _hsl(hue, 0.10, 0.89),
        "INVERSE_ON_SURFACE": _hsl(hue, 0.12, 0.18),
        "INVERSE_PRIMARY": _hsl(hue, sat, 0.38),
        "SEED": "#" + h,
    }


def mix(a: str, b: str, t: float) -> str:
    """Blend two '#rrggbb' colours (t=0 -> a, t=1 -> b)."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(ca, cb))


def mix_palette(old: dict, new: dict, t: float) -> dict:
    return {k: mix(old.get(k, v), v, t) for k, v in new.items()}


def seed_distance(a: str, b: str) -> float:
    ra = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    rb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5


def hex_rgb(h: str):
    """'#rrggbb' or 'rrggbb' -> (r, g, b) floats 0..1 (for cairo)."""
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
