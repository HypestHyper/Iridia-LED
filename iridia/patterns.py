"""Static pattern generators for LED strips."""

from typing import List


def _lerp_hex(c1: str, c2: str, t: float) -> str:
    """Linear interpolation between two hex colors."""
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"{r:02x}{g:02x}{b:02x}"


class PatternGenerator:
    """Generate static color distributions for addressable LED strips."""

    PATTERNS = ["solid", "gradient", "segments", "center_out", "edges_in", "alternating"]

    def generate(self, pattern: str, colors: List[str], led_count: int) -> List[str]:
        """Generate a list of hex colors (one per LED) for the given pattern."""
        if not colors:
            colors = ["642107"]
        if led_count <= 0:
            return []

        method = getattr(self, f"_{pattern}", self._solid)
        return method(colors, led_count)

    def _solid(self, colors: List[str], led_count: int) -> List[str]:
        return [colors[0]] * led_count

    def _gradient(self, colors: List[str], led_count: int) -> List[str]:
        if len(colors) == 1:
            return [colors[0]] * led_count

        result = []
        segments = len(colors) - 1
        for i in range(led_count):
            pos = i / (led_count - 1) if led_count > 1 else 0
            seg = pos * segments
            idx = int(seg)
            t = seg - idx
            if idx >= segments:
                c = colors[-1]
            else:
                c = _lerp_hex(colors[idx], colors[idx + 1], t)
            result.append(c)
        return result

    def _segments(self, colors: List[str], led_count: int) -> List[str]:
        if len(colors) == 1:
            return [colors[0]] * led_count

        seg_size = led_count // len(colors)
        result = []
        for i, color in enumerate(colors):
            if i == len(colors) - 1:
                count = led_count - len(result)
            else:
                count = seg_size
            result.extend([color] * count)
        return result

    def _center_out(self, colors: List[str], led_count: int) -> List[str]:
        if len(colors) == 1:
            return [colors[0]] * led_count

        result = [None] * led_count
        center = led_count / 2.0
        for i in range(led_count):
            dist = abs(i - center) / center
            idx = min(int(dist * len(colors)), len(colors) - 1)
            result[i] = colors[idx]
        return result

    def _edges_in(self, colors: List[str], led_count: int) -> List[str]:
        if len(colors) == 1:
            return [colors[0]] * led_count

        result = [None] * led_count
        center = led_count / 2.0
        for i in range(led_count):
            dist = 1.0 - (abs(i - center) / center)
            idx = min(int(dist * len(colors)), len(colors) - 1)
            result[i] = colors[idx]
        return result

    def _alternating(self, colors: List[str], led_count: int) -> List[str]:
        return [colors[i % len(colors)] for i in range(led_count)]
