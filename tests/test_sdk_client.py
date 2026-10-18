"""Iridia's own OpenRGB SDK client (protocol 6).

The device description in tests/data/openrgb1.0-device-v6.bin was written by OpenRGB 1.0's own
encoder (RGBController::GetDeviceDescriptionData from the release_1.0 sources, compiled with a
small test program), and the mode description below was read back correctly by OpenRGB's own
parser (RGBController::SetModeDescription). The fake OpenRGB's descriptions were checked the
same way, so these tests don't just agree with themselves.
"""
import os
import socket
import subprocess
import sys
import time

import pytest

from iridia import sdk_client as S

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, "fakes", "openrgb")


def test_reads_openrgb_10s_own_device_description():
    with open(os.path.join(HERE, "data", "openrgb1.0-device-v6.bin"), "rb") as f:
        d = S.parse_device(f.read(), S.Device(None, 0, 42))
    assert (d.type, d.name, d.vendor, d.description, d.version, d.serial) == \
        (4, "Test ARGB Controller", "Tester", "a test", "1.0", "S1")
    assert (d.location, d.flags, d.display_name, d.configuration) == ("HID: /dev/hidraw9", 3, "My Controller", '{"a":1}')
    assert d.active_mode == 1 and [m.name for m in d.modes] == ["Direct", "Static"]
    static = d.modes[1]
    assert (static.color_mode, static.colors_min, static.colors_max, static.speed) == (2, 1, 1, 3)
    assert [(c.red, c.green, c.blue) for c in static.colors] == [(0x99, 0x66, 0x33)]
    one, two = d.zones
    assert (one.name, one.leds_count, one.leds_max, one.display_name) == ("Channel 1", 3, 80, "")
    assert [(c.red, c.green, c.blue) for c in one.colors] == [(3, 2, 1), (4, 2, 1), (5, 2, 1)]
    # a zone whose size is only for hardware effects is one LED for per-LED colours, as in OpenRGB
    assert (two.name, two.display_name, two.leds_count, two.leds_count_effects) == ("Channel 2", "Shelf", 1, 2)
    assert [(c.red, c.green, c.blue) for c in two.colors] == [(6, 2, 1)]
    assert two.segments[0]["name"] == "Seg A" and [m.name for m in two.modes] == ["Zone Rainbow"]
    assert d.leds == ["Channel 1 LED 1", "Channel 1 LED 2", "Channel 1 LED 3", "Channel 2 LED 1"]


def test_mode_description_is_what_openrgb_reads():
    m = S.Mode(1, "Static")
    m.flags, m.speed_min, m.speed_max, m.brightness_min, m.brightness_max = 80, 1, 5, 0, 100
    m.colors_min, m.colors_max, m.speed, m.brightness, m.direction, m.color_mode = 1, 2, 3, 90, 2, 2
    m.colors = [S.RGB(0x11, 0x22, 0x33), (0x44, 0x55, 0x66)]
    assert m.pack().hex() == ("0700537461746963005000000001000000050000000000000064000000010000000200000003000000"
                              "5a000000020000000200000002001122330044556600")


def test_a_short_description_is_an_error_not_garbage():
    with open(os.path.join(HERE, "data", "openrgb1.0-device-v6.bin"), "rb") as f:
        data = f.read()
    with pytest.raises(ValueError):
        S.parse_device(data[:200], S.Device(None, 0, 1))


# ------------------------------------------------------------ against the fake OpenRGB

def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def server(tmp_path):
    procs = []

    def start(protocol=6, delay=0.0, **extra):
        port = _port()
        env = dict(os.environ, FAKE_OPENRGB_MODE="devices", FAKE_OPENRGB_PROTOCOL=str(protocol),
                   FAKE_OPENRGB_UPDATE_DELAY=str(delay), FAKE_OPENRGB_PACKETS=str(tmp_path / "packets.log"),
                   **{f"FAKE_OPENRGB_{k.upper()}": str(v) for k, v in extra.items()})
        p = subprocess.Popen([sys.executable, FAKE, "--server", "--server-port", str(port)], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(p)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                return port
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("fake OpenRGB didn't start")
    yield start
    for p in procs:
        p.terminate()
        p.wait(5)


def _wait(cond, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_a_session_with_protocol_6(server):
    port = server()
    c = S.SDKClient("127.0.0.1", port, "Iridia test")
    other = S.SDKClient("127.0.0.1", port, "someone else")
    try:
        assert c.ids == [500, 501]                                # controller IDs, not positions
        argb, ram = c.devices
        assert (argb.name, argb.id, argb.cid) == ("Fake ARGB Controller", 0, 500)
        assert [z.name for z in argb.zones] == ["Channel 1", "Channel 2"] and len(argb.leds) == 40
        assert [m.name for m in argb.modes][:2] == ["Direct", "Static"] and argb.active_mode == 1
        # every update waits for OpenRGB's acknowledgement
        argb.set_mode(argb.modes[0])
        argb.update_leds(b"\x28\x00" + bytes([9, 8, 7, 0]) * 40)
        argb.zones[1].set_colors([(1, 2, 3)] * 20)
        # another program switching the mode is seen at once (OpenRGB announces it)
        other.devices[0].set_mode(other.devices[0].modes[3])
        assert _wait(lambda: argb.active_mode == 3)
        # resizing reads the device again
        argb.zones[0].resize(30)
        assert argb.zones[0].leds_count == 30 and len(argb.leds) == 50
        # a request OpenRGB refuses is an error, not silence
        with pytest.raises(S.SDKError):
            c.request(999, S.UPDATE_LEDS, b"\x06\x00\x00\x00\x00\x00")
    finally:
        c.disconnect()
        other.disconnect()


def test_older_openrgb_is_told_apart(server):
    port = server(protocol=3)
    with pytest.raises(S.ProtocolTooOld):
        S.SDKClient("127.0.0.1", port)


def test_the_controller_falls_back_to_openrgb_python(server):
    from iridia.openrgb_ctl import OpenRGBController
    for protocol, expect in ((6, 6), (3, 0)):
        ctl = OpenRGBController("127.0.0.1", server(protocol=protocol))
        try:
            assert ctl.ensure_connected(retry_interval=0)
            assert ctl.protocol == expect
            assert set(ctl.devices) == {"Fake ARGB Controller", "Fake RAM"}
            assert ctl.send("Fake RAM", ["ff0000"] * 8, {"Stick": {"enabled": True}})
            assert ctl.send_frames("Fake ARGB Controller", {"": [(1, 2, 3)] * 40}) is True
            assert ctl.resize_zone("Fake ARGB Controller", "Channel 2", 25) is None
        finally:
            ctl.disconnect()


def test_a_device_openrgb_finds_after_we_connected_is_picked_up(server):
    """OpenRGB answers while it's still finding devices (the RAM first, USB ones later). Whether it
    says so or not, and whichever client talks to it, the late device shows up."""
    from iridia.openrgb_ctl import OpenRGBController
    for protocol, silent in ((6, ""), (6, "1"), (3, "")):
        ctl = OpenRGBController("127.0.0.1", server(protocol=protocol, late=0.4, late_silent=silent))
        try:
            assert ctl.ensure_connected(retry_interval=0)
            assert set(ctl.devices) == {"Fake RAM"}
            time.sleep(0.6)
            ctl.maybe_enumerate(interval=0)
            assert set(ctl.devices) == {"Fake RAM", "Fake ARGB Controller"}, (protocol, silent)
            assert ctl.send("Fake ARGB Controller", ["00ff00"] * 40, {"Channel 1": {"enabled": True},
                                                                       "Channel 2": {"enabled": True}})
        finally:
            ctl.disconnect()


def test_a_closed_connection_is_a_connection_error(server):
    port = server()
    c = S.SDKClient("127.0.0.1", port)
    c.disconnect()
    with pytest.raises(ConnectionError):
        c.devices[0].update_leds(b"\x00\x00")
