"""The Layout tab (GTK 4): your strips drawn where they are, with live colours.

Arrange: drag a strip to move it; every bend is ringed on the canvas, and the selected strip
gets one round knob per section (behind LED 1, and on the outside of every corner): turn it to
turn that section and everything after it. Right-click a LED to add a
bend there, flip, clone, rename or lock. The paint tools colour single LEDs. "Lock
layout" stops strips from moving so painting and colour stops are safe to drag.
"""

import math
import time
from typing import Dict, List, Optional

from gi.repository import Gdk, GLib, Gtk

from iridia.i18n import _, ngettext  # noqa: F401
from iridia import theme
from iridia.colors import resolve_colors
from iridia.layout import (Layout, fraction_to_stop, led_at_path, path_at_led, path_points, point_along, project,
                           split_key, stop_to_fraction, zone_count)
from iridia.patterns import PatternGenerator
from iridia.ui import fonts, serial
from iridia.ui.widgets import (Dropdown, Group, QuickColors, Spin, Swatch, SwatchPicker, Toggle, button, divider, hbox, icon,
                               label, rgb, set_button_text, themed, vbox)
from iridia.ui.zonecard import PATTERN_KEYS, PATTERN_NAMES

GRID = 20.0
TOOLS = (("arrange", _("Arrange"), "open_with"), ("find", _("Find LEDs: light one LED on the real strip"), "target"),
         ("paint", _("Paint"), "brush"), ("erase", _("Erase (back to the zone's own color)"), "ink_eraser"),
         ("fill", _("Fill"), "format_color_fill"), ("gradient", _("Gradient"), "gradient"))


PAINT_TOOLS = ("paint", "fill", "gradient")


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2[i:i + 2], 16) for i in (0, 2, 4)]
    return "%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


class LayoutTab(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.app = app
        self.layout = Layout()
        self.patterns = PatternGenerator()
        self.status: dict = {}
        self._cfg: Dict[str, dict] = {}
        self._hold: Dict[str, float] = {}
        self._enabled = set()
        self._sel: Optional[str] = None
        self._sel_seg = 0
        self.tool = "arrange"
        self.color_a, self.color_b = "ff8800", "3355ff"
        self._grad_anchor = None
        self._drag = None
        self._save_job = None
        self._handles = []
        self._pointer = (0.0, 0.0)
        self._visible = False
        self._dirty = True
        self._snap = True
        self._build()

    # ================================================================ UI
    def _build(self):
        self._hint = label("", ("small", "faint"), wrap=True)
        self.append(self._hint)
        main = hbox(12, vexpand=True)
        overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        frame = Gtk.Box(hexpand=True, vexpand=True)
        frame.add_css_class("canvas-frame")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.cv = Gtk.DrawingArea(hexpand=True, vexpand=True)
        themed(self.cv)
        self.cv.set_draw_func(self._draw)
        frame.append(self.cv)
        overlay.set_child(frame)

        bar = hbox(4)
        bar.add_css_class("floating-toolbar")
        bar.set_halign(Gtk.Align.CENTER)
        bar.set_valign(Gtk.Align.END)
        bar.set_margin_bottom(16)
        self._tools = Group([(k, "", ico) for k, _t, ico in TOOLS], "arrange", self._set_tool)
        for k, t, _ico in TOOLS:
            self._tools.buttons[k].set_tooltip_text(t)
        bar.append(self._tools)
        self._wells = {}
        for which in ("a", "b"):
            sw = Swatch(self.color_a if which == "a" else self.color_b, 34,
                        on_click=lambda w=which: self._pick_well(w), tooltip=_("Paint color"))
            sw.set_margin_start(4)
            self._wells[which] = sw
            bar.append(sw)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4))
        bar.append(button(icon_name="zoom_out", style="text small", cb=lambda: self._zoom_by(0.8), tooltip=_("Zoom out")))
        bar.append(button(icon_name="zoom_in", style="text small", cb=lambda: self._zoom_by(1.25), tooltip=_("Zoom in")))
        bar.append(button(icon_name="fit_screen", style="text small", cb=self._fit, tooltip=_("Show everything")))
        self._lock_btn = button(icon_name="lock_open", style="tonal small", cb=self._toggle_lock,
                                tooltip=_("Lock layout"))
        bar.append(self._lock_btn)
        overlay.add_overlay(bar)
        main.append(overlay)

        side = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, hexpand=False)
        side.set_size_request(310, -1)
        side.set_propagate_natural_width(False)
        side.add_css_class("panel")
        self._panel = vbox(8)
        for m in ("top", "bottom", "start", "end"):
            getattr(self._panel, f"set_margin_{m}")(16)
        side.set_child(self._panel)
        self._side = side
        main.append(side)
        self.append(main)

        drag = Gtk.GestureDrag(button=1)
        drag.connect("drag-begin", self._press)
        drag.connect("drag-update", self._motion)
        drag.connect("drag-end", self._release)
        self.cv.add_controller(drag)
        pan = Gtk.GestureDrag(button=2)
        pan.connect("drag-begin", lambda g, x, y: self._pan_start(x, y))
        pan.connect("drag-update", lambda g, ox, oy: self._pan_move(ox, oy))
        pan.connect("drag-end", lambda *_a: self._schedule_save())
        self.cv.add_controller(pan)
        ctx = Gtk.GestureClick(button=3)
        ctx.connect("pressed", lambda g, n, x, y: self._context(x, y))
        self.cv.add_controller(ctx)
        mot = Gtk.EventControllerMotion()
        mot.connect("motion", lambda c, x, y: setattr(self, "_pointer", (x, y)))
        self.cv.add_controller(mot)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._scroll)
        self.cv.add_controller(scroll)
        self._apply_lock_ui()
        self._show_hint()
        self._build_panel()

    # ============================================================ status
    def set_visible_tab(self, on: bool):
        self._visible = on
        if not on:
            self._stop_find()
        if on and self._dirty:
            self._dirty = False
            self.cv.queue_draw()
            self._build_panel()

    def update_status(self, status: dict):
        self.status = status
        devs = status.get("device_configs", {}) or {}
        now = time.time()
        keys = []
        for d, dc in devs.items():
            zones = dc.get("zones")
            items = zones.items() if zones else [("", dc)]
            for z, zc in items:
                k = f"{d}|{z}"
                if now >= self._hold.get(k, 0):
                    self._cfg[k] = zc
                if dc.get("enabled", True) and zc.get("enabled", True):
                    keys.append(k)
        self._enabled = set(keys)
        if self.layout.ensure_zones(keys):
            self._schedule_save()
        sig = repr((sorted(self._cfg.items()), status.get("extracted_colors"), status.get("identify"),
                    status.get("probe"), status.get("lights_off"), status.get("asleep")))
        if sig != getattr(self, "_sig", None):
            self._sig = sig
            if self._visible and self._drag is None:
                self.cv.queue_draw()
                self._refresh_panel_values()
            else:
                self._dirty = True

    def zone_colors(self, key: str, overrides: bool = True) -> List[str]:
        cfg = self._cfg.get(key) or {}
        n = int(cfg.get("led_count", 20))
        st = self.status if overrides else {"extracted_colors": self.status.get("extracted_colors")}
        d, z = split_key(key)
        if st.get("lights_off") or st.get("asleep"):
            return ["000000"] * n
        ident, probe = st.get("identify"), st.get("probe")
        if ident:
            return ["ffffff" if (ident["device"], ident.get("zone") or "") == (d, z) else "000000"] * n
        if probe:
            out = ["000000"] * n
            if (probe["device"], probe.get("zone") or "") == (d, z) and probe["index"] < n:
                out[probe["index"]] = "ffffff"
            return out
        extracted = list(st.get("extracted_colors") or ["642107"])
        colors = resolve_colors(cfg.get("pattern_colors", [0]), extracted) or [extracted[0]]
        return self.patterns.generate(cfg.get("pattern", "solid"), colors, n, params=cfg.get("pattern_params") or {})

    def _name(self, key: str) -> str:
        d, z = split_key(key)
        own = (self._cfg.get(key) or {}).get("display_name")
        if own:
            return own
        if z and any(k != key and split_key(k)[1] == z and not (self._cfg.get(k) or {}).get("display_name")
                     for k in self._cfg):
            return f"{z} ({d})"           # "Channel 1" on two controllers
        return z or d

    def _count(self, key: str) -> int:
        cfg = self._cfg.get(key)
        if cfg is not None:
            return int(cfg.get("led_count", 20))
        return zone_count(self.status.get("device_configs", {}) or {}, key) or 0

    # =========================================================== drawing
    def w2s(self, x, y):
        z = self.layout.view["zoom"]
        px, py = self.layout.view["pan"]
        return x * z + px, y * z + py

    def s2w(self, x, y):
        z = self.layout.view["zoom"]
        px, py = self.layout.view["pan"]
        return (x - px) / z, (y - py) / z

    def _strips(self):
        return [s for s in self.layout.strips if s["zone"] in self._enabled and not s.get("hidden")]

    def _strip_locked(self, s):
        return self.layout.locked or s["locked"]

    def _draw(self, _a, cr, w, h):
        self._handles = []
        self._label_rects = []
        cr.set_source_rgb(*rgb("SURFACE_CONTAINER_LOW"))
        cr.paint()
        z = self.layout.view["zoom"]
        step = GRID * z
        while step < 14:
            step *= 5
        px, py = self.layout.view["pan"]
        cr.set_source_rgb(*rgb("GRID"))
        cr.set_line_width(1)
        x = px % step
        while x < w:
            cr.move_to(int(x) + 0.5, 0)
            cr.line_to(int(x) + 0.5, h)
            x += step
        y = py % step
        while y < h:
            cr.move_to(0, int(y) + 0.5)
            cr.line_to(w, int(y) + 0.5)
            y += step
        cr.stroke()
        strips = self._strips()
        for s in strips:
            if s["id"] != self._sel:
                self._draw_strip(cr, s)
        sel = self.layout.get(self._sel) if self._sel else None
        if sel and sel in strips:
            self._draw_strip(cr, sel)
        if not strips:
            self._text(cr, w / 2, h / 2, _("No enabled zones yet. They show up here once the daemon reports them."),
                       "ON_SURFACE_VARIANT", 14, center=True)

    def _text(self, cr, x, y, t, role, size, center=False, bold=False):
        cr.select_font_face(fonts.TEXT_FAMILY, 0, 1 if bold else 0)
        cr.set_font_size(size)
        cr.set_source_rgb(*rgb(role))
        ext = cr.text_extents(t)
        cr.move_to(x - (ext.width / 2 + ext.x_bearing if center else 0), y)
        cr.show_text(t)

    def _draw_strip(self, cr, s):
        key = s["zone"]
        n = self._count(key)
        if n <= 0:
            return
        pts = path_points(s, n)
        spts = [self.w2s(x, y) for x, y in pts]
        colors = self.zone_colors(key)
        z = self.layout.view["zoom"]
        sel = s["id"] == self._sel
        tape_w = max(6.0, 12 * z)
        cr.set_line_cap(1)
        cr.set_line_join(1)
        if len(spts) > 1:
            if sel:
                cr.set_source_rgb(*rgb("PRIMARY"))
                cr.set_line_width(tape_w + 5)
                self._poly(cr, spts)
                cr.stroke()
            cr.set_source_rgb(*rgb("SURFACE_CONTAINER_HIGHEST"))
            cr.set_line_width(tape_w)
            self._poly(cr, spts)
            cr.stroke()
        r = max(2.0, min(s["segments"][0]["spacing"] * 0.34, 6.0) * z)
        for k, (x, y) in enumerate(spts):
            i = led_at_path(s, n, k)
            col = colors[i] if i < len(colors) else "000000"
            cr.set_source_rgb(*theme.hex_rgb(col))
            cr.arc(x, y, r, 0, 2 * math.pi)
            cr.fill()
        # Bend points: always visible, on every strip, in every tool.
        for bi, seg in enumerate(s["segments"][1:], 1):
            c = seg["start"] - 1
            if 0 <= c < len(spts) - 1:
                bx, by = spts[c]
                cr.set_source_rgb(*rgb("PRIMARY" if sel else "OUTLINE"))
                cr.set_line_width(2.2 if sel else 1.6)
                cr.arc(bx, by, r + 4, 0, 2 * math.pi)
                cr.stroke()
                if sel and not (self.tool == "arrange" and not self._strip_locked(s)):
                    ox, oy = self._knob_pos(s, bi, spts, 22)
                    self._text(cr, ox, oy + 4, f"B{bi}", "PRIMARY", 11, center=True, bold=True)
        found = getattr(self, "_found", None)
        if found and found[0] == s["id"] and found[1] < len(spts):
            x, y = spts[found[1]]
            cr.set_source_rgb(*rgb("PRIMARY"))
            cr.set_line_width(3)
            cr.arc(x, y, r + 7, 0, 2 * math.pi)
            cr.stroke()
            self._text(cr, x, y + r + 22, _('LED {n}').format(n=found[2] + 1), "PRIMARY", 13, center=True, bold=True)
        fx, fy = spts[path_at_led(s, n, 0)]
        if sel or z >= 0.35:            # far out, the end numbers only clutter
            self._text(cr, fx, fy - r - 6, "1", "ON_SURFACE_VARIANT", 11, center=True)
        if n > 1 and (sel or z >= 0.35):
            lx, ly = spts[path_at_led(s, n, n - 1)]
            self._text(cr, lx, ly - r - 6, str(n), "OUTLINE", 11, center=True)
        name = self._name(key)
        if len(name) > 36 and not sel:
            name = name[:34].rstrip() + "…"
        text = f"{name}  ·  " + ngettext("{n} LED", "{n} LEDs", n).format(n=n) + \
            (f"  ·  {_('clone')}" if s["clone"] else "") + (f"  ·  {_('locked')}" if s["locked"] else "")
        x0, y0 = spts[0]
        a = math.radians(s["segments"][0]["angle"] - 90)
        tx, ty = x0 + math.cos(a) * (tape_w + 12), y0 + math.sin(a) * (tape_w + 12)
        cr.select_font_face(fonts.TEXT_FAMILY, 0, 1 if sel else 0)
        cr.set_font_size(12.5)
        ext = cr.text_extents(text)
        rect = (tx - 2, ty - 14, tx + ext.x_advance + 2, ty + 4)
        # Strips close together (zoomed far out) would print their names over each other:
        # skip a name that would overlap one already drawn; the selected strip always gets its name.
        clash = any(rect[0] < r[2] and r[0] < rect[2] and rect[1] < r[3] and r[1] < rect[3]
                    for r in self._label_rects)
        if sel or not clash:
            self._label_rects.append(rect)
            self._text(cr, tx, ty, text, "ON_SURFACE" if sel else "ON_SURFACE_VARIANT", 12.5, bold=sel)
        if sel:
            self._draw_handles(cr, s, n, spts)

    @staticmethod
    def _poly(cr, pts):
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)

    def _draw_handles(self, cr, s, n, spts):
        segs = s["segments"]
        if self.tool == "arrange" and self._strip_locked(s):
            self._text(cr, 16, 26, _("This strip is locked. Unlock it (side panel or the lock button) to move or "
                       "bend it."), "ON_SURFACE_VARIANT", 12)
        elif self.tool == "arrange":
            # One turn knob per section, on the outside of its corner (behind LED 1 for the first
            # section). Turning it turns the section and everything after it around the corner LED.
            for i, seg in enumerate(segs):
                if seg["start"] >= n or (i > 0 and seg["start"] < 1):
                    continue
                px, py = self._pivot(spts, seg, i)
                active = bool(self._drag and self._drag.get("kind") == "turn" and self._drag.get("i") == i
                              and self._drag.get("sid") == s["id"])
                kx, ky = self._knob_pos(s, i, spts, 34, self._drag.get("offset") if active else None)
                on = active or i == self._sel_seg
                cr.save()
                cr.set_dash([3, 3])
                cr.set_source_rgb(*rgb("OUTLINE"))
                cr.set_line_width(1.5)
                cr.move_to(px, py)
                cr.line_to(kx, ky)
                cr.stroke()
                cr.restore()
                cr.arc(kx, ky, 12, 0, 2 * math.pi)
                cr.set_source_rgb(*rgb("PRIMARY" if on else "SURFACE_CONTAINER_HIGHEST"))
                cr.fill_preserve()
                cr.set_source_rgb(*rgb("PRIMARY"))
                cr.set_line_width(2)
                cr.stroke()
                # a little turning arrow
                fg = rgb("ON_PRIMARY" if on else "PRIMARY")
                cr.set_source_rgb(*fg)
                cr.set_line_width(1.8)
                cr.arc(kx, ky, 5.5, math.radians(-60), math.radians(210))
                cr.stroke()
                ax, ay = kx + 5.5 * math.cos(math.radians(-60)), ky + 5.5 * math.sin(math.radians(-60))
                cr.move_to(ax + 3.2, ay - 1.2)
                cr.line_to(ax, ay)
                cr.line_to(ax + 0.6, ay + 3.4)
                cr.stroke()
                self._handles.append(("turn", s["id"], i, kx, ky, 15))
                if i > 0:
                    self._text(cr, kx, ky - 17, f"B{i}", "PRIMARY", 11, center=True, bold=True)
                if active:
                    self._text(cr, kx + 17, ky + 4, f"{int(round(seg['angle'])) % 360}°", "PRIMARY", 12,
                               bold=True)
        cfg = self._cfg.get(s["zone"]) or {}
        pat = PatternGenerator.normalize(cfg.get("pattern", "solid"))
        stops = self._stops(cfg)
        if stops and n > 1:
            params = cfg.get("pattern_params") or {}
            for k, v in enumerate(stops):
                for j, f in enumerate(stop_to_fraction(v, pat, bool(params.get("reverse")), bool(params.get("mirror")))):
                    led = f * (n - 1)
                    pk = (n - 1 - led) if s["flip"] else led
                    x, y = point_along(spts, pk)
                    cr.move_to(x, y - 11)
                    cr.line_to(x + 9, y)
                    cr.line_to(x, y + 11)
                    cr.line_to(x - 9, y)
                    cr.close_path()
                    cr.set_source_rgb(*rgb("PRIMARY" if j == 0 else "OUTLINE_VARIANT"))
                    cr.fill_preserve()
                    cr.set_source_rgb(*rgb("SURFACE_DIM"))
                    cr.set_line_width(1.5)
                    cr.stroke()
                    if j == 0:
                        self._handles.append(("stop", s["id"], k, x, y, 11))

    @staticmethod
    def _pivot(spts, seg, i):
        """The point a section turns around: LED 1 for the first section, the corner LED for bends."""
        return spts[0 if i == 0 else max(0, min(len(spts) - 1, seg["start"] - 1))]

    @staticmethod
    def _knob_offset(segs, i):
        """Where a section's knob sits, as degrees relative to the section's direction.

        First section: straight behind LED 1. Bends: on the outside of the corner, so it never
        sits on the strip itself (a straight 'bend' gets it beside the strip)."""
        a1 = math.radians(segs[i]["angle"])
        if i == 0:
            return 180.0
        a0 = math.radians(segs[i - 1]["angle"])
        sx, sy = -math.cos(a0) + math.cos(a1), -math.sin(a0) + math.sin(a1)
        if math.hypot(sx, sy) < 0.35:
            return 90.0
        return (math.degrees(math.atan2(-sy, -sx)) - segs[i]["angle"]) % 360

    def _knob_pos(self, s, i, spts, dist, offset=None):
        segs = s["segments"]
        px, py = self._pivot(spts, segs[i], i)
        off = self._knob_offset(segs, i) if offset is None else offset
        a = math.radians(segs[i]["angle"] + off)
        return px + math.cos(a) * dist, py + math.sin(a) * dist

    def _stops(self, cfg) -> List[float]:
        pat = PatternGenerator.normalize(cfg.get("pattern", "solid"))
        if pat not in PatternGenerator.EDITABLE:
            return []
        extracted = list(self.status.get("extracted_colors") or ["642107"])
        ncol = len(resolve_colors(cfg.get("pattern_colors", [0]), extracted) or [1])
        want = PatternGenerator.handle_count(pat, ncol)
        if want <= 0:
            return []
        cur = (cfg.get("pattern_params") or {}).get("stops")
        if isinstance(cur, list) and len(cur) == want:
            return list(cur)
        return PatternGenerator.default_stops(pat, ncol)

    # ========================================================== hit tests
    def _hit_strip(self, sx, sy):
        best = None
        for s in reversed(self._strips()):
            n = self._count(s["zone"])
            if n <= 0:
                continue
            spts = [self.w2s(x, y) for x, y in path_points(s, n)]
            f, d = project(spts, sx, sy)
            tol = max(10, 8 * self.layout.view["zoom"])
            if d <= tol and (best is None or d < best[2]):
                best = (s, f, d, n)
        return best

    def _hit_handle(self, sx, sy):
        for kind, sid, i, x, y, r in reversed(self._handles):
            if math.hypot(sx - x, sy - y) <= r:
                return kind, sid, i
        return None

    # ========================================================== mouse
    def _press(self, g, x, y):
        self.app.note_activity()
        self._start = (x, y)
        h = self._hit_handle(x, y)
        if h:
            kind, sid, idx = h
            self._sel = sid
            self._drag = {"kind": kind, "sid": sid, "i": idx}
            if kind == "turn":
                self._sel_seg = idx
                st = self.layout.get(sid)
                if st is not None and 0 <= idx < len(st["segments"]):
                    self._drag["offset"] = self._knob_offset(st["segments"], idx)
            self._build_panel()
            return
        hit = self._hit_strip(x, y)
        if hit is None:
            if self.tool == "gradient":
                self._grad_anchor = None
            self._drag = {"kind": "pan", "pan": list(self.layout.view["pan"])}
            if self._sel is not None:
                self._sel = None
                self._build_panel()
            self.cv.queue_draw()
            return
        s, f, _d, n = hit
        k = int(round(f))
        changed = s["id"] != self._sel
        self._sel = s["id"]
        self._sel_seg = self.layout.segment_index(s, k)
        if self.tool == "arrange":
            if not self._strip_locked(s):
                wx, wy = self.s2w(x, y)
                self._drag = {"kind": "move", "sid": s["id"], "off": (s["x"] - wx, s["y"] - wy)}
            else:
                self._drag = None
        elif self.tool == "find":
            self._drag = {"kind": "find", "sid": s["id"]}
            self._find_at(s, n, k)
        else:
            self._drag = {"kind": "paint", "sid": s["id"], "last": None}
            self._paint_at(s, n, k, start=True)
        if changed:
            self._build_panel()
        self.cv.queue_draw()

    def _motion(self, g, ox, oy):
        dr = self._drag
        if not dr:
            return
        x, y = self._start[0] + ox, self._start[1] + oy
        kind = dr["kind"]
        if kind == "pan":
            self.layout.view["pan"] = [dr["pan"][0] + ox, dr["pan"][1] + oy]
            self.cv.queue_draw()
            return
        s = self.layout.get(dr.get("sid", ""))
        if s is None:
            return
        n = self._count(s["zone"])
        state = g.get_current_event_state()
        if kind == "move":
            wx, wy = self.s2w(x, y)
            nx, ny = wx + dr["off"][0], wy + dr["off"][1]
            if self._snap:
                nx, ny = round(nx / (GRID / 2)) * (GRID / 2), round(ny / (GRID / 2)) * (GRID / 2)
            s["x"], s["y"] = nx, ny
        elif kind == "turn":
            i = dr["i"]
            if i >= len(s["segments"]) or n <= 0:
                return
            seg = s["segments"][i]
            px, py = self._pivot(path_points(s, n), seg, i)
            wx, wy = self.s2w(x, y)
            if math.hypot(wx - px, wy - py) < 4:
                return
            ang = math.degrees(math.atan2(wy - py, wx - px)) - dr.get("offset", 90.0)
            if self._snap and not (state & Gdk.ModifierType.SHIFT_MASK):
                ang = round(ang / 15) * 15
            self.layout.rotate_from(s, i, ang - seg["angle"])
        elif kind == "stop":
            cfg = self._cfg.get(s["zone"]) or {}
            pts = [self.w2s(px_, py_) for px_, py_ in path_points(s, n)]
            f, _u = project(pts, x, y)
            led = (n - 1 - f) if s["flip"] else f
            params = dict(cfg.get("pattern_params") or {})
            pat = PatternGenerator.normalize(cfg.get("pattern", "solid"))
            v = fraction_to_stop(led / max(1, n - 1), pat, bool(params.get("reverse")), bool(params.get("mirror")))
            stops = self._stops(cfg)
            k = dr["i"]
            lo = stops[k - 1] if k > 0 else 0.0
            hi = stops[k + 1] if k + 1 < len(stops) else 1.0
            stops[k] = round(max(lo, min(hi, v)), 4)
            params["stops"] = stops
            self._set_local(s["zone"], pattern_params=params)
            dr["stops"] = stops
        elif kind == "find":
            f, d = project([self.w2s(a, b) for a, b in path_points(s, n)], x, y)
            if d < 40:
                self._find_at(s, n, int(round(f)))
        elif kind == "paint":
            f, d = project([self.w2s(a, b) for a, b in path_points(s, n)], x, y)
            if self.tool in ("paint", "erase") and d < 40:
                self._paint_at(s, n, int(round(f)))
        self.cv.queue_draw()

    def _release(self, g, ox, oy):
        dr, self._drag = self._drag, None
        if not dr:
            return
        if dr["kind"] in ("move", "turn", "pan"):
            self._schedule_save()
            self._refresh_panel_values()
        elif dr["kind"] == "stop" and dr.get("stops"):
            d, z = split_key(self.layout.get(dr["sid"])["zone"])
            self._send(self.app.client.set_zone_pattern_params, d, z, {"stops": dr["stops"]})
        elif dr["kind"] == "paint":
            self._commit_paint(self.layout.get(dr["sid"]))

    def _pan_start(self, x, y):
        self._pan0 = list(self.layout.view["pan"])

    def _pan_move(self, ox, oy):
        self.layout.view["pan"] = [self._pan0[0] + ox, self._pan0[1] + oy]
        self.cv.queue_draw()

    def _scroll(self, c, dx, dy):
        self._zoom_at(*self._pointer, 1 / 1.12 if dy > 0 else 1.12)
        return True

    def _zoom_at(self, sx, sy, factor):
        v = self.layout.view
        z1 = max(0.04, min(6.0, v["zoom"] * factor))
        wx, wy = self.s2w(sx, sy)
        v["zoom"] = z1
        v["pan"] = [sx - wx * z1, sy - wy * z1]
        self.cv.queue_draw()
        self._schedule_save()

    def _zoom_by(self, factor):
        self._zoom_at(self.cv.get_width() / 2, self.cv.get_height() / 2, factor)

    def _fit(self):
        pts = []
        for s in self._strips():
            pts += path_points(s, self._count(s["zone"]))
        if not pts:
            return
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(1, self.cv.get_width() - 80), max(1, self.cv.get_height() - 140)
        bw, bh = max(20, max(xs) - min(xs)), max(20, max(ys) - min(ys))
        z = max(0.04, min(6.0, min(w / bw, h / bh)))
        self.layout.view = {"zoom": z, "pan": [40 - min(xs) * z + (w - bw * z) / 2,
                                               50 - min(ys) * z + (h - bh * z) / 2]}
        self.cv.queue_draw()
        self._schedule_save()

    # ========================================================== painting
    def _set_local(self, key, **fields):
        cfg = dict(self._cfg.get(key) or {})
        cfg.update(fields)
        self._cfg[key] = cfg
        self._hold[key] = time.time() + 3.0

    def _paint_at(self, s, n, k, start=False):
        key = s["zone"]
        cfg = self._cfg.get(key) or {}
        i = led_at_path(s, n, max(0, min(n - 1, k)))
        d, z = split_key(key)
        if PatternGenerator.normalize(cfg.get("pattern", "solid")) != "paint":
            current = self.zone_colors(key, overrides=False)
            params = dict(cfg.get("pattern_params") or {})
            params.update(paint=current, reverse=False, mirror=False)
            self._set_local(key, pattern="paint", pattern_params=params)
            self._send(self.app.client.set_zone_pattern, d, z, "paint")
            self._send(self.app.client.set_zone_pattern_params, d, z,
                       {"paint": current, "reverse": False, "mirror": False})
            cfg = self._cfg[key]
            GLib.idle_add(lambda: (self._build_panel(), False)[1])
        params = dict(cfg.get("pattern_params") or {})
        paint = (list(params.get("paint") or []) + [None] * n)[:n]
        tool = self.tool
        if tool == "fill":
            paint = [self.color_a] * n
        elif tool == "gradient":
            if self._grad_anchor is None or self._grad_anchor[0] != s["id"]:
                self._grad_anchor = (s["id"], i)
                paint[i] = self.color_a
                self._hint.set_label(_("Gradient: now click the LED where it should end."))
            else:
                a, b = sorted((self._grad_anchor[1], i))
                ca, cb = ((self.color_a, self.color_b) if self._grad_anchor[1] <= i else (self.color_b, self.color_a))
                for j in range(a, b + 1):
                    paint[j] = _mix(ca, cb, (j - a) / (b - a) if b > a else 0.0)
                self._grad_anchor = None
                self._show_hint()
        else:
            val = self.color_a if tool == "paint" else None
            last = self._drag.get("last") if (self._drag and not start) else None
            lo, hi = (min(last, i), max(last, i)) if last is not None else (i, i)
            for j in range(lo, hi + 1):
                paint[j] = val
            if self._drag:
                self._drag["last"] = i
        params["paint"] = paint
        self._set_local(key, pattern_params=params)
        if tool in ("fill", "gradient"):
            self._commit_paint(s)

    def _commit_paint(self, s):
        if s is None:
            return
        paint = ((self._cfg.get(s["zone"]) or {}).get("pattern_params") or {}).get("paint")
        if paint is None:
            return
        d, z = split_key(s["zone"])
        self._send(self.app.client.set_zone_pattern_params, d, z, {"paint": paint})

    def _send(self, fn, *args):
        serial.send(fn, *args)

    def _set_well(self, which, h):
        if which == "a":
            self.color_a = h
        else:
            self.color_b = h
        self._wells[which].set_state(hex6=h)

    def _pick_well(self, which):
        cur = self.color_a if which == "a" else self.color_b

        def done(h):
            if h:
                self._set_well(which, h)
        self.app.pick_color(cur, _("Paint color"), done)

    # ========================================================== tools / lock
    # ========================================================== find LEDs
    def _find_at(self, s, n, k):
        """Light only this LED on the real strip (everything else goes dark) so you can see where it is."""
        k = max(0, min(n - 1, k))
        i = led_at_path(s, n, k)
        found = (s["id"], k, i)
        if found == getattr(self, "_found", None):
            return
        self._found = found
        d, z = split_key(s["zone"])
        self._send(self.app.client.led_probe, d, z, i)
        self._hint.set_label(_('LED {led} of {n} on {strip} is lit on your strip; the rest are dark. Click or drag along the strip to move it. Right-click to add a bend there. Pick another tool to go back to normal.').format(led=i + 1, n=n, strip=self._name(s['zone'])))
        self.cv.queue_draw()

    def _stop_find(self):
        if getattr(self, "_found", None):
            self._found = None
            self._send(self.app.client.led_probe_off)
            self.cv.queue_draw()

    def _set_tool(self, tool):
        if tool != "find":
            self._stop_find()
        was = self.tool in PAINT_TOOLS
        self.tool = tool
        if was != (tool in PAINT_TOOLS):
            self._build_panel()
        self._grad_anchor = None
        self.cv.set_cursor(Gdk.Cursor.new_from_name("move" if tool == "arrange" else "crosshair"))
        self._show_hint()
        self.cv.queue_draw()

    def _show_hint(self):
        if self.tool == "arrange":
            t = (_("Layout locked: click a strip to select it, drag the diamonds to move color stops.")
                 if self.layout.locked else
                 _("Drag a strip to move it. Select it, then turn a section with its round knob: behind LED 1 for "
                   "the whole strip, outside each corner for a bend (it snaps to 15°, "
                   "hold Shift for free angles). Right-click a LED to add a bend there. Scroll to zoom, drag the "
                   "background to pan."))
        elif self.tool == "find":
            t = _("Find LEDs: click a LED (or drag along a strip) and only that LED lights up on your real strip, "
                  "so you can see where corners and bends are. Right-click it to add a bend there.")
        elif self.tool == "gradient":
            t = _("Gradient: click the first LED, then the last one. Uses both colors.")
        elif self.tool == "fill":
            t = _("Fill: click a strip to give every LED of it the first color.")
        elif self.tool == "erase":
            t = _("Erase: click or drag over LEDs to give them back the zone's own color (the one set on the zone "
                  "or on Everything).")
        else:
            t = _("Paint: click or drag over LEDs. Painting switches that zone to the Painted pattern.")
        self._hint.set_label(t)

    def _toggle_lock(self):
        self.layout.locked = not self.layout.locked
        self._apply_lock_ui()
        self._schedule_save()
        self.cv.queue_draw()

    def _apply_lock_ui(self):
        locked = self.layout.locked
        self._lock_btn.set_child(icon("lock" if locked else "lock_open", fill=locked))
        self._lock_btn.set_tooltip_text(_("Layout locked: click to unlock") if locked else _("Lock layout"))
        (self._lock_btn.add_css_class if locked else self._lock_btn.remove_css_class)("toggled")
        self._show_hint()

    # ========================================================== context menu
    def _context(self, x, y):
        hit = self._hit_strip(x, y)
        if hit is None:
            return
        s, f, _d, n = hit
        k = int(round(f))
        self._sel = s["id"]
        self._sel_seg = self.layout.segment_index(s, k)
        self._build_panel()
        self.cv.queue_draw()
        pop = Gtk.Popover(has_arrow=False)
        pop.set_parent(self.cv)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        box = vbox(0)
        locked = self._strip_locked(s)
        led = led_at_path(s, n, k) + 1
        box.append(label(_('LED {led} of {n}').format(led=led, n=n), ("small", "faint")))
        segi = next((i for i, g in enumerate(s["segments"]) if i > 0 and abs(g["start"] - k) <= 1), None)

        def item(text, ico, cb, enabled=True):
            b = button(text, ico, "text small", lambda: (pop.popdown(), cb()))
            b.set_sensitive(enabled)
            b.set_halign(Gtk.Align.FILL)
            b.get_child().set_halign(Gtk.Align.START)
            box.append(b)
        item(_("Add a bend here"), "polyline", lambda: self._do(self.layout.add_bend, s, k), not locked)
        item(_("Remove this bend"), "remove", lambda: self._do(self.layout.remove_bend, s, segi),
             bool(segi) and not locked)
        item(_("Straighten"), "linear_scale", lambda: self._do(self.layout.reset_shape, s), not locked)
        item(_("Flip LED order") + ("  ✓" if s["flip"] else ""), "swap_horiz", lambda: self._flip(s), not locked)
        item(_("Rename\u2026"), "edit", lambda: self._rename(s["zone"]))
        item(_("Clone this strip"), "content_copy", lambda: self._clone(s))
        item(_("Hide this strip"), "visibility_off", lambda: self._set_hidden(s, True))
        if s["clone"]:
            item(_("Delete this clone"), "delete", lambda: self._delete(s))
        item(_("Unlock this strip") if s["locked"] else _("Lock this strip"), "lock_open" if s["locked"] else "lock",
             lambda: self._lock_strip(s))
        item(_("Identify (light only this zone)"), "flare", lambda: self._identify(s))
        pop.set_child(box)
        pop.connect("closed", lambda p: GLib.idle_add(lambda: (p.unparent(), False)[1]))
        pop.popup()

    def _do(self, fn, *args):
        fn(*args)
        self._schedule_save()
        self.cv.queue_draw()
        self._build_panel()

    def _set_hidden(self, s, hidden):
        s["hidden"] = bool(hidden)
        if hidden and self._sel == s["id"]:
            self._sel = None
        self._schedule_save()
        self.cv.queue_draw()
        self._build_panel()
        if hidden:
            self.app.toast(_('{strip} is hidden. Show it again from the strip list.').format(strip=self._name(s['zone'])),
                           _("Undo"), lambda: self._set_hidden(s, False))

    def _select(self, s):
        if s.get("hidden"):
            s["hidden"] = False
            self._schedule_save()
        self._sel = s["id"]
        self._sel_seg = 0
        self._build_panel()
        self.cv.queue_draw()

    def _flip(self, s):
        s["flip"] = not s["flip"]
        self._do(lambda: None)

    def _clone(self, s):
        c = self.layout.clone(s["id"])
        if c:
            self._sel = c["id"]
        self._do(lambda: None)

    def _delete(self, s):
        self.layout.remove(s["id"])
        self._sel = None
        self._do(lambda: None)

    def _lock_strip(self, s):
        s["locked"] = not s["locked"]
        self._do(lambda: None)

    def _identify(self, s):
        d, z = split_key(s["zone"])
        self._send(self.app.client.identify, d, z, 30)

    # ========================================================== side panel
    def _clear_panel(self):
        c = self._panel.get_first_child()
        while c:
            n = c.get_next_sibling()
            self._panel.remove(c)
            c = n

    def _build_panel(self):
        self._clear_panel()
        p = self._panel
        s = self.layout.get(self._sel) if self._sel else None
        self._pv = {}
        if self.tool in PAINT_TOOLS:
            p.append(label(_("Paint colors"), ("subheading",)))
            p.append(QuickColors(self.app.saved_colors, self.app.recent_colors,
                                 lambda h: self._set_well("a", h), lambda h: self._set_well("b", h),
                                 lambda: self.app.save_color(self.color_a), size=28, per_line=8))
            p.append(label(_("Click a color for the first paint color, right-click for the second (Gradient only). "
                           "+ saves the first one."), ("tiny", "faint"), wrap=True))
            p.append(divider())
        if s is None:
            p.append(label(_("Nothing selected"), ("heading",)))
            p.append(label(_("Click a strip to select it. Each enabled zone has one strip; add clones for strips that "
                           "share a wire."), ("small", "dim"), wrap=True))
            row = hbox(12, Toggle(self._snap, lambda v: setattr(self, "_snap", v)), label(_("Snap to grid"), ("body",)))
            row.set_margin_top(10)
            p.append(row)
            p.append(divider())
            p.append(label(_("Strips"), ("subheading",)))
            p.append(label(_("Hide a strip to get it out of the way; it keeps its place and colors."), ("tiny", "faint"),
                           wrap=True))
            for st in [x for x in self.layout.strips if x["zone"] in self._enabled]:
                hidden = bool(st.get("hidden"))
                r_ = hbox(6)
                eye = button(icon_name="visibility_off" if hidden else "visibility", style="text small",
                             cb=lambda st=st, h=hidden: self._set_hidden(st, not h),
                             tooltip=_("Show this strip") if hidden else _("Hide this strip"))
                r_.append(eye)
                name = self._name(st["zone"]) + (f"  \u00b7  {_('clone')}" if st["clone"] else "")
                nb = Gtk.Button(label=name, hexpand=True)
                d_, z_ = split_key(st["zone"])
                nb.set_tooltip_text(_('{zone} on {device}').format(zone=z_, device=d_) if z_ else d_)
                nb.add_css_class("text")
                nb.add_css_class("small")
                nb.get_child().set_xalign(0)
                nb.get_child().set_ellipsize(3)
                if hidden:
                    nb.add_css_class("dim")
                nb.connect("clicked", lambda _b, st=st: self._select(st))
                r_.append(nb)
                r_.append(label(f"{self._count(st['zone'])}", ("tiny", "faint")))
                p.append(r_)
            return
        key = s["zone"]
        d, z = split_key(key)
        n = self._count(key)
        head = hbox(4)
        head.append(label(self._name(key), ("heading",), wrap=True))
        head.append(Gtk.Box(hexpand=True))
        head.append(button(icon_name="edit", style="text small", cb=lambda: self._rename(key),
                           tooltip=_("Rename this strip")))
        p.append(head)
        orig = z or d
        sub = (_("{zone} on {device}").format(zone=orig, device=d) if z else _("Whole device")) \
            if self._name(key) != orig else (d if z else _("Whole device"))
        if s["clone"]:
            sub += "  ·  " + _("clone (shows the same colors)")
        p.append(label(sub, ("small", "dim"), wrap=True))
        self._pv["count"] = label(ngettext("{n} LED", "{n} LEDs", n).format(n=n), ("body",))
        p.append(self._pv["count"])
        row = hbox(6)
        row.append(button(_("Identify"), "flare", "tonal small", lambda: self._identify(s)))
        row.append(button(_("Count LEDs"), "straighten", "tonal small",
                          lambda: self.app.count_leds(d, z, n, lambda c: self._send(self.app.client.set_zone_led_count,
                                                                                     d, z, c))))
        p.append(row)

        cfg = self._cfg.get(key) or {}
        pat = PatternGenerator.normalize(cfg.get("pattern", "solid"))
        p.append(label(_("Pattern"), ("small", "dim")))
        dd = Dropdown([PATTERN_NAMES[x] for x in PatternGenerator.PATTERNS], PATTERN_NAMES.get(pat),
                      lambda v: self._set_pattern(key, PATTERN_KEYS.get(v, "solid")))
        dd.set_halign(Gtk.Align.START)
        p.append(dd)
        self._pv["pattern"] = pat
        if pat != "paint":
            picker = SwatchPicker(list(self.status.get("extracted_colors") or []), list(cfg.get("pattern_colors", [0])),
                                  lambda entries, k=key: self._set_colors(k, entries),
                                  custom=list(self.status.get("custom_colors") or []), size=30, hint=False,
                                  max_select=1 if pat == "solid" else 8)
            p.append(picker)
        else:
            p.append(label(_("Painted: use the Paint, Erase, Fill and Gradient tools below."), ("tiny", "faint"),
                           wrap=True))

        p.append(divider())
        locked = self._strip_locked(s)
        p.append(label(_("Shape"), ("subheading",)))
        p.append(hbox(12, Toggle(s["flip"], lambda v: self._flip(s)), label(_("Flip LED order (drawing only)"),
                                                                            ("small",))))
        p.append(hbox(12, Toggle(s["locked"], lambda v: self._lock_strip(s)), label(_("Lock this strip"), ("small",))))

        segs = s["segments"]
        turn = hbox(6)
        turn.append(label(_("Turn"), ("small", "dim")))
        for ico, delta, tip in (("rotate_left", -90, _("Turn 90\u00b0 left")), ("rotate_right", 90, _("Turn 90\u00b0 right"))):
            b_ = button(icon_name=ico, style="tonal small", cb=lambda d_=delta: self._turn_all(s, d_), tooltip=tip)
            b_.set_sensitive(not locked)
            turn.append(b_)
        sp = Spin(0, 359, round(segs[0]["angle"]) % 360, lambda v: self._set_angle(s, 0, v), step=15)
        sp.set_sensitive(not locked)
        turn.append(sp)
        turn.append(label("\u00b0", ("small", "dim")))
        p.append(turn)

        dens = hbox(6)
        lpp = self._lpp(key)
        dens.append(label(_("LEDs per metre"), ("small", "dim")))
        sp = Spin(5, 300, round(1000 * lpp / segs[0]["spacing"]), lambda v: self._density(s, v, None))
        sp.set_sensitive(not locked)
        dens.append(sp)
        p.append(dens)
        p.append(label(_("The density printed on the strip or its listing: 30, 60, 96 or 144 are common. The strip is "
                       "drawn at its real length.")
                       + (" " + _('Each dot is one pixel of {lpp} LEDs (set on the Devices tab, Strip type).').format(lpp=lpp) if lpp > 1
                          else ""), ("tiny", "faint"), wrap=True))

        p.append(label(_("Bends"), ("small", "dim")))
        if len(segs) == 1:
            p.append(label(_("None yet. Right-click a LED, or add one below."), ("tiny", "faint"), wrap=True))
        for i, seg in enumerate(segs[1:], start=1):
            g = Gtk.Grid(column_spacing=8, row_spacing=4)
            g.attach(label(_('Bend {i}').format(i=i), ("small",)), 0, 0, 1, 1)
            rm = button(icon_name="close", style="text small", cb=lambda i=i: self._do(self.layout.remove_bend, s, i),
                        tooltip=_("Remove this bend"))
            rm.set_sensitive(not locked)
            rm.set_halign(Gtk.Align.END)
            g.attach(rm, 1, 0, 1, 1)
            g.attach(label(_("at LED"), ("tiny", "faint")), 0, 1, 1, 1)
            st = Spin(2, max(2, n), seg["start"] + 1, lambda v, i=i: self._move_bend(s, i, int(v) - 1))
            st.set_sensitive(not locked)
            g.attach(st, 1, 1, 1, 1)
            g.attach(label(_("direction \u00b0"), ("tiny", "faint")), 0, 2, 1, 1)
            an = Spin(0, 359, round(seg["angle"]) % 360, lambda v, i=i: self._set_angle(s, i, v), step=15)
            an.set_sensitive(not locked)
            g.attach(an, 1, 2, 1, 1)
            p.append(g)
        add = hbox(6)
        nb = Spin(2, max(2, n), max(2, n // 2), None)
        nb.set_sensitive(not locked)
        add.append(button(_("Add a bend at LED"), "add", "tonal small",
                          lambda: self._do(self.layout.add_bend, s, int(nb.get_value()) - 1)))
        add.append(nb)
        add.set_sensitive(not locked and n > 2)
        p.append(add)
        p.append(label(_("On the canvas (Arrange tool), turn a section with its round knob: behind LED 1 for the whole strip, "
                       "outside the corner for a bend."), ("tiny", "faint"),
                       wrap=True))

        row2 = hbox(6)
        row2.set_margin_top(6)
        row2.append(button(_("Clone"), "content_copy", "tonal small", lambda: self._clone(s)))
        row2.append(button(_("Hide"), "visibility_off", "tonal small", lambda: self._set_hidden(s, True)))
        if s["clone"]:
            row2.append(button(_("Delete clone"), "delete", "danger small", lambda: self._delete(s)))
        p.append(row2)

    def _refresh_panel_values(self):
        s = self.layout.get(self._sel) if self._sel else None
        if s is None or "count" not in getattr(self, "_pv", {}):
            return
        self._pv["count"].set_label(ngettext('{n} LED', '{n} LEDs', self._count(s['zone'])).format(n=self._count(s['zone'])))
        cfg = self._cfg.get(s["zone"]) or {}
        if self._pv.get("pattern") != PatternGenerator.normalize(cfg.get("pattern", "solid")):
            self._build_panel()

    def _lpp(self, key) -> int:
        """LEDs per pixel (12V strips where one chip drives a group of LEDs)."""
        try:
            return max(1, int((self._cfg.get(key) or {}).get("leds_per_pixel", 1) or 1))
        except (TypeError, ValueError):
            return 1

    def pixel_size_changed(self, key, old, new):
        """LEDs per pixel changed on the Devices tab: keep the LEDs per metre, so a pixel gets longer."""
        if not old or old == new:
            return
        cfg = dict(self._cfg.get(key) or {})
        cfg["leds_per_pixel"] = new
        self._cfg[key] = cfg
        for st in self.layout.strips:
            if st["zone"] == key:
                for seg in st["segments"]:
                    seg["spacing"] = max(2.0, min(200.0, seg["spacing"] * new / old))
        self._schedule_save()
        self.cv.queue_draw()
        if self._sel and (self.layout.get(self._sel) or {}).get("zone") == key:
            self._build_panel()

    def _density(self, s, value, seg_index):
        sp = 1000.0 * self._lpp(s["zone"]) / max(5.0, min(300.0, float(value)))
        for i, seg in enumerate(s["segments"]):
            if seg_index is None or i == seg_index:
                seg["spacing"] = sp
        self._schedule_save()
        self.cv.queue_draw()

    def _set_angle(self, s, i, value):
        i = min(i, len(s["segments"]) - 1)
        self.layout.rotate_from(s, i, (float(value) % 360) - s["segments"][i]["angle"])
        self._schedule_save()
        self.cv.queue_draw()

    def _turn_all(self, s, delta):
        self.layout.rotate_from(s, 0, delta)
        self._schedule_save()
        self.cv.queue_draw()
        self._build_panel()

    def _move_bend(self, s, i, start):
        segs = s["segments"]
        if not 0 < i < len(segs):
            return
        lo = segs[i - 1]["start"] + 1
        hi = (segs[i + 1]["start"] - 1) if i + 1 < len(segs) else self._count(s["zone"]) - 1
        segs[i]["start"] = max(lo, min(hi, start))
        self._schedule_save()
        self.cv.queue_draw()

    def _rename(self, key):
        d, z = split_key(key)

        def after(name):
            cfg = dict(self._cfg.get(key) or {})
            if name:
                cfg["display_name"] = name
            else:
                cfg.pop("display_name", None)
            self._cfg[key] = cfg
            self._hold[key] = time.time() + 3.0
            self.cv.queue_draw()
            self._build_panel()
        self.app.rename_zone(d, z, (self._cfg.get(key) or {}).get("display_name", ""), after)

    def _set_pattern(self, key, pattern):
        d, z = split_key(key)
        self._set_local(key, pattern=pattern)
        self._send(self.app.client.set_zone_pattern, d, z, pattern)
        self.cv.queue_draw()
        GLib.idle_add(lambda: (self._build_panel(), False)[1])

    def _set_colors(self, key, entries):
        d, z = split_key(key)
        self._set_local(key, pattern_colors=list(entries))
        self._send(self.app.client.set_zone_colors, d, z, list(entries))
        self.cv.queue_draw()

    # ========================================================== saving
    def _schedule_save(self):
        if self._save_job:
            GLib.source_remove(self._save_job)
        self._save_job = GLib.timeout_add(400, self._save)

    def _save(self):
        self._save_job = None
        try:
            self.layout.save()
        except OSError:
            pass
        return False

    def reload(self):
        self.layout.load()
        self._sel = None
        self._apply_lock_ui()
        self._build_panel()
        self.cv.queue_draw()


__all__ = ["LayoutTab", "set_button_text"]
