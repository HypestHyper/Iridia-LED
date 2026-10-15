"""Controls for animated effects (Devices tab) and the controllers' own effects."""

import math
import time
import zlib
from typing import Callable, Dict, List, Optional, Sequence

from gi.repository import GLib, Gtk

from iridia import animations
from iridia.i18n import _
from iridia.ui.widgets import (DualRange, Group, hbox, label, no_scroll, rgb, switch_row,
                               themed)

EFFECT_NAMES = {
    "breathing": _("Breathing"),
    "comet": _("Comet"),
    "fill": _("Fill"),
    "embers": _("Embers"),
    "rainbow": _("Rainbow"),
    "rainbow_vomit": "Rainbow vomit",          # its name, never translated
    "color_cycle": _("Color cycle"),
}
EFFECT_KEYS = {v: k for k, v in EFFECT_NAMES.items()}
EFFECT_NOTES = {
    "breathing": _("Fades between two brightness levels. A minimum above 0 keeps the dark end smooth on strips "
                   "that step at low brightness."),
    "comet": _("Bright heads with a fading tail run along the strip."),
    "fill": _("The strip fills up with its pattern, then empties."),
    "embers": _("Points glow up and die down like embers, drifting through the colors picked below. Fire "
                "uses fire colors instead."),
    "rainbow": _("A moving rainbow. Ignores the zone's colors."),
    "rainbow_vomit": _("The loud one: a fast, uneven rainbow with random sparkles."),
    "color_cycle": _("The whole zone fades from one color to the next."),
}

# param -> (label, unit or None, step)
_LABELS = {
    "min": (_("Brightness range"), "%", 1),
    "easing": (_("Easing"), None, None),
    "cycle_colors": (_("Next color at each breath"), None, None),
    "tail": (_("Tail length"), _("LEDs"), 1),
    "heads": (_("Heads"), None, 1),
    "spacing": (_("Spacing (0 spreads them evenly)"), _("LEDs"), 1),
    "bounce": (_("Bounce back and forth"), None, None),
    "reverse": (_("Reverse direction"), None, None),
    "background": (_("Background"), None, None),
    "pause": (_("Pause when full and empty"), _("s"), 0.1),
    "origin": (_("Fill from"), None, None),
    "empty": (_("Empty"), None, None),
    "density": (_("Density"), "%", 1),
    "softness": (_("Softness"), "%", 1),
    "flicker": (_("Flicker"), "%", 1),
    "palette": (_("Colors"), None, None),
    "width": (_("Width (LEDs per rainbow)"), _("LEDs"), 1),
    "saturation": (_("Saturation"), "%", 1),
    "chaos": (_("Chaos"), "%", 1),
    "hold": (_("Hold each color"), _("s"), 0.1),
    "follow_layout": (_("Follow the layout"), None, None),
    "angle": (_("Direction"), "°", 1),
    "sync": (_("Keep zones with this effect in step"), None, None),
}
_SPEED = {
    "breathing": (_("Seconds per breath"), _("s"), 0.1),
    "comet": (_("Speed"), _("LEDs/s"), 1),
    "fill": (_("Speed"), _("LEDs/s"), 1),
    "embers": (_("Speed"), None, 0.05),
    "rainbow": (_("Speed"), _("LEDs/s"), 1),
    "rainbow_vomit": (_("Speed"), _("LEDs/s"), 1),
    "color_cycle": (_("Fade time"), _("s"), 0.1),
}
_CHOICES = {
    "sine": _("Sine"), "smooth": _("Smooth"), "sharp": _("Sharp"),
    "off": _("Off"), "dim": _("Dim"), "second": _("Second color"),
    "start": _("Start"), "end": _("End"), "center": _("Center"),
    "reverse": _("Back"), "same": _("Same way"), "reset": _("Reset"),
    "warm": _("Fire"), "zone": _("Picked colors"),
}


class Slider(Gtk.Box):
    """A labelled slider that shows its value."""

    def __init__(self, text: str, lo: float, hi: float, value: float, step: float, unit: Optional[str],
                 cb: Callable[[float], None]):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._unit = unit or ""
        self._digits = 0 if step >= 1 else (1 if step >= 0.1 else 2)
        self._cb = cb
        self._quiet = False
        name = label(text, ("body", "dim"), wrap=True)
        name.set_width_chars(22)
        name.set_max_width_chars(22)
        self.append(name)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        self.scale.set_draw_value(False)
        no_scroll(self.scale)
        self.scale.set_hexpand(True)
        self.scale.set_size_request(160, -1)
        self.scale.set_value(value)
        self.scale.connect("value-changed", self._changed)
        self.append(self.scale)
        self.value_lbl = label("", ("body", "mono"), xalign=1.0)
        self.value_lbl.set_width_chars(9)
        self.append(self.value_lbl)
        self._show()

    def _show(self):
        v = self.scale.get_value()
        txt = f"{v:.{self._digits}f}"
        self.value_lbl.set_label(f"{txt} {self._unit}".strip())

    def _changed(self, *_a):
        self._show()
        if not self._quiet:
            self._cb(round(self.scale.get_value(), self._digits))

    def set_quiet(self, v: float):
        self._quiet = True
        self.scale.set_value(v)
        self._show()
        self._quiet = False


class Dial(Gtk.DrawingArea):
    """A small round direction picker: 0 degrees points right, 90 down (like the Layout tab)."""

    def __init__(self, angle: int, cb: Callable[[int], None], size: int = 64):
        super().__init__()
        themed(self)
        self.angle = int(angle) % 360
        self._cb = cb
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", lambda _g, x, y: self._set(x, y))
        g.connect("drag-update", self._drag)
        self.add_controller(g)
        self._start = (0.0, 0.0)

    def _drag(self, g, dx, dy):
        ok, x, y = g.get_start_point()
        if ok:
            self._set(x + dx, y + dy)

    def _set(self, x, y):
        w, h = self.get_width(), self.get_height()
        a = int(round(math.degrees(math.atan2(y - h / 2, x - w / 2)))) % 360
        a = int(round(a / 5.0) * 5) % 360
        if a != self.angle:
            self.angle = a
            self.queue_draw()
            self._cb(a)

    def _draw(self, _a, cr, w, h):
        r = min(w, h) / 2 - 3
        cx, cy = w / 2, h / 2
        cr.set_source_rgb(*rgb("SECONDARY_CONTAINER"))
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        a = math.radians(self.angle)
        cr.set_source_rgb(*rgb("PRIMARY"))
        cr.set_line_width(4)
        cr.set_line_cap(1)
        cr.move_to(cx, cy)
        cr.line_to(cx + math.cos(a) * (r - 6), cy + math.sin(a) * (r - 6))
        cr.stroke()
        cr.arc(cx + math.cos(a) * (r - 6), cy + math.sin(a) * (r - 6), 5, 0, 2 * math.pi)
        cr.fill()


class EffectControls(Gtk.Box):
    """The settings of one effect. on_change(params) fires about 100 ms after the last change."""

    def __init__(self, on_change: Callable[[dict], None], show_sync: bool = False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._on_change = on_change
        self._show_sync = show_sync
        self.params: Dict = {}
        self._job = None
        self._effect = None
        self._widgets: Dict[str, object] = {}

    def set_effect(self, params: Optional[dict]):
        """Show the controls for params["effect"] with these values (None hides everything)."""
        params = animations.clean(params) if params else None
        if params is None:
            self._effect = None
            self.params = {}
            self._clear()
            self.set_visible(False)
            return
        self.set_visible(True)
        if params["effect"] == self._effect and params == self.params:
            return
        if params["effect"] == self._effect and not self._busy():
            self.params = params
            self._sync_values()
            return
        if params["effect"] != self._effect:
            self._effect = params["effect"]
            self.params = params
            self._build()

    def _busy(self) -> bool:
        return self._job is not None

    def _clear(self):
        c = self.get_first_child()
        while c:
            n = c.get_next_sibling()
            self.remove(c)
            c = n
        self._widgets = {}

    def _build(self):
        self._clear()
        e = self._effect
        p = self.params
        self.append(label(EFFECT_NOTES.get(e, ""), ("tiny", "faint"), wrap=True))
        spec = animations.EFFECTS[e]
        txt, unit, step = _SPEED[e]
        self._slider("speed", txt, spec["speed"], unit, step)
        for key, s in spec.items():
            if key in ("speed", "max"):
                continue
            if key == "min":
                r = hbox(12)
                r.append(label(_LABELS["min"][0], ("body", "dim")))
                rng = DualRange(p["min"], p["max"], lambda a, b: self._set_many(min=a, max=b))
                r.append(rng)
                self._widgets["min"] = rng
                self.append(r)
            elif s[0] == "bool":
                row, sw = switch_row(_LABELS[key][0], bool(p[key]), lambda v, k=key: self._set(k, v))
                self._widgets[key] = sw
                self.append(row)
            elif s[0] == "choice":
                r = hbox(10)
                r.append(label(_LABELS[key][0], ("body", "dim")))
                g = Group([(o, _CHOICES.get(o, o)) for o in s[2]], p[key], lambda v, k=key: self._set(k, v))
                self._widgets[key] = g
                r.append(g)
                self.append(r)
            else:
                t, u, st = _LABELS[key]
                self._slider(key, t, s, u, st)
        # moving effects can run through the room, following the Layout tab
        if e in ("comet", "fill", "rainbow", "rainbow_vomit", "embers"):
            r = hbox(14)
            row, sw = switch_row(_LABELS["follow_layout"][0], bool(p["follow_layout"]), self._on_follow)
            self._widgets["follow_layout"] = sw
            r.append(row)
            self._dial_box = hbox(8)
            dial = Dial(p["angle"], lambda a: self._set("angle", a))
            self._widgets["angle"] = dial
            self._angle_lbl = label(f"{p['angle']}°", ("body", "mono"))
            self._dial_box.append(label(_LABELS["angle"][0], ("body", "dim")))
            self._dial_box.append(dial)
            self._dial_box.append(self._angle_lbl)
            self._dial_box.set_visible(bool(p["follow_layout"]))
            r.append(self._dial_box)
            self.append(r)
            self.append(label(_("Follow the layout runs the effect through the room, across every strip that follows "
                                "it, using where the LEDs are on the Layout tab."), ("tiny", "faint"), wrap=True))
        if self._show_sync:
            row, sw = switch_row(_LABELS["sync"][0], bool(p["sync"]), lambda v: self._set("sync", v))
            self._widgets["sync"] = sw
            self.append(row)

    def _slider(self, key, text, spec, unit, step):
        s = Slider(text, spec[2], spec[3], self.params[key], step, unit, lambda v, k=key: self._set(k, v))
        self._widgets[key] = s
        self.append(s)

    def _sync_values(self):
        for k, w in self._widgets.items():
            v = self.params.get(k)
            if isinstance(w, Slider):
                w.set_quiet(v)
            elif isinstance(w, DualRange):
                if not w.dragging():
                    w.set(self.params["min"], self.params["max"])
            elif isinstance(w, Group):
                w.set_active(v)
            elif isinstance(w, Dial):
                if w.angle != v:
                    w.angle = v
                    w.queue_draw()
            elif hasattr(w, "set_value"):
                w.set_value(bool(v))

    def _on_follow(self, v):
        if hasattr(self, "_dial_box"):
            self._dial_box.set_visible(bool(v))
        self._set("follow_layout", v)

    def _set(self, key, value):
        self._set_many(**{key: value})

    def _set_many(self, **kw):
        self.params = animations.clean(dict(self.params, **kw)) or self.params
        if "angle" in kw and hasattr(self, "_angle_lbl"):
            self._angle_lbl.set_label(f"{self.params['angle']}°")
        if self._job:
            GLib.source_remove(self._job)
        self._job = GLib.timeout_add(100, self._fire)

    def _fire(self):
        self._job = None
        self._on_change(dict(self.params))
        return False


def anim_clock(status: dict) -> float:
    """The daemon's animation clock now (it ticks on between status polls)."""
    a = status.get("animations") or {}
    t0 = a.get("time") or time.time()
    return float(a.get("clock") or 0.0) + (time.time() - t0) * float(a.get("rate") or 1.0)


def live_animation(status: dict, key: str, cfg: dict) -> Optional[dict]:
    """The effect this zone shows right now, according to the daemon, or None."""
    a = status.get("animations") or {}
    if key not in (a.get("zones") or []) or a.get("paused") or not a.get("enabled", True):
        return None
    ov = (status.get("overlays") or {}).get(key) or {}
    if "effect" in ov:
        return animations.clean(ov["effect"]) if ov["effect"] else None
    return animations.clean(cfg.get("animation"))


def preview(status: dict, key: str, anim: dict, colors: Sequence[str], base: Sequence[str], n: int,
            positions=None, extent=None) -> List[str]:
    """One frame of the zone's effect as hex colors, the same frame the daemon sends (before brightness
    and color correction)."""
    a = status.get("animations") or {}
    crc = zlib.crc32(key.encode())
    t = anim_clock(status) + (0.0 if anim.get("sync", True) else (crc % 10000) / 100.0)
    frame = animations.render(anim["effect"], anim, n, t, [animations.hex_to_rgb(c) for c in colors],
                              crc ^ int(a.get("seed") or 0), positions,
                              [animations.hex_to_rgb(c) for c in base] if base else None, extent)
    return [animations.rgb_to_hex(c) for c in frame]
