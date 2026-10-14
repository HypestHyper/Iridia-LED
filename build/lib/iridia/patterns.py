"""Static LED layouts.

Every pattern is a pure function of (colors, led_count, params) and
returns one hex colour per LED. Animated patterns were removed: OpenRGB
plus USB controllers can't deliver frames fast enough to look smooth.

params (all optional, stored per zone as ``pattern_params``):
    stops    list of floats in 0..1
               segments / center_out / edges_in : n-1 boundaries between colours
               gradient                         : n positions, one per colour
             Wrong-length lists fall back to even spacing, so changing the
             number of selected colours never breaks a zone.
    reverse  bool, flip the strip end for end
    mirror   bool, draw the pattern on the first half and mirror it onto the second
    paint    list of hex strings (or null), used by the "paint" pattern; null LEDs show the zone's colour
"""

from typing import List, Optional

from iridia.colors import normalize_hex

ANIMATED_PATTERNS: set = set()          # kept for old callers
OFF = "000000"


def _lerp_hex(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = int(round(r1 + (r2 - r1) * t))
    g = int(round(g1 + (g2 - g1) * t))
    b = int(round(b1 + (b2 - b1) * t))
    return f"{r:02x}{g:02x}{b:02x}"


def even_boundaries(n_colors: int) -> List[float]:
    return [k / n_colors for k in range(1, n_colors)]


def even_positions(n_colors: int) -> List[float]:
    return [k / (n_colors - 1) for k in range(n_colors)] if n_colors > 1 else [0.0]


def _clean_stops(stops, want: int, default: List[float]) -> List[float]:
    try:
        vals = [min(1.0, max(0.0, float(x))) for x in (stops or [])]
    except (TypeError, ValueError):
        return default
    if len(vals) != want:
        return default
    return sorted(vals)


class PatternGenerator:
    PATTERNS = ["solid", "gradient", "segments", "center_out", "edges_in", "alternating", "paint"]
    LABELS = {"center_out": "center out", "edges_in": "edges in"}
    # Patterns whose boundaries can be moved in the strip editor, and how many handles.
    EDITABLE = {"segments": "boundaries", "center_out": "boundaries", "edges_in": "boundaries",
                "gradient": "positions"}

    def is_animated(self, pattern: str) -> bool:
        return False

    @classmethod
    def normalize(cls, pattern: str) -> str:
        """Unknown/removed patterns (breathing, rainbow, ...) become solid."""
        return pattern if pattern in cls.PATTERNS else "solid"

    @classmethod
    def handle_count(cls, pattern: str, n_colors: int) -> int:
        kind = cls.EDITABLE.get(pattern)
        if not kind or n_colors < 2:
            return 0
        return n_colors if kind == "positions" else n_colors - 1

    @classmethod
    def default_stops(cls, pattern: str, n_colors: int) -> List[float]:
        kind = cls.EDITABLE.get(pattern)
        if kind == "positions":
            return even_positions(n_colors)
        if kind == "boundaries":
            return even_boundaries(n_colors)
        return []

    def generate(self, pattern: str, colors: List[str], led_count: int, t: float = 0.0,
                 params: Optional[dict] = None) -> List[str]:
        if led_count <= 0:
            return []
        params = params if isinstance(params, dict) else {}
        pattern = self.normalize(pattern)
        if pattern == "paint":
            out = self._paint(led_count, params, colors[0] if colors else OFF)
        else:
            if not colors:
                colors = ["642107"]
            shape = getattr(self, f"_{pattern}")
            if params.get("mirror") and led_count > 1:
                half = (led_count + 1) // 2
                base = shape(colors, half, params)
                out = base + base[:led_count - half][::-1]
            else:
                out = shape(colors, led_count, params)
        if params.get("reverse"):
            out = out[::-1]
        return out

    # ---------------------------------------------------------------- shapes
    def _solid(self, colors, n, params):
        return [colors[0]] * n

    def _segments(self, colors, n, params):
        if len(colors) == 1:
            return [colors[0]] * n
        b = _clean_stops(params.get("stops"), len(colors) - 1, even_boundaries(len(colors)))
        out = []
        for i in range(n):
            pos = (i + 0.5) / n
            k = sum(1 for x in b if pos >= x)
            out.append(colors[min(k, len(colors) - 1)])
        return out

    def _gradient(self, colors, n, params):
        if len(colors) == 1:
            return [colors[0]] * n
        p = _clean_stops(params.get("stops"), len(colors), even_positions(len(colors)))
        out = []
        for i in range(n):
            pos = i / (n - 1) if n > 1 else 0.0
            if pos <= p[0]:
                out.append(colors[0])
            elif pos >= p[-1]:
                out.append(colors[-1])
            else:
                k = max(j for j in range(len(p) - 1) if p[j] <= pos)
                span = p[k + 1] - p[k]
                out.append(_lerp_hex(colors[k], colors[k + 1], (pos - p[k]) / span if span > 0 else 1.0))
        return out

    def _radial(self, colors, n, params, from_center: bool):
        if len(colors) == 1:
            return [colors[0]] * n
        b = _clean_stops(params.get("stops"), len(colors) - 1, even_boundaries(len(colors)))
        out = []
        for i in range(n):
            d = abs((i + 0.5) / n - 0.5) * 2          # 0 at the middle, 1 at the ends
            if not from_center:
                d = 1.0 - d
            k = sum(1 for x in b if d >= x)
            out.append(colors[min(k, len(colors) - 1)])
        return out

    def _center_out(self, colors, n, params):
        return self._radial(colors, n, params, True)

    def _edges_in(self, colors, n, params):
        return self._radial(colors, n, params, False)

    def _alternating(self, colors, n, params):
        return [colors[i % len(colors)] for i in range(n)]

    def _paint(self, n, params, base=OFF):
        """Painted LEDs keep their colour; unpainted (erased) ones show the zone's own colour,
        the one set on the zone or on Everything."""
        painted = params.get("paint")
        if not isinstance(painted, list):
            painted = []
        out = []
        for i in range(n):
            c = normalize_hex(painted[i]) if i < len(painted) and painted[i] is not None else ""
            out.append(c or base)
        return out
