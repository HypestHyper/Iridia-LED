"""Material 3 dark colour scheme derived from one seed colour (the LED colour).

Pure functions only: the GTK window turns the palette into CSS (iridia/ui/style.py).
"""

import colorsys

DEFAULT_SEED = "4f7bff"      # before there is a wallpaper: a cool blue


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
    # Surfaces and text are a near-neutral grey (a hint of the seed's hue, never a brown or blue wash):
    # the wall the lights glow on. The seed's colour is kept for the few things that are light.
    ns = 0.05
    return {
        "SURFACE_DIM": _hsl(hue, ns, 0.072),
        "SURFACE_CONTAINER_LOWEST": _hsl(hue, ns, 0.055),
        "SURFACE_CONTAINER_LOW": _hsl(hue, ns, 0.092),
        "SURFACE_CONTAINER": _hsl(hue, ns, 0.115),
        "SURFACE_CONTAINER_HIGH": _hsl(hue, ns, 0.150),
        "SURFACE_CONTAINER_HIGHEST": _hsl(hue, ns, 0.185),
        "SURFACE_BRIGHT": _hsl(hue, ns, 0.225),
        "PRIMARY": _hsl(hue, sat, 0.68),
        "ON_PRIMARY": _hsl(hue, sat, 0.12),
        "PRIMARY_HOVER": _hsl(hue, sat, 0.76),
        "PRIMARY_CONTAINER": _hsl(hue, sat * 0.55, 0.22),
        "ON_PRIMARY_CONTAINER": _hsl(hue, sat, 0.86),
        "SECONDARY_CONTAINER": _hsl(hue, 0.06, 0.205),
        "SECONDARY_CONTAINER_HOVER": _hsl(hue, 0.07, 0.25),
        "ON_SECONDARY_CONTAINER": _hsl(hue, 0.05, 0.90),
        "TERTIARY": _hsl(hue + 0.17, 0.45, 0.72),
        "TERTIARY_CONTAINER": _hsl(hue + 0.17, 0.20, 0.25),
        "ON_TERTIARY_CONTAINER": _hsl(hue + 0.17, 0.35, 0.88),
        "ERROR": "#f2a49a",
        "ERROR_CONTAINER": "#4a2622",
        "ERROR_HOVER": "#5c2d28",
        "ON_ERROR_CONTAINER": "#f6cdc7",
        "ON_SURFACE": _hsl(hue, 0.04, 0.905),
        "ON_SURFACE_VARIANT": _hsl(hue, 0.05, 0.69),
        "OUTLINE": _hsl(hue, 0.05, 0.57),      # small grey help text: at least 5:1 on every surface
        "OUTLINE_VARIANT": _hsl(hue, 0.05, 0.24),
        "GRID": _hsl(hue, 0.05, 0.16),
        "INVERSE_SURFACE": _hsl(hue, 0.04, 0.89),
        "INVERSE_ON_SURFACE": _hsl(hue, 0.05, 0.16),
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
