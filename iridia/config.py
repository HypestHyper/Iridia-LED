"""Configuration management with defaults, validation, and hot-reload support."""

import copy
import json
import logging
import os
import threading

logger = logging.getLogger("iridia")

DEFAULT_CONFIG = {
    "wallpaper": {
        "source": "auto",
        "manual_path": None,
        "watch_folder": "~/Pictures/Wallpapers"
    },
    "color": {
        "backend": "auto",
        "mode": "full",
        "palette_mode": "exact"
    },
    "openrgb": {
        "host": "127.0.0.1",
        "port": None,
        "start_server": True,
        "server_command": "",
        "auto_restart_on_missing_device": True,
        "missing_device_restart_threshold_sec": 45.0,
        "restart_cooldown_sec": 120.0
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
    "custom_colors": [],
    "profiles": {
        "auto_restore": True,
        "last_profile": None
    }
}


class Config:
    """JSON config with defaults, auto-create, and hot-reload.

    Every access goes through self._lock. The daemon's IPC server spawns
    a new thread per client connection (see ipc.py), and the config-file
    watcher fires from yet another (watchdog's own) thread, so a
    GUI-driven `set()` and a file-watcher-driven `reload()` can and do
    land at the same moment. Without a lock, `reload()`'s pattern of
    swapping `self._data` out for a freshly-rebuilt dict could stomp
    on a `set()` that had already navigated into the *old* dict object
    on another thread, silently discarding that change — or worse,
    losing entire devices, since `_load()` rebuilds the whole tree
    from whatever the file contained at that instant.
    """

    def __init__(self, path: str = "~/.config/iridia/config.json"):
        self.path = os.path.expanduser(path)
        self._lock = threading.RLock()
        self._data = {}
        self._load()

    def _load(self):
        with self._lock:
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r") as f:
                        loaded = json.load(f)
                    self._data = copy.deepcopy(DEFAULT_CONFIG)
                    if not isinstance(loaded, dict):
                        raise json.JSONDecodeError("the top level isn't an object", "", 0)
                    self._deep_update(self._data, loaded)
                    self._sanitize()
                except json.JSONDecodeError as e:
                    logger.error(f"Config file {self.path} has invalid JSON ({e}), "
                                f"backing it up to {self.path}.bak and starting fresh")
                    backup = self.path + ".bak"
                    try:
                        os.replace(self.path, backup)
                    except OSError as be:
                        logger.error(f"Couldn't back up broken config: {be}")
                    self._data = copy.deepcopy(DEFAULT_CONFIG)
                    self._save()
                except OSError as e:
                    logger.error(f"Couldn't read config file {self.path}: {e}, using defaults for this session")
                    self._data = copy.deepcopy(DEFAULT_CONFIG)
            else:
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                self._save()

    def _sanitize(self):
        """Fix types a hand edit can break, so a typo can't stop the daemon. Settings
        with a number or true/false default must be one; sections must be objects;
        devices and zones must be objects."""
        d = self._data
        for sec, defaults in DEFAULT_CONFIG.items():
            if not isinstance(defaults, dict):
                continue
            if not isinstance(d.get(sec), dict):
                logger.warning(f"Config: '{sec}' should be an object, using the defaults for it")
                d[sec] = copy.deepcopy(defaults)
                continue
            for key, dv in defaults.items():
                v = d[sec].get(key, dv)
                if isinstance(dv, bool):
                    if not isinstance(v, bool):
                        nv = str(v).strip().lower() in ("1", "true", "yes", "on")
                        logger.warning(f"Config: {sec}.{key} should be true or false, reading {v!r} as {nv}")
                        d[sec][key] = nv
                elif isinstance(dv, (int, float)):
                    try:
                        nv = type(dv)(v)
                        if nv != nv or nv < 0:
                            raise ValueError
                        if nv != v:
                            d[sec][key] = nv
                    except (TypeError, ValueError):
                        logger.warning(f"Config: {sec}.{key} should be a number, using {dv}")
                        d[sec][key] = dv
                elif isinstance(dv, str) and not isinstance(v, str):
                    logger.warning(f"Config: {sec}.{key} should be text, using {dv!r}")
                    d[sec][key] = dv
        devs = d.get("devices")
        clean = {}
        for name, cfg in (devs.items() if isinstance(devs, dict) else []):
            if not isinstance(cfg, dict):
                logger.warning(f"Config: device {name!r} isn't an object, ignoring it")
                continue
            zones = cfg.get("zones")
            if zones is not None and not isinstance(zones, dict):
                logger.warning(f"Config: zones of {name!r} aren't an object, ignoring them")
                cfg.pop("zones")
            elif isinstance(zones, dict):
                for zn in [z for z, zc in zones.items() if not isinstance(zc, dict)]:
                    logger.warning(f"Config: zone {zn!r} of {name!r} isn't an object, ignoring it")
                    zones.pop(zn)
            clean[name] = cfg
        d["devices"] = clean
        if not isinstance(d.get("custom_colors"), list):
            d["custom_colors"] = []

    def _deep_update(self, base, update):
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def _save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                # Write to a temp file and rename into place rather than
                # truncating the real file in-place: a concurrent reader
                # (reload(), or another process) can never observe a
                # half-written file this way, since os.replace is atomic.
                tmp_path = self.path + ".tmp"
                with open(tmp_path, "w") as f:
                    json.dump(self._data, f, indent=2)
                os.replace(tmp_path, self.path)
                self._mtime = os.path.getmtime(self.path)
            except OSError as e:
                # Deliberately not re-raised: a failed save means this
                # change only lives in memory until something works
                # again, but a raised exception here would otherwise
                # propagate out of every set() call and take down
                # whichever IPC command was in progress.
                logger.error(f"Couldn't save config to {self.path}: {e}, "
                            "change is only in memory until this is fixed "
                            "(disk full? permissions?)")

    def reload(self):
        with self._lock:
            if os.path.exists(self.path):
                mtime = os.path.getmtime(self.path)
                if hasattr(self, "_mtime") and mtime == self._mtime:
                    return False
                self._mtime = mtime
                self._load()
                return True
            return False

    @staticmethod
    def _keys(key_path):
        """A path is "a.b.c", or a tuple/list of keys when a key may contain dots
        (OpenRGB device names like "Lian Li Uni Hub - AL v1.0")."""
        return list(key_path) if isinstance(key_path, (tuple, list)) else key_path.split(".")

    def get(self, key_path, default=None):
        with self._lock:
            keys = self._keys(key_path)
            value = self._data
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return default
            return copy.deepcopy(value) if isinstance(value, (dict, list)) else value

    def set(self, key_path, value):
        with self._lock:
            keys = self._keys(key_path)
            target = self._data
            for key in keys[:-1]:
                if not isinstance(target.get(key), dict):
                    target[key] = {}
                target = target[key]
            target[keys[-1]] = value
            self._save()

    @property
    def raw(self):
        with self._lock:
            return copy.deepcopy(self._data)

    @property
    def devices(self):
        with self._lock:
            return copy.deepcopy(self._data.get("devices", {}))

    @property
    def timing(self):
        with self._lock:
            return copy.deepcopy(self._data.get("timing", {}))

    @property
    def logging(self):
        with self._lock:
            return copy.deepcopy(self._data.get("logging", {}))

    @property
    def ddc(self):
        with self._lock:
            return copy.deepcopy(self._data.get("ddc", {}))

    @property
    def openrgb(self):
        with self._lock:
            return copy.deepcopy(self._data.get("openrgb", {}))

    @property
    def color_mode(self):
        with self._lock:
            return self._data.get("color", {}).get("mode", "full")

    @property
    def palette_mode(self):
        with self._lock:
            return self._data.get("color", {}).get("palette_mode", "exact")
