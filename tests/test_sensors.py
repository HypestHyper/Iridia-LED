"""Sensors from a fake /sys and /proc, and how a sensor part is drawn."""
import os

from iridia import sections as S
from iridia.sensors import SensorHub, default_range, valid_id


def _hwmon(root, n, name, temps):
    d = root / "sys" / "class" / "hwmon" / f"hwmon{n}"
    d.mkdir(parents=True)
    (d / "name").write_text(name + "\n")
    for i, (label, milli) in enumerate(temps, 1):
        (d / f"temp{i}_input").write_text(f"{milli}\n")
        if label:
            (d / f"temp{i}_label").write_text(label + "\n")


def _machine(tmp_path, cpu=("k10temp", [("Tccd1", 61000), ("Tctl", 55500)]), gpu_busy="37"):
    _hwmon(tmp_path, 0, "acpitz", [("", 40000)])
    _hwmon(tmp_path, 1, *cpu)
    _hwmon(tmp_path, 2, "amdgpu", [("edge", 48000), ("junction", 52000)])
    _hwmon(tmp_path, 3, "nvme", [("Composite", 38850)])
    card = tmp_path / "sys" / "class" / "drm" / "card1" / "device"
    card.mkdir(parents=True)
    (card / "gpu_busy_percent").write_text(gpu_busy + "\n")
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 1 1 1\n")
    (proc / "meminfo").write_text("MemTotal:       16000000 kB\nMemFree:  1 kB\nMemAvailable:    4000000 kB\n")
    return SensorHub(str(tmp_path / "sys"), str(proc))


def test_finds_the_usual_sensors(tmp_path, monkeypatch):
    monkeypatch.setattr("iridia.sensors.shutil.which", lambda exe: None)       # no NVIDIA here
    hub = _machine(tmp_path)
    src = hub.discover()
    assert {"cpu_load", "ram", "cpu_temp", "gpu_temp", "gpu_load", "disk_temp"} <= set(src)
    assert src["cpu_temp"].read() == 55.5              # Tctl, not a CCD
    assert src["gpu_temp"].read() == 48.0              # edge
    assert src["gpu_load"].read() == 37.0
    assert src["disk_temp"].read() == 38.85
    assert src["ram"].read() == 75.0
    assert "hwmon:k10temp:Tccd1" in src and src["hwmon:acpitz:temp1"].read() == 40.0
    # Intel names its package sensor differently
    other = tmp_path / "intel"
    hub2 = _machine(other, cpu=("coretemp", [("Core 0", 70000), ("Package id 0", 66000)]))
    assert hub2.discover()["cpu_temp"].read() == 66.0


def test_cpu_load_is_the_busy_share_since_last_time(tmp_path, monkeypatch):
    monkeypatch.setattr("iridia.sensors.shutil.which", lambda exe: None)
    hub = _machine(tmp_path)
    load = hub.discover()["cpu_load"].read
    assert load() is None                               # needs two readings
    (tmp_path / "proc" / "stat").write_text("cpu  150 0 150 900 0 0 0 0 0 0\n")
    assert load() == 50.0


def test_readings_are_smoothed_and_only_the_wanted_ones(tmp_path, monkeypatch):
    monkeypatch.setattr("iridia.sensors.shutil.which", lambda exe: None)
    hub = _machine(tmp_path)
    assert not hub.update(0.0)                          # nothing wanted, nothing read
    hub.set_wanted({"cpu_temp", "nope!"})
    assert hub.update(10.0) and hub.value("cpu_temp") == 55.5
    hot = tmp_path / "sys" / "class" / "hwmon" / "hwmon1" / "temp2_input"
    hot.write_text("85500\n")
    hub.update(11.0)
    first = hub.value("cpu_temp")
    assert 55.5 < first < 70                            # moving, not jumping
    for k in range(12, 40):
        hub.update(float(k))
    assert abs(hub.value("cpu_temp") - 85.5) < 0.5
    assert hub.values() == {"cpu_temp": round(hub.value("cpu_temp"), 1)}
    os.remove(hot)                                      # the sensor went away: no value, not a stale one
    hub.update(41.0)
    assert hub.value("cpu_temp") is None


def test_ids_and_ranges():
    assert valid_id("cpu_temp") and valid_id("hwmon:nvme:Composite") and not valid_id("../etc") \
        and not valid_id(3)
    assert default_range("gpu_temp") == (30.0, 90.0) and default_range("ram") == (0.0, 100.0)


def _part(**kw):
    return S.clean([{"start": 0, "type": "same"}, dict({"start": 2, "type": "sensor"}, **kw)], 12)[1]


def test_sensor_parts_are_cleaned():
    p = _part(sensor="ram", show="nope", min="x", palette="colors", colors=[1], background="dim", flash_above=True)
    assert (p["sensor"], p["show"], p["min"], p["max"], p["palette"], p["background"], p["flash_above"]) == \
        ("ram", "level", 0.0, 100.0, "colors", "dim", None)
    assert _part(sensor="../x")["sensor"] == "cpu_temp" and _part(min=50, max=50)["max"] == 51


def test_level_color_and_both():
    resolve = lambda e: ["000000", "ffffff"]           # noqa: E731
    half = _part(sensor="ram", show="level", palette="colors")
    out = S.sensor_part(half, 10, 50.0, resolve)
    assert out[5:] == [(0, 0, 0)] * 5 and out[0] != out[4] and out[4] != (0, 0, 0)   # a ramp up to half
    tip = S.sensor_part(half, 10, 55.0, resolve)        # the next LED is half lit
    assert 0 < tip[5][0] < S.sensor_part(half, 10, 60.0, resolve)[5][0]
    col = S.sensor_part(_part(sensor="ram", show="color", palette="colors"), 4, 100.0, resolve)
    assert col == [(255, 255, 255)] * 4
    both = S.sensor_part(_part(sensor="ram", show="both", palette="colors", background="dim"), 4, 50.0, resolve)
    assert both[0] == both[1] == (127, 127, 127) and both[3] == (15, 15, 15)
    rev = S.sensor_part(_part(sensor="ram", show="level", palette="colors", params={"reverse": True}), 10, 50.0,
                        resolve)
    assert rev == out[::-1]
    none = S.sensor_part(half, 4, None, resolve)
    assert none[1:] == [(0, 0, 0)] * 3                  # no reading: one faint LED, not "0"
    flash = _part(sensor="ram", show="color", palette="colors", flash_above=80)
    assert S.sensor_part(flash, 2, 90.0, resolve, t=0.2) != S.sensor_part(flash, 2, 90.0, resolve, t=0.7)
    assert S.sensor_part(flash, 2, 70.0, resolve, t=0.2) == S.sensor_part(flash, 2, 70.0, resolve, t=0.7)


def test_the_discrete_gpu_wins_and_twin_drives_get_their_own_ids(tmp_path, monkeypatch):
    monkeypatch.setattr("iridia.sensors.shutil.which", lambda exe: None)
    hub = _machine(tmp_path)                            # card1: an iGPU, hwmon2 its amdgpu sensor
    (tmp_path / "sys/class/drm/card1/device/mem_info_vram_total").write_text("536870912\n")
    dgpu = tmp_path / "sys/class/drm/card0/device"
    (dgpu / "hwmon" / "hwmon9").mkdir(parents=True)
    (dgpu / "gpu_busy_percent").write_text("88\n")
    (dgpu / "mem_info_vram_total").write_text("17163091968\n")
    (dgpu / "hwmon/hwmon9/name").write_text("amdgpu\n")
    (dgpu / "hwmon/hwmon9/temp1_input").write_text("71000\n")
    (dgpu / "hwmon/hwmon9/temp1_label").write_text("edge\n")
    hw = tmp_path / "sys/class/hwmon/hwmon9"
    hw.symlink_to(dgpu / "hwmon/hwmon9")
    _hwmon(tmp_path, 4, "nvme", [("Composite", 45000)])
    src = hub.discover()
    assert src["gpu_load"].read() == 88.0 and src["gpu_temp"].read() == 71.0
    assert src["hwmon:nvme:Composite"].read() == 38.85 and src["hwmon:nvme#2:Composite"].read() == 45.0


def test_readings_are_shown_with_a_steady_width():
    from iridia.sensors import format_value
    assert format_value(45.26174, "°C") == "45 °C" and format_value(7.25, "%") == "7 %"
    assert format_value(1.2345, "GB") == "1.2 GB" and format_value(None, "°C") == "-"


def test_a_bar_from_the_middle():
    """It grows both ways at once. With an even number of LEDs the two middle ones light together (no
    lopsided middle); with an odd number the middle one fills first. Both sides always match."""
    from iridia import sections as S

    def bar(n, value):
        sec = S.clean_section({"start": 0, "type": "sensor", "sensor": "ram", "show": "both", "min": 0, "max": 100,
                               "palette": "colors", "colors": ["ffffff"], "params": {"middle": True}})
        lv = []
        S.sensor_part(sec, n, value, lambda e: ["ffffff"], 0.0, lv)
        return lv
    for n in (8, 9):
        for v in (0, 10, 25, 37, 50, 80, 100):
            lv = bar(n, v)
            assert lv == lv[::-1], (n, v)                    # symmetric
    even = bar(8, 25)                                        # 25% of 4 LEDs each way: the middle two
    assert even[3] == even[4] == 1.0 and even[2] == 0.0
    even = bar(8, 37.5)                                      # and the next ones half on each side
    assert even[3] == 1.0 and abs(even[2] - 0.5) < 1e-9 and even[2] == even[5]
    odd = bar(9, 100 * 0.5 / 4.5)                            # just the middle LED
    assert odd[4] == 1.0 and odd[3] == 0.0
    assert bar(8, 100) == [1.0] * 8 and bar(9, 0) == [0.0] * 9
    assert S.clean_section({"start": 0, "type": "sensor", "sensor": "ram",
                            "params": {"middle": True}})["params"] == {"middle": True}
