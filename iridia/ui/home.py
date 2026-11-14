"""Home: what your lights show right now (the backlight), the wallpaper's colours to pick from, and your
Favourites underneath."""

import math
import os
import threading

import cairo

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from iridia.colors import resolve_colors
from iridia.i18n import _
from iridia.theme import hex_rgb
from iridia.ui import widgets
from iridia.ui.widgets import Swatch, WavyBar, button, hbox, icon, label, rgb, themed, vbox

RADIUS = 28


def _rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def lit_colors(st: dict, limit: int = 8) -> list[str]:
    """The colours your strips show now, one per strip (its first colour), each once, in order: what
    the backlight glows with. Strips Iridia doesn't control, hidden ones and switched-off ones aren't
    counted; with none, the wallpaper's own colours."""
    extracted = list(st.get("extracted_colors") or [])
    out = []
    for dc in (st.get("device_configs") or {}).values():
        if not isinstance(dc, dict) or not dc.get("enabled", True):
            continue
        zones = dc.get("zones") or {}
        for zc in (zones.values() if zones else [dc]):
            if not isinstance(zc, dict) or not zc.get("enabled", True) or zc.get("hands_off") or zc.get("hidden"):
                continue
            cols = resolve_colors(zc.get("pattern_colors", [0]), extracted)
            if cols and cols[0] not in out:
                out.append(cols[0])
    return (out or extracted)[:limit]


class Backlight(Gtk.DrawingArea):
    """The hero's background: a dark panel with your lights' colours glowing up from under its bottom
    edge, like a bias light behind a screen, and the strip itself as a thin line of those colours."""

    def __init__(self):
        super().__init__()
        themed(self)
        self.colors: list[str] = []
        self.level = 1.0
        self.set_draw_func(self._draw)
        self.set_hexpand(True)

    def set_state(self, colors, level):
        colors, level = list(colors), max(0.0, min(1.0, level))
        if colors != self.colors or abs(level - self.level) > 0.01:
            self.colors, self.level = colors, level
            self.queue_draw()

    def _draw(self, _a, cr, w, h):
        _rounded(cr, 0, 0, w, h, RADIUS)
        cr.clip()
        cr.set_source_rgb(*rgb("SURFACE_CONTAINER"))
        cr.paint()
        cols = self.colors or []
        n = len(cols)
        if not n:
            return
        # each colour glows from its own place along the bottom; dimmer lights glow less
        strength = 0.18 + 0.5 * self.level
        reach = max(h * 1.15, w / n * 0.95)
        for i, c in enumerate(cols):
            r, g, b = hex_rgb(c)
            x = w * (i + 0.5) / n
            grad = cairo.RadialGradient(x, h + reach * 0.18, 0, x, h + reach * 0.18, reach)
            grad.add_color_stop_rgba(0.0, r, g, b, strength)
            grad.add_color_stop_rgba(0.45, r, g, b, strength * 0.35)
            grad.add_color_stop_rgba(1.0, r, g, b, 0.0)
            cr.set_source(grad)
            cr.paint()
        # the strip: a thin line of the colours along the bottom edge
        seg = w / n
        for i, c in enumerate(cols):
            r, g, b = hex_rgb(c)
            cr.set_source_rgba(r, g, b, 0.35 + 0.65 * self.level)
            cr.rectangle(i * seg, h - 3, seg + 0.5, 3)
            cr.fill()


def _cover(pb, w, h):
    """The middle of an image, scaled to fill w x h."""
    sw, sh = pb.get_width(), pb.get_height()
    k = max(w / sw, h / sh)
    tw, th = max(1, int(sw * k + 0.5)), max(1, int(sh * k + 0.5))
    scaled = pb.scale_simple(tw, th, GdkPixbuf.InterpType.BILINEAR)
    return scaled.new_subpixbuf((tw - w) // 2, (th - h) // 2, w, h)


class Thumb(Gtk.DrawingArea):
    """The wallpaper, small, with rounded corners: read off the main thread (a big image takes a moment)
    at the screen's own scale, and drawn at a fixed size (an image widget would size itself by the
    image's pixels, twice as big on a 2x screen)."""

    W, H = 176, 104

    def __init__(self):
        super().__init__()
        self.set_content_width(self.W)
        self.set_content_height(self.H)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)
        self._path = None
        self._pb = None
        self._k = 1

    def show_path(self, path):
        if path == self._path:
            return
        self._path = path
        if not path or not os.path.isfile(path):
            self._pb = None
            self.set_visible(False)
            return
        k = max(1, self.get_scale_factor())

        def load():
            try:
                src = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, -1, self.H * k * 2, True)
                pb = _cover(src, self.W * k, self.H * k)
            except GLib.Error:
                pb = None
            GLib.idle_add(done, pb)

        def done(pb):
            if path == self._path:
                self._pb, self._k = pb, k
                self.set_visible(pb is not None)
                self.queue_draw()
            return False
        threading.Thread(target=load, daemon=True).start()

    def _draw(self, _a, cr, w, h):
        if self._pb is None:
            return
        _rounded(cr, 0, 0, w, h, 14)
        cr.clip()
        cr.scale(1 / self._k, 1 / self._k)
        Gdk.cairo_set_source_pixbuf(cr, self._pb, 0, 0)
        cr.paint()


class Hero(Gtk.Overlay):
    """What your lights are doing: the wallpaper and its colours (click one to use it everywhere),
    brightness, Freeze and the lights' power."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.set_valign(Gtk.Align.START)
        self.add_css_class("backlight-hero")
        self.light = Backlight()
        self.set_child(self.light)
        body = vbox(14)
        for m in ("top", "start", "end"):
            getattr(body, f"set_margin_{m}")(22)
        body.set_margin_bottom(26)
        self.add_overlay(body)
        self.set_measure_overlay(body, True)

        top = hbox(18)
        self.thumb = Thumb()
        top.append(self.thumb)
        words = vbox(2, hexpand=True)
        words.set_valign(Gtk.Align.CENTER)
        self.title = label(_("Waiting for the daemon…"), ("display-s",), ellipsize=True)
        self.sub = label("", ("body", "dim"), ellipsize=True)
        words.append(self.title)
        words.append(self.sub)
        top.append(words)
        body.append(top)

        self.swatches = hbox(8)
        self.swatches.set_valign(Gtk.Align.CENTER)
        row = hbox(10)
        row.append(self.swatches)
        row.append(button(None, "colorize", "tonal small circle", app._pick_custom_color,
                          tooltip=_("Pick any colour for all your lights")))
        body.append(row)

        bottom = hbox(12)
        bottom.append(icon("light_mode", classes=("dim",)))
        self.wave = WavyBar(180)
        self.wave.set_hexpand(False)
        bottom.append(self.wave)
        self.bright = label("", ("subheading", "tnum"))
        self.bright.set_width_chars(4)
        bottom.append(self.bright)
        bottom.append(Gtk.Box(hexpand=True))
        app._freeze_btn = button(_("Freeze colours"), "ac_unit", "tonal small", app._toggle_freeze,
                                 tooltip=_("Keep these colours when the wallpaper changes"))
        app._freeze_btn.set_valign(Gtk.Align.CENTER)
        bottom.append(app._freeze_btn)
        self.power = button(None, "power_settings_new", "small circle power on glow", self._toggle_power)
        self.power.set_valign(Gtk.Align.CENTER)
        bottom.append(self.power)
        body.append(bottom)
        self._off = False

    def _toggle_power(self):
        on = self._off
        self._show_power(on)
        self.app.bg(lambda: self.app.client.lights(on), lambda _r: self.app._poll_once())

    def _show_power(self, on):
        self._off = not on
        self.power.remove_css_class("off" if on else "on")
        self.power.add_css_class("on" if on else "off")
        self.power.set_tooltip_text(_("Lights on: click to turn them off") if on else
                                    _("Lights off: click to turn them on"))

    def update(self, st: dict, choice, frozen: bool):
        wallpaper = st.get("wallpaper") or ""
        night = st.get("night") or {}
        off = bool(st.get("lights_off") or st.get("asleep"))
        brightness = st.get("brightness") or 0
        name = os.path.splitext(os.path.basename(wallpaper))[0] if wallpaper else ""
        self.title.set_label(name or _("No wallpaper found yet"))
        self.title.set_tooltip_text(wallpaper or None)
        if st.get("asleep"):
            sub = _("Off while the PC sleeps")
        elif st.get("lights_off"):
            sub = _("Lights are off")
        elif frozen:
            sub = _("Colours frozen: a new wallpaper won't change them")
        elif night.get("active"):
            sub = _("Night mode until {time}, at most {cap}%").format(time=night.get("end"), cap=night.get("cap"))
        elif not wallpaper:
            sub = _("Your lights use these colours until Iridia finds your wallpaper")
        else:
            sub = _("Your lights follow this wallpaper")
        self.sub.set_label(sub)
        self.thumb.show_path(wallpaper)
        self.wave.set_value(brightness / 100)
        self.bright.set_label(f"{brightness}%")
        if self._off != off:
            self._show_power(not off)
        level = 0.0 if off else brightness / 100
        self.light.set_state(lit_colors(st), level)

    def set_swatches(self, colors, choice):
        widgets.clear(self.swatches)
        for i, c in enumerate(colors[:8]):
            self.swatches.append(Swatch(c, 36, bool(choice) and choice.get("index") == i,
                                        on_click=lambda i=i: self.app._set_color_choice(index=i),
                                        tooltip=_("Use this colour on all your lights")))
        if not colors:
            self.swatches.append(label(_("No colours yet"), ("small", "faint")))

