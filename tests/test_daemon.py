"""The daemon's command handling and rendering, with OpenRGB and DDC replaced by fakes.

Every file the daemon touches lives under a temporary HOME, so these never read
or change your real settings, and nothing talks to hardware.
"""
import json

import pytest

from iridia import daemon as daemon_mod
from iridia.daemon import clean_zone_cfg, pack_rgbw, reorder


class FakeOpenRGB:
    """Stands in for OpenRGBController: records what would have been sent."""

    def __init__(self, host=None, port=None):
        self.host = host or "127.0.0.1"
        self.client = None
        self.connected_since = None
        self.last_error = None
        self.no_devices_since = None
        self.devices = {}
        self.sent = []                # (device, colors, zones_config)

        self.frames = []              # (device, {zone: [(r, g, b), ...]}) from the animation thread
        self._hw_applied = {}
        self.real = {}                # device -> [zone names]: what list_devices() reports

    def list_devices(self):
        return [{"name": d, "zones": [{"name": z, "led_count": 0} for z in zs],
                 "hardware_modes": [{"name": "Rainbow", "speed": [1, 3, 2]}]} for d, zs in self.real.items()]

    def send_frames(self, device, frames):
        self.frames.append((device, {z: list(f) for z, f in frames.items()}))
        return True

    def apply_hardware_mode(self, device, spec):
        self._hw_applied[device] = repr(spec)

    def hardware_mode_released(self, device):
        self._hw_applied.pop(device, None)

    def send(self, device_name, colors, zones_config=None):
        self.sent.append((device_name, list(colors), zones_config))
        return True

    def disconnect(self):
        pass

    def last(self, device):
        for dev, colors, _ in reversed(self.sent):
            if dev == device:
                return colors
        return None


class FakeDDC:
    def __init__(self, **kwargs):
        self.brightness = 100
        self.last_error = None

    def is_available(self):
        return False

    def get_brightness(self):
        return self.brightness


DEVICES = {
    # A flat, single-zone device (most ARGB headers)
    "Strip": {"led_count": 4, "pattern": "solid", "pattern_colors": ["ff0000"],
              "brightness_sync": False, "manual_brightness": 100},
    # A device with real zones; the name has dots on purpose
    "Hub v1.0": {"zones": {
        "A": {"led_count": 2, "pattern": "solid", "pattern_colors": ["00ff00"],
              "brightness_sync": False, "manual_brightness": 100},
        "B": {"led_count": 2, "pattern": "solid", "pattern_colors": ["0000ff"],
              "brightness_sync": False, "manual_brightness": 100},
    }},
}


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr("iridia.setups.CONFIG_DIR", str(tmp_path / ".config" / "iridia"))
    monkeypatch.setattr(daemon_mod, "OpenRGBController", FakeOpenRGB)
    monkeypatch.setattr(daemon_mod, "DDCController", FakeDDC)
    cfg_dir = tmp_path / ".config" / "iridia"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"devices": DEVICES}))
    dm = daemon_mod.Daemon()
    yield dm
    dm.ipc.stop()


def _cmd(d, cmd, **kw):
    return d.handle_command(dict(kw, cmd=cmd))


# ----------------------------------------------------------------- commands

def test_ping_and_unknown(d):
    assert _cmd(d, "ping")["ok"] is True
    resp = _cmd(d, "no_such_thing")
    assert resp == {"ok": False, "error": "unknown command: no_such_thing"}


def test_status_works_without_openrgb(d):
    resp = _cmd(d, "status")
    assert resp["ok"] is True
    assert resp["openrgb_connected"] is False
    assert set(resp["device_configs"]) == {"Strip", "Hub v1.0"}


def test_zone_pattern_goes_to_zone_or_flat_device(d):
    assert _cmd(d, "set_zone_pattern", device="Hub v1.0", zone="A", pattern="gradient")["ok"]
    assert d.config.get(("devices", "Hub v1.0", "zones", "A", "pattern")) == "gradient"
    assert d.config.get(("devices", "Hub v1.0", "zones", "B", "pattern")) == "solid"
    # A flat device stores it on the device, and must not grow a "zones" section
    assert _cmd(d, "set_zone_pattern", device="Strip", zone="Strip", pattern="segments")["ok"]
    assert d.config.get(("devices", "Strip", "pattern")) == "segments"
    assert "zones" not in d.config.get(("devices", "Strip"))


def test_zone_pattern_rejects_bad_input(d):
    assert not _cmd(d, "set_zone_pattern", device="Nope", zone="", pattern="solid")["ok"]
    assert not _cmd(d, "set_zone_pattern", device="Strip", zone="", pattern="rainbow")["ok"]


def test_changing_pattern_drops_stops(d):
    assert _cmd(d, "set_zone_pattern_params", device="Strip", zone="",
                params={"stops": [0.25], "reverse": 1})["ok"]
    assert d.config.get(("devices", "Strip", "pattern_params")) == {"stops": [0.25], "reverse": True}
    _cmd(d, "set_zone_pattern", device="Strip", zone="", pattern="gradient")
    assert d.config.get(("devices", "Strip", "pattern_params")) == {"reverse": True}


def test_pattern_params_validation(d):
    assert not _cmd(d, "set_zone_pattern_params", device="Strip", zone="", params="x")["ok"]
    assert not _cmd(d, "set_zone_pattern_params", device="Strip", zone="", params={"stops": ["a"]})["ok"]
    _cmd(d, "set_zone_pattern_params", device="Strip", zone="", params={"stops": [5, -1]})
    assert d.config.get(("devices", "Strip", "pattern_params", "stops")) == [1.0, 0.0]


def test_zone_colors_validation(d):
    assert _cmd(d, "set_zone_colors", device="Strip", zone="", indices=[1, "#ABCDEF"])["ok"]
    assert d.config.get(("devices", "Strip", "pattern_colors")) == [1, "abcdef"]
    for bad in ([], [True], [-1], ["nothex"], "ff0000"):
        assert not _cmd(d, "set_zone_colors", device="Strip", zone="", indices=bad)["ok"], bad


def test_zone_mode_validation(d):
    assert _cmd(d, "set_zone_mode", device="Strip", zone="", mode="palette")["ok"]
    assert not _cmd(d, "set_zone_mode", device="Strip", zone="", mode="vivid")["ok"]


def test_unknown_zone_on_zoned_device_is_an_error_reply(d):
    for cmd, kw in (("set_zone_pattern", {"pattern": "solid"}), ("set_zone_colors", {"indices": [0]}),
                    ("set_zone_manual_brightness", {"value": 50}), ("set_zone_enabled", {"enabled": False})):
        resp = _cmd(d, cmd, device="Hub v1.0", zone="Z", **kw)
        assert resp == {"ok": False, "error": "zone 'Z' not found on 'Hub v1.0'"}, cmd
    assert "Z" not in d.config.get(("devices", "Hub v1.0", "zones"))


def test_set_all(d):
    resp = _cmd(d, "set_all", field="manual_brightness", value=40)
    assert resp == {"ok": True, "zones": 3}
    assert d.config.get(("devices", "Strip", "manual_brightness")) == 40
    assert d.config.get(("devices", "Hub v1.0", "zones", "B", "manual_brightness")) == 40
    assert not _cmd(d, "set_all", field="manual_brightness", value=101)["ok"]
    assert not _cmd(d, "set_all", field="manual_brightness", value=True)["ok"]
    assert not _cmd(d, "set_all", field="brightness_range", value=[50, 10])["ok"]
    assert not _cmd(d, "set_all", field="led_count", value=5)["ok"]


def test_zone_name(d):
    assert _cmd(d, "set_zone_name", device="Hub v1.0", zone="A", name="  Desk   back ")["ok"]
    assert d.config.get(("devices", "Hub v1.0", "zones", "A", "display_name")) == "Desk back"
    _cmd(d, "set_zone_name", device="Hub v1.0", zone="A", name="")
    assert "display_name" not in d.config.get(("devices", "Hub v1.0", "zones", "A"))
    assert not _cmd(d, "set_zone_name", device="Hub v1.0", zone="Z", name="x")["ok"]


def test_removing_custom_color_updates_zones(d):
    assert _cmd(d, "add_custom_color", hex="#FF0000")["ok"]
    assert not _cmd(d, "add_custom_color", hex="red")["ok"]
    _cmd(d, "remove_custom_color", hex="ff0000")
    # "Strip" only used that colour, so it falls back to the first wallpaper colour
    assert d.config.get(("devices", "Strip", "pattern_colors")) == [0]
    assert d.config.get(("devices", "Hub v1.0", "zones", "A", "pattern_colors")) == ["00ff00"]


def test_get_log_clamps_lines(d):
    assert _cmd(d, "get_log", lines="lots")["ok"]
    assert _cmd(d, "get_log", lines=10 ** 9)["ok"]


# ---------------------------------------------------------------- rendering

def test_renders_configured_colors(d):
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ff0000"] * 4
    zoned = [(cfg, colors) for dev, colors, cfg in d.openrgb.sent if dev == "Hub v1.0"]
    assert ({"A"}, ["00ff00"] * 2) in [(set(cfg), colors) for cfg, colors in zoned]
    assert ({"B"}, ["0000ff"] * 2) in [(set(cfg), colors) for cfg, colors in zoned]


def test_unchanged_colors_are_not_resent(d):
    d._update_all_devices()
    n = len(d.openrgb.sent)
    d._update_all_devices()
    assert len(d.openrgb.sent) == n


def test_manual_brightness_scales_colors(d):
    _cmd(d, "set_zone_manual_brightness", device="Strip", zone="", value=50)
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["7f0000"] * 4


def test_monitor_brightness_with_range_and_invert(d):
    d.config.set(("devices", "Strip", "brightness_sync"), True)
    d.config.set(("devices", "Strip", "brightness_range"), [20, 60])
    d._current_brightness = 50
    zcfg = clean_zone_cfg(d.config.get(("devices", "Strip")))
    assert d._zone_brightness_raw(zcfg) == 40
    zcfg["invert_brightness"] = True
    d._current_brightness = 100
    assert d._zone_brightness_raw(zcfg) == 20


def test_disabled_zone_and_lights_off_send_black(d):
    _cmd(d, "set_zone_enabled", device="Strip", zone="", enabled=False)
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["000000"] * 4
    _cmd(d, "set_zone_enabled", device="Strip", zone="", enabled=True)
    _cmd(d, "lights", on=False)
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["000000"] * 4
    assert _cmd(d, "lights", on=True) == {"ok": True, "lights_off": False}
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ff0000"] * 4


def test_color_order_and_power_limit(d):
    d.config.set(("devices", "Strip", "color_order"), "GRB")
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["00ff00"] * 4      # red sent as G R B
    # 4 LEDs of full red at 60 mA per white LED = 0.08 A; cap it at half that
    d.config.set(("devices", "Strip", "color_order"), "RGB")
    d.config.set(("devices", "Strip", "power_limit"), 0.04)
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["7f0000"] * 4
    assert d._strip_info["Strip|"]["limited"] is True


def test_one_broken_zone_does_not_stop_the_others(d, monkeypatch):
    real = d._update_zone

    def flaky(device, zone, *a, **kw):
        if zone == "A":
            raise RuntimeError("boom")
        return real(device, zone, *a, **kw)

    monkeypatch.setattr(d, "_update_zone", flaky)
    d._update_all_devices()
    assert ("Hub v1.0", "A") in d._zone_errors
    assert d.openrgb.last("Strip") == ["ff0000"] * 4


# ------------------------------------------------------------------ helpers

def test_clean_zone_cfg_repairs_junk():
    z = clean_zone_cfg({"led_count": "lots", "pattern_colors": [True, -1, 3, "#00FF00", "bad"],
                        "pattern": 5, "mode": "vivid", "manual_brightness": 900,
                        "brightness_range": [80, 20], "color_order": "grb", "strip_type": "laser"})
    assert z["led_count"] == 20
    assert z["pattern_colors"] == [3, "00ff00"]
    assert z["pattern"] == "solid"
    assert "mode" not in z and "strip_type" not in z
    assert z["manual_brightness"] == 100
    assert z["brightness_range"] == [20, 80]
    assert z["color_order"] == "GRB"


def test_reorder():
    assert reorder("112233", "RGB") == "112233"
    assert reorder("112233", "GRB") == "221133"
    assert reorder("112233", "BGR") == "332211"


def test_pack_rgbw():
    # White goes to the W channel; 2 RGBW LEDs (8 bytes) become 3 padded RGB "LEDs"
    out = pack_rgbw(["ffffff", "ff0000"])
    assert len(out) == 3
    stream = []
    for c in out:          # undo the header's G R B byte order
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        stream += [g, r, b]
    assert stream[:8] == [0, 0, 0, 255, 0, 255, 0, 0]


# --------------------------------------------------------------- animations

def _animate(d, device="Strip", zone="", **anim):
    r = _cmd(d, "set_zone_animation", device=device, zone=zone, animation=anim)
    assert r["ok"], r
    return r["animation"]


def _jobs(d):
    d.openrgb.real = {"Strip": [], "Hub v1.0": ["A", "B"]}
    d._refresh_animations(True)
    d._animator.stop()                  # tests drive frames by hand
    return {j.key: j for _w, js in d._animator._jobs.values() for j in js}


def test_set_zone_animation_validates_and_keeps_settings(d):
    a = _animate(d, effect="breathing", speed=999, min=80, max=20)
    assert a["speed"] == 30.0 and (a["min"], a["max"]) == (20, 80)
    a = _animate(d, effect="breathing", easing="sharp")     # same effect: other settings kept
    assert a["easing"] == "sharp" and a["speed"] == 30.0
    a = _animate(d, effect="comet")                          # new effect: its own defaults
    assert a["effect"] == "comet" and a["speed"] == 30.0 and "easing" not in a
    assert not _cmd(d, "set_zone_animation", device="Strip", zone="", animation={"effect": "disco"})["ok"]
    assert _cmd(d, "set_zone_animation", device="Strip", zone="", animation="static")["animation"] is None
    assert d.config.get(("devices", "Strip", "animation")) is None


def test_set_all_effect_and_status(d):
    assert _cmd(d, "set_all", field="animation", value={"effect": "rainbow", "width": 50}) == {"ok": True, "zones": 3}
    st = _cmd(d, "status")
    assert st["device_configs"]["Hub v1.0"]["zones"]["B"]["animation"]["width"] == 50
    assert set(_jobs(d)) == {"Strip|", "Hub v1.0|A", "Hub v1.0|B"}
    assert _cmd(d, "set_all", field="animation", value=None)["ok"]
    assert _jobs(d) == {}


def test_animated_zone_is_left_to_the_animator_until_something_pauses_it(d):
    _animate(d, effect="color_cycle")
    jobs = _jobs(d)
    d._update_all_devices()
    assert d.openrgb.last("Strip") is None                  # the static path leaves it alone
    assert jobs["Strip|"].frame(0.0) is not None
    _cmd(d, "identify", device="Strip", zone="", seconds=30)
    assert jobs["Strip|"].frame(0.0) is None                # paused: the static path shows identify
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ffffff"] * 4


def test_paused_or_switched_off_animations_show_the_first_color(d):
    _animate(d, effect="rainbow")
    _jobs(d)
    assert _cmd(d, "animations", action="pause") == {"ok": True, "paused": True}
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ff0000"] * 4
    _cmd(d, "animations", action="resume")
    assert _cmd(d, "animations", enabled=False)["settings"]["enabled"] is False
    d._last_sent = {}
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ff0000"] * 4
    assert not _cmd(d, "animations", fps=25)["ok"]
    assert _cmd(d, "animations", fps=60)["settings"]["fps"] == 60


def test_keybind_effect_toggles_and_can_be_saved(d):
    r = _cmd(d, "zone_action", target="Strip", actions=["effect", "breathing", "speed=3", "min=20"])
    assert r["ok"] and d._overlays["Strip|"]["effect"]["speed"] == 3.0
    assert "Strip|" in _jobs(d)
    _cmd(d, "zone_action", target="Strip", actions=["effect", "breathing", "speed=3", "min=20"])
    assert "Strip|" not in d._overlays                      # same key again: back to normal
    assert not _cmd(d, "zone_action", target="Strip", actions=["effect", "disco"])["ok"]
    assert not _cmd(d, "zone_action", target="Strip", actions=["effect", "comet", "color", "ff0000"])["ok"]
    r = _cmd(d, "zone_action", target="all", actions=["effect", "comet"], save=True)
    assert r["ok"] and d.config.get(("devices", "Hub v1.0", "zones", "A", "animation"))["effect"] == "comet"
    _cmd(d, "zone_action", target="Strip", actions=["effect", "static"], save=True)
    assert d.config.get(("devices", "Strip", "animation")) is None


@pytest.mark.parametrize("mode", ["full", "palette", "calibrated"])
def test_animated_frames_get_the_same_correction_as_static(d, mode):
    """A still frame from the animator must equal what the static path sends for the same colors."""
    d.config.set(("devices", "Strip", "mode"), mode)
    d.config.set(("devices", "Strip", "manual_brightness"), 40)
    d.config.set(("devices", "Strip", "pattern_colors"), ["e0a030"])
    d.config.set(("devices", "Strip", "gamma_correction"), mode == "full")
    d._update_all_devices()
    static = d.openrgb.last("Strip")
    _animate(d, effect="color_cycle")                       # one color: a still frame
    frame = _jobs(d)["Strip|"].frame(5.0)
    assert ["%02x%02x%02x" % c for c in frame] == static


def test_controller_effect_takes_the_device_off_iridia(d):
    d.openrgb.real = {"Strip": [], "Hub v1.0": ["A", "B"]}
    assert _cmd(d, "set_device_hardware_effect", device="Strip", effect={"mode": "Rainbow", "speed": 2})["ok"]
    d._apply_hardware_effects()
    assert "Strip" not in d.openrgb._hw_applied             # off until switched on in Settings
    _cmd(d, "set_hardware_effects", enabled=True)
    d.openrgb.devices = {"Strip": object()}
    d._apply_hardware_effects()
    assert "Strip" in d.openrgb._hw_applied
    d._update_all_devices()
    assert d.openrgb.last("Strip") is None                  # it runs its own effect
    _cmd(d, "lights", on=False)
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["000000"] * 4        # lights off still darkens it
    _cmd(d, "lights", on=True)
    _cmd(d, "set_device_hardware_effect", device="Strip", effect=None)
    d._apply_hardware_effects()
    assert "Strip" not in d.openrgb._hw_applied


def test_brightness_glides_instead_of_jumping(d):
    zc = clean_zone_cfg(d.config.get(("devices", "Strip")))
    assert d._brightness_now("Strip|", zc) == 100
    zc["manual_brightness"] = 0
    first = d._brightness_now("Strip|", zc)
    assert first == 100 and d._glide_active                # starts gliding from where it was
    import time as _t
    _t.sleep(d.GLIDE_SEC / 2)
    mid = d._brightness_now("Strip|", zc)
    assert 10 < mid < 90
    _t.sleep(d.GLIDE_SEC)
    assert d._brightness_now("Strip|", zc) == 0
