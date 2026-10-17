"""IPC client wrapper for the GUI."""

import os
from iridia.ipc import IPCClient

SOCKET_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
    f"iridia-{os.getuid()}.sock"
)

class Client:
    def __init__(self):
        self._ipc = IPCClient(SOCKET_PATH, timeout=2.0)

    def status(self) -> dict:
        return self._ipc.send({"cmd": "status"})

    def preview_color(self, hex_color, raw: bool = False, exact: bool = False) -> dict:
        return self._ipc.send({"cmd": "preview_color", "hex": hex_color, "raw": raw, "exact": exact})

    def set_zone_calibration_profile(self, device: str, zone: str, name: str) -> dict:
        return self._ipc.send({"cmd": "set_zone_calibration_profile", "device": device, "zone": zone, "name": name})

    def reload_calibration(self) -> dict:
        return self._ipc.send({"cmd": "reload_calibration"})

    def shutdown(self) -> dict:
        return self._ipc.send({"cmd": "shutdown"})

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

    # Zone-level commands
    def set_zone_enabled(self, device: str, zone: str, enabled: bool) -> dict:
        return self._ipc.send({"cmd": "set_zone_enabled", "device": device, "zone": zone, "enabled": enabled})

    def set_zone_pattern(self, device: str, zone: str, pattern: str) -> dict:
        return self._ipc.send({"cmd": "set_zone_pattern", "device": device, "zone": zone, "pattern": pattern})

    def set_zone_mode(self, device: str, zone: str, mode: str) -> dict:
        return self._ipc.send({"cmd": "set_zone_mode", "device": device, "zone": zone, "mode": mode})

    def set_zone_colors(self, device: str, zone: str, indices: list) -> dict:
        return self._ipc.send({"cmd": "set_zone_colors", "device": device, "zone": zone, "indices": indices})

    def set_zone_pattern_params(self, device: str, zone: str, params: dict) -> dict:
        return self._ipc.send({"cmd": "set_zone_pattern_params", "device": device, "zone": zone, "params": params})

    def set_zone_led_count(self, device: str, zone: str, count: int) -> dict:
        return self._ipc.send({"cmd": "set_zone_led_count", "device": device, "zone": zone, "count": count})

    def set_zone_brightness_sync(self, device: str, zone: str, enabled: bool) -> dict:
        return self._ipc.send({"cmd": "set_zone_brightness_sync", "device": device, "zone": zone, "enabled": enabled})

    def set_zone_manual_brightness(self, device: str, zone: str, value: int) -> dict:
        return self._ipc.send({"cmd": "set_zone_manual_brightness", "device": device, "zone": zone, "value": value})

    def set_zone_brightness_range(self, device: str, zone: str, min_val: int, max_val: int) -> dict:
        return self._ipc.send({"cmd": "set_zone_brightness_range", "device": device, "zone": zone,
                                "min": min_val, "max": max_val})

    def set_zone_invert(self, device: str, zone: str, enabled: bool) -> dict:
        return self._ipc.send({"cmd": "set_zone_invert", "device": device, "zone": zone, "enabled": enabled})

    def set_zone_gamma(self, device: str, zone: str, enabled: bool) -> dict:
        return self._ipc.send({"cmd": "set_zone_gamma", "device": device, "zone": zone, "enabled": enabled})

    def set_wallpaper_color(self, index: int = None, hex_color: str = None) -> dict:
        req = {"cmd": "set_wallpaper_color"}
        if index is not None:
            req["index"] = index
        if hex_color is not None:
            req["hex"] = hex_color
        return self._ipc.send(req)

    def clear_wallpaper_color(self) -> dict:
        return self._ipc.send({"cmd": "clear_wallpaper_color"})

    def set_zone_name(self, device: str, zone: str, name: str) -> dict:
        return self._ipc.send({"cmd": "set_zone_name", "device": device, "zone": zone, "name": name})

    def freeze(self, on: bool = True) -> dict:
        return self._ipc.send({"cmd": "freeze", "on": on})

    def identify(self, device: str, zone: str, seconds: int = 60) -> dict:
        return self._ipc.send({"cmd": "identify", "device": device, "zone": zone, "seconds": seconds})

    def identify_off(self) -> dict:
        return self._ipc.send({"cmd": "identify", "off": True})

    def led_probe(self, device: str, zone: str, index: int) -> dict:
        return self._ipc.send({"cmd": "led_probe", "device": device, "zone": zone, "index": index})

    def led_probe_off(self) -> dict:
        return self._ipc.send({"cmd": "led_probe", "off": True})

    def resize_zone(self, device: str, zone: str, size: int, keep_count: bool = False) -> dict:
        return self._ipc.send({"cmd": "resize_zone", "device": device, "zone": zone, "size": size,
                               "keep_count": keep_count})

    def set_zone_strip(self, device: str, zone: str, **fields) -> dict:
        """strip_type (addressable, addressable12, single, rgbw or auto), color_order, leds_per_pixel,
        power_limit (A, 0 = none), ma_per_led."""
        return self._ipc.send(dict(fields, cmd="set_zone_strip", device=device, zone=zone))

    def set_zone_sections(self, device: str, zone: str, **fields) -> dict:
        """sections (a list, [] joins the strip again), led_overrides ({LED: hex}) and/or
        set_led ([LED, hex or None]); see iridia/sections.py."""
        return self._ipc.send(dict(fields, cmd="set_zone_sections", device=device, zone=zone))

    def test_colors(self, device: str, zone: str, off: bool = False) -> dict:
        return self._ipc.send({"cmd": "test_colors", "device": device, "zone": zone, "off": off})

    def set_night(self, **kw) -> dict:
        return self._ipc.send(dict(kw, cmd="set_night"))

    def session(self, **kw) -> dict:
        """Lock and idle: lock, idle (keep/dim/off), idle_minutes, dim, test (seconds), or nothing to ask."""
        return self._ipc.send(dict(kw, cmd="session"))

    def set_sleep(self, lights_off: bool) -> dict:
        return self._ipc.send({"cmd": "set_sleep", "lights_off": lights_off})

    def setup(self, action: str, **kw) -> dict:
        """action: list | save | load | restore_backup | delete | rename | export | import"""
        return self._ipc.send(dict(kw, cmd=f"setup_{action}"))

    def lights(self, on: bool) -> dict:
        return self._ipc.send({"cmd": "lights", "on": on})

    def zone_action(self, target, actions, toggle: bool = True) -> dict:
        """Keybind actions for one or more strips: a list like ["on", "color", "ff0000", "bright", "40"],
        or ["normal"]. target: a name, 'all', a comma list, or a list of names."""
        if isinstance(actions, str):
            actions = actions.split()
        return self._ipc.send({"cmd": "zone_action", "target": target, "actions": list(actions), "toggle": toggle})

    def set_color_exact(self, hex_color: str, exact: bool = True) -> dict:
        """Show this colour exactly as picked (skip Palette/Calibrated correction), or not."""
        return self._ipc.send({"cmd": "set_color_exact", "hex": hex_color, "exact": exact})

    def raw(self, req: dict) -> dict:
        return self._ipc.send(dict(req))

    def zone_targets(self) -> dict:
        return self._ipc.send({"cmd": "zone_targets"})

    def forget_all_wallpaper_colors(self) -> dict:
        return self._ipc.send({"cmd": "forget_all_wallpaper_colors"})

    def set_zone_animation(self, device: str, zone: str, animation) -> dict:
        """animation: {"effect": ..., settings...}, or None for the static pattern."""
        return self._ipc.send({"cmd": "set_zone_animation", "device": device, "zone": zone, "animation": animation})

    def animations(self, **kw) -> dict:
        """action="pause"/"resume"/"toggle", or settings: enabled, fps, night_pause, night_slow."""
        return self._ipc.send(dict(kw, cmd="animations"))

    def set_all(self, field: str, value) -> dict:
        return self._ipc.send({"cmd": "set_all", "field": field, "value": value})

    def add_custom_color(self, hex_color: str) -> dict:
        return self._ipc.send({"cmd": "add_custom_color", "hex": hex_color})

    def remove_custom_color(self, hex_color: str) -> dict:
        return self._ipc.send({"cmd": "remove_custom_color", "hex": hex_color})

    def refresh(self) -> dict:
        return self._ipc.send({"cmd": "refresh_wallpaper"})

    def get_log(self, lines: int = 20) -> dict:
        return self._ipc.send({"cmd": "get_log", "lines": lines})

    def reset_detection(self) -> dict:
        """Forget the cached wallpaper-detection backend and probe everything again."""
        return self._ipc.send({"cmd": "reset_detection"})

    def restart(self) -> dict:
        return self._ipc.send({"cmd": "restart"})

    def reload_config(self) -> dict:
        return self._ipc.send({"cmd": "reload_config"})

    def reconnect_openrgb(self) -> dict:
        return self._ipc.send({"cmd": "reconnect_openrgb"})

    def restart_openrgb_server(self) -> dict:
        return self._ipc.send({"cmd": "restart_openrgb_server"})

    def is_alive(self) -> bool:
        return self._ipc.is_alive()
