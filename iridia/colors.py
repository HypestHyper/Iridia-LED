"""Color extraction from wallpaper images."""

import os
from typing import List, Tuple


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"{r:02x}{g:02x}{b:02x}"


def _delta_e_rgb(hex1: str, hex2: str) -> float:
    r1, g1, b1 = _hex_to_rgb(hex1)
    r2, g2, b2 = _hex_to_rgb(hex2)
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def _is_valid_color(hex_color: str, min_value: int = 30, min_saturation: int = 15) -> bool:
    r, g, b = _hex_to_rgb(hex_color)
    mx = max(r, g, b)
    mn = min(r, g, b)
    return mx >= min_value and (mx - mn) >= min_saturation


def normalize_hex(value) -> str:
    """'#FF8800' / 'ff8800' -> 'ff8800'; '' if it isn't a valid 6-digit hex."""
    h = str(value).strip().lstrip("#").lower()
    return h if len(h) == 6 and all(c in "0123456789abcdef" for c in h) else ""


def resolve_colors(entries, extracted: List[str]) -> List[str]:
    """Turn a zone's color selection into hex colors.

    Each entry is either an int (index into the wallpaper's extracted
    colors) or a hex string (a custom color, fixed regardless of
    wallpaper). Invalid or out-of-range entries are skipped.
    """
    out = []
    for e in entries or []:
        if isinstance(e, bool):
            continue
        if isinstance(e, int):
            if 0 <= e < len(extracted):
                out.append(extracted[e])
        else:
            h = normalize_hex(e)
            if h:
                out.append(h)
    return out


def _deduplicate(colors: List[str], threshold: float = 30.0) -> List[str]:
    result = []
    for c in colors:
        if _is_valid_color(c) and all(_delta_e_rgb(c, r) > threshold for r in result):
            result.append(c)
    return result


class ColorExtractor:
    """Extract dominant and accent colors from a wallpaper image.

    Backends (config ``color.backend``):
        auto      Caelestia's scheme file when Caelestia is what set the
                  wallpaper *and* the file is up to date, else Material
                  (if installed), else Pillow.  <- default
        caelestia Same as auto (kept so older configs keep working).
        material  Material Color Utilities "prominent colors" (falls back to Pillow).
        pillow    Median-cut dominant colours; no extra dependencies.
    Whatever the backend, a failure falls through to the next one.
    """

    BACKENDS = ["auto", "caelestia", "material", "pillow"]
    SCHEME_PATH = "~/.config/hypr/scheme/current.conf"

    def __init__(self, backend: str = "auto"):
        self.backend = backend if backend in self.BACKENDS else "auto"
        self.last_used = ""   # which method produced the latest result (for logs/GUI)
        self._has_material = self._check_material()

    def _check_material(self) -> bool:
        try:
            import material_color_utilities  # noqa: F401
            return True
        except ImportError:
            return False

    def extract(self, image_path: str, wallpaper_source: str = "") -> List[str]:
        """wallpaper_source: name of the detector backend that found the
        image (e.g. "caelestia"); lets "auto" know whether Caelestia's
        scheme file can be trusted for this image."""
        if not os.path.exists(image_path):
            return ["642107"]

        use_scheme = self.backend in ("auto", "caelestia") and wallpaper_source == "caelestia"
        steps = []
        if use_scheme:
            steps.append(("caelestia-scheme", lambda: self._extract_caelestia(image_path)))
        if self.backend != "pillow" and self._has_material:
            steps.append(("material", lambda: self._extract_material(image_path)))
        steps.append(("pillow", lambda: self._extract_pillow(image_path)))
        colors = []
        for name, fn in steps:
            colors = fn()
            if colors:
                self.last_used = name
                break

        raw = [c for c in (normalize_hex(c) for c in colors or []) if c]
        colors = _deduplicate(raw)
        if not colors and raw:
            # A black-and-white or very dark wallpaper: every colour failed the "colourful
            # enough" test. Use its own greys (the brightest first) rather than an unrelated
            # default colour.
            greys = []
            for c in sorted(raw, key=lambda h: -max(_hex_to_rgb(h))):
                if all(_delta_e_rgb(c, g) > 30 for g in greys):
                    greys.append(c)
            colors = greys[:8]
        if not colors:
            colors = ["642107"]
        return colors

    def _extract_caelestia(self, image_path: str = "") -> List[str]:
        """Read Caelestia's already-extracted primary color.

        Caelestia writes the correct dominant color to:
            ~/.config/hypr/scheme/current.conf
        as $primaryPaletteKeyColor = ff4400
        """
        path = os.path.expanduser(self.SCHEME_PATH)
        if not os.path.exists(path):
            return None
        # Caelestia regenerates the scheme *after* it records a new wallpaper.
        # A scheme file older than the wallpaper change describes the
        # previous image; give it a moment to be rewritten, else skip it.
        state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        marker = os.path.join(state, "caelestia", "wallpaper", "path.txt")
        try:
            import time as _t
            for _ in range(6):
                if os.path.getmtime(path) >= os.path.getmtime(marker) - 1.0:
                    break
                _t.sleep(0.5)
            else:
                import logging
                logging.getLogger("iridia").info(
                    "Caelestia scheme file is older than the wallpaper change; using image analysis instead")
                return None
        except OSError:
            pass
        try:
            with open(path, "r") as f:
                for line in f:
                    if "$primaryPaletteKeyColor" in line:
                        parts = line.split("=")
                        if len(parts) == 2:
                            hex_c = parts[1].strip().lstrip("#").lower()
                            if len(hex_c) == 6:
                                return [hex_c]
        except Exception:
            pass
        return None

    def _extract_material(self, image_path: str) -> List[str]:
        """Extract using PyPI material-color-utilities 0.2.x API."""
        try:
            from PIL import Image
            from material_color_utilities import prominent_colors_from_image

            img = Image.open(image_path)
            if img.mode != "RGB":
                img = img.convert("RGB")

            # prominent_colors_from_image returns list of hex strings like '#f49325'
            raw_colors = prominent_colors_from_image(img, 8)
            colors = []
            for c in raw_colors:
                hex_c = c.lstrip("#").lower() if isinstance(c, str) else str(c)
                if _is_valid_color(hex_c) and hex_c not in colors:
                    colors.append(hex_c)

            return colors[:8] if colors else None
        except Exception as e:
            import logging
            logging.getLogger("iridia").warning(f"Material backend failed: {e}")
            return None

    def _extract_pillow(self, image_path: str) -> List[str]:
        """Standard Pillow median-cut extraction, sorted by pixel frequency."""
        try:
            from PIL import Image

            img = Image.open(image_path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img = img.resize((200, 200))

            # Image.Quantize is Pillow 9.1+; older ones (Ubuntu 22.04's 9.0) have Image.MEDIANCUT
            quantized = img.quantize(colors=16, method=getattr(Image, "Quantize", Image).MEDIANCUT)
            palette = quantized.getpalette()
            colors = []
            if palette:
                count = min(12, len(palette) // 3)
                for i in range(count):
                    r, g, b = palette[i * 3:(i + 1) * 3]
                    colors.append(_rgb_to_hex(r, g, b))

            hist = quantized.histogram()
            indexed = [(colors[i], hist[i]) for i in range(len(colors))]
            indexed.sort(key=lambda x: x[1], reverse=True)
            colors = [c for c, _ in indexed]

            # Filter out near-black/near-white/near-gray for dominant mode
            def _is_background(c):
                r, g, b = _hex_to_rgb(c)
                mx, mn = max(r, g, b), min(r, g, b)
                if mx < 40 or mn > 220:
                    return True
                if mx - mn < 25:
                    return True
                return False

            fg = [c for c in colors if not _is_background(c)]
            result = fg if len(fg) >= 3 else colors
            return result[:8]
        except Exception:
            return ["642107"]
