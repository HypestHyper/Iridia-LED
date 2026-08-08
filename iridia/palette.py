"""48-color hue-bucketed palette with exact and interpolated mapping."""

import json
import os


DEFAULT_PALETTE = [
    (7.50, "ff0000", "Red"),
    (15.00, "ff0800", "Red-Orange"),
    (22.50, "ff1500", "Orange-Red"),
    (30.00, "ff2400", "Orange"),
    (37.50, "ff3300", "Orange-Amber"),
    (45.00, "ff4400", "Amber"),
    (52.50, "ff5500", "Amber-Gold"),
    (60.00, "ff6600", "Gold"),
    (67.50, "ff7700", "Gold-Yellow"),
    (75.00, "ff8800", "Yellow-Orange"),
    (82.50, "ff9900", "Yellow"),
    (90.00, "ffaa00", "Yellow-Lime"),
    (97.50, "ffbb00", "Lime-Yellow"),
    (105.00, "ffcc00", "Lime"),
    (112.50, "ffdd00", "Lime-Green"),
    (120.00, "ffee00", "Chartreuse"),
    (127.50, "eedd00", "Yellow-Green"),
    (135.00, "ccdd00", "Green-Yellow"),
    (142.50, "aacc00", "Spring Green"),
    (150.00, "88bb00", "Green"),
    (157.50, "66aa00", "Forest Green"),
    (165.00, "44aa00", "Emerald"),
    (172.50, "22aa00", "Jade"),
    (180.00, "00aa22", "Green-Cyan"),
    (187.50, "00aa44", "Cyan-Green"),
    (195.00, "00aa66", "Teal"),
    (202.50, "00aa88", "Sea Green"),
    (210.00, "0099aa", "Cyan"),
    (217.50, "0088aa", "Sky Blue"),
    (225.00, "0077aa", "Azure"),
    (232.50, "0066aa", "Blue"),
    (240.00, "0055aa", "Royal Blue"),
    (247.50, "0044aa", "Deep Blue"),
    (255.00, "0033aa", "Navy"),
    (262.50, "0022aa", "Indigo"),
    (270.00, "1111aa", "Violet"),
    (277.50, "2200aa", "Purple"),
    (285.00, "3300aa", "Magenta-Purple"),
    (292.50, "4400aa", "Magenta"),
    (300.00, "5500aa", "Fuchsia"),
    (307.50, "6600aa", "Hot Pink"),
    (315.00, "7700aa", "Pink"),
    (322.50, "8800aa", "Rose"),
    (330.00, "9900aa", "Rose-Red"),
    (337.50, "aa00aa", "Magenta-Red"),
    (345.00, "bb00aa", "Crimson"),
    (352.50, "cc00aa", "Ruby"),
    (360.00, "dd0088", "Magenta-Pink"),
]


def _hex_to_hue(hex_color: str) -> float:
    """Convert hex to HSL hue (0-360)."""
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx - mn
    if df == 0:
        return 0.0
    if mx == r:
        h = (60 * ((g - b) / df) + 360) % 360
    elif mx == g:
        h = (60 * ((b - r) / df) + 120) % 360
    else:
        h = (60 * ((r - g) / df) + 240) % 360
    return h


def _hue_diff(a: float, b: float) -> float:
    """Shortest distance between two hues on the 0-360 circle."""
    d = abs(a - b)
    return min(d, 360 - d)


def _blend_hex(c1: str, c2: str, t: float) -> str:
    """Linear blend between two hex colors. t=0 -> c1, t=1 -> c2."""
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"{r:02x}{g:02x}{b:02x}"


class Palette:
    """Editable 48-color hue palette."""

    def __init__(self, path: str = "~/.config/iridia/palette.json"):
        self.path = os.path.expanduser(path)
        self.colors = []  # list of (hue, hex, name)
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                self.colors = [
                    (c["hue"], c["hex"].lower(), c["name"])
                    for c in data
                ]
            except (json.JSONDecodeError, KeyError, OSError):
                self.colors = list(DEFAULT_PALETTE)
                self._save()
        else:
            self.colors = list(DEFAULT_PALETTE)
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = [{"hue": h, "hex": c, "name": n} for h, c, n in self.colors]
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def reset(self):
        """Reset to factory defaults."""
        self.colors = list(DEFAULT_PALETTE)
        self._save()

    def update(self, index: int, hex_color: str, name: str = None):
        """Update a single palette entry."""
        if 0 <= index < len(self.colors):
            h = self.colors[index][0]
            n = name if name else self.colors[index][2]
            self.colors[index] = (h, hex_color.lower(), n)
            self._save()

    def nearest(self, hex_color: str) -> str:
        """Find nearest palette entry by hue. Returns hex string."""
        hue = _hex_to_hue(hex_color)
        best = self.colors[0]
        best_dist = float("inf")
        for h, c, n in self.colors:
            d = _hue_diff(hue, h)
            if d < best_dist:
                best_dist = d
                best = (h, c, n)
        return best[1]

    def nearest_interpolated(self, hex_color: str) -> str:
        """Blend two nearest palette entries by hue, then snap to nearest."""
        hue = _hex_to_hue(hex_color)

        # Sort by hue proximity
        by_dist = sorted(self.colors, key=lambda x: _hue_diff(hue, x[0]))
        c1, c2 = by_dist[0], by_dist[1]

        d1 = _hue_diff(hue, c1[0])
        d2 = _hue_diff(hue, c2[0])
        total = d1 + d2
        if total == 0:
            return c1[1]

        # Inverse distance weighting
        w1 = d2 / total
        w2 = d1 / total

        blended = _blend_hex(c1[1], c2[1], w2)
        return self.nearest(blended)
