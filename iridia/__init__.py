"""Iridia, LED wallpaper sync for Linux."""

__version__ = "1.1.0"


def get_version() -> str:
    try:
        from importlib.metadata import version
        return version("iridia")
    except Exception:
        return __version__          # running from a source checkout
