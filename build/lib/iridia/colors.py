"""Color extraction from wallpaper images."""

import os
from typing import List, Tuple


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"{r:02x}{g:02x}{b:02x}"


def _delta_e_rgb(hex1: str, hex2: str) -> float:
    """Approximate perceptual distance in RGB space."""
    r1, g1, b1 = _hex_to_rgb(hex1)
    r2, g2, b2 = _hex_to_rgb(hex2)
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def _is_valid_color(hex_color: str) -> bool:
    """Check if color has enough saturation/value."""
    r, g, b = _hex_to_rgb(hex_color)
    mx = max(r, g, b)
    mn = min(r, g, b)
    return mx >= 30 and (mx - mn) >= 15


def _deduplicate(colors: List[str], threshold: float = 30.0) -> List[str]:
    """Remove colors that are too similar to already-selected ones."""
    result = []
    for c in colors:
        if _is_valid_color(c) and all(_delta_e_rgb(c, r) > threshold for r in result):
            result.append(c)
    return result


class ColorExtractor:
    """Extract dominant and accent colors from a wallpaper image."""

    def __init__(self, backend: str = "material"):
        self.backend = backend
        self._has_material = self._check_material()

    def _check_material(self) -> bool:
        try:
            import material_color_utilities  # noqa: F401
            return True
        except ImportError:
            return False

    def extract(self, image_path: str) -> List[str]:
        """Return list of hex colors (dominant first), deduplicated."""
        if not os.path.exists(image_path):
            return ["642107"]

        if self.backend == "material" and self._has_material:
            colors = self._extract_material(image_path)
        else:
            colors = self._extract_pillow(image_path)

        # Deduplicate and ensure we have at least one color
        colors = _deduplicate(colors)
        if not colors:
            colors = ["642107"]
        return colors

    def _extract_material(self, image_path: str) -> List[str]:
        """Extract colors using Google's Material Color Utilities (PyPI package).

        Uses theme_from_image() to get the Material You source color and palette.
        Equivalent to Caelestia's primaryPaletteKeyColor + accent palette.
        """
        try:
            from material_color_utilities import (
                theme_from_image, theme_from_color, hex_from_argb, argb_from_hex
            )
            from PIL import Image

            img = Image.open(image_path)
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Method 1: theme_from_image — gets source color from image directly
            theme = theme_from_image(img)

            colors = []

            # Extract source color from theme
            # The theme has a 'source' color that represents the image
            try:
                source = theme.source
                if hasattr(source, 'color'):
                    source = source.color
                if isinstance(source, int):
                    source_hex = hex_from_argb(source)
                    colors.append(source_hex.lstrip("#"))
            except Exception:
                pass

            # Extract scheme colors (primary, secondary, tertiary, etc.)
            try:
                scheme = theme.schemes.light
                for attr in ["primary", "secondary", "tertiary", "error",
                             "primary_container", "secondary_container", "tertiary_container"]:
                    try:
                        val = getattr(scheme, attr, None)
                        if val is not None:
                            if hasattr(val, 'color'):
                                val = val.color
                            if isinstance(val, int):
                                hex_c = hex_from_argb(val).lstrip("#")
                                if hex_c not in colors and _is_valid_color(hex_c):
                                    colors.append(hex_c)
                    except Exception:
                        continue
            except Exception:
                pass

            # Method 2: If theme_from_image didn't give good colors, 
            # use theme_from_color with the source color to get a full palette
            if len(colors) < 3 and colors:
                try:
                    source_argb = argb_from_hex("#" + colors[0])
                    theme2 = theme_from_color("#" + colors[0])
                    scheme2 = theme2.schemes.light
                    for attr in ["primary", "secondary", "tertiary", "error"]:
                        try:
                            val = getattr(scheme2, attr, None)
                            if val is not None:
                                if hasattr(val, 'color'):
                                    val = val.color
                                if isinstance(val, int):
                                    hex_c = hex_from_argb(val).lstrip("#")
                                    if hex_c not in colors and _is_valid_color(hex_c):
                                        colors.append(hex_c)
                        except Exception:
                            continue
                except Exception:
                    pass

            if not colors:
                raise RuntimeError("Material extraction returned no colors")

            return colors[:8]
        except Exception as e:
            # Material backend failed — log and fall back to Pillow
            import logging
            logging.getLogger("iridia").warning(f"Material backend failed: {e}, falling back to Pillow")
            return self._extract_pillow(image_path)

    def _extract_pillow(self, image_path: str) -> List[str]:
        try:
            from PIL import Image

            img = Image.open(image_path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img = img.resize((200, 200))

            # Get dominant colors via adaptive palette
            quantized = img.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
            palette = quantized.getpalette()
            colors = []
            if palette:
                count = min(8, len(palette) // 3)
                for i in range(count):
                    r, g, b = palette[i * 3:(i + 1) * 3]
                    colors.append(_rgb_to_hex(r, g, b))

            # Sort by prominence (frequency in quantized image)
            hist = quantized.histogram()
            indexed = [(colors[i], hist[i]) for i in range(len(colors))]
            indexed.sort(key=lambda x: x[1], reverse=True)
            colors = [c for c, _ in indexed]

            return colors[:8]
        except Exception:
            return ["642107"]
