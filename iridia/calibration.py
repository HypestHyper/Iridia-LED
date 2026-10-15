"""Colour calibration profiles.

A profile maps the colour you *mean* (hue, saturation, value) to the hex that
should be sent to a given kind of LED strip, so the colour you see matches the
colour you picked. WS2812B strips need this: raw RGB drifts by hue.

Profiles live as one JSON file each in ~/.config/iridia/calibration/, named
after the profile (WS2812B.json is the one that ships). A profile holds:

  anchors         [[hue_degrees, "hex to send"], ...]  hardware-confirmed points,
                  linearly interpolated per whole degree between neighbours
  grey            hex sent for a colour with no saturation
  sat_exponent    how fast saturation fades toward white (0.5 = square root)
  blue_nudge      pushes blue-heavy blends toward sky blue instead of violet
  grey_sharpness  how close to zero saturation the grey takes over
  min_out_sat     saturation floor on the output: a color is never sent whiter than this
                  (capped by the input's own saturation, so greys stay grey)

Edit anchors in the app (Settings, Color calibration) or by hand.
"""

import colorsys
import json
import logging
import os
import re
import tempfile
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("iridia")

DEFAULT_NAME = "WS2812B"

DEFAULT_PROFILE = {
    "name": DEFAULT_NAME,
    "description": "WS2812B strip on an RGB controller, tuned by eye.",
    "anchors": [
        [0, "ff0000"], [30, "ff3900"], [45, "ff3000"], [60, "ff5000"], [120, "00ff00"],
        [150, "007313"], [180, "007373"], [195, "004d66"], [210, "0080ff"], [240, "000066"],
        [270, "4000ff"], [300, "ff00cc"], [330, "ff4d9a"], [360, "ff0000"],
    ],
    "grey": "793913",
    "sat_exponent": 0.5,
    "blue_nudge": 0.3,
    "grey_sharpness": 8.0,
    "min_out_sat": 0.55,
}

NEUTRAL_NAME = "Neutral"
NEUTRAL_PROFILE = {
    "name": NEUTRAL_NAME,
    "description": "No correction yet: pure colors at every hue. A starting point for strips other than "
                   "WS2812B (12V RGB, SK6812, WS2811...). Tune its anchors by eye in the editor.",
    "anchors": [[0, "ff0000"], [60, "ffff00"], [120, "00ff00"], [180, "00ffff"], [240, "0000ff"],
                [300, "ff00ff"], [360, "ff0000"]],
    "grey": "ffffff",
    "sat_exponent": 1.0,
    "blue_nudge": 0.0,
    "grey_sharpness": 8.0,
    "min_out_sat": 0.0,
}

_HEX = re.compile(r"^[0-9a-f]{6}$")
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.()\-]{0,39}$")

# Friendly names for the usual anchor hues (used by the editor)
def N_(text):
    """Marks a string for translation without translating it here (the window translates it)."""
    return text


HUE_NAMES = {0: N_("Red"), 15: N_("Red-orange"), 30: N_("Orange"), 45: N_("Amber"), 60: N_("Yellow"),
             90: N_("Lime"), 120: N_("Green"), 150: N_("Spring green"), 180: N_("Cyan"), 195: N_("Teal"),
             210: N_("Sky blue"), 240: N_("Blue"), 270: N_("Violet"), 300: N_("Magenta"), 330: N_("Pink"),
             360: N_("Red (wraps around)")}


def _rgb(h: str) -> List[int]:
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def clean_hex(value) -> Optional[str]:
    h = str(value or "").strip().lstrip("#").lower()
    return h if _HEX.match(h) else None


def valid_name(name: str) -> bool:
    return bool(_NAME_OK.match(name or ""))


def normalize(data) -> Tuple[Optional[dict], Optional[str]]:
    """(clean profile dict, None) or (None, reason it is unusable)."""
    if not isinstance(data, dict):
        return None, "profile must be a JSON object"
    anchors = []
    for item in data.get("anchors", []):
        try:
            hue, hx = float(item[0]), clean_hex(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None, f"bad anchor: {item!r}"
        if hx is None or not 0 <= hue <= 360:
            return None, f"bad anchor: {item!r}"
        anchors.append([int(round(hue)), hx])
    if len(anchors) < 2:
        return None, "need at least two anchors"
    anchors.sort(key=lambda a: a[0])
    hues = [a[0] for a in anchors]
    if len(set(hues)) != len(hues):
        return None, "two anchors share the same hue"
    if anchors[0][0] != 0:
        anchors.insert(0, [0, anchors[-1][1]])        # wrap: hue 0 mirrors the last anchor
    if anchors[-1][0] != 360:
        anchors.append([360, anchors[0][1]])          # wrap: hue 360 mirrors hue 0
    else:
        anchors[-1][1] = anchors[0][1]
    grey = clean_hex(data.get("grey", DEFAULT_PROFILE["grey"]))
    if grey is None:
        return None, "grey must be a 6 digit hex"
    out = {
        "name": str(data.get("name") or DEFAULT_NAME),
        "description": str(data.get("description") or ""),
        "anchors": anchors,
        "grey": grey,
    }
    for key, lo, hi in (("sat_exponent", 0.1, 3.0), ("blue_nudge", 0.0, 1.0), ("grey_sharpness", 1.0, 30.0),
                         ("min_out_sat", 0.0, 1.0)):
        try:
            v = float(data.get(key, DEFAULT_PROFILE[key]))
        except (TypeError, ValueError):
            return None, f"{key} must be a number"
        out[key] = min(hi, max(lo, v))
    return out, None


def _floor_sat(rgb: List[float], floor: float) -> List[float]:
    """Raise saturation to `floor` if the color is whiter than that; hue and brightness are kept."""
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s >= floor or v == 0:
        return rgb
    r, g, b = colorsys.hsv_to_rgb(h, floor, v)
    return [r * 255, g * 255, b * 255]


class Profile:
    """One calibration profile: builds its lookup table once, then maps colours."""

    def __init__(self, data: dict):
        clean, err = normalize(data)
        if clean is None:
            raise ValueError(err)
        self.data = clean
        self.name = clean["name"]
        self._grey = _rgb(clean["grey"])
        self._lut = self._build_lut(clean["anchors"])
        self._cache: Dict[tuple, str] = {}

    @staticmethod
    def _build_lut(anchors) -> List[List[float]]:
        lut = []
        for deg in range(360):
            for (h0, c0), (h1, c1) in zip(anchors, anchors[1:]):
                if h0 <= deg < h1:
                    t = (deg - h0) / (h1 - h0)
                    a, b = _rgb(c0), _rgb(c1)
                    lut.append([a[i] + (b[i] - a[i]) * t for i in range(3)])
                    break
        return lut

    def picker_to_led(self, hue_deg: float, sat: float, val: float) -> str:
        """hue 0..360, saturation 0..1, value 0..1 -> hex to send to the strip."""
        d = self.data
        base = self._lut[int(hue_deg) % 360]
        peak_base = max(base)
        s_eff = sat ** d["sat_exponent"]

        # fade toward a white at the base colour's peak brightness
        desat = [base[i] * s_eff + peak_base * (1 - s_eff) for i in range(3)]
        # nudge blue-heavy blends toward sky blue rather than violet
        desat[1] += d["blue_nudge"] * base[2] * (1 - s_eff)
        # lift dim blends back toward full peak; fades out at full saturation
        peak = max(desat)
        if peak > 0:
            lift = 1 + (255 / peak - 1) * (1 - sat)
            desat = [c * lift for c in desat]
        # calibrated grey only near zero saturation
        k = (1 - sat) ** d["grey_sharpness"]
        out = [desat[i] * (1 - k) + self._grey[i] * k for i in range(3)]
        # saturation floor: never washed out, but near-greys keep their own low saturation
        out = _floor_sat(out, min(d["min_out_sat"], sat))
        # brightness last, a plain multiply
        out = [max(0, min(255, round(c * val))) for c in out]
        return "".join(f"{c:02x}" for c in out)

    def correct(self, hex_color: str, brightness_pct: float = 100.0) -> str:
        """Intended colour (hex) plus brightness 0..100 -> hex to send."""
        key = (hex_color, round(brightness_pct))
        hit = self._cache.get(key)
        if hit is None:
            r, g, b = (c / 255 for c in _rgb(hex_color))
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            hit = self.picker_to_led(h * 360, s, v * max(0.0, min(100.0, brightness_pct)) / 100.0)
            if len(self._cache) > 8192:
                self._cache.clear()
            self._cache[key] = hit
        return hit


class Profiles:
    """The folder of profile files. Safe to use from several threads."""

    def __init__(self, folder: str = "~/.config/iridia/calibration"):
        self.folder = os.path.expanduser(folder)
        self._lock = threading.RLock()
        self._loaded: Dict[str, Tuple[float, Profile]] = {}     # name -> (mtime, profile)
        self._default = Profile(DEFAULT_PROFILE)

    # ---- files
    def path(self, name: str) -> str:
        return os.path.join(self.folder, f"{name}.json")

    def ensure_default(self):
        """Write WS2812B.json on first run (never overwrites your edits)."""
        with self._lock:
            os.makedirs(self.folder, exist_ok=True)
            if not os.path.exists(self.path(DEFAULT_NAME)):
                self._write(DEFAULT_NAME, DEFAULT_PROFILE)
            # The Neutral starting point is added once; if you delete it, it stays deleted.
            marker = os.path.join(self.folder, ".neutral-added")
            if not os.path.exists(marker):
                try:
                    if not os.path.exists(self.path(NEUTRAL_NAME)):
                        self._write(NEUTRAL_NAME, NEUTRAL_PROFILE)
                    open(marker, "w").close()
                except OSError:
                    pass

    def _write(self, name: str, data: dict):
        os.makedirs(self.folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.folder, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp, self.path(name))
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def list(self) -> List[str]:
        with self._lock:
            try:
                names = [f[:-5] for f in os.listdir(self.folder) if f.endswith(".json")]
            except OSError:
                names = []
        names = [n for n in names if valid_name(n)]
        if DEFAULT_NAME not in names:
            names.append(DEFAULT_NAME)
        return sorted(names, key=lambda n: (n != DEFAULT_NAME, n.lower()))

    # ---- reading
    def get(self, name: Optional[str]) -> Profile:
        """The named profile; the built-in WS2812B values if it is missing or broken."""
        name = name or DEFAULT_NAME
        if not valid_name(name):
            return self._default
        path = self.path(name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return self._default
        with self._lock:
            hit = self._loaded.get(name)
            if hit and hit[0] == mtime:
                return hit[1]
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data.setdefault("name", name)
                data["name"] = name
                prof = Profile(data)
            except (OSError, ValueError) as e:
                logger.warning(f"Calibration profile '{name}' is unusable ({e}); using built-in WS2812B values")
                return self._default
            self._loaded[name] = (mtime, prof)
            return prof

    def read_data(self, name: str) -> dict:
        return dict(self.get(name).data)

    # ---- editing
    def save(self, name: str, data: dict) -> Optional[str]:
        """Validate and write. Returns an error string or None."""
        if not valid_name(name):
            return "Use letters, numbers, spaces, dashes, underscores and brackets (up to 40 characters)."
        data = dict(data, name=name)
        clean, err = normalize(data)
        if clean is None:
            return err
        with self._lock:
            self._write(name, clean)
            self._loaded.pop(name, None)
        return None

    def add(self, name: str, base: Optional[str] = None) -> Optional[str]:
        if not valid_name(name):
            return "Use letters, numbers, spaces, dashes, underscores and brackets (up to 40 characters)."
        if name in self.list():
            return f"A profile called '{name}' already exists."
        return self.save(name, self.read_data(base or DEFAULT_NAME))

    def delete(self, name: str) -> Optional[str]:
        if name == DEFAULT_NAME:
            return "The built-in WS2812B profile can't be deleted. Use Reset to restore its values."
        with self._lock:
            try:
                os.remove(self.path(name))
            except FileNotFoundError:
                pass
            except OSError as e:
                return str(e)
            self._loaded.pop(name, None)
        return None

    def reset_default(self):
        self.save(DEFAULT_NAME, DEFAULT_PROFILE)

    def export_to(self, name: str, dest: str) -> Optional[str]:
        try:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(self.read_data(name), f, indent=2)
        except OSError as e:
            return str(e)
        return None

    def import_from(self, src: str) -> Tuple[Optional[str], Optional[str]]:
        """(name it was saved under, None) or (None, error)."""
        try:
            with open(src, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            return None, f"Couldn't read that file: {e}"
        clean, err = normalize(data)
        if clean is None:
            return None, err
        base = clean["name"] if valid_name(clean["name"]) else os.path.splitext(os.path.basename(src))[0]
        if not valid_name(base):
            base = "Imported"
        name, n = base, 2
        existing = set(self.list())
        while name in existing:
            name = f"{base} ({n})"
            n += 1
        err = self.save(name, clean)
        return (name, None) if err is None else (None, err)
