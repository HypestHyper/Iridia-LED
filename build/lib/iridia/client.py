"""IPC client wrapper for the tray GUI."""

import os
from iridia.ipc import IPCClient


SOCKET_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
    f"iridia-{os.getuid()}.sock"
)


class Client:
    """High-level client for talking to the Iridia daemon."""

    def __init__(self):
        self._ipc = IPCClient(SOCKET_PATH, timeout=2.0)

    def status(self) -> dict:
        return self._ipc.send({"cmd": "status"})

    def set_device(self, name: str, enabled: bool) -> dict:
        return self._ipc.send({"cmd": "set_device", "device": name, "enabled": enabled})

    def set_pattern(self, name: str, pattern: str) -> dict:
        return self._ipc.send({"cmd": "set_pattern", "device": name, "pattern": pattern})

    def set_mode(self, name: str, mode: str) -> dict:
        return self._ipc.send({"cmd": "set_mode", "device": name, "mode": mode})

    def set_led_count(self, name: str, zone: str, count: int) -> dict:
        return self._ipc.send({"cmd": "set_led_count", "device": name, "zone": zone, "count": count})

    def set_brightness_sync(self, name: str, enabled: bool) -> dict:
        return self._ipc.send({"cmd": "set_brightness_sync", "device": name, "enabled": enabled})

    def set_manual_brightness(self, name: str, value: int) -> dict:
        return self._ipc.send({"cmd": "set_manual_brightness", "device": name, "value": value})

    def set_brightness_range(self, name: str, min_val: int, max_val: int) -> dict:
        return self._ipc.send({"cmd": "set_brightness_range", "device": name, "min": min_val, "max": max_val})

    def set_invert(self, name: str, enabled: bool) -> dict:
        return self._ipc.send({"cmd": "set_invert", "device": name, "enabled": enabled})

    def set_gamma(self, name: str, enabled: bool) -> dict:
        return self._ipc.send({"cmd": "set_gamma", "device": name, "enabled": enabled})

    def set_selected_colors(self, name: str, indices: list) -> dict:
        return self._ipc.send({"cmd": "set_selected_colors", "device": name, "indices": indices})

    def refresh(self) -> dict:
        return self._ipc.send({"cmd": "refresh_wallpaper"})

    def restart(self) -> dict:
        return self._ipc.send({"cmd": "restart"})

    def reload_config(self) -> dict:
        return self._ipc.send({"cmd": "reload_config"})

    def is_alive(self) -> bool:
        return self._ipc.is_alive()
