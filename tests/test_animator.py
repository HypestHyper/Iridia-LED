"""The animation thread: pacing per device, skipping instead of queueing, lowering the rate of a
device that can't keep up, one packet per device when every zone animates, and no thread at all
while nothing animates."""
import logging
import struct
import threading
import time

from iridia import animations
from iridia.animator import Animator, Job
from iridia.openrgb_ctl import OpenRGBController, _pack_rgb


class Recorder:
    """Stands in for OpenRGBController.send_frames; can be slow for one device."""

    def __init__(self, slow=None, delay=0.0):
        self.sent = []                  # (time, device, frames)
        self.slow, self.delay = slow, delay
        self.lock = threading.Lock()

    def __call__(self, device, frames):
        if device == self.slow:
            time.sleep(self.delay)
        with self.lock:
            self.sent.append((time.monotonic(), device, {z: list(f) for z, f in frames.items()}))
        return True

    def count(self, device):
        with self.lock:
            return sum(1 for _t, d, _f in self.sent if d == device)


def job(device, zone, n=10, effect="rainbow"):
    p = animations.defaults(effect)
    return Job(f"{device}|{zone}", device, zone, n,
               lambda clock: animations.render(effect, p, n, clock, [(255, 0, 0)]))


def run(anim, seconds):
    time.sleep(seconds)
    anim.stop()


def test_no_thread_without_jobs():
    rec = Recorder()
    a = Animator(rec)
    a.set_jobs({}, 30)
    assert not a.running()
    time.sleep(0.2)
    assert rec.sent == []


def test_runs_at_the_frame_rate_and_stops_when_the_work_is_gone():
    rec = Recorder()
    a = Animator(rec)
    a.set_jobs({"A": (False, [job("A", "z")])}, 30)
    assert a.running()
    time.sleep(1.0)
    n = rec.count("A")
    assert 24 <= n <= 33, n                     # about 30, never more (nothing is queued)
    a.set_jobs({}, 30)
    time.sleep(0.2)
    assert not a.running()
    later = rec.count("A")
    time.sleep(0.3)
    assert rec.count("A") == later


def test_a_slow_device_skips_frames_and_gets_a_lower_rate(caplog):
    rec = Recorder(slow="Slow", delay=0.05)    # 50 ms per frame: can't do 60 or 30 fps
    a = Animator(rec)
    caplog.set_level(logging.INFO, logger="iridia.animator")
    a.set_jobs({"Slow": (False, [job("Slow", "z")]), "Fast": (False, [job("Fast", "z")])}, 60)
    time.sleep(3.0)                             # long enough to step down 60 -> 30 -> 15
    mark = time.monotonic()
    run(a, 1.5)
    msgs = [r.message for r in caplog.records]
    assert any("can't keep up with 60 fps" in m and "using 30" in m for m in msgs)
    assert any("can't keep up with 30 fps" in m and "using 15" in m for m in msgs)
    late = [(t, d) for t, d, _f in rec.sent if t >= mark]
    slow = sum(1 for _t, d in late if d == "Slow") / 1.5
    fast = sum(1 for _t, d in late if d == "Fast") / 1.5
    assert slow <= 16                           # held to 15 fps: frames skipped, not queued
    assert fast >= 12                           # the other device keeps getting frames
    gaps = [b - a_ for (a_, d1, _), (b, d2, _) in zip(rec.sent, rec.sent[1:]) if d1 == d2 == "Slow"]
    assert all(g >= 0.045 for g in gaps)        # never two frames back to back (no queue)


def test_unchanged_frames_are_not_sent():
    rec = Recorder()
    a = Animator(rec)
    still = Job("A|z", "A", "z", 5, lambda clock: [(10, 20, 30)] * 5)
    a.set_jobs({"A": (False, [still])}, 30)
    run(a, 0.5)
    assert rec.count("A") == 1


def test_whole_device_in_one_packet_and_paused_zones_skipped():
    rec = Recorder()
    a = Animator(rec)
    paused = {"on": False}
    z1 = job("D", "one", 3)
    z2 = Job("D|two", "D", "two", 2, lambda clock: None if paused["on"] else [(1, 2, 3)] * 2)
    a.set_jobs({"D": (True, [z1, z2])}, 30)
    time.sleep(0.3)
    whole = [f for _t, d, f in rec.sent if d == "D"]
    assert whole and set(whole[-1]) == {""} and len(whole[-1][""]) == 5
    paused["on"] = True
    time.sleep(0.3)
    a.stop()
    last = [f for _t, d, f in rec.sent if d == "D"][-1]
    assert set(last) == {"one"}                 # the paused zone is left to the daemon


def test_the_clock_runs_at_the_set_rate():
    a = Animator(Recorder())
    a.set_jobs({"A": (False, [job("A", "z")])}, 30, rate=0.5)
    time.sleep(1.0)
    a.stop()
    assert 0.35 <= a.clock <= 0.6


# ------------------------------------------------------------ packets

class Comms:
    def __init__(self):
        self.out = []

    def send_header(self, dev, ptype, size):
        self.out.append(("h", dev, ptype, size))

    def send_data(self, data):
        self.out.append(("d", data))


class Zone:
    def __init__(self, zid, name, n):
        self.id, self.name, self.leds = zid, name, [None] * n


class Mode:
    def __init__(self, name):
        self.name = name


class Dev:
    def __init__(self):
        self.id, self.name = 3, "D"
        self.comms = Comms()
        self.zones = [Zone(0, "A", 2), Zone(1, "B", 3)]
        self.leds = [None] * 5
        self.modes = [Mode("Direct")]
        self.active_mode = 0
        self.set_modes = []

    def set_mode(self, m):
        self.set_modes.append(m.name)


def test_frame_packets_match_the_sdk_format():
    ctl = OpenRGBController()
    dev = Dev()
    ctl.devices, ctl.client = {"D": dev}, object()
    assert ctl.send_frames("D", {"B": [(1, 2, 3)] * 3}) is True
    h, d = dev.comms.out[-2], dev.comms.out[-1]
    body = struct.pack("iH", 1, 3) + bytes([1, 2, 3, 0] * 3)
    assert h == ("h", 3, 1051, len(body) + 4) and d == ("d", struct.pack("I", len(body) + 4) + body)
    assert ctl.send_frames("D", {"": [(9, 8, 7)] * 4}) is True       # short frames repeat the last LED
    h, d = dev.comms.out[-2], dev.comms.out[-1]
    body = struct.pack("H", 5) + bytes([9, 8, 7, 0] * 5)
    assert h == ("h", 3, 1050, len(body) + 4) and d[1] == struct.pack("I", len(body) + 4) + body
    assert _pack_rgb([(1, 2, 3), (4, 5, 6)]) == bytes([1, 2, 3, 0, 4, 5, 6, 0])


def test_direct_mode_is_set_again_once_per_connection():
    ctl = OpenRGBController()
    dev = Dev()
    ctl.devices, ctl.client = {"D": dev}, object()
    ctl.send_frames("D", {"A": [(1, 1, 1)] * 2})
    ctl.send_frames("D", {"A": [(2, 2, 2)] * 2})
    assert dev.set_modes == ["Direct"]          # once, even though OpenRGB said Direct already
    ctl._asserted.clear()                       # what a reconnect does
    ctl.send_frames("D", {"A": [(3, 3, 3)] * 2})
    assert dev.set_modes == ["Direct", "Direct"]
