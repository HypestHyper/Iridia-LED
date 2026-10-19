"""Iridia, LED wallpaper sync for Linux."""

__version__ = "1.3.2"


def get_version() -> str:
    try:
        from importlib.metadata import version
        return version("iridia")
    except Exception:
        return __version__          # running from a source checkout


def code_fingerprint() -> str:
    """A short hash of the installed code, so a daemon still running older code can be told apart
    from a fresh one with the same version number."""
    import hashlib
    import os
    h = hashlib.sha256()
    root = os.path.dirname(os.path.abspath(__file__))
    for folder, dirs, files in sorted(os.walk(root)):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for f in sorted(files):
            if f.endswith(".py"):
                try:
                    with open(os.path.join(folder, f), "rb") as fh:
                        h.update(f.encode() + fh.read())
                except OSError:
                    pass
    return h.hexdigest()[:10]
