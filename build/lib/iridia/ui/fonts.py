"""Bundled fonts: Material Symbols Rounded (icons) and Google Sans Flex (text).

They are registered with fontconfig for this process only, so nothing is
installed into the user's font folders.
"""

import ctypes
import json
import logging
import os

logger = logging.getLogger("iridia")

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "fonts")
ICON_FAMILY = "Material Symbols Rounded"
TEXT_FAMILY = "Google Sans Flex 18pt"

_icons = None
_registered = False


def register() -> bool:
    """Make the bundled fonts visible to GTK. Call before the first window."""
    global _registered
    if _registered:
        return True
    try:
        fc = ctypes.CDLL("libfontconfig.so.1")
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        ok = True
        for fn in sorted(os.listdir(FONT_DIR)):
            if fn.endswith(".ttf"):
                ok &= bool(fc.FcConfigAppFontAddFile(None, os.path.join(FONT_DIR, fn).encode()))
        _registered = ok
    except OSError as e:
        logger.warning(f"Couldn't load the bundled fonts ({e}); icons may show as boxes")
    return _registered


def codepoint(name: str) -> str:
    global _icons
    if _icons is None:
        try:
            with open(os.path.join(FONT_DIR, "icons.json")) as f:
                _icons = {k: int(v) for k, v in json.load(f).items()}
        except (OSError, ValueError):
            _icons = {}
    cp = _icons.get(name)
    return chr(cp) if cp else "?"
