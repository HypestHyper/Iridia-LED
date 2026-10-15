#!/usr/bin/env python3
"""How much CPU animations cost: runs the daemon's real animation path (effects, brightness, color
correction, packet building) for 6 zones of 80 LEDs at 30 fps for 10 seconds, sending to a stand-in
that only builds the bytes, and prints the CPU time used.

    python3 scripts/bench_animations.py [--fps 30] [--seconds 10] [--effect comet] [--mode full]

It uses a throwaway home folder, so your settings and OpenRGB are not touched.
"""
import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=30, choices=[15, 30, 60])
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--zones", type=int, default=6)
    ap.add_argument("--leds", type=int, default=80)
    ap.add_argument("--effect", default="mixed", help="an effect name, or 'mixed' (a different one per zone)")
    ap.add_argument("--mode", default="full", choices=["full", "palette", "calibrated"], help="color correction")
    args = ap.parse_args()

    home = tempfile.mkdtemp(prefix="iridia-bench-")
    os.environ["HOME"] = home
    os.environ["XDG_RUNTIME_DIR"] = home
    os.makedirs(os.path.join(home, ".config", "iridia"))
    from iridia import animations
    effects = animations.ORDER if args.effect == "mixed" else [args.effect]
    zones = {f"Channel {i + 1}": {"led_count": args.leds, "pattern": "gradient", "pattern_colors": [0, 1, 2],
                                  "mode": args.mode, "brightness_sync": False, "manual_brightness": 80,
                                  "animation": {"effect": effects[i % len(effects)]}}
             for i in range(args.zones)}
    cfg = {"devices": {"Bench": {"zones": zones}}, "ddc": {"enabled": False},
           "animations": {"fps": args.fps}, "logging": {"enabled": False}}
    with open(os.path.join(home, ".config", "iridia", "config.json"), "w") as f:
        json.dump(cfg, f)

    from iridia import daemon as dm
    from iridia.openrgb_ctl import _pack_rgb

    sent = {"frames": 0, "bytes": 0}

    class Ctl:
        """Builds every packet like the real controller, but sends nothing."""
        def __init__(self, *a, **k):
            self.host, self.client, self.devices = "127.0.0.1", object(), {}
            self.connected_since = self.last_error = self.no_devices_since = None

        def list_devices(self):
            return [{"name": "Bench", "zones": [{"name": z, "led_count": args.leds} for z in zones]}]

        def send_frames(self, device, frames):
            for f in frames.values():
                sent["bytes"] += len(_pack_rgb(f)) + 10
            sent["frames"] += 1
            return True

    class DDC:
        def __init__(self, **k):
            self.last_error = None

        def get_brightness(self):
            return 100

        def is_available(self):
            return False

    dm.OpenRGBController, dm.DDCController = Ctl, DDC
    d = dm.Daemon()
    d._real_zone_size = lambda dev, zone: args.leds
    d._refresh_animations(True)
    cpu0, wall0 = time.process_time(), time.monotonic()
    time.sleep(args.seconds)
    cpu = time.process_time() - cpu0
    wall = time.monotonic() - wall0
    d._animator.stop()
    print(f"{args.zones} zones x {args.leds} LEDs, effects: {', '.join(effects)}, correction: {args.mode}")
    print(f"{sent['frames'] / wall:.1f} device frames per second (target {args.fps})")
    print(f"CPU: {cpu:.2f} s in {wall:.1f} s = {100 * cpu / wall:.1f}% of one core")


if __name__ == "__main__":
    main()
