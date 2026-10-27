"""The daemon's command handling and rendering, with OpenRGB and DDC replaced by fakes.

Every file the daemon touches lives under a temporary HOME, so these never read
or change your real settings, and nothing talks to hardware.
"""
import json
import os
import time

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
        self.real = {}                # device -> [zone names]: what list_devices() reports
        self.epoch = 1                # goes up when OpenRGB reconnects or its device list changes

    def list_devices(self):
        return [{"name": d, "zones": [{"name": z, "led_count": 0} for z in zs]} for d, zs in self.real.items()]

    def send_frames(self, device, frames):
        self.frames.append((device, {z: list(f) for z, f in frames.items()}))
        return True

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
    def __init__(self, bus_number=None, **kwargs):
        self.brightness = 100
        self.last_error = None
        self.available = False
        self.source, self.bus, self.choice, self.displays = None, None, bus_number, []
        self.polls = 0
        self.redetected = []

    def is_available(self):
        return self.available

    def get_brightness(self):
        self.polls += 1
        return self.brightness

    def redetect(self, choice="unchanged"):
        self.redetected.append(choice)
        if choice != "unchanged":
            self.choice = choice


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
    d.ddc.available = True
    d.config.set(("devices", "Strip", "brightness_sync"), True)
    d.config.set(("devices", "Strip", "brightness_range"), [20, 60])
    d._current_brightness = 50
    zcfg = clean_zone_cfg(d.config.get(("devices", "Strip")))
    assert d._zone_brightness_raw(zcfg) == 40
    zcfg["invert_brightness"] = True
    d._current_brightness = 100
    assert d._zone_brightness_raw(zcfg) == 20


def test_following_a_monitor_that_isnt_there_uses_the_manual_brightness(d):
    """No ddcutil, no monitor answering, or the chosen one off: Follow monitor brightness falls back to
    the zone's Manual value instead of a frozen reading; ddcutil is only asked while a zone follows."""
    d.config.set(("devices", "Strip", "manual_brightness"), 30)
    d.config.set(("devices", "Strip", "brightness_sync"), True)
    d._current_brightness = 80
    zcfg = clean_zone_cfg(d.config.get(("devices", "Strip")))
    assert d._zone_brightness_raw(zcfg) == 30
    d.ddc.available = True
    assert d._zone_brightness_raw(zcfg) == 80
    st = _cmd(d, "status")
    assert st["monitor_brightness"] == 80 and st["brightness"] == 100      # the brightest zone: the hub's
    # nothing follows the monitor: ddcutil isn't asked, and the header shows what the LEDs use
    d.config.set(("devices", "Strip", "brightness_sync"), False)
    d.ddc.polls = 0
    d._read_brightness()
    assert d.ddc.polls == 0
    st = _cmd(d, "status")
    assert st["monitor_brightness"] is None and st["brightness"] == 100     # the other devices' 100%
    d.config.set(("devices", "Strip", "brightness_sync"), True)
    d._read_brightness()
    assert d.ddc.polls == 1


def test_a_new_device_doesnt_follow_the_monitor(d):
    d.openrgb.real["New Board"] = ["ARGB 1"]
    d._autoadd_devices()
    assert d.config.get(("devices", "New Board", "zones", "ARGB 1", "brightness_sync")) is False


def test_colours_are_sent_again_after_openrgb_reconnects(d):
    """Static colours are only sent when they change. A restarted OpenRGB shows its own colours, so after
    a reconnect (or a changed device list) everything goes out again, and once more a moment later."""
    t = 1000.0

    def step():
        d._check_openrgb_epoch(t)
        d._update_all_devices()
        return len(d.openrgb.sent)
    n = step()
    assert n and d.openrgb.last("Strip") == ["ff0000"] * 4
    d._needs_update = True
    assert step() == n                                  # nothing changed: nothing sent
    d.openrgb.epoch += 1                                # OpenRGB came back
    assert step() == 2 * n
    t += d.SETTLE_RESEND_SEC + 0.1                      # and once more, for a slow controller
    assert step() == 3 * n
    assert step() == 3 * n                              # then quiet again


def test_picking_the_monitor(d):
    assert _cmd(d, "ddc", bus=6)["ok"]
    assert d.config.get("ddc.bus_number") == 6 and d.ddc.redetected == [6]
    assert _cmd(d, "ddc", bus=None)["ok"]
    assert d.config.get("ddc.bus_number") is None and d.ddc.choice is None
    assert _cmd(d, "ddc", rescan=True)["ok"] and d.ddc.redetected[-1] == "unchanged"
    assert not _cmd(d, "ddc", bus="DP-1")["ok"] and not _cmd(d, "ddc", bus=True)["ok"]


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


def test_picking_a_static_pattern_stops_the_effect(d):
    _animate(d, effect="embers")
    _animate(d, device="Hub v1.0", zone="A", effect="comet")
    _animate(d, device="Hub v1.0", zone="B", effect="comet")
    assert _cmd(d, "set_zone_pattern", device="Strip", zone="", pattern="solid")["ok"]   # Layout tab, painting
    assert d.config.get(("devices", "Strip", "animation")) is None
    assert set(_jobs(d)) == {"Hub v1.0|A", "Hub v1.0|B"}
    assert _cmd(d, "set_all", field="pattern", value="gradient")["ok"]                  # the Everything card
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


# ----------------------------------------------------------------- sections and single LEDs

def test_sections_and_single_leds_on_a_static_strip(d):
    d.config.set(("devices", "Strip", "led_count"), 8)
    r = _cmd(d, "set_zone_sections", device="Strip", zone="",
             sections=[{"start": 3, "type": "pattern", "pattern": "solid", "colors": ["0000ff"]},
                       {"start": 5, "type": "off"}, {"start": 6, "type": "same"}],
             led_overrides={"7": "ffffff", "40": "ffffff"})
    assert r["ok"]
    assert d.config.get(("devices", "Strip", "led_overrides")) == {"7": "ffffff"}
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ff0000"] * 3 + ["0000ff"] * 2 + ["000000", "ff0000", "ffffff"]
    assert _cmd(d, "set_zone_sections", device="Strip", zone="", set_led=[0, "00ff00"])["ok"]
    assert _cmd(d, "set_zone_sections", device="Strip", zone="", set_led=[7, None])["ok"]
    assert not _cmd(d, "set_zone_sections", device="Strip", zone="", set_led=[8, "00ff00"])["ok"]
    assert not _cmd(d, "set_zone_sections", device="Strip", zone="", set_led=[1, "nope"])["ok"]
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["00ff00"] + ["ff0000"] * 2 + ["0000ff"] * 2 + ["000000", "ff0000", "ff0000"]
    assert _cmd(d, "set_zone_sections", device="Strip", zone="", sections=[])["ok"]   # joined again
    assert d.config.get(("devices", "Strip", "sections")) == []
    # a new LED count moves the dividers with it
    _cmd(d, "set_zone_sections", device="Strip", zone="", sections=[{"start": 4, "type": "off"}])
    _cmd(d, "set_zone_led_count", device="Strip", zone="", count=16)
    assert [s["start"] for s in d.config.get(("devices", "Strip", "sections"))] == [0, 8]


def test_an_effect_part_animates_a_static_strip(d):
    d.config.set(("devices", "Strip", "led_count"), 6)
    _cmd(d, "set_zone_sections", device="Strip", zone="",
         sections=[{"start": 2, "type": "effect", "animation": {"effect": "rainbow"}, "colors": ["00ff00"]},
                   {"start": 4, "type": "same"}])
    jobs = _jobs(d)
    assert "Strip|" in jobs
    a, b = jobs["Strip|"].frame(0.0), jobs["Strip|"].frame(1.0)
    assert a[:2] == a[4:] == [(255, 0, 0)] * 2 and a[2:4] != b[2:4]
    d._update_all_devices()
    assert d.openrgb.last("Strip") is None                  # the animator sends it
    _cmd(d, "animations", action="pause")
    d._update_all_devices()                                 # paused: the effect part shows its first color
    assert d.openrgb.last("Strip") == ["ff0000"] * 2 + ["00ff00"] * 2 + ["ff0000"] * 2


def test_an_effect_strip_keeps_its_static_parts(d):
    d.config.set(("devices", "Strip", "led_count"), 6)
    _animate(d, effect="rainbow")
    _cmd(d, "set_zone_sections", device="Strip", zone="", sections=[{"start": 3, "type": "off"}],
         led_overrides={"0": "0000ff"})
    f = _jobs(d)["Strip|"].frame(2.0)
    assert f[0] == (0, 0, 255) and f[3:] == [(0, 0, 0)] * 3 and f[1] != (0, 0, 0)


def test_split_cli(d, monkeypatch, capsys):
    from iridia import cli

    class C:
        def send(self, req):
            return d.handle_command(dict(req))
    monkeypatch.setattr(cli, "_client", lambda: C())
    d.config.set(("devices", "Strip", "led_count"), 10)

    def run(*words):
        return cli.main(["split", "Strip", *words])
    assert run("even", "3") == 0
    assert "3 parts, 10 LEDs (4 + 3 + 3)" in capsys.readouterr().out
    assert run("part", "2", "pattern", "gradient", "ff0000", "1") == 0
    assert run("part", "3", "off") == 0
    assert run("led", "1", "ffffff") == 0 and run("led", "2", "off") == 0
    out = capsys.readouterr().out
    assert "2. LEDs 5-7: pattern gradient, colors ff0000 0" in out and "3. LEDs 8-10: off" in out
    assert "Single LEDs: 1=ffffff, 2=off" in out
    assert run("at", "3") == 0 and "2 parts" in capsys.readouterr().out
    assert run("part", "9", "off") == 2 and run("led", "11", "ffffff") == 1
    assert run("join") == 0 and run("clear-leds") == 0
    assert "one part (10 LEDs), not split" in capsys.readouterr().out


# ----------------------------------------------------------------- lock and idle

def test_lock_and_idle_fade_the_leds(d, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(daemon_mod.time, "monotonic", lambda: clock[0])
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ff0000"] * 4
    r = _cmd(d, "session", lock="off", idle="dim", dim=50, idle_minutes=5)
    assert r["ok"] and r["session"]["lock"] == "off" and r["session"]["state"] == "active"
    assert not _cmd(d, "session", lock="sometimes")["ok"]
    _cmd(d, "session", idle_hook=True)                      # hypridle: iridia idle on
    assert d._sess_state == "idle"
    clock[0] += 0.5                                          # fading: part of the way down
    d._last_sent = {}
    d._update_all_devices()
    mid = d.openrgb.last("Strip")[0]
    assert "7f0000" < mid < "ff0000"
    clock[0] += 5
    d._last_sent = {}
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["7f0000"] * 4        # dimmed to 50%
    _cmd(d, "session", lock_hook=True)                      # locked wins: off
    clock[0] += 5
    d._last_sent = {}
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["000000"] * 4
    # a zone set to ignore it stays lit
    assert _cmd(d, "set_zone_strip", device="Hub v1.0", zone="A", session_ignore=True)["ok"]
    d._update_all_devices()
    zoned = [c for dev, c, cfg in d.openrgb.sent if dev == "Hub v1.0" and set(cfg) == {"A"}]
    assert zoned[-1] == ["00ff00"] * 2
    _cmd(d, "session", lock_hook=False, idle_hook=False)
    assert d._sess_state == "active"
    clock[0] += 5
    d._last_sent = {}
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ff0000"] * 4


def test_try_it_shows_off_even_when_lock_is_keep(d, monkeypatch):
    clock = [50.0]
    monkeypatch.setattr(daemon_mod.time, "monotonic", lambda: clock[0])
    r = _cmd(d, "session", test=5)
    assert r["session"]["state"] == "locked" and r["session"]["factor"] == 0.0
    clock[0] += 6
    d._update_session()
    assert d._sess_state == "active"


def test_session_cli(d, monkeypatch, capsys):
    from iridia import cli

    class C:
        def send(self, req):
            return d.handle_command(dict(req))
    monkeypatch.setattr(cli, "_client", lambda: C())
    assert cli.main(["session", "--lock", "off", "--idle", "dim", "--dim", "30", "--idle-minutes", "15"]) == 0
    out = capsys.readouterr().out
    assert "When the screen locks: turn off" in out and "After 15 min without input: dim to 30%" in out
    assert cli.main(["idle", "on"]) == 0 and d._hooks["idle"] is True
    assert cli.main(["session"]) == 0 and "Now: idle" in capsys.readouterr().out
    assert cli.main(["idle", "off"]) == 0 and cli.main(["lock", "on"]) == 0 and d._hooks == {"lock": True,
                                                                                         "idle": False}
    assert cli.main(["session", "hooks"]) == 0 and "on-timeout = iridia idle on" in capsys.readouterr().out


# ----------------------------------------------------------------- sensors

class FakeSensors:
    def __init__(self):
        self.wanted, self.vals = set(), {}

    def set_wanted(self, ids):
        self.wanted = set(ids)

    def update(self, now=None):
        return True

    def value(self, sid):
        return self.vals.get(sid)

    def values(self):
        return {k: self.vals.get(k) for k in sorted(self.wanted)}

    def listing(self):
        return [{"id": "ram", "name": "Memory use", "unit": "%", "value": self.vals.get("ram"), "min": 0,
                 "max": 100, "wakes_gpu": False}]

    def stop(self):
        pass


def test_a_sensor_part_shows_the_reading(d):
    d.sensors = FakeSensors()
    d.sensors.vals["ram"] = 50.0
    d.config.set(("devices", "Strip", "led_count"), 4)
    assert _cmd(d, "set_zone_sections", device="Strip", zone="",
                sections=[{"start": 0, "type": "sensor", "sensor": "ram", "show": "both", "palette": "colors",
                           "colors": ["ffffff"]}])["ok"]
    d._update_sensors()
    assert d.sensors.wanted == {"ram"} and d._sensor_zones == {("Strip", "")}
    d._update_sensor_zones()
    assert not d._sensor_zones
    assert d.openrgb.last("Strip") == ["ffffff"] * 2 + ["000000"] * 2
    d.sensors.vals["ram"] = 100.0
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ffffff"] * 4
    st = _cmd(d, "status")
    assert st["sensors"] == {"ram": 100.0}
    assert _cmd(d, "sensors")["sensors"][0]["id"] == "ram"
    _cmd(d, "set_zone_enabled", device="Strip", zone="", enabled=False)       # nobody shows it: not read
    d._update_sensors()
    assert d.sensors.wanted == set()


def test_a_dim_rest_of_bar_stays_dim_with_palette_correction(d):
    """Palette snaps by hue: the bar's dimmed rest (and its tip) came out at full strength, so "the rest of
    the bar dim" lit the whole strip. Correction now works on the full color, the level is applied after."""
    d.sensors = FakeSensors()
    d.sensors.vals["ram"] = 55.0
    d.config.set(("devices", "Strip", "led_count"), 10)
    d.config.set(("devices", "Strip", "mode"), "palette")
    assert _cmd(d, "set_zone_sections", device="Strip", zone="",
                sections=[{"start": 0, "type": "sensor", "sensor": "ram", "show": "both", "palette": "colors",
                           "colors": ["ff2000"], "background": "dim"}])["ok"]
    d._update_all_devices()
    leds = [sum(bytes.fromhex(c)) for c in d.openrgb.last("Strip")]
    full = leds[0]
    assert full > 0 and leds[:5] == [full] * 5
    assert 0 < leds[5] < full                           # the tip: partly on (55% of 10 LEDs)
    assert all(0 < v <= full * 0.2 for v in leds[6:])   # the rest: dim, not lit


def test_sensor_cli(d, monkeypatch, capsys):
    from iridia import cli

    class C:
        def send(self, req):
            return d.handle_command(dict(req))
    monkeypatch.setattr(cli, "_client", lambda: C())
    d.sensors = FakeSensors()
    d.sensors.vals["ram"] = 42.0
    assert cli.main(["sensors"]) == 0 and "Memory use" in capsys.readouterr().out
    d.config.set(("devices", "Strip", "led_count"), 10)
    assert cli.main(["split", "Strip", "even", "2"]) == 0
    assert cli.main(["split", "Strip", "part", "2", "sensor", "cpu_temp", "both", "max=85", "flash=80",
                     "background=dim"]) == 0
    out = capsys.readouterr().out
    assert "2. LEDs 6-10: sensor cpu_temp as both, 30 to 85, flashing above 80" in out


def test_a_daemon_started_in_a_session_stops_when_it_ends(d, tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    d._sessions_dir = str(sessions)
    monkeypatch.setenv("XDG_SESSION_ID", "4")
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv("SYSTEMD_EXEC_PID", raising=False)
    assert not d._session_over()                        # no session file yet: nothing to go by
    (sessions / "4").write_text("UID=1000\nSTATE=active\n")
    assert not d._session_over()
    (sessions / "4").write_text("UID=1000\nSTATE=closing\n")
    assert d._session_over()
    (sessions / "4").unlink()
    assert d._session_over()                            # seen before, gone now
    monkeypatch.setenv("SYSTEMD_EXEC_PID", str(os.getpid()))
    assert not d._session_over()                        # systemd stops its own services


# ----------------------------------------------------------------- notification flashes

class FakeWatcher:
    def __init__(self):
        self.running, self.method = False, "dbus-monitor"

    def set_needed(self, on):
        self.running = on

    def stop(self):
        self.running = False


def _peak(d):
    d._flash.t0 = time.monotonic() - d._flash.duration * 0.25      # a pulse at its brightest


def test_a_notification_flashes_only_the_chosen_leds(d, monkeypatch):
    monkeypatch.setattr("iridia.notifywatch.dnd_on", lambda: False)
    d.notifywatch = FakeWatcher()
    r = _cmd(d, "notify", enabled=True, color="custom", hex="0000ff",
             targets=[{"device": "Strip", "zone": "", "start": 2, "end": 3}, {"device": "Nope"}])
    assert r["ok"] and r["notify"]["targets"] == [{"device": "Strip", "zone": "", "start": 2, "end": 3},
                                                   {"device": "Nope", "zone": ""}]
    d._update_notify()
    assert d.notifywatch.running                    # listening only now that it's wanted
    d._update_all_devices()
    d._on_notification("Signal", False)
    d._update_notify()
    assert d._flash is not None and "Signal" in d.config.get("notify")["seen"]
    _peak(d)
    jobs = _jobs(d)
    assert jobs["Strip|"].frame(0.0) == [(255, 0, 0), (0, 0, 255), (0, 0, 255), (255, 0, 0)]
    d._update_all_devices()
    sent = len(d.openrgb.sent)
    d._update_all_devices()
    assert len(d.openrgb.sent) == sent              # the flash job sends it, not the static path
    d._flash.t0 -= 10                               # over: the static colours go out again
    d._update_notify()
    assert d._flash is None and "Strip|" not in _jobs(d)
    d._update_all_devices()
    assert d.openrgb.last("Strip") == ["ff0000"] * 4


def test_a_flash_on_one_zone_sends_the_whole_device(d, monkeypatch):
    d.notifywatch = FakeWatcher()
    _cmd(d, "notify", targets=[{"device": "Hub v1.0", "zone": "A"}], color="custom", hex="ffffff",
         effect="flash")
    d._update_all_devices()
    assert _cmd(d, "notify", test=True)["ok"]
    d._flash.t0 = time.monotonic() - 0.01           # the first blink
    jobs = _jobs(d)
    assert jobs["Hub v1.0|A"].frame(0.0) == [(255, 255, 255)] * 2
    assert jobs["Hub v1.0|B"].frame(0.0) == [(0, 0, 255)] * 2


def test_a_flash_over_a_part_of_an_animated_strip(d):
    d.notifywatch = FakeWatcher()
    d.config.set(("devices", "Strip", "led_count"), 6)
    _animate(d, effect="rainbow")
    _cmd(d, "set_zone_sections", device="Strip", zone="", sections=[{"start": 4, "type": "same"}])
    _cmd(d, "notify", targets=[{"device": "Strip", "zone": "", "part": 1}], color="custom", hex="00ff00")
    assert _cmd(d, "notify", test=True)["ok"]
    _peak(d)
    f = _jobs(d)["Strip|"].frame(1.0)
    assert f[4:] == [(0, 255, 0)] * 2 and (0, 255, 0) not in f[:4]


def test_which_notifications_flash(d, monkeypatch):
    dnd = [False]
    monkeypatch.setattr("iridia.notifywatch.dnd_on", lambda: dnd[0])
    d.notifywatch = FakeWatcher()
    _cmd(d, "notify", enabled=True, targets=[{"device": "Strip"}], apps="except", app_list=["Signal"])
    for app, urgent, flashes in (("Signal", True, False), ("Thunderbird", True, True)):
        d._flash = None
        d._on_notification(app, urgent)
        d._update_notify()
        assert (d._flash is not None) == flashes, app
    assert d._flash.rgb == (255, 0, 0)              # urgent: red
    dnd[0] = True
    d._flash = None
    d._on_notification("Thunderbird", False)
    d._update_notify()
    assert d._flash is None                         # Do Not Disturb
    assert _cmd(d, "notify", forget=True)["notify"]["seen"] == []
    assert not _cmd(d, "notify", test=True, test_targets=[])["ok"]
    _cmd(d, "notify", enabled=False)
    d._update_notify()
    assert not d.notifywatch.running


def test_notify_cli(d, monkeypatch, capsys):
    from iridia import cli

    class C:
        def send(self, req):
            return d.handle_command(dict(req))
    monkeypatch.setattr(cli, "_client", lambda: C())
    d.notifywatch = FakeWatcher()
    assert cli.main(["notify", "add", "Hub v1.0/A", "leds", "2-2"]) == 0
    assert cli.main(["notify", "add", "Strip", "part", "1"]) == 0
    assert cli.main(["notify", "on", "--effect", "sweep", "--color", "#00FF00", "--duration", "2"]) == 0
    out = capsys.readouterr().out
    assert "Hub v1.0/A: LEDs 2-2" in out and "Strip: part 1" in out and "sweep, 2.0 s, #00ff00" in out
    assert d._notify_settings()["enabled"] is True
    assert cli.main(["notify", "test"]) == 0 and d._flash is not None
    assert cli.main(["notify", "add", "nothing-here"]) == 1
    assert cli.main(["notify", "add", "Strip", "half"]) == 2
    assert cli.main(["notify", "clear"]) == 0 and d._notify_settings()["targets"] == []


def test_the_leds_come_all_the_way_back_after_unlocking(d, monkeypatch):
    """The main loop looks once a second: a fade shorter than that must still end at full brightness."""
    clock = [1000.0]
    monkeypatch.setattr(daemon_mod.time, "monotonic", lambda: clock[0])
    d.sessionwatch = None

    def tick(after):
        clock[0] += after
        d._update_session()
        if d._glide_active:
            d._needs_update = True
        if d._needs_update:
            d._glide_active = False
            d._update_all_devices()
    _cmd(d, "session", lock="off")
    tick(0)
    _cmd(d, "session", lock_hook=True)                      # locked: fades out over 2 seconds
    for _ in range(4):
        tick(1.0)
    assert d.openrgb.last("Strip") == ["000000"] * 4
    _cmd(d, "session", lock_hook=False)                     # unlocked: half a second back up
    tick(0.01)
    assert d.openrgb.last("Strip") != ["ff0000"] * 4        # the first step of the fade
    tick(1.0)
    assert d.openrgb.last("Strip") == ["ff0000"] * 4
    _cmd(d, "session", lock="dim", dim=10, lock_hook=True)
    for _ in range(4):
        tick(1.0)
    _cmd(d, "session", lock_hook=False)
    tick(0.01)
    tick(1.0)
    assert d.openrgb.last("Strip") == ["ff0000"] * 4
