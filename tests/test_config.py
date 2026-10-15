import json

from iridia.config import DEFAULT_CONFIG, Config


def test_creates_defaults(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(str(path))
    assert path.exists()
    assert cfg.raw == DEFAULT_CONFIG


def test_repairs_bad_types(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "ddc": {"enabled": "yes", "fallback_brightness": "oops"},
        "timing": {"ddc_poll_interval_sec": "2.5"},
        "logging": "nope",
        "devices": {"Good": {"zones": {"Z": {}, "Bad": 3}, "hardware_effect": {"mode": "Wave"}}, "Broken": 5},
        "custom_colors": {},
        "hardware_effects": {"enabled": True},       # from 1.2.0 test builds
    }))
    cfg = Config(str(path))
    assert cfg.get("ddc.enabled") is True
    assert cfg.get("ddc.fallback_brightness") == 100
    assert cfg.get("timing.ddc_poll_interval_sec") == 2.5
    assert cfg.logging == DEFAULT_CONFIG["logging"]
    assert cfg.devices == {"Good": {"zones": {"Z": {}}}}
    assert cfg.get("custom_colors") == []
    assert "hardware_effects" not in cfg.raw


def test_invalid_json_is_backed_up(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    cfg = Config(str(path))
    assert (tmp_path / "config.json.bak").read_text() == "{not json"
    assert cfg.raw == DEFAULT_CONFIG


def test_set_get_with_dotted_device_names(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(str(path))
    cfg.set(("devices", "Hub v1.0", "led_count"), 42)
    assert cfg.get(("devices", "Hub v1.0", "led_count")) == 42
    assert json.loads(path.read_text())["devices"]["Hub v1.0"]["led_count"] == 42
    # get() returns copies, so callers can't mutate the config by accident
    cfg.get("devices")["Hub v1.0"]["led_count"] = 1
    assert cfg.get(("devices", "Hub v1.0", "led_count")) == 42
