"""Colour picker dialog: saturation/value square or hue wheel, gradient sliders, hex, saved colours.

pick_color(parent, initial, saved, title, on_done, on_change=None, extra=None)
  on_done(hex or None) when closed; on_change(hex) while the colour moves (live LED preview);
  extra = (label, fn(hex) -> hex) shows a third swatch, e.g. what is sent to the strip.
"""

import colorsys
import math
from typing import Callable, List, Optional

import cairo
from gi.repository import Gdk, Gtk

from iridia.i18n import _
from iridia.colors import normalize_hex
from iridia.ui.dialogs import Dialog
from iridia.ui.widgets import (Group, Swatch, Toggle, button, hbox, label, rgb, rounded_rect, themed, vbox)

SQ = 240
_wheel_surface = None


def _wheel() -> cairo.ImageSurface:
    global _wheel_surface
    if _wheel_surface is not None:
        return _wheel_surface
    n = SQ
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, n, n)
    stride = surf.get_stride()
    buf = bytearray(stride * n)
    c = (n - 1) / 2.0
    for y in range(n):
        dy = (y - c) / c
        row = y * stride
        for x in range(n):
            dx = (x - c) / c
            d = math.hypot(dx, dy)
            if d > 1.0:
                continue
            h = (math.atan2(-dy, dx) / (2 * math.pi)) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, d, 1.0)
            a = 255 if d < 0.985 else int(255 * max(0.0, (1.0 - d) / 0.015))
            i = row + x * 4
            buf[i] = int(b * a)          # premultiplied BGRA
            buf[i + 1] = int(g * a)
            buf[i + 2] = int(r * a)
            buf[i + 3] = a
    surf.get_data()[:] = bytes(buf)
    surf.mark_dirty()
    _wheel_surface = surf
    return surf


class GradSlider(Gtk.DrawingArea):
    def __init__(self, on_change: Callable[[float], None], width: int = 200):
        super().__init__()
        themed(self)
        self._cb = on_change
        self.t = 0.0
        self.stops = [(0, 0, 0), (1, 1, 1)]
        self.set_content_width(width)
        self.set_content_height(28)
        self.set_draw_func(self._draw)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", lambda g, x, y: self._set(x))
        g.connect("drag-update", lambda g, ox, oy: self._set(g.get_start_point()[1] + ox))
        self.add_controller(g)

    def _set(self, x):
        w = self.get_width()
        self.t = max(0.0, min(1.0, (x - 10) / max(1, w - 20)))
        self.queue_draw()
        self._cb(self.t)

    def update(self, t, stops):
        self.t, self.stops = max(0.0, min(1.0, t)), stops
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        g = cairo.LinearGradient(10, 0, w - 10, 0)
        n = len(self.stops) - 1
        for i, s in enumerate(self.stops):
            g.add_color_stop_rgb(i / n if n else 0, *s)
        rounded_rect(cr, 10, h / 2 - 7, w - 20, 14, 7)
        cr.set_source(g)
        cr.fill()
        x = 10 + (w - 20) * self.t
        cr.set_source_rgb(*rgb("SURFACE_CONTAINER"))
        rounded_rect(cr, x - 5, 1, 10, h - 2, 4)
        cr.fill()
        cr.set_source_rgb(*rgb("ON_SURFACE"))
        rounded_rect(cr, x - 2, 3, 4, h - 6, 2)
        cr.fill()


class ColorPicker(Dialog):
    def __init__(self, parent, initial: str, saved: Optional[List[str]], title: str,
                 on_done: Callable[[Optional[str]], None], on_change: Optional[Callable[[str], None]] = None,
                 extra=None, recent: Optional[List[str]] = None, on_save: Optional[Callable[[str], None]] = None,
                 exact: Optional[bool] = None, exact_colors=None, on_exact: Optional[Callable[[bool], None]] = None):
        super().__init__(parent, title, width=560, on_close=self._closing)
        self._done_cb = on_done
        self._result = None
        self._on_change = None
        self._extra = extra
        self.exact = bool(exact)
        self._exact_colors = set(exact_colors or [])
        self._on_exact = on_exact
        init = normalize_hex(initial) or "ff8800"
        self._initial = init
        r, g, b = (int(init[i:i + 2], 16) / 255 for i in (0, 2, 4))
        self._h, self._s, self._v = colorsys.rgb_to_hsv(r, g, b)
        self._mode = "swatch"
        self._last_emit = init
        self._updating = False

        head = hbox(8)
        head.append(label(title, ("title",)))
        sp = Gtk.Box(hexpand=True)
        head.append(sp)
        head.append(Group([("swatch", _("Swatch"), "texture"), ("wheel", _("Wheel"), "palette")], "swatch", self._set_mode))
        self.body.append(head)

        main = hbox(22)
        left = vbox(8)
        self._area = Gtk.DrawingArea()
        themed(self._area)
        self._area.set_content_width(SQ)
        self._area.set_content_height(SQ)
        self._area.set_draw_func(self._draw_area)
        self._area.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda g, x, y: self._area_at(x, y))
        drag.connect("drag-update", lambda g, ox, oy: self._area_at(g.get_start_point()[1] + ox,
                                                                     g.get_start_point()[2] + oy))
        self._area.add_controller(drag)
        left.append(self._area)
        self._hue_bar = GradSlider(lambda t: self._set_hsv(h=t), width=SQ)
        left.append(self._hue_bar)
        main.append(left)

        side = vbox(6)
        pv = hbox(0)
        self._old = Gtk.DrawingArea(content_width=64, content_height=44)
        self._new = Gtk.DrawingArea(content_width=64, content_height=44)
        self._old.set_draw_func(lambda a, cr, w, h: self._fill(cr, w, h, self._initial, left=True))
        self._new.set_draw_func(lambda a, cr, w, h: self._fill(cr, w, h, self._hex(), right=not extra))
        pv.append(self._old)
        pv.append(self._new)
        caption = _("current  →  new")
        if extra:
            self._ext = Gtk.DrawingArea(content_width=64, content_height=44, margin_start=10)
            self._ext.set_draw_func(lambda a, cr, w, h: self._fill(cr, w, h, self._extra_hex(), left=True, right=True))
            pv.append(self._ext)
            caption += f"  |  {extra[0].lower()}"
        side.append(pv)
        side.append(label(caption, ("tiny", "faint")))
        self._ext_lbl = label("", ("mono", "dim"))
        side.append(self._ext_lbl)
        hx = hbox(6)
        hx.append(label(_("Hex  #"), ("body", "dim")))
        self._hex_entry = Gtk.Entry(max_length=7, width_chars=8)
        self._hex_entry.connect("changed", self._on_hex)
        hx.append(self._hex_entry)
        side.append(hx)
        self._sliders, self._vals = {}, {}
        for key in ("h", "s", "v", "r", "g", "b"):
            row = hbox(4)
            row.append(label(key.upper(), ("subheading", "dim")))
            sl = GradSlider(lambda t, k=key: self._on_slider(k, t), width=200)
            row.append(sl)
            val = label("0", ("mono", "dim"), xalign=1.0)
            val.set_width_chars(4)
            row.append(val)
            self._sliders[key], self._vals[key] = sl, val
            side.append(row)
        self._exact_sw = None
        if exact is not None:
            self._exact_sw = Toggle(self.exact, self._set_exact)
            row = hbox(10, self._exact_sw, label(_("Exact color"), ("body",)))
            row.set_margin_top(10)
            left.append(row)
            note = label(_("The LEDs show this hex as it is: no Palette or Calibrated correction, only brightness. "
                         "Saved colors with a dot are exact."), ("tiny", "faint"), wrap=True)
            note.set_max_width_chars(34)
            left.append(note)
        main.append(side)
        self.body.append(main)

        self._saved = [c for c in (saved or []) if normalize_hex(c)]
        self._on_save = on_save
        self._saved_box = vbox(4)
        self.body.append(self._saved_box)
        self._render_saved()
        recent = [c for c in (recent or []) if normalize_hex(c)]
        if recent:
            self.body.append(label(_("Recently used"), ("small", "dim")))
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=16, column_spacing=4,
                               halign=Gtk.Align.START)
            flow.set_min_children_per_line(min(16, len(recent)))
            for c in recent[:16]:
                flow.append(Swatch(c, 30, on_click=lambda c=c: self._pick_listed(c), tooltip=f"#{c}"))
            self.body.append(flow)
        btns = [button(_("Cancel"), style="text", cb=self.close), button(_("Select"), style="filled", cb=self._ok)]
        if on_save:
            btns.insert(0, button(_("Save color"), "add", "tonal", self._save_current))
        self.buttons(*btns)
        self.on_enter = self._ok
        self._refresh()
        self._on_change = on_change
        self.present()

    def _render_saved(self):
        c = self._saved_box.get_first_child()
        while c:
            n = c.get_next_sibling()
            self._saved_box.remove(c)
            c = n
        if not self._saved:
            if self._on_save:
                self._saved_box.append(label(_("No saved colors yet. \u201cSave color\u201d keeps the current one here and "
                                             "in every color list."), ("tiny", "faint"), wrap=True))
            return
        self._saved_box.append(label(_("Your saved colors"), ("small", "dim")))
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=16, column_spacing=4,
                           halign=Gtk.Align.START)
        flow.set_min_children_per_line(min(16, len(self._saved)))
        for col in self._saved[:32]:
            flow.append(Swatch(col, 30, on_click=lambda col=col: self._pick_listed(col), tooltip=f"#{col}"))
        self._saved_box.append(flow)

    def _save_current(self):
        h = self._hex()
        if h not in self._saved:
            self._saved.append(h)
            self._render_saved()
        self._on_save(h)

    # ------------------------------------------------------------ state
    def _rgb(self):
        r, g, b = colorsys.hsv_to_rgb(self._h, self._s, self._v)
        return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))

    def _hex(self):
        return "%02x%02x%02x" % self._rgb()

    def _set_exact(self, on):
        self.exact = bool(on)
        if self._on_exact:
            self._on_exact(self.exact)
        if self._extra:
            self._ext_lbl.set_label(f"{self._extra[0]}: #{self._extra_hex()}")
            self._ext.queue_draw()

    def _pick_listed(self, h):
        """A saved or recent colour: it brings its own exact setting along."""
        self._from_hex(h)
        if self._exact_sw is not None:
            want = normalize_hex(h) in self._exact_colors
            if want != self.exact:
                self._exact_sw.set_active(want)
                self._set_exact(want)

    def _extra_hex(self):
        if self.exact:
            return self._hex()
        try:
            return self._extra[1](self._hex()) if self._extra else self._hex()
        except Exception:
            return self._hex()

    def _from_hex(self, h):
        h = normalize_hex(h)
        if not h:
            return
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        self._h, self._s, self._v = colorsys.rgb_to_hsv(r, g, b)
        self._refresh()

    def _set_hsv(self, h=None, s=None, v=None):
        if h is not None:
            self._h = h
        if s is not None:
            self._s = s
        if v is not None:
            self._v = v
        self._refresh()

    def _on_slider(self, key, t):
        if key in "hsv":
            self._set_hsv(**{key: t})
        else:
            r, g, b = self._rgb()
            vals = {"r": r, "g": g, "b": b}
            vals[key] = int(round(t * 255))
            self._h, self._s, self._v = colorsys.rgb_to_hsv(vals["r"] / 255, vals["g"] / 255, vals["b"] / 255)
            self._refresh()

    def _on_hex(self, e):
        if self._updating:
            return
        h = normalize_hex(e.get_text())
        if h:
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
            self._h, self._s, self._v = colorsys.rgb_to_hsv(r, g, b)
            self._refresh(from_entry=True)

    def _set_mode(self, m):
        self._mode = m
        self._hue_bar.set_visible(m == "swatch")
        self._area.queue_draw()

    def _area_at(self, x, y):
        if self._mode == "swatch":
            self._set_hsv(s=max(0.0, min(1.0, x / (SQ - 1))), v=max(0.0, min(1.0, 1 - y / (SQ - 1))))
        else:
            c = (SQ - 1) / 2
            dx, dy = (x - c) / c, (y - c) / c
            self._set_hsv(h=(math.atan2(-dy, dx) / (2 * math.pi)) % 1.0, s=min(1.0, math.hypot(dx, dy)))

    def _refresh(self, from_entry=False):
        hx = self._hex()
        r, g, b = self._rgb()
        H, S, V = self._h, self._s, self._v
        hue_stops = [colorsys.hsv_to_rgb(i / 6, 1, 1) for i in range(7)]
        self._sliders["h"].update(H, hue_stops)
        self._sliders["s"].update(S, [colorsys.hsv_to_rgb(H, 0, V), colorsys.hsv_to_rgb(H, 1, V)])
        self._sliders["v"].update(V, [(0, 0, 0), colorsys.hsv_to_rgb(H, S, 1)])
        self._sliders["r"].update(r / 255, [(0, g / 255, b / 255), (1, g / 255, b / 255)])
        self._sliders["g"].update(g / 255, [(r / 255, 0, b / 255), (r / 255, 1, b / 255)])
        self._sliders["b"].update(b / 255, [(r / 255, g / 255, 0), (r / 255, g / 255, 1)])
        self._hue_bar.update(H, hue_stops)
        for k, v in (("h", round(H * 360)), ("s", round(S * 100)), ("v", round(V * 100)), ("r", r), ("g", g), ("b", b)):
            self._vals[k].set_label(str(v))
        if not from_entry:
            self._updating = True
            self._hex_entry.set_text(hx)
            self._updating = False
        if self._extra:
            self._ext_lbl.set_label(f"{self._extra[0]}: #{self._extra_hex()}")
            self._ext.queue_draw()
        self._new.queue_draw()
        self._area.queue_draw()
        if self._on_change and hx != self._last_emit:
            self._last_emit = hx
            self._on_change(hx)

    # ------------------------------------------------------------ drawing
    def _fill(self, cr, w, h, hx, left=False, right=False):
        rl, rr = (12 if left else 0), (12 if right else 0)
        cr.new_sub_path()
        cr.arc(w - rr, rr, rr, -math.pi / 2, 0) if rr else cr.move_to(w, 0)
        cr.arc(w - rr, h - rr, rr, 0, math.pi / 2) if rr else cr.line_to(w, h)
        cr.arc(rl, h - rl, rl, math.pi / 2, math.pi) if rl else cr.line_to(0, h)
        cr.arc(rl, rl, rl, math.pi, 3 * math.pi / 2) if rl else cr.line_to(0, 0)
        cr.close_path()
        cr.set_source_rgb(*(int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4)))
        cr.fill()

    def _draw_area(self, _a, cr, w, h):
        if self._mode == "swatch":
            rounded_rect(cr, 0, 0, w, h, 20)
            cr.clip()
            cr.set_source_rgb(*colorsys.hsv_to_rgb(self._h, 1, 1))
            cr.paint()
            g = cairo.LinearGradient(0, 0, w, 0)
            g.add_color_stop_rgba(0, 1, 1, 1, 1)
            g.add_color_stop_rgba(1, 1, 1, 1, 0)
            cr.set_source(g)
            cr.paint()
            g2 = cairo.LinearGradient(0, 0, 0, h)
            g2.add_color_stop_rgba(0, 0, 0, 0, 0)
            g2.add_color_stop_rgba(1, 0, 0, 0, 1)
            cr.set_source(g2)
            cr.paint()
            mx, my = self._s * (w - 1), (1 - self._v) * (h - 1)
        else:
            cr.set_source_surface(_wheel(), 0, 0)
            cr.paint()
            if self._v < 1:
                cr.arc(w / 2, h / 2, w / 2 - 0.5, 0, 2 * math.pi)
                cr.set_source_rgba(0, 0, 0, 1 - self._v)
                cr.fill()
            c = (SQ - 1) / 2
            a = self._h * 2 * math.pi
            mx, my = c + math.cos(a) * self._s * c, c - math.sin(a) * self._s * c
        cr.reset_clip()
        cr.arc(mx, my, 9, 0, 2 * math.pi)
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(3)
        cr.stroke()
        cr.arc(mx, my, 10.5, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.set_line_width(1)
        cr.stroke()

    # ------------------------------------------------------------ close
    def _ok(self):
        self._result = self._hex()
        self.close()

    def _closing(self):
        self._done_cb(self._result)


def pick_color(parent, initial, saved, title, on_done, on_change=None, extra=None, recent=None,
               on_save=None, exact=None, exact_colors=None, on_exact=None) -> ColorPicker:
    return ColorPicker(parent, initial, saved, title, on_done, on_change, extra, recent, on_save,
                       exact, exact_colors, on_exact)
