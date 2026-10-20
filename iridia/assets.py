"""Locate bundled package assets (icon, etc.) at runtime.

Uses a plain __file__-relative path rather than importlib.resources so
this works identically on Python 3.8+ regardless of install method
(venv, pipx, editable install, system package) with no extra API surface
to get wrong.
"""

import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

ICON_NAME = "iridia"
APP_ID = "io.github.HypestHyper.Iridia"   # GTK application id; the launcher file is named after it
# launcher file names used by older versions, removed on install and uninstall
OLD_LAUNCHERS = ("iridia.desktop", "io.github.iridia.Iridia.desktop")


def desktop_entry(exec_path: str = APP_ID) -> str:
    """The launcher file. data/io.github.HypestHyper.Iridia.desktop is this with Exec=APP_ID (a test
    keeps the two the same); the installed one names the full path of iridia-gui, since launchers
    don't run through a login shell and so don't see ~/.local/bin in PATH."""
    return f"""[Desktop Entry]
Type=Application
Name=Iridia
GenericName=RGB lighting
Comment=Set RGB lights from the colours of your wallpaper, through OpenRGB
Exec={exec_path}
Icon={ICON_NAME}
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=led;rgb;argb;openrgb;wallpaper;lighting;light;strip;ws2812b;colour;color;ambient;
StartupNotify=true
StartupWMClass={APP_ID}
X-GNOME-UsesNotifications=true
"""


def icon_svg_path() -> str:
    """Absolute path to the bundled iridia.svg inside the installed package.

    This is the icon installed into the hicolor theme (scalable/apps) so
    launchers, app grids, and window-switchers can look it up by name.
    """
    return os.path.join(_DATA_DIR, "iridia.svg")


ICON_SIZES = (48, 64, 128, 256)


def icon_png_for(size: int) -> str:
    return os.path.join(_DATA_DIR, f"iridia-{size}.png")


def icon_png_path() -> str:
    """Absolute path to a pre-rendered PNG of the icon.

    Used only for the GUI window's own icon (Tk's PhotoImage has no SVG
    support), rendered once at packaging time so there's no runtime
    dependency on an SVG rasterizer.
    """
    return os.path.join(_DATA_DIR, "iridia-64.png")


def read_icon_svg() -> str:
    with open(icon_svg_path(), "r", encoding="utf-8") as f:
        return f.read()


def logo_png_path() -> str:
    """White glyph-only PNG (from iridia-dark.svg) for use on the GUI's dark surfaces."""
    return os.path.join(_DATA_DIR, "iridia-logo.png")


def symbolic_svg_path() -> str:
    """currentColor glyph for themed panels/trays (installed as iridia-symbolic)."""
    return os.path.join(_DATA_DIR, "iridia-symbolic.svg")
