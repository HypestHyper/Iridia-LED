"""Where your LED strips are: the model behind the Layout tab.

Saved in ~/.config/iridia/layout.json. Units are layout units (about a
millimetre at 100% zoom); nothing here talks to the daemon.

A strip is drawn for one zone ("device|zone"). Clones are extra strips for the
same zone (two strips on one wire): they show the same colours and are only a
drawing, nothing extra is sent. A clone can have its own name.

    {"id": "a1b2", "zone": "Razer...|Channel 1", "clone": false,
     "x": 120, "y": 80,                 # where LED 1 (the data input) sits
     "flip": false,                     # LED 1 is drawn at the other end
     "locked": false, "hidden": false,
     "name": "",                        # clones only: its own name (empty: the zone's)
     "segments": [                      # bends: each section starts at a LED
        {"start": 0,  "angle": 0,  "spacing": 16.6},
        {"start": 40, "angle": 90, "spacing": 16.6,
         "gap": 50, "hide": false}]}    # a wire gap before it, its LEDs left out of the drawing

`angle` is the absolute heading in degrees (0 = right, 90 = down) and
`spacing` the distance between neighbouring LEDs in that section, so a
60 LEDs/m strip and a 144 LEDs/m strip can be shown at their real lengths.
`gap` is extra distance before the section's first LED, for a strip cut and
joined again with a wire. `hide` leaves the section's LEDs out of the drawing
(they still light up).
"""

import json
import math
import os
import tempfile
import uuid
from typing import Dict, List, Optional, Tuple

PATH = os.path.expanduser("~/.config/iridia/layout.json")
DEFAULT_SPACING = 16.6          # 60 LEDs per metre, in layout units (mm)
MAX_GAP = 5000.0                # a wire gap of up to 5 m


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def zone_key(device: str, zone: str) -> str:
    return f"{device}|{zone or ''}"


def split_key(key: str) -> Tuple[str, str]:
    d, _, z = key.partition("|")
    return d, z


class Layout:
    def __init__(self, path: str = PATH):
        self.path = path
        self.strips: List[dict] = []
        self.locked = False
        self.view = {"zoom": 1.0, "pan": [40.0, 40.0]}
        self.labels = True              # strip names and LED numbers on the canvas
        self.load()

    # ------------------------------------------------------------ files
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        self.from_dict(data)

    def from_dict(self, data: dict):
        self.strips = [s for s in (self._clean(s) for s in data.get("strips", [])) if s]
        self.locked = bool(data.get("locked", False))
        self.labels = data.get("labels", True) is not False
        v = data.get("view") or {}
        try:
            self.view = {"zoom": max(0.04, min(8.0, float(v.get("zoom", 1.0)))),
                         "pan": [float(v.get("pan", [40, 40])[0]), float(v.get("pan", [40, 40])[1])]}
        except (TypeError, ValueError, IndexError):
            self.view = {"zoom": 1.0, "pan": [40.0, 40.0]}

    def to_dict(self) -> dict:
        return {"version": 1, "locked": self.locked, "labels": self.labels, "view": self.view, "strips": self.strips}

    def save(self):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _clean(s) -> Optional[dict]:
        if not isinstance(s, dict) or not isinstance(s.get("zone"), str):
            return None
        segs = []
        for seg in s.get("segments") or [{"start": 0, "angle": 0, "spacing": DEFAULT_SPACING}]:
            try:
                g = {"start": max(0, int(seg.get("start", 0))),
                     "angle": float(seg.get("angle", 0)) % 360,
                     "spacing": max(2.0, min(200.0, float(seg.get("spacing", DEFAULT_SPACING))))}
                try:
                    gap = float(seg.get("gap", 0) or 0)
                except (TypeError, ValueError):
                    gap = 0.0                # a bad gap mustn't lose the bend
                if gap == gap and gap > 0:
                    g["gap"] = min(MAX_GAP, gap)
                if seg.get("hide") is True:
                    g["hide"] = True
                segs.append(g)
            except (TypeError, ValueError, AttributeError):
                continue
        segs.sort(key=lambda g: g["start"])
        if segs and segs[0]["start"] == 0:
            segs[0].pop("gap", None)         # nothing comes before LED 1
        if not segs or segs[0]["start"] != 0:
            segs.insert(0, {"start": 0, "angle": segs[0]["angle"] if segs else 0.0,
                            "spacing": segs[0]["spacing"] if segs else DEFAULT_SPACING})
        dedup = []
        for seg in segs:
            if dedup and dedup[-1]["start"] == seg["start"]:
                dedup[-1] = seg
            else:
                dedup.append(seg)
        try:
            x, y = float(s.get("x", 40)), float(s.get("y", 40))
        except (TypeError, ValueError):
            x, y = 40.0, 40.0
        out = {"id": str(s.get("id") or new_id()), "zone": s["zone"], "clone": bool(s.get("clone", False)),
               "x": x, "y": y, "flip": bool(s.get("flip", False)), "locked": bool(s.get("locked", False)),
               "hidden": bool(s.get("hidden", False)),
               "segments": dedup}
        name = s.get("name")
        if out["clone"] and isinstance(name, str) and name.strip():
            out["name"] = name.strip()[:40]
        return out

    # ---------------------------------------------------------- editing
    def ensure_zones(self, keys: List[str]) -> bool:
        """Add a strip for every zone that has none yet. True if something was added."""
        have = {s["zone"] for s in self.strips if not s["clone"]}
        added = False
        y = max([s["y"] for s in self.strips] + [0.0]) + 60
        for k in keys:
            if k not in have:
                self.strips.append(self._clean({"id": new_id(), "zone": k, "x": 40, "y": y}))
                y += 60
                added = True
        return added

    def get(self, sid: str) -> Optional[dict]:
        return next((s for s in self.strips if s["id"] == sid), None)

    def clone(self, sid: str) -> Optional[dict]:
        src = self.get(sid)
        if src is None:
            return None
        c = json.loads(json.dumps(src))
        c.update(id=new_id(), clone=True, x=src["x"] + 30, y=src["y"] + 40, locked=False)
        c.pop("name", None)       # named on its own, not after the strip it was copied from
        self.strips.append(c)
        return c

    def remove(self, sid: str) -> bool:
        s = self.get(sid)
        if s is None or not s["clone"]:
            return False          # the strip for a real zone stays; only clones can go
        self.strips.remove(s)
        return True

    @staticmethod
    def segment_index(strip: dict, k: int) -> int:
        idx = 0
        for i, seg in enumerate(strip["segments"]):
            if seg["start"] <= k:
                idx = i
        return idx

    @staticmethod
    def add_bend(strip: dict, k: int) -> bool:
        if k <= 0 or any(seg["start"] == k for seg in strip["segments"]):
            return False
        cur = strip["segments"][Layout.segment_index(strip, k)]
        new = {"start": k, "angle": cur["angle"], "spacing": cur["spacing"]}
        if cur.get("hide"):
            new["hide"] = True            # splitting a hidden part keeps both halves hidden
        strip["segments"].append(new)
        strip["segments"].sort(key=lambda g: g["start"])
        return True

    @staticmethod
    def add_cut(strip: dict, k: int, gap: Optional[float] = None) -> bool:
        """A wire gap before LED k (path order): the strip was cut there and joined with a wire.
        Starts a section there if there's none yet; the default gap is three LEDs long."""
        if k <= 0:
            return False
        Layout.add_bend(strip, k)
        seg = strip["segments"][Layout.segment_index(strip, k)]
        seg["gap"] = max(0.0, min(MAX_GAP, gap if gap is not None else seg["spacing"] * 3))
        if not seg["gap"]:
            seg.pop("gap")
        return True

    @staticmethod
    def set_gap(strip: dict, seg_index: int, gap: float):
        if 0 < seg_index < len(strip["segments"]):
            seg = strip["segments"][seg_index]
            if gap > 0:
                seg["gap"] = min(MAX_GAP, float(gap))
            else:
                seg.pop("gap", None)

    @staticmethod
    def set_section_hidden(strip: dict, seg_index: int, hide: bool):
        if 0 <= seg_index < len(strip["segments"]):
            if hide:
                strip["segments"][seg_index]["hide"] = True
            else:
                strip["segments"][seg_index].pop("hide", None)

    @staticmethod
    def remove_bend(strip: dict, seg_index: int) -> bool:
        if seg_index <= 0 or seg_index >= len(strip["segments"]):
            return False
        del strip["segments"][seg_index]
        return True

    @staticmethod
    def rotate_from(strip: dict, seg_index: int, delta: float):
        """Turn a section and everything after it (rigidly) by delta degrees."""
        for seg in strip["segments"][seg_index:]:
            seg["angle"] = (seg["angle"] + delta) % 360

    @staticmethod
    def reset_shape(strip: dict):
        """Straight again: bends go; cuts and hidden sections stay, in line with the start."""
        first = strip["segments"][0]
        keep = [dict(seg, angle=first["angle"], spacing=first["spacing"]) for seg in strip["segments"][1:]
                if seg.get("gap") or seg.get("hide")]
        strip["segments"] = [dict(first)] + keep


# ------------------------------------------------------------- geometry

def path_points(strip: dict, n: int) -> List[Tuple[float, float]]:
    """Centre of each LED along the strip, in path order (LED input first, unless flipped)."""
    pts = []
    x, y = strip["x"], strip["y"]
    segs = strip["segments"]
    si = 0
    for k in range(max(0, n)):
        if k > 0:
            while si + 1 < len(segs) and segs[si + 1]["start"] <= k:
                si += 1
            seg = segs[si]
            a = math.radians(seg["angle"])
            step = seg["spacing"] + (seg.get("gap", 0.0) if seg["start"] == k else 0.0)
            x += math.cos(a) * step
            y += math.sin(a) * step
        pts.append((x, y))
    return pts


def hidden_path(strip: dict, n: int) -> List[bool]:
    """For each LED in path order: is it left out of the drawing?"""
    out = [False] * max(0, n)
    segs = strip["segments"]
    for i, seg in enumerate(segs):
        if seg.get("hide"):
            end = segs[i + 1]["start"] if i + 1 < len(segs) else n
            for k in range(seg["start"], min(end, n)):
                out[k] = True
    return out


def gap_starts(strip: dict, n: int) -> List[int]:
    """Path positions of LEDs that come after a wire gap."""
    return [seg["start"] for seg in strip["segments"][1:] if seg.get("gap") and 0 < seg["start"] < n]


def led_points(strip: dict, n: int) -> List[Tuple[float, float]]:
    """Where each LED sits, in the order they're sent (LED 1 first, whatever the flip)."""
    pts = path_points(strip, n)
    return [pts[path_at_led(strip, n, i)] for i in range(n)]


def led_at_path(strip: dict, n: int, k: int) -> int:
    """Which LED (as sent) sits at path position k."""
    return n - 1 - k if strip.get("flip") else k


def path_at_led(strip: dict, n: int, i: int) -> int:
    return n - 1 - i if strip.get("flip") else i


def point_along(pts: List[Tuple[float, float]], f: float) -> Tuple[float, float]:
    """Point at fractional path index f (0..len-1), interpolated between LED centres."""
    if not pts:
        return 0.0, 0.0
    f = max(0.0, min(len(pts) - 1.0, f))
    i = int(f)
    if i >= len(pts) - 1:
        return pts[-1]
    t = f - i
    (x0, y0), (x1, y1) = pts[i], pts[i + 1]
    return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t


def project(pts: List[Tuple[float, float]], px: float, py: float) -> Tuple[float, float]:
    """(fractional path index nearest to the point, distance)."""
    if not pts:
        return 0.0, float("inf")
    if len(pts) == 1:
        return 0.0, math.hypot(px - pts[0][0], py - pts[0][1])
    best, bd = 0.0, float("inf")
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
        qx, qy = x0 + dx * t, y0 + dy * t
        d = math.hypot(px - qx, py - qy)
        if d < bd:
            best, bd = i + t, d
    return best, bd


# ----------------------------------------------- pattern stops <-> LEDs
# Same mapping as the Devices tab's strip editor, as a fraction 0..1 of the
# strip's LEDs (as sent, before the layout's flip).

def stop_to_fraction(v: float, pattern: str, reverse: bool, mirror: bool) -> List[float]:
    """Where a stop value sits along the LEDs; two places for mirrored/radial patterns."""
    if pattern == "center_out":
        f = 0.5 + v / 2
    elif pattern == "edges_in":
        f = 0.5 + (1 - v) / 2
    else:
        f = v
    if mirror:
        f = f / 2
    if reverse:
        f = 1 - f
    out = [f]
    if pattern in ("center_out", "edges_in") or mirror:
        out.append(1 - f)
    return out


def fraction_to_stop(f: float, pattern: str, reverse: bool, mirror: bool) -> float:
    f = max(0.0, min(1.0, f))
    if reverse:
        f = 1 - f
    if mirror:
        return max(0.0, min(1.0, min(f, 1 - f) * 2))
    if pattern == "center_out":
        return max(0.0, min(1.0, 2 * max(f, 1 - f) - 1))
    if pattern == "edges_in":
        return max(0.0, min(1.0, 2 - 2 * max(f, 1 - f)))
    return f


def bounds(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float, float]]:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def zone_count(device_configs: Dict, key: str) -> Optional[int]:
    d, z = split_key(key)
    dev = device_configs.get(d)
    if dev is None:
        return None
    zones = dev.get("zones")
    if zones:
        zc = zones.get(z)
        return None if zc is None else int(zc.get("led_count", 20))
    return int(dev.get("led_count", 20)) if not z else None
