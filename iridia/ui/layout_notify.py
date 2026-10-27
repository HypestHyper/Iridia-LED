"""The Layout tab's Notifications tool: which LEDs flash for a notification, picked by clicking or
dragging over them on the map, and two points A and B that a moving flash runs between. Play shows
the flash on the map (with the same code the daemon uses) and on the real strips.

Mixed into LayoutTab; it uses the tab's canvas, handles, drag state and side panel."""

import math
import time
from typing import Dict, Optional, Set

from gi.repository import GLib, Gtk

from iridia.i18n import _, ngettext
from iridia import notifyflash, theme
from iridia import sections as zone_sections
from iridia.layout import led_at_path, led_points, path_points, project, split_key
from iridia.ui.widgets import (Dropdown, Group, QuickColors, Spin, Toggle, button, divider, hbox, label, no_scroll,
                               rgb)

EFFECT_NAMES = {"pulse": _("Pulse"), "flash": _("Flash"), "sweep": _("Sweep"), "comet": _("Comet"),
                "fill": _("Fill"), "ripple": _("Ripple")}
DIRECTION_NAMES = {"ab": _("A to B"), "ba": _("B to A"), "abba": _("A to B and back"),
                   "out": _("From the middle out")}
HOLD_SEC = 3.0                  # local edits win over the daemon's status for this long


class MiniSlider(Gtk.Box):
    """A narrow slider with its value, for side panels: name, slider, value. The callback comes once
    the slider rests (not on every step of a drag); the mouse wheel scrolls the page, not the value."""

    def __init__(self, text, lo, hi, value, step, unit, cb):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._cb, self._unit, self._job, self._quiet = cb, unit, None, False
        self._digits = 0 if step >= 1 else 1
        self.append(label(text, ("body", "dim")))
        self.scale = no_scroll(Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step))
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_size_request(110, -1)
        self.scale.set_value(value)
        self.scale.connect("value-changed", self._changed)
        self.append(self.scale)
        self._lbl = label("", ("body", "tnum"), xalign=1.0)
        self._lbl.set_width_chars(7)
        self.append(self._lbl)
        self._show()

    def _show(self):
        self._lbl.set_label(f"{self.scale.get_value():.{self._digits}f} {self._unit}")

    def _changed(self, *_a):
        self._show()
        if self._quiet:
            return
        if self._job:
            GLib.source_remove(self._job)
        self._job = GLib.timeout_add(250, self._fire)

    def _fire(self):
        self._job = None
        self._cb(round(self.scale.get_value(), self._digits))
        return False

    def set_quiet(self, v):
        if self._job is None and abs(self.scale.get_value() - v) > 1e-9:
            self._quiet = True
            self.scale.set_value(v)
            self._show()
            self._quiet = False


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2[i:i + 2], 16) for i in (0, 2, 4)]
    return "%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


COLOUR_NAMES = {"accent": _("Wallpaper"), "app": _("One per app"), "custom": _("Custom"), "painted": _("Painted")}
BRUSHES = (("choose", _("Choose LEDs")), ("paint", _("Paint")), ("erase", _("Erase colour")))


class NotifyLayer:
    def _nt_init(self):
        self._nt: dict = notifyflash.clean({})
        self._nt_hold = 0.0
        self._nt_paint: Dict[str, Set[int]] = {}        # zone key -> LEDs while dragging over them
        self._nt_cols: Dict[str, Dict[str, Optional[str]]] = {}  # zone key -> LED -> colour while painting
        self._nt_brush = "choose"                       # what a click or drag does: choose, paint, erase
        self._nt_preview: Optional[notifyflash.Flash] = None
        self._nt_job = None

    # ------------------------------------------------------------ state
    def _nt_update(self, status: dict):
        st = status.get("notify")
        if isinstance(st, dict) and time.time() >= self._nt_hold:
            self._nt = notifyflash.clean(st)

    def _nt_set(self, **kw):
        """Change settings here at once and in the daemon."""
        self._nt = notifyflash.clean(dict(self._nt, **kw))
        self._nt_hold = time.time() + HOLD_SEC
        self._send(lambda: self.app.client.notify(**kw))
        self.cv.queue_draw()

    def _nt_sections(self, key: str, n: int):
        return zone_sections.clean((self._cfg.get(key) or {}).get("sections"), n)

    def _nt_leds(self, key: str, n: int) -> Set[int]:
        """The LEDs of this zone that flash (0-based, as sent)."""
        if key in self._nt_paint:
            return self._nt_paint[key]
        d, z = split_key(key)
        out: Set[int] = set()
        for t in self._nt["targets"]:
            if (t["device"], t["zone"]) == (d, z):
                r = notifyflash.target_range(t, n, self._nt_sections(key, n), zone_sections.spans)
                if r:
                    out.update(range(*r))
        return out

    def _nt_painted(self, key: str) -> Dict[str, str]:
        """LED (as text) -> painted colour for this zone, with a stroke in progress on top."""
        out = dict(self._nt["paint"].get(key) or {})
        for i, h in (self._nt_cols.get(key) or {}).items():
            if h is None:
                out.pop(i, None)
            else:
                out[i] = h
        return out

    def _nt_fill(self) -> Optional[str]:
        """The colour a chosen LED flashes in, when it's one colour for all (not painted, not per app)."""
        st = self._nt
        if st["color"] == "custom":
            return st["hex"]
        if st["color"] == "app":
            return None
        return self.status.get("led_color") or (self.status.get("extracted_colors") or ["ffffff"])[0]

    def _nt_count(self):
        leds = strips = 0
        for key in self._enabled:
            k = len(self._nt_leds(key, self._count(key)))
            if k:
                leds, strips = leds + k, strips + 1
        return leds, strips

    # ------------------------------------------------------------ drawing
    def _nt_draw(self, cr):
        z = self.layout.view["zoom"]
        pv = self._nt_preview
        if pv is not None and pv.done():
            pv = self._nt_preview = None
        for s in self._strips():
            key = s["zone"]
            n = self._count(key)
            if n <= 0:
                continue
            chosen = self._nt_leds(key, n)
            if not chosen:
                continue
            pts = [self.w2s(x, y) for x, y in led_points(s, n)]
            r = max(2.0, min(s["segments"][0]["spacing"] * 0.34, 6.0) * z)
            frame = None
            if pv is not None and key in pv.leds:
                base = [theme.hex_rgb(c) for c in self.zone_colors(key)]
                frame = pv.mix(key, [(int(a * 255), int(b * 255), int(c * 255)) for a, b, c in base])
            painted = self._nt_painted(key) if self._nt["color"] == "painted" else {}
            fill = self._nt_fill()
            cr.set_line_width(2)
            for i in chosen:
                if i >= len(pts):
                    continue
                x, y = pts[i]
                if frame is not None:
                    cr.set_source_rgb(*(v / 255 for v in frame[i]))
                    cr.arc(x, y, r, 0, 2 * math.pi)
                    cr.fill()
                elif painted.get(str(i)) or fill:        # the colour it will flash in
                    cr.set_source_rgb(*theme.hex_rgb(painted.get(str(i)) or fill))
                    cr.arc(x, y, r, 0, 2 * math.pi)
                    cr.fill()
                cr.set_source_rgb(*rgb("PRIMARY"))
                cr.arc(x, y, r + 2.5, 0, 2 * math.pi)
                cr.stroke()
        path = self._nt["path"]
        if path:
            ax, ay = self.w2s(*path["a"])
            bx, by = self.w2s(*path["b"])
            on = self._nt["spatial"]
            cr.set_source_rgb(*rgb("PRIMARY" if on else "OUTLINE"))
            cr.set_line_width(2)
            if not on:
                cr.set_dash([6, 6])
            cr.move_to(ax, ay)
            cr.line_to(bx, by)
            cr.stroke()
            cr.set_dash([])
            ang = math.atan2(by - ay, bx - ax)          # an arrowhead halfway, pointing to B
            mx, my = (ax + bx) / 2, (ay + by) / 2
            for side in (-1, 1):
                cr.move_to(mx + 8 * math.cos(ang), my + 8 * math.sin(ang))
                cr.line_to(mx - 6 * math.cos(ang) + side * 7 * math.sin(ang),
                           my - 6 * math.sin(ang) - side * 7 * math.cos(ang))
            cr.stroke()
            for name, (x, y) in (("A", (ax, ay)), ("B", (bx, by))):
                cr.set_source_rgb(*rgb("PRIMARY" if on else "SURFACE_CONTAINER_HIGHEST"))
                cr.arc(x, y, 13, 0, 2 * math.pi)
                cr.fill()
                self._text(cr, x, y + 5, name, "ON_PRIMARY" if on else "ON_SURFACE", 14, center=True, bold=True)
                self._handles.append(("nt_" + name.lower(), None, 0, x, y, 16))

    # ------------------------------------------------------------ pointer
    def _nt_press(self, s, n, k):
        """Click or drag over LEDs. Choose: adds them, or takes them out when the first one was chosen.
        Paint: gives them the first paint colour (and chooses them). Erase: takes their colour off."""
        key = s["zone"]
        i = led_at_path(s, n, k)
        cur = set(self._nt_leds(key, n))
        if self._nt_brush == "choose":
            mode = "remove" if i in cur else "add"
        else:
            mode = self._nt_brush
            self._nt_cols[key] = {}
        self._nt_paint[key] = cur
        self._drag = {"kind": "ntpaint", "sid": s["id"], "mode": mode, "last": k}
        self._nt_apply(s, n, k, k)

    def _nt_apply(self, s, n, k0, k1):
        leds = self._nt_paint[s["zone"]]
        cols = self._nt_cols.get(s["zone"])
        mode = self._drag["mode"]
        for k in range(min(k0, k1), max(k0, k1) + 1):
            i = led_at_path(s, n, k)
            if mode in ("add", "paint"):
                leds.add(i)
            elif mode == "remove":
                leds.discard(i)
            if mode == "paint":
                cols[str(i)] = self.color_a
            elif mode == "erase":
                cols[str(i)] = None

    def _nt_motion(self, s, n, x, y):
        f, d = project([self.w2s(a, b) for a, b in path_points(s, n)], x, y)
        if d < 40:
            k = int(round(f))
            self._nt_apply(s, n, self._drag["last"], k)
            self._drag["last"] = k

    def _nt_release(self, s):
        key = s["zone"]
        leds = self._nt_paint.pop(key, None)
        cols = self._nt_cols.pop(key, None)
        if leds is None:
            return
        d, z = split_key(key)
        if cols:
            paint = {k: dict(v) for k, v in self._nt["paint"].items()}
            zone = paint.setdefault(key, {})
            for i, h in cols.items():
                if h is None:
                    zone.pop(i, None)
                else:
                    zone[i] = h
            self._nt = dict(self._nt, paint=paint)
            self._send(lambda: self.app.client.notify(paint_set={"key": key, "leds": cols}))
            if self._nt["color"] != "painted" and any(h for h in cols.values()):
                self._nt_set(color="painted")            # painting means: flash in the painted colours
                self.app.toast(_("Notification colours: Painted. Unpainted LEDs use the wallpaper colour."))
        old = self._nt_leds(key, self._count(key))
        if leds != old:
            others = [t for t in self._nt["targets"] if (t["device"], t["zone"]) != (d, z)]
            self._nt_set(targets=others + notifyflash.targets_for(d, z, leds))
        self.cv.queue_draw()
        self._nt_refresh_panel()

    def _nt_drag_point(self, which: str, x: float, y: float):
        wx, wy = self.s2w(x, y)
        path = dict(self._nt["path"] or {})
        path[which] = [round(wx, 1), round(wy, 1)]
        self._nt = dict(self._nt, path=path)
        self._nt_hold = time.time() + HOLD_SEC

    def _nt_drop_point(self):
        if self._nt["path"]:
            self._nt_set(path=self._nt["path"])

    # ------------------------------------------------------------ actions
    def _nt_place_points(self):
        """A and B at the two ends of the chosen LEDs (or of every strip), across their longer side."""
        xs, ys = [], []
        for s in self._strips():
            if s.get("clone"):                          # a copy of a strip drawn elsewhere: not where LEDs are
                continue
            n = self._count(s["zone"])
            chosen = self._nt_leds(s["zone"], n)
            pts = led_points(s, n)
            for i, p in enumerate(pts):
                if i in chosen or not any(self._nt["targets"]):
                    xs.append(p[0])
                    ys.append(p[1])
        if not xs:
            return
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if x1 - x0 >= y1 - y0:
            a, b = [x0, (y0 + y1) / 2], [x1, (y0 + y1) / 2]
        else:
            a, b = [(x0 + x1) / 2, y0], [(x0 + x1) / 2, y1]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1:
            b = [a[0] + 100, a[1]]
        self._nt_set(path={"a": [round(v, 1) for v in a], "b": [round(v, 1) for v in b]}, spatial=True)
        self._nt_refresh_panel()

    def _nt_places(self, effect):
        """Where each chosen LED lies along a flash of this effect, as the daemon works it out."""
        st = self._nt
        ranges, positions, spacing = {}, {}, {}
        for s in self.layout.strips:
            if s.get("clone") or s["zone"] not in self._enabled:
                continue
            n = self._count(s["zone"])
            chosen = sorted(self._nt_leds(s["zone"], n))
            if chosen:
                ranges[s["zone"]] = [(i, i + 1) for i in chosen]
                positions[s["zone"]] = led_points(s, n)
                spacing[s["zone"]] = s["segments"][0]["spacing"]
        # ranges here are single LEDs; along a strip, t still has to run over the whole chosen run
        return notifyflash.led_places(self._nt_runs(ranges), positions, effect,
                                      st["path"] if st["spatial"] else None, spacing)

    def _nt_play(self):
        """The flash on the map, and on the real strips."""
        st = self._nt
        accent = self.status.get("led_color") or (self.status.get("extracted_colors") or ["ffffff"])[0]
        effect, color, painted = notifyflash.style_for(st, "Iridia", False, accent)
        leds = self._nt_places(effect)
        if not leds:
            return
        self._nt_preview = notifyflash.Flash(leds, color, effect, st["duration"], direction=st["direction"],
                                             band=st["band"], repeat=st["repeat"], brightness=st["brightness"],
                                             paint=notifyflash.paint_rgb(st["paint"]) if painted else None)
        if self._nt_job is None:
            self._nt_job = GLib.timeout_add(33, self._nt_tick)
        self._send(lambda: self.app.client.notify(test=True))

    def _nt_gradient(self):
        """Paint the chosen LEDs from the first paint colour to the second: between A and B by where
        they are when that's on, else along each strip."""
        places = self._nt_places("sweep")
        if not places:
            self.app.toast(_("Choose some LEDs first."))
            return
        a, b = self.color_a, self.color_b
        paint = {k: dict(v) for k, v in self._nt["paint"].items()}
        for key, leds in places.items():
            cols = {str(i): _mix(a, b, t) for i, t, _span in leds}
            paint.setdefault(key, {}).update(cols)
            self._send(lambda key=key, cols=cols: self.app.client.notify(paint_set={"key": key, "leds": cols}))
        self._nt = dict(self._nt, paint=paint)
        if self._nt["color"] != "painted":
            self._nt_set(color="painted")
        self._nt_hold = time.time() + HOLD_SEC
        self.cv.queue_draw()
        self._nt_refresh_panel()

    def _nt_clear_colours(self):
        self._nt_set(paint_clear=True)
        self._nt = dict(self._nt, paint={})

    @staticmethod
    def _nt_runs(ranges):
        out = {}
        for key, rs in ranges.items():
            leds = sorted(lo for lo, _hi in rs)
            runs, run = [], None
            for i in leds:
                if run and i == run[1]:
                    run[1] = i + 1
                else:
                    if run:
                        runs.append(tuple(run))
                    run = [i, i + 1]
            if run:
                runs.append(tuple(run))
            out[key] = runs
        return out

    def _nt_tick(self):
        self.cv.queue_draw()
        if self._nt_preview is None or self._nt_preview.done():
            self._nt_preview = None
            self._nt_job = None
            self.cv.queue_draw()
            return False
        return True

    # ------------------------------------------------------------ side panel
    def _nt_build_panel(self, p):
        st = self._nt
        self._ntw = {}
        head = hbox(8, label(_("Notifications"), ("heading",)))
        head.get_first_child().set_hexpand(True)
        head.append(button(_("All settings"), "settings", "text small", self.app.open_notify_settings))
        p.append(head)
        self._ntw["enabled"] = Toggle(st["enabled"], lambda v: self._nt_set(enabled=v))
        p.append(hbox(12, self._ntw["enabled"], label(_("Flash LEDs for notifications"), ("body",))))
        self._ntw["count"] = label("", ("small", "dim"))
        row = hbox(8, self._ntw["count"])
        self._ntw["count"].set_hexpand(True)
        row.append(button(_("Clear"), "close", "text small", lambda: (self._nt_set(targets=[]),
                                                                     self._nt_refresh_panel())))
        p.append(row)
        p.append(divider())
        p.append(label(_("Click or drag on the map"), ("subheading",)))
        self._ntw["brush"] = Group(list(BRUSHES), self._nt_brush, lambda v: setattr(self, "_nt_brush", v))
        p.append(self._ntw["brush"])
        p.append(label(_("Choose LEDs: adds them, or takes them out if you start on a ringed one. Paint: gives them "
                         "the first paint colour. Gradient: from the first colour to the second."), ("tiny", "faint"),
                       wrap=True))
        p.append(QuickColors(self.app.saved_colors, self.app.recent_colors,
                             lambda h: self._set_well("a", h), lambda h: self._set_well("b", h),
                             lambda: self.app.save_color(self.color_a), size=26, per_line=8))
        row = hbox(8, button(_("Gradient"), "gradient", "tonal small", self._nt_gradient),
                   button(_("Clear colours"), "ink_eraser", "text small", self._nt_clear_colours))
        p.append(row)
        self._ntw["color"] = Dropdown(list(COLOUR_NAMES.values()), COLOUR_NAMES[st["color"]],
                                      lambda v: self._nt_set(**self._nt_colour_of(v)))
        p.append(hbox(10, label(_("Colour"), ("body", "dim")), self._ntw["color"]))
        p.append(divider())
        eff = Dropdown(list(EFFECT_NAMES.values()), EFFECT_NAMES[st["effect"]],
                       lambda v: self._nt_set(effect=self._key_of(EFFECT_NAMES, v)))
        p.append(hbox(10, label(_("Effect"), ("body", "dim")), eff))
        self._ntw["effect"] = eff
        dr = Dropdown(list(DIRECTION_NAMES.values()), DIRECTION_NAMES[st["direction"]],
                      lambda v: self._nt_set(direction=self._key_of(DIRECTION_NAMES, v)))
        self._ntw["direction"] = dr
        p.append(hbox(10, label(_("Direction"), ("body", "dim")), dr))
        self._ntw["band"] = MiniSlider(_("Band"), 1, notifyflash.BAND_MAX, st["band"], 1, _("LEDs"),
                                       lambda v: self._nt_set(band=int(v)))
        p.append(self._ntw["band"])
        self._ntw["duration"] = MiniSlider(_("Length"), 0.5, 5, st["duration"], 0.1, "s",
                                           lambda v: self._nt_set(duration=v))
        p.append(self._ntw["duration"])
        self._ntw["repeat"] = Spin(1, 5, st["repeat"], lambda v: self._nt_set(repeat=int(v)))
        p.append(hbox(10, label(_("Plays"), ("body", "dim")), self._ntw["repeat"], label(_("times"), ("body", "dim"))))
        p.append(divider())
        p.append(label(_("A and B"), ("subheading",)))
        self._ntw["spatial"] = Toggle(st["spatial"], lambda v: (self._nt_set(spatial=v) if self._nt["path"]
                                                                else self._nt_place_points()))
        p.append(hbox(12, self._ntw["spatial"], label(_("Run through the room from A to B"), ("body",))))
        p.append(label(_("The flash runs over your LEDs by where they are, across every strip, and only between A "
                         "and B (Ripple: out from A, as far as B). Off: along each strip."), ("tiny", "faint"),
                       wrap=True))
        p.append(button(_("Put A and B at the ends"), "open_with", "tonal small", self._nt_place_points))
        p.append(divider())
        p.append(button(_("Play"), "play_arrow", "filled small", self._nt_play))
        p.append(label(_("Apps, urgent ones and quiet times: All settings."), ("tiny", "faint"), wrap=True))
        self._nt_refresh_panel()

    def _nt_colour_of(self, text: str) -> dict:
        key = self._key_of(COLOUR_NAMES, text)
        return {"color": key, "hex": self.color_a} if key == "custom" else {"color": key}

    @staticmethod
    def _key_of(names: dict, text: str) -> str:
        return next((k for k, v in names.items() if v == text), next(iter(names)))

    def _nt_refresh_panel(self):
        w = getattr(self, "_ntw", None)
        if not w or self.tool != "notify":
            return
        st = self._nt
        leds, strips = self._nt_count()
        w["count"].set_label(ngettext("{n} LED", "{n} LEDs", leds).format(n=leds) + " · " +
                             ngettext("{n} strip", "{n} strips", strips).format(n=strips) if leds else
                             _("No LEDs chosen yet."))
        w["enabled"].set_value(st["enabled"])
        w["spatial"].set_value(st["spatial"])
        w["effect"].set_value(EFFECT_NAMES[st["effect"]])
        w["color"].set_value(COLOUR_NAMES[st["color"]])
        w["direction"].set_value(DIRECTION_NAMES[st["direction"]])
        moving = st["effect"] in notifyflash.MOVING
        w["direction"].set_sensitive(moving and st["effect"] != "ripple")
        w["band"].set_sensitive(moving)
        for k in ("band", "duration", "repeat"):
            w[k].set_quiet(st[k])
