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
        self.devices = {}
        self.sent = []                # (device, colors, zones_config)

    def list_devices(self):
        return []

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
