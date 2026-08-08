"""Configuration management with defaults, validation, and hot-reload support."""

import copy
import json
import os


DEFAULT_CONFIG = {
    "wallpaper": {
        "source": "auto",
        "manual_path": None,
        "watch_folder": "~/Pictures/Wallpapers"
    },
    "color": {
        "backend": "material",
        "mode": "palette",
        "palette_mode": "exact"
    },
    "openrgb": {
        "host": "127.0.0.1",
        "port": None
    },
    "timing": {
        "openrgb_retry_interval_sec": 5.0,
        "device_enumeration_interval_sec": 10.0,
        "ddc_poll_interval_sec": 5.0,
        "wallpaper_debounce_ms": 300,
        "health_check_interval_sec": 30.0,
        "socket_timeout_sec": 2.0
    },
    "logging": {
        "enabled": False,
        "file_path": "~/.local/share/iridia/iridia.log",
        "max_size_kb": 1024,
        "level": "info"
    },
    "ddc": {
        "enabled": True,
        "bus_number": None,
        "suppress_errors": True,
        "fallback_brightness": 100
    },
    "devices": {},
    "profiles": {
        "auto_restore": True,
        "last_profile": None
    }
}


class Config:
    """JSON config with defaults, auto-create, and hot-reload."""

    def __init__(self, path: str = "~/.config/iridia/config.json"):
        self.path = os.path.expanduser(path)
        self._data = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    loaded = json.load(f)
                # Merge with defaults so new keys are always present
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                self._deep_update(self._data, loaded)
            except (json.JSONDecodeError, OSError) as e:
                # Backup corrupt config and load defaults
                backup = self.path + ".bak"
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                self._save()
        else:
            self._data = copy.deepcopy(DEFAULT_CONFIG)
            self._save()

    def _deep_update(self, base, update):
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)

    def reload(self):
        """Reload from disk. Returns True if successful."""
        if os.path.exists(self.path):
            mtime = os.path.getmtime(self.path)
            if hasattr(self, "_mtime") and mtime == self._mtime:
                return False
            self._mtime = mtime
            self._load()
            return True
        return False

    def get(self, key_path: str, default=None):
        """Dot-notation access: config.get('timing.openrgb_retry_interval_sec')"""
        keys = key_path.split(".")
        value = self._data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value):
        keys = key_path.split(".")
        target = self._data
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value
        self._save()

    @property
    def raw(self):
        return self._data

    @property
    def devices(self):
        return self._data.get("devices", {})

    @property
    def timing(self):
        return self._data.get("timing", {})

    @property
    def logging(self):
        return self._data.get("logging", {})

    @property
    def ddc(self):
        return self._data.get("ddc", {})

    @property
    def openrgb(self):
        return self._data.get("openrgb", {})

    @property
    def color_mode(self):
        return self._data.get("color", {}).get("mode", "palette")

    @property
    def palette_mode(self):
        return self._data.get("color", {}).get("palette_mode", "exact")
