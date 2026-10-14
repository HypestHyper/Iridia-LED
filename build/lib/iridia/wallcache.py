"""Per-wallpaper color cache + user color choice.

Stored in ~/.config/iridia/wallpaper_colors.json:

    { "/path/to/img.jpg": {
          "mtime": 1760000000.0,            # image mtime when colors were extracted
          "colors": ["b03f0f", "c4750b"],   # cached extraction result
          "choice": {"index": 1}            # optional user pick: an extracted color...
                    # or {"hex": "ff8800"}   # ...or a custom color
      } }

Extraction (the expensive part) runs once per image; if the image file
changes (different mtime) the cached colors are refreshed but the user's
choice is kept. A choice is stored per image, so it survives restarts and
switching away and back.
"""

import json
import logging
import os
import threading
from typing import Dict, List, Optional

logger = logging.getLogger("iridia")


def _valid_hex(h) -> bool:
    return isinstance(h, str) and len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h)


class WallpaperColorCache:
    def __init__(self, path: str = "~/.config/iridia/wallpaper_colors.json"):
        self.path = os.path.expanduser(path)
        self._lock = threading.RLock()
        self._data: Dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(image_path: str) -> str:
        return os.path.realpath(image_path)

    def _load(self):
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # Drop entries for images that no longer exist so the file
                # can't grow forever — but keep any with a user choice
                # (the image may be on a drive that isn't mounted right now).
                self._data = {k: v for k, v in data.items()
                              if isinstance(v, dict) and (os.path.exists(k) or v.get("choice") or v.get("zones"))}
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Couldn't read {self.path} ({type(e).__name__}: {e}), starting with an empty color cache")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._data, f, indent=1)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning(f"Couldn't save {self.path}: {type(e).__name__}: {e}")

    def get_colors(self, image_path: str, backend: Optional[str] = None) -> Optional[List[str]]:
        """Cached colors if still valid for this image file (and, when
        given, produced by the same extraction backend setting), else None."""
        with self._lock:
            e = self._data.get(self._key(image_path))
            if not e or not e.get("colors"):
                return None
            if backend is not None and e.get("backend", backend) != backend:
                return None
            try:
                if abs(os.path.getmtime(image_path) - e.get("mtime", -1)) > 0.001:
                    return None
            except OSError:
                return None
            return list(e["colors"])

    def store_colors(self, image_path: str, colors: List[str], backend: Optional[str] = None):
        with self._lock:
            e = self._data.setdefault(self._key(image_path), {})
            try:
                e["mtime"] = os.path.getmtime(image_path)
            except OSError:
                e["mtime"] = 0
            e["colors"] = list(colors)
            if backend is not None:
                e["backend"] = backend
            self._save()

    def get_choice(self, image_path: str) -> Optional[dict]:
        with self._lock:
            c = self._data.get(self._key(image_path), {}).get("choice")
            return dict(c) if c else None

    def set_choice(self, image_path: str, choice: Optional[dict]):
        """choice: {"index": N} | {"hex": "rrggbb"} | None (back to automatic)."""
        with self._lock:
            key = self._key(image_path)
            e = self._data.setdefault(key, {})
            if choice:
                e["choice"] = choice
            else:
                e.pop("choice", None)
            self._save()

    # ---- per-zone picks, remembered per wallpaper
    def get_zone_colors(self, image_path: str) -> dict:
        """{"device|zone": pattern_colors list} saved for this image (may be empty)."""
        with self._lock:
            z = self._data.get(self._key(image_path), {}).get("zones") or {}
            return {k: list(v) for k, v in z.items() if isinstance(v, list)}

    def set_zone_colors(self, image_path: str, picks: dict):
        """Remember zone picks ({"device|zone": entries}) for this image, merged with earlier ones."""
        if not picks:
            return
        with self._lock:
            e = self._data.setdefault(self._key(image_path), {})
            z = e.setdefault("zones", {})
            for k, v in picks.items():
                z[k] = list(v)
            self._save()

    def forget(self, image_path: str):
        """Drop everything remembered about the user's color picks for this image."""
        with self._lock:
            e = self._data.get(self._key(image_path))
            if e:
                e.pop("choice", None)
                e.pop("zones", None)
                self._save()

    def forget_all(self) -> int:
        """Drop every remembered pick (extracted colors stay cached). Returns images affected."""
        n = 0
        with self._lock:
            for e in self._data.values():
                if isinstance(e, dict) and ("choice" in e or "zones" in e):
                    e.pop("choice", None)
                    e.pop("zones", None)
                    n += 1
            if n:
                self._save()
        return n

    def has_picks(self, image_path: str) -> bool:
        with self._lock:
            e = self._data.get(self._key(image_path), {})
            return bool(e.get("choice") or e.get("zones"))
