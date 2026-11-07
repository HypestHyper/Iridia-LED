"""WiZ and Govee lights over the network: stand-ins for both on localhost, speaking their protocols."""
import json
import socket
import threading
import time

import pytest

from iridia import netlights as N


def test_colour_and_brightness_split():
    assert N.split_brightness((40, 20, 0)) == ((255, 128, 0), 16)
    assert N.split_brightness((0, 0, 0)) == ((0, 0, 0), 0)
    assert N.average(["ff0000", "0000ff"]) == (128, 0, 128)
    assert N.wiz_command((0, 0, 0)) == {"method": "setState", "params": {"state": False}}
    p = N.wiz_command((255, 0, 0))["params"]
    assert (p["r"], p["g"], p["b"], p["dimming"]) == (255, 0, 0, 100)
    assert N.wiz_command((2, 0, 0))["params"]["dimming"] == 10          # WiZ can't go below 10%
    cmds = N.govee_commands((0, 128, 0), was_on=None)
    assert [c["msg"]["cmd"] for c in cmds] == ["turn", "colorwc", "brightness"]
    assert cmds[1]["msg"]["data"]["color"] == {"r": 0, "g": 255, "b": 0} and cmds[2]["msg"]["data"]["value"] == 50
    assert [c["msg"]["cmd"] for c in N.govee_commands((9, 9, 9), was_on=True)] == ["colorwc", "brightness"]
    assert N.govee_commands((0, 0, 0), was_on=False) == []                # already off


def _udp(port=0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.settimeout(0.1)
    return s


class Fakes:
    """A WiZ light, and a Govee light (its scan port and its command port)."""

    def __init__(self):
        self.wiz, self.gscan, self.gcmd = _udp(), _udp(), _udp()
        probe = _udp()
        self.glisten = probe.getsockname()[1]
        probe.close()
        self.wiz_got, self.govee_got = [], []
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            for s in (self.wiz, self.gscan, self.gcmd):
                try:
                    data, addr = s.recvfrom(4096)
                except (socket.timeout, OSError):
                    continue
                try:
                    self._answer(s, json.loads(data), addr)
                except OSError:
                    pass                        # closed while answering: the test is over

    def _answer(self, s, msg, addr):
        if s is self.wiz:
            if msg.get("method") == "getSystemConfig":
                s.sendto(json.dumps({"method": "getSystemConfig", "env": "pro", "result": {
                    "mac": "a8bb50d1e2f3", "moduleName": "ESP01_SHRGB_03"}}).encode(), addr)
            else:
                self.wiz_got.append(msg)
        elif s is self.gscan:      # the answer goes to port 4002 (here: glisten), as the doc says
            self.gscan.sendto(json.dumps({"msg": {"cmd": "scan", "data": {
                "ip": "127.0.0.1", "device": "1F:80:C5:32:32:36:72:4E", "sku": "H6159",
                "bleVersionHard": "3.01.01", "wifiVersionSoft": "1.02.03"}}}).encode(),
                ("127.0.0.1", self.glisten))
        else:
            self.govee_got.append(msg["msg"])

    def point(self, nl):
        nl.targets = {"wiz": ("127.0.0.1", self.wiz.getsockname()[1]),
                      "govee": ("127.0.0.1", self.gscan.getsockname()[1]),
                      "govee_cmd": self.gcmd.getsockname()[1], "govee_listen": self.glisten}

    def close(self):
        self.running = False
        time.sleep(0.15)
        for s in (self.wiz, self.gscan, self.gcmd):
            s.close()


@pytest.fixture
def fakes():
    f = Fakes()
    yield f
    f.close()


def wait(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not pred():
        time.sleep(0.02)
    return pred()


def test_finds_and_drives_both(fakes):
    nl = N.NetLights()
    fakes.point(nl)
    nl.set_enabled(True)
    try:
        assert wait(lambda: len(nl.lights) == 2)
        assert set(nl.lights) == {"WiZ D1E2F3", "Govee H6159 36724E"}
        dev = {d["name"]: d for d in nl.list_devices()}
        assert dev["Govee H6159 36724E"]["net"]["ip"] == "127.0.0.1" and dev["WiZ D1E2F3"]["led_count"] == 1
        nl.send("WiZ D1E2F3", ["800000"] * 3)
        nl.send("Govee H6159 36724E", ["0000ff"])
        assert wait(lambda: fakes.wiz_got and len(fakes.govee_got) >= 3)
        p = fakes.wiz_got[-1]["params"]
        assert fakes.wiz_got[-1]["method"] == "setPilot" and (p["r"], p["dimming"]) == (255, 50)
        assert [m["cmd"] for m in fakes.govee_got[:3]] == ["turn", "colorwc", "brightness"]
        # a burst of colours: the light gets the last one, not all of them
        n = len(fakes.wiz_got)
        for i in range(20):
            nl.send("WiZ D1E2F3", ["%02x0000" % (i * 10 + 50)])
        assert wait(lambda: fakes.wiz_got[-1]["params"].get("r") == 255
                    and fakes.wiz_got[-1]["params"]["dimming"] == round(240 * 100 / 255))
        assert len(fakes.wiz_got) - n < 8
        nl.send("WiZ D1E2F3", ["000000"])
        assert wait(lambda: fakes.wiz_got[-1]["method"] == "setState")
    finally:
        nl.stop()


def test_the_daemon_adds_them_and_shows_its_colours(fakes, tmp_path, monkeypatch):
    from tests.test_daemon import DEVICES, FakeDDC, FakeOpenRGB
    from iridia import daemon as daemon_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr("iridia.setups.CONFIG_DIR", str(tmp_path / ".config" / "iridia"))
    monkeypatch.setattr(daemon_mod, "OpenRGBController", FakeOpenRGB)
    monkeypatch.setattr(daemon_mod, "DDCController", FakeDDC)
    cfg = tmp_path / ".config" / "iridia"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(json.dumps({"devices": DEVICES}))
    d = daemon_mod.Daemon()
    try:
        fakes.point(d.netlights)
        assert not d._cmd_netlights({"scan": True})["ok"]               # off: nothing to look with
        assert d._cmd_netlights({"enabled": True})["enabled"]
        assert wait(lambda: len(d.netlights.lights) == 2)
        d._autoadd_devices(d.netlights.list_devices())
        conf = d.config.get(("devices", "WiZ D1E2F3"))
        assert conf["net"] == "wiz" and conf["strip_type"] == "single" and conf["led_count"] == 1
        d._extracted_colors = ["00ff00"]
        d._update_all_devices()
        assert wait(lambda: fakes.wiz_got and fakes.wiz_got[-1]["params"].get("g") == 255)
        d._check_missing_devices()
        assert "WiZ D1E2F3" not in d._device_missing_since                # not an OpenRGB device
        st = d._cmd_status()
        assert {x["name"] for x in st["netlights"]["found"]} == {"WiZ D1E2F3", "Govee H6159 36724E"}
        assert not d._cmd_netlights({"add_host": "my lamp"})["ok"]
        assert d._cmd_netlights({"add_host": "192.168.20.0/24"})["hosts"] == ["192.168.20.0/24"]
        assert d.netlights.hosts == ["192.168.20.0/24"]
        assert d._cmd_netlights({"remove_host": "192.168.20.0/24"})["hosts"] == []
        assert not d._cmd_netlights({"add_light": {"kind": "hue", "ip": "10.0.0.9"}})["ok"]
        r = d._cmd_netlights({"add_light": {"kind": "govee", "ip": "10.0.0.9"}})
        assert r["manual"] == [{"kind": "govee", "ip": "10.0.0.9"}] and d.netlights.has("Govee 10.0.0.9")
        d._autoadd_devices(d.netlights.list_devices())
        assert d.config.get(("devices", "Govee 10.0.0.9", "net")) == "govee"
        assert d._cmd_netlights({"probe": "127.0.0.1"})["probe"]["wiz"]
        assert d._cmd_netlights({"remove_light": "10.0.0.9"})["manual"] == []
        assert d.config.get(("devices", "Govee 10.0.0.9")) is None          # its card went with it
        assert not d.netlights.has("Govee 10.0.0.9")
        _ = d.handle_command({"cmd": "zone_action", "target": "WiZ D1E2F3", "actions": ["off"]})
        d._update_all_devices()
        assert wait(lambda: fakes.wiz_got[-1]["method"] == "setState")
    finally:
        d.netlights.stop()
        d.ipc.stop()


def test_cli_text():
    from iridia.cli import _netlights_text
    t = _netlights_text({"netlights": {"enabled": True, "found": [{"name": "WiZ D1E2F3", "net": {"ip": "10.0.0.5"}}]}})
    assert "looking" in t and "WiZ D1E2F3  10.0.0.5" in t
    assert "LAN Control" in _netlights_text({"enabled": True, "found": []})
    assert "off" in _netlights_text({"enabled": False})


def test_hosts_and_networks():
    assert N.clean_hosts(["192.168.20.31", "192.168.20.0/24", "192.168.20.7/24", "nope", "10.0.0.0/8", "::1"]) == \
        ["192.168.20.31", "192.168.20.0/24"]                      # /8 is too many to ask one by one
    ips = N.expand(["192.168.20.0/30", "10.1.1.9"])
    assert ips == ["192.168.20.1", "192.168.20.2", "10.1.1.9"]


def test_lights_on_another_network_are_asked_directly(fakes):
    """Broadcast and multicast don't reach them (another VLAN): the search misses, asking directly finds."""
    nl = N.NetLights()
    fakes.point(nl)
    nl.targets["wiz"] = ("127.0.0.2", nl.targets["wiz"][1])        # the broadcast goes nowhere
    nl.targets["govee"] = ("127.0.0.2", nl.targets["govee"][1])    # and so does the multicast
    nl.set_enabled(True)
    try:
        time.sleep(0.6)
        assert nl.lights == {}
        nl.hosts = ["127.0.0.1"]
        nl.scan()
        assert wait(lambda: len(nl.lights) == 2)
    finally:
        nl.stop()


def test_keep_its_own_colour():
    assert N.wiz_brightness((0, 0, 128)) == {"method": "setPilot", "params": {"state": True, "dimming": 50}}
    assert N.wiz_brightness((0, 0, 0))["method"] == "setState"
    assert [c["msg"]["cmd"] for c in N.govee_commands((90, 90, 90), was_on=None, keep_color=True)] == \
        ["turn", "brightness"]


def test_keep_colour_on_a_light(fakes):
    nl = N.NetLights()
    fakes.point(nl)
    nl.set_enabled(True)
    try:
        assert wait(lambda: "WiZ D1E2F3" in nl.lights)
        nl.set_keep_color({"WiZ D1E2F3"})
        nl.send("WiZ D1E2F3", ["808080"])
        assert wait(lambda: fakes.wiz_got and fakes.wiz_got[-1]["params"] == {"state": True, "dimming": 50})
    finally:
        nl.stop()


def test_a_test_says_what_came_back_and_a_light_can_be_added_by_address(fakes):
    from iridia.cli import probe_text
    nl = N.NetLights()
    fakes.point(nl)
    nl.targets["wiz"] = ("127.0.0.2", nl.targets["wiz"][1])        # no search reaches them
    nl.targets["govee"] = ("127.0.0.2", nl.targets["govee"][1])
    nl.set_enabled(True)
    try:
        p = nl.probe("127.0.0.1", wait=2.0)
        assert p["wiz"] and p["govee"]                            # both stand-ins answer when asked directly
        assert "answered" in probe_text(p)
        p = nl.probe("127.0.0.3", wait=0.3)                       # nobody there
        assert not p["wiz"] and not p["govee"]
        assert "No answer from 127.0.0.3" in probe_text(dict(p, firewall="ufw")) and "ufw allow 4002" in \
            probe_text(dict(p, firewall="ufw"))
        # driven without ever hearing from it
        nl.set_manual([("govee", "127.0.0.1")])
        assert nl.has("Govee 127.0.0.1") and nl.list_devices()[0]["net"]["manual"]
        n = len(fakes.govee_got)
        nl.send("Govee 127.0.0.1", ["ff0000"])
        assert wait(lambda: len(fakes.govee_got) >= n + 3)
        nl.set_manual([])
        assert not nl.has("Govee 127.0.0.1")
    finally:
        nl.stop()


def test_only_when_i_change_it(fakes, tmp_path, monkeypatch):
    """A Govee strip a Google Home automation switches on and off: Iridia never switches it, and sends
    its colour and brightness only when they're changed on its card."""
    from tests.test_daemon import DEVICES, FakeDDC, FakeOpenRGB
    from iridia import daemon as daemon_mod
    assert N.on_demand_commands("govee", (0, 0, 0)) == []
    assert [c["msg"]["cmd"] for c in N.on_demand_commands("govee", (255, 0, 0))] == ["colorwc", "brightness"]
    assert "state" not in N.on_demand_commands("wiz", (255, 0, 0))[0]["params"]
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr("iridia.setups.CONFIG_DIR", str(tmp_path / ".config" / "iridia"))
    monkeypatch.setattr(daemon_mod, "OpenRGBController", FakeOpenRGB)
    monkeypatch.setattr(daemon_mod, "DDCController", FakeDDC)
    cfg = tmp_path / ".config" / "iridia"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(json.dumps({"devices": DEVICES}))
    d = daemon_mod.Daemon()
    try:
        fakes.point(d.netlights)
        d._cmd_netlights({"enabled": True})
        assert wait(lambda: d.netlights.has("Govee H6159 36724E"))
        d._autoadd_devices(d.netlights.list_devices())
        name = "Govee H6159 36724E"
        assert d.handle_command({"cmd": "set_zone_strip", "device": name, "zone": "", "on_demand": True})["ok"]
        d._extracted_colors = ["00ff00"]
        d._update_all_devices()
        time.sleep(0.4)
        assert fakes.govee_got == []                             # choosing the mode sends nothing
        d._lights_off = True                                     # nor lights off, sleep, a new wallpaper
        d._asleep = True
        d._extracted_colors = ["0000ff"]
        d._needs_update = True
        d._update_all_devices()
        d.netlights.resend()                                     # nor the minute's re-send
        time.sleep(0.4)
        assert fakes.govee_got == []
        # changed on its card: its colour and brightness, now, and never "turn"
        assert d.handle_command({"cmd": "set_zone_manual_brightness", "device": name, "zone": "", "value": 50})["ok"]
        d._update_all_devices()
        assert wait(lambda: len(fakes.govee_got) >= 2)
        cmds = [m["cmd"] for m in fakes.govee_got]
        assert "turn" not in cmds and cmds[:2] == ["colorwc", "brightness"]
        assert fakes.govee_got[0]["data"]["color"] == {"r": 0, "g": 0, "b": 255}
        assert fakes.govee_got[1]["data"]["value"] == 50
        n = len(fakes.govee_got)
        d._update_all_devices()                                  # and only that once
        time.sleep(0.4)
        assert len(fakes.govee_got) == n
    finally:
        d.netlights.stop()
        d.ipc.stop()


def test_searches_at_once_on_a_machine_that_just_started(fakes, monkeypatch):
    """time.monotonic() counts from boot: right after it, "60 s since the last search" mustn't hold
    the first search back (a daemon started at login, or a fresh CI machine)."""
    t0 = time.monotonic()
    monkeypatch.setattr(N.time, "monotonic", lambda: time.perf_counter() - t0 + 5.0)     # 5 s after boot
    nl = N.NetLights()
    fakes.point(nl)
    nl.set_enabled(True)
    try:
        assert wait(lambda: len(nl.lights) == 2)
    finally:
        nl.stop()
