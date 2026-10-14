"""User-saved custom colours, kept in their own file.

~/.config/iridia/custom_colors.json  ->  {"colors": ["ff8800", ...], "exact": ["ff0000", ...]}

"exact" lists colours you asked to see exactly as picked: wherever an LED has
one of them, Palette and Calibrated correction (and gamma) leave it alone.

Separate from config.json on purpose: resetting, regenerating or hand-
editing the main config can't wipe the colours you built up. Colours that
older versions kept under "custom_colors" in config.json are moved here
the first time the daemon starts.
"""

import json
import logging
import os
import threading
from typing import List

from iridia.colors import normalize_hex

logger = logging.getLogger("iridia")


class CustomColors:
    def __init__(self, path: str = "~/.config/iridia/custom_colors.json"):
        self.path = os.path.expanduser(path)
        self._lock = threading.RLock()
        self._colors: List[str] = []
        self._exact: List[str] = []
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("colors", []) if isinstance(data, dict) else data
            self._colors = self._clean(raw)
            self._exact = self._clean(data.get("exact", []) if isinstance(data, dict) else [])
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            logger.warning(f"Couldn't read {self.path} ({e}); keeping an empty list in memory "
                           "and leaving the file untouched")

    @staticmethod
    def _clean(raw) -> List[str]:
        out: List[str] = []
        for c in raw or []:
            h = normalize_hex(c)
            if h and h not in out:
                out.append(h)
        return out

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"colors": self._colors, "exact": self._exact}, f, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            logger.warning(f"Couldn't save custom colours to {self.path}: {e}")

    def migrate_from(self, legacy) -> bool:
        """Merge colours from the old config.json key. Returns True if any were found."""
        legacy = self._clean(legacy)
        if not legacy:
            return False
        with self._lock:
            for c in legacy:
                if c not in self._colors:
                    self._colors.append(c)
            self._save()
        return True

    def list(self) -> List[str]:
        with self._lock:
            return list(self._colors)

    def add(self, hex_color: str) -> List[str]:
        h = normalize_hex(hex_color)
        with self._lock:
            if h and h not in self._colors:
                self._colors.append(h)
                self._save()
            return list(self._colors)

    def remove(self, hex_color: str) -> List[str]:
        h = normalize_hex(hex_color)
        with self._lock:
            if h in self._colors or h in self._exact:
                if h in self._colors:
                    self._colors.remove(h)
                if h in self._exact:
                    self._exact.remove(h)
                self._save()
            return list(self._colors)

    # ------------------------------------------------------------ exact colours
    MAX_EXACT = 64

    def exact(self) -> List[str]:
        with self._lock:
            return list(self._exact)

    def exact_set(self) -> frozenset:
        with self._lock:
            return frozenset(self._exact)

    def set_exact(self, hex_color: str, on: bool) -> bool:
        """Mark a colour as exact (or not). True if something changed."""
        h = normalize_hex(hex_color)
        if not h:
            return False
        with self._lock:
            if on and h not in self._exact:
                self._exact.append(h)
                del self._exact[:-self.MAX_EXACT]
            elif not on and h in self._exact:
                self._exact.remove(h)
            else:
                return False
            self._save()
            return True
