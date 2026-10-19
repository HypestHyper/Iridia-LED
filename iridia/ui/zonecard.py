"""Zone cards for the Devices tab (one per zone, plus the "Everything" card)."""

import time

from gi.repository import GLib, Gtk

from iridia.i18n import _, ngettext, pgettext  # noqa: F401
from iridia import animations
from iridia.colors import resolve_colors
from iridia.patterns import PatternGenerator, led_even_boundaries, segment_sizes
from iridia.ui import effects as fx
from iridia.ui import fonts, serial
from iridia.ui.sections_panel import SectionsPanel
from iridia.ui.widgets import (DualRange, Dropdown, Group, QuickColors, Spin, StripEditor, Swatch, SwatchPicker, Toggle,
                               button, card, hbox, icon, label, set_button_text, switch_row, vbox, wrap_row)

ZONE_FIELDS_DEFAULT = {
    "enabled": True, "led_count": 20, "pattern": "solid", "mode": "full",
    "pattern_colors": [0], "brightness_sync": False, "manual_brightness": 100,
    "brightness_range": [0, 100], "invert_brightness": False, "gamma_correction": False,
    "pattern_params": {}, "calibration_profile": "WS2812B", "animation": None,
}

MODE_LABELS = {"full": pgettext("color correction", "Off"), "palette": _("Palette"), "calibrated": _("Calibrated")}
MODE_CAPTIONS = {
    "full": _("No correction. The color you pick is sent to the strip as it is."),
    "palette": _("Keeps every LED on the 48 safe colors that cheap LED strips show cleanly."),
    "calibrated": _("Corrects colors so they look right on your strip. Choose the profile that matches it "
                    "(edit them in Settings)."),
    "mixed": _("Zones use different corrections. Pick one to set them all."),
}
PATTERN_NAMES = {"solid": _("Solid"), "gradient": _("Gradient"), "segments": _("Segments"),
                 "center_out": _("Center out"), "edges_in": _("Edges in"), "alternating": _("Alternating"),
                 "paint": _("Painted")}
PATTERN_KEYS = {v: k for k, v in PATTERN_NAMES.items()}


def merge_zone_cfgs(cfgs):
    merged, mixed = {}, set()
    for key, default in ZONE_FIELDS_DEFAULT.items():
        vals = [c.get(key, default) for c in cfgs] or [default]
        merged[key] = vals[0]
        if any(v != vals[0] for v in vals[1:]):
            mixed.add(key)
    return merged, mixed


class GlobalClient:
    """The ZoneCard interface, but every call applies to all zones (daemon `set_all`)."""

    def __init__(self, client):
        self._c = client

    def set_zone_enabled(self, d, z, v):
        return self._c.set_all("enabled", v)

    def set_zone_pattern(self, d, z, v):
        return self._c.set_all("pattern", v)

    def set_zone_mode(self, d, z, v):
        return self._c.set_all("mode", v)

    def set_zone_colors(self, d, z, v):
        return self._c.set_all("pattern_colors", v)

    def set_zone_brightness_sync(self, d, z, v):
        return self._c.set_all("brightness_sync", v)

    def set_zone_manual_brightness(self, d, z, v):
        return self._c.set_all("manual_brightness", v)

    def set_zone_brightness_range(self, d, z, lo, hi):
        return self._c.set_all("brightness_range", [lo, hi])

    def set_zone_invert(self, d, z, v):
        return self._c.set_all("invert_brightness", v)

    def set_zone_gamma(self, d, z, v):
        return self._c.set_all("gamma_correction", v)

    def set_zone_pattern_params(self, d, z, params):
        return self._c.set_all("pattern_params", params)

    def set_zone_animation(self, d, z, anim):
        return self._c.set_all("animation", anim)

    def set_zone_calibration_profile(self, d, z, name):
        return self._c.set_all("calibration_profile", name)

    def set_zone_led_count(self, d, z, v):
        return {"ok": True}

    def identify(self, *a, **k):
        return {"ok": False}

    def identify_off(self):
        return self._c.identify_off()

    def add_custom_color(self, h):
        return self._c.add_custom_color(h)

    def remove_custom_color(self, h):
        return self._c.remove_custom_color(h)


STRIP_TYPES = [
    # (key, name, note)
    ("auto", _("Automatic"), ""),
    ("addressable", _("Addressable 5V (WS2812B, SK6812)"),
     _("Every LED has its own chip and color (3 pins: 5V, data, GND). Sold as ARGB, RGBIC or digital.")),
    ("addressable12", _("Addressable 12V in groups (WS2811, COB)"),
     _("One chip drives a group of LEDs, so a group is one pixel. OpenRGB counts pixels, not LEDs; set "
       "how many LEDs are in a pixel so the Layout tab draws the real length.")),
    ("single", _("One color (plain 12V RGB, 4 pins)"),
     _("The whole strip shows one color (12V, R, G, B pins). Patterns, painting and color stops don't "
       "apply, so they're hidden.")),
    ("rgbw", _("RGBW addressable (SK6812 RGBW, experimental)"),
     _("OpenRGB sends 3 bytes per LED, RGBW strips read 4. Iridia packs the white channel into the data "
       "itself, which needs the OpenRGB zone to be a third larger than the strip. Assumes the header "
       "sends GRB (like WS2812B); use Color order if colors come out swapped. Count LEDs doesn't work on "
       "these strips: set the LED count by hand.")),
]
STRIP_NAMES = {k: n for k, n, _t in STRIP_TYPES}
STRIP_KEYS = {n: k for k, n, _t in STRIP_TYPES}
ORDERS = [("RGB", _("RGB (normal)")), ("RBG", "RBG"), ("GRB", "GRB"), ("GBR", "GBR"), ("BRG", "BRG"), ("BGR", "BGR")]


class ZoneCard(Gtk.Box):
    GLOBAL_PREVIEW_LEDS = 30
    PROFILES = ["WS2812B"]

    def __init__(self, app, device_name, zone_name, zone_cfg, extracted, custom, client,
                 global_mode=False, expanded=False, title=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("card")
        self.app = app
        self.device_name, self.zone_name = device_name, zone_name
        self.cfg = dict(zone_cfg)
        self.extracted = list(extracted)
        self.custom = list(custom)
        self.client = client
        self.patterns = PatternGenerator()
        self.global_mode = global_mode
        self._title = title or zone_name
        self._mixed = set()
        self._hold_until = 0.0
        self._jobs = {}
        self._layout_open = False
        self._params = dict(zone_cfg.get("pattern_params") or {})
        self._identifying = False
        self._testing = False
        self._stype = "addressable"         # effective strip type (from the daemon)
        self._strip_info = {}
        self._anim = animations.clean(zone_cfg.get("animation"))
        self._last_effect = self._anim["effect"] if self._anim else "breathing"
        self._preview_last = None
        self._sections = None
        self._build_header(expanded)
        self._build_details()
        self._refresh_summary()
        self._apply_color_limit()
        self._update_preview()

    def _count(self):
        return self.GLOBAL_PREVIEW_LEDS if self.global_mode else int(self.cfg.get("led_count", 20))

    # ------------------------------------------------------------ header
    def _build_header(self, expanded):
        hdr = hbox(14)
        self._enabled = Toggle(self.cfg.get("enabled", True), self._on_enabled)
        hdr.append(self._enabled)
        txt = vbox(0, hexpand=True)
        self._title_lbl = label(self._display_title(), ("heading",))
        txt.append(self._title_lbl)
        self._summary = label("", ("small", "dim"))
        txt.append(self._summary)
        hdr.append(txt)
        if not self.global_mode:
            hdr.append(button(icon_name="edit", style="text small", cb=self._rename, tooltip=_("Rename this strip")))
        self._chev = icon("expand_less" if expanded else "expand_more", classes=("dim",))
        hdr.append(self._chev)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_a: self._toggle_expand())
        txt.add_controller(click)
        click2 = Gtk.GestureClick()
        click2.connect("released", lambda *_a: self._toggle_expand())
        self._chev.add_controller(click2)
        self.append(hdr)
        self._rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=260,
                                 reveal_child=expanded)
        self._details = vbox(10)
        self._details.set_margin_top(14)
        self._rev.set_child(self._details)
        self.append(self._rev)

    def _display_title(self):
        return self.cfg.get("display_name") or self._title

    def _rename(self):
        def after(name):
            self.cfg = dict(self.cfg, display_name=name)
            if not name:
                self.cfg.pop("display_name", None)
            self._hold_until = time.time() + 2.5
            self._title_lbl.set_label(self._display_title())
            self._refresh_summary()
        self.app.rename_zone(self.device_name, self.zone_name, self.cfg.get("display_name", ""), after)

    @property
    def expanded(self):
        return self._rev.get_reveal_child()

    def _toggle_expand(self):
        on = not self._rev.get_reveal_child()
        self._rev.set_reveal_child(on)
        self._chev.set_label(fonts.codepoint("expand_less" if on else "expand_more"))
        if on:
            GLib.idle_add(lambda: (self._ensure_preview(), False)[1])

    def _menu_items(self):
        if self._anim is not None:
            return [fx.EFFECT_NAMES[e] for e in animations.ORDER]
        return [PATTERN_NAMES[p] for p in PatternGenerator.PATTERNS if not (self.global_mode and p == "paint")]

    def _menu_value(self):
        if self._anim is not None:
            return None if "animation" in self._mixed else fx.EFFECT_NAMES[self._anim["effect"]]
        return None if "pattern" in self._mixed else PATTERN_NAMES.get(
            PatternGenerator.normalize(self.cfg.get("pattern", "solid")))

    def _refresh_summary(self):
        pat = _("mixed") if "pattern" in self._mixed else PATTERN_NAMES.get(
            PatternGenerator.normalize(self.cfg.get("pattern", "solid")), "")
        if "animation" in self._mixed:
            pat = _("mixed")
        elif self._anim is not None:
            pat = fx.EFFECT_NAMES[self._anim["effect"]]
        mode = _("mixed") if "mode" in self._mixed else {"full": _("no correction"), "palette": _("palette"),
                                                          "calibrated": _("calibrated")}.get(self.cfg.get("mode", "full"), "")
        n_leds = int(self.cfg.get("led_count", 20) or 0)
        parts = [pat, mode] + ([] if self.global_mode else [ngettext("{n} LED", "{n} LEDs", n_leds).format(n=n_leds)])
        if not self.global_mode and self.cfg.get("display_name"):
            parts.insert(0, self.zone_name or self.device_name)
        self._summary.set_label("  ·  ".join(p for p in parts if p))

    # ------------------------------------------------------------ details
    def _build_details(self):
        d = self._details
        self._hw_note = label("", ("small", "accent"), wrap=True)
        self._hw_note.set_visible(False)
        d.append(self._hw_note)
        row = wrap_row(10)
        if not self.global_mode:
            self._led_spin = Spin(1, 1000, self.cfg.get("led_count", 20), self._on_led_change)
            row.append(hbox(10, label(_("LEDs"), ("small", "dim")), self._led_spin))
        else:
            self._led_spin = None
        # label, kind and menu stay together when the row wraps
        self._pattern_lbl = label(_("Pattern"), ("small", "dim"))
        self._kind = Group([("static", _("Static")), ("animated", _("Animated"))],
                           "animated" if self._anim else "static", self._on_kind)
        self._pattern = Dropdown(self._menu_items(), self._menu_value(), self._on_pattern_change)
        row.append(hbox(10, self._pattern_lbl, self._kind, self._pattern))
        d.append(row)
        self._fx = fx.EffectControls(self._on_effect_params, show_sync=self.global_mode)
        self._fx.set_effect(self._anim)
        d.append(self._fx)
        if not self.global_mode:
            self._build_strip_box(d)

        if not self.global_mode:
            tools = hbox(6)
            self._identify_btn = button(_("Identify"), "flare", "tonal small", self._on_identify)
            tools.append(self._identify_btn)
            self._count_btn = button(_("Count LEDs"), "straighten", "tonal small", self._on_count)
            tools.append(self._count_btn)
            tools.append(label(_("Identify lights only this zone, so you can see which strip it is."), ("tiny", "faint"),
                               wrap=True))
            d.append(tools)

        self._picker = SwatchPicker(self.extracted, list(self.cfg.get("pattern_colors", [0])), self._on_colors_change,
                                    custom=self.custom, on_add=self._add_custom, on_remove_custom=self._remove_custom)
        d.append(self._picker)

        self._strip = StripEditor(render=self._render_with_stops, on_stops=self._on_stops, on_paint=self._on_paint)
        self._strip.set_ruler(not self.global_mode)
        d.append(self._strip)
        self._layout_row = hbox(14)
        self._layout_btn = button(_("Edit layout"), "tune", "text small", self._toggle_layout)
        self._layout_row.append(self._layout_btn)
        self._rev_row, self._reverse = switch_row(_("Reverse"), bool(self._params.get("reverse")), self._on_reverse)
        self._mir_row, self._mirror = switch_row(_("Mirror"), bool(self._params.get("mirror")), self._on_mirror)
        self._layout_row.append(self._rev_row)
        self._layout_row.append(self._mir_row)
        d.append(self._layout_row)
        # segments: how many LEDs each colour gets, and a button to split them evenly
        self._split_row = hbox(10)
        self._split_lbl = label("", ("small", "dim"), wrap=True)
        self._split_lbl.set_hexpand(True)
        self._split_btn = button(_("Space evenly"), "linear_scale", "tonal small", self._space_evenly)
        self._split_row.append(self._split_lbl)
        self._split_row.append(self._split_btn)
        self._split_warn = label("", ("small", "warn-text"), wrap=True)
        d.append(vbox(2, self._split_row, self._split_warn))
        self._chips = hbox(4)
        d.append(self._chips)
        self._paint_bar = hbox(6)
        self._paint_box = vbox(6, self._paint_bar)
        if not self.global_mode:
            self._build_paint_bar()
        d.append(self._paint_box)
        if not self.global_mode:
            self._sections = SectionsPanel(self)
            d.append(self._sections)

        # brightness
        br = card(inner=True)
        br.set_margin_top(6)
        br.append(label(_("Brightness"), ("subheading",)))
        r1 = hbox(10)
        row1, self._sync = switch_row(_("Follow monitor brightness"), self.cfg.get("brightness_sync", False), self._on_sync)
        r1.append(row1)
        r1.append(label(_("Manual"), ("small", "dim"), xalign=1.0))
        self._manual = Spin(0, 100, self.cfg.get("manual_brightness", 100), self._on_manual)
        r1.append(self._manual)
        br.append(r1)
        self._follow_ok = True
        self._sync_note = label(_("No monitor brightness to follow (see Settings, Monitor brightness), so Manual is "
                                  "used."), ("small", "faint"), wrap=True)
        self._sync_note.set_visible(False)
        br.append(self._sync_note)
        if self.global_mode:
            # the same choice as Settings, Monitor brightness (one monitor for every strip)
            self._mon_row = hbox(10)
            self._mon_row.append(label(_("Monitor"), ("small", "dim")))
            self._mon_dd = Dropdown([_("Automatic")], _("Automatic"), lambda v: self.app._ddc_pick(v), placeholder="")
            self._mon_row.append(self._mon_dd)
            self._mon_row.set_visible(False)
            br.append(self._mon_row)
        r2 = hbox(12)
        r2.append(label(_("Range"), ("small", "dim")))
        rng = self.cfg.get("brightness_range", [0, 100])
        self._range = DualRange(rng[0], rng[1], lambda a, b: self._autosave("range", self._on_range, 400))
        r2.append(self._range)
        br.append(r2)
        r3 = hbox(24)
        row3, self._invert = switch_row(_("Invert (bias lighting)"), self.cfg.get("invert_brightness", False),
                                        self._on_invert)
        self._gamma_row, self._gamma = switch_row(_("Gamma correction"), self.cfg.get("gamma_correction", False),
                                                  self._on_gamma)
        r3.append(row3)
        r3.append(self._gamma_row)
        br.append(r3)
        if not self.global_mode:
            row5, self._sess_ignore = switch_row(_("Stay lit when the screen locks or you're away"),
                                                 bool(self.cfg.get("session_ignore")), self._on_session_ignore)
            br.append(row5)
        r4 = hbox(10)
        r4.set_margin_top(6)
        r4.append(label(_("Color correction"), ("small", "dim")))
        self._mode_val = self.cfg.get("mode", "full")
        self._mode_group = Group([(m, MODE_LABELS[m]) for m in ("full", "palette", "calibrated")], self._mode_val,
                                 self._on_mode)
        r4.append(self._mode_group)
        self._profile = Dropdown(self.PROFILES, self.cfg.get("calibration_profile", "WS2812B"), self._on_profile)
        r4.append(self._profile)
        br.append(r4)
        self._mode_caption = label("", ("tiny", "faint"), wrap=True)
        br.append(self._mode_caption)
        d.append(br)
        self._apply_mode_ui()
        self._apply_strip_ui()

    # ------------------------------------------------------------ strip type
    def _build_strip_box(self, d):
        self._strip_exp = Gtk.Expander(label=_("Strip type and wiring"))
        self._strip_exp.add_css_class("strip-exp")
        box = card(inner=True)
        r = hbox(10)
        r.append(label(_("Strip type"), ("small", "dim")))
        cur = self.cfg.get("strip_type") or "auto"
        self._stype_dd = Dropdown([n for _k, n, _t in STRIP_TYPES], STRIP_NAMES.get(cur, _("Automatic")),
                                  lambda v: self._strip_set(strip_type=STRIP_KEYS.get(v, "auto")))
        r.append(self._stype_dd)
        box.append(r)
        self._stype_note = label("", ("tiny", "faint"), wrap=True)
        box.append(self._stype_note)

        r = hbox(10)
        r.append(label(_("Color order"), ("small", "dim")))
        self._order_dd = Dropdown([n for _k, n in ORDERS], dict(ORDERS).get(self.cfg.get("color_order", "RGB")),
                                  lambda v: self._strip_set(color_order=next(k for k, n in ORDERS if n == v)))
        r.append(self._order_dd)
        self._test_btn = button(_("Test colors"), "palette", "tonal small", self._on_test)
        r.append(self._test_btn)
        box.append(r)
        box.append(label(_("Test colors lights this strip red at the LED 1 end, green in the middle and blue at the far "
                         "end (a one-color strip cycles red, green, blue). If the colors are wrong, change the order "
                         "until they match."), ("tiny", "faint"), wrap=True))

        self._lpp_row = hbox(10)
        self._lpp_row.append(label(_("LEDs per pixel"), ("small", "dim")))
        self._lpp = Spin(1, 20, self.cfg.get("leds_per_pixel", 1), lambda v: self._on_lpp(int(v)))
        self._lpp_row.append(self._lpp)
        box.append(self._lpp_row)

        self._power_box = vbox(4)
        r = hbox(10)
        r.append(label(_("Power limit"), ("small", "dim")))
        self._plimit = Spin(0, 100, self.cfg.get("power_limit", 0),
                            lambda v: self._strip_set(power_limit=round(float(v), 1)), step=0.5, digits=1)
        r.append(self._plimit)
        r.append(label(_("A  (0 = no limit)"), ("small", "dim")))
        self._power_box.append(r)
        self._power_lbl = label("", ("tiny", "faint"), wrap=True)
        self._power_box.append(self._power_lbl)
        self._power_box.append(label(_("Long 5V strips at full white pull a lot of current: the far end turns orange or "
                                     "pink, or the controller resets. Set your power supply's amps (minus a bit) and "
                                     "Iridia dims only when a color would go over it. The estimate assumes 60 mA per "
                                     "LED at full white."), ("tiny", "faint"), wrap=True))
        box.append(self._power_box)

        self._rgbw_row = hbox(10)
        self._rgbw_lbl = label("", ("small", "accent"), wrap=True)
        self._rgbw_row.append(self._rgbw_lbl)
        self._rgbw_btn = button(_("Resize the OpenRGB zone"), "straighten", "tonal small", self._rgbw_resize)
        self._rgbw_row.append(self._rgbw_btn)
        self._rgbw_row.set_visible(False)
        box.append(self._rgbw_row)
        self._strip_exp.set_child(box)
        d.append(self._strip_exp)

    def _strip_set(self, **fields):
        if "strip_type" in fields:
            self.cfg = dict(self.cfg, strip_type=None if fields["strip_type"] == "auto" else fields["strip_type"])
            if fields["strip_type"] != "auto":
                self._stype = fields["strip_type"]
        self.cfg.update({k: v for k, v in fields.items() if k != "strip_type"})
        self._hold_until = time.time() + 2.0
        self._call(lambda: self.client.set_zone_strip(self.device_name, self.zone_name, **fields))
        self._apply_strip_ui()

    def _on_lpp(self, v):
        old = int(self.cfg.get("leds_per_pixel", 1) or 1)
        self._strip_set(leds_per_pixel=v)
        if hasattr(self.app, "_layout_tab"):
            self.app._layout_tab.pixel_size_changed(f"{self.device_name}|{self.zone_name}", old, v)

    def _on_test(self):
        self._testing = not self._testing
        set_button_text(self._test_btn, _("Stop test") if self._testing else _("Test colors"),
                        "stop" if self._testing else "palette")
        self._call(lambda: self.client.test_colors(self.device_name, self.zone_name, off=not self._testing))
        if self._testing:
            GLib.timeout_add_seconds(60, self._test_timeout)

    def _test_timeout(self):
        if self._testing:
            self._testing = False
            set_button_text(self._test_btn, _("Test colors"), "palette")
        return False

    def _rgbw_resize(self):
        need = self._strip_info.get("needs_size")
        if not need:
            return
        self._call(lambda: self.client.resize_zone(self.device_name, self.zone_name, need, keep_count=True))
        self.app.toast(_('Asked OpenRGB for {need} LEDs on this zone').format(need=need))

    def set_strip_info(self, info):
        info = dict(info or {})
        changed = info != self._strip_info
        self._strip_info = info
        t = info.get("type")
        if t and t != self._stype and time.time() >= self._hold_until:
            self._stype = t
            changed = True
        if changed:
            self._apply_strip_ui()

    def _apply_strip_ui(self):
        if self.global_mode or not hasattr(self, "_stype_dd"):
            return
        chosen = self.cfg.get("strip_type") or "auto"
        t = self._stype if chosen == "auto" else chosen
        self._stype = t
        single = t == "single"
        auto_txt = ("  " + _("(looks like: {type})").format(type=STRIP_NAMES.get(t, t))) if chosen == "auto" else ""
        self._stype_note.set_label(next((n for k, _x, n in STRIP_TYPES if k == t), "") + auto_txt)
        self._strip_exp.set_label(_('Strip: {type}').format(type=STRIP_NAMES.get(t, t).split(' (')[0])
                                  + ("" if self.cfg.get("color_order", "RGB") == "RGB"
                                     else f", {self.cfg.get('color_order')}"))
        self._lpp_row.set_visible(t == "addressable12")
        self._power_box.set_visible(not single)
        info = self._strip_info
        if "amps" in info:
            txt = _("Right now about {now:.1f} A, {full:.1f} A at full white.").format(
                now=info['amps'], full=info.get('full_amps', 0))
            if info.get("limited"):
                txt += " " + _("Dimmed to stay under the limit (would be {amps:.1f} A).").format(
                    amps=info.get('wanted_amps', 0))
            self._power_lbl.set_label(txt)
        self._power_lbl.set_visible("amps" in info)
        need = info.get("needs_size") if t == "rgbw" else None
        self._rgbw_row.set_visible(bool(need))
        if need:
            self._rgbw_lbl.set_label(_('For {n} RGBW LEDs the OpenRGB zone needs {need} LEDs; right now the end of the strip stays dark.').format(n=self.cfg.get('led_count', 0), need=need))
        # one-colour strips: no patterns, painting or stops
        for w in (self._pattern_lbl, self._pattern, self._strip, self._count_btn, self._sections):
            if w is not None:
                w.set_visible(not single)
        self._update_preview()
        self._apply_color_limit()

    def _build_paint_bar(self):
        b = self._paint_bar
        b.append(label(_("Paint"), ("small", "dim")))
        self._wells = {}
        for which, init in (("a", "ff8800"), ("b", "3355ff")):
            sw = Swatch(init, 32, on_click=lambda w=which: self._pick_well(w), tooltip=_("Paint color"))
            self._wells[which] = sw
            b.append(sw)
        self._tool_group = Group([("paint", _("Paint"), "brush"), ("erase", _("Erase"), "ink_eraser"),
                                  ("gradient", _("Gradient"), "gradient")], "paint", self._set_tool)
        b.append(self._tool_group)
        b.append(button(_("Fill"), "format_color_fill", "tonal small", lambda: self._strip.fill_all(self._strip.color_a)))
        b.append(button(_("Clear"), "delete", "tonal small", lambda: self._strip.fill_all(None)))
        self._paint_box.append(QuickColors(self.app.saved_colors, self.app.recent_colors,
                                           lambda h: self._set_well("a", h), lambda h: self._set_well("b", h),
                                           lambda: self.app.save_color(self._strip.color_a), size=24, per_line=16))

    def _apply_mode_ui(self):
        mode = "mixed" if "mode" in self._mixed else self._mode_val
        self._mode_group.set_active(None if mode == "mixed" else mode)
        self._mode_caption.set_label(MODE_CAPTIONS.get(mode, ""))
        self._profile.set_visible(mode == "calibrated")
        self._gamma_row.set_visible(mode != "calibrated")

    def _sent_fn(self):
        mode = self._mode_val
        if "mode" in self._mixed or mode == "full":
            return None
        if mode == "palette":
            return lambda h: self.app.palette().snap(h)
        prof = self.app.profiles().get(self._profile.value())
        return lambda h: prof.correct(h, 100)

    # ------------------------------------------------------------ preview
    def _pattern_key(self):
        if getattr(self, "_stype", "") == "single" and not self.global_mode:
            return "solid"
        v = self._pattern.value()
        return PATTERN_KEYS.get(v, "solid") if v else "solid"

    def _current_colors(self):
        cols = resolve_colors(self._picker.selected, self.extracted)
        return cols or ([self.extracted[0]] if self.extracted else ["642107"])

    def _render_with_stops(self, stops):
        p = dict(self._params)
        p["stops"] = stops
        return self.patterns.generate(self._pattern_key(), self._current_colors(), self._count(), params=p)

    def _stops_for_edit(self):
        pat, n = self._pattern_key(), len(self._current_colors())
        want = PatternGenerator.handle_count(pat, n)
        cur = self._params.get("stops")
        if isinstance(cur, list) and len(cur) == want:
            return list(cur)
        return PatternGenerator.default_stops(pat, n)

    def _update_preview(self):
        count = self._count()
        pat = self._pattern_key()
        if self._anim is not None:
            self._ensure_preview()
        painted = pat == "paint" and not self.global_mode
        base = self.patterns.generate(pat, self._current_colors(), count, params=self._params)
        shown = base
        if self._sections is not None:
            if self._sections.active() and not self._layout_open and not painted:
                shown = self._sections.compose(base)
            self._sections.refresh(base, shown)
        self._strip.set_state(count, shown, pat)
        editable = pat in PatternGenerator.EDITABLE and PatternGenerator.handle_count(pat, len(self._current_colors())) > 0
        can_rev = pat in ("gradient", "segments", "alternating")
        self._layout_row.set_visible(editable or can_rev)
        self._layout_btn.set_visible(editable)
        self._rev_row.set_visible(can_rev)
        self._mir_row.set_visible(can_rev)
        self._strip.set_flags(can_rev and bool(self._params.get("reverse")), can_rev and bool(self._params.get("mirror")))
        if not editable:
            self._layout_open = False
        set_button_text(self._layout_btn, _("Done editing") if self._layout_open else _("Edit layout"),
                        "check" if self._layout_open else "tune")
        if self._anim is not None:
            self._layout_btn.set_visible(False)       # stops belong to static patterns
            self._layout_open = False
            editable = False
        self._strip.set_layout(self._layout_open and editable, self._stops_for_edit() if editable else [])
        self._update_split()
        self._rebuild_chips()
        self._paint_box.set_visible(painted)
        self._strip.base_color = self._current_colors()[0]
        self._strip.set_paint(painted, self._params.get("paint") or [] if painted else [])

    def _rebuild_chips(self):
        c = self._chips.get_first_child()
        while c:
            n = c.get_next_sibling()
            self._chips.remove(c)
            c = n
        pat = self._pattern_key()
        show = self._layout_open and pat in PatternGenerator.EDITABLE
        self._chips.set_visible(show)
        if not show:
            return
        self._chips.append(label(_("Colors in order (click to change):"), ("small", "dim")))
        for i, col in enumerate(self._current_colors()):
            self._chips.append(Swatch(col, 28, on_click=lambda i=i: self._edit_slot(i)))

    def _edit_slot(self, i):
        cols = self._current_colors()

        def done(h):
            if not h:
                return
            sel = list(self._picker.selected)
            if i < len(sel):
                sel[i] = h
            else:
                sel.append(h)
            if h not in self.custom:
                self.custom.append(h)
                self._call(self.client.add_custom_color, h)
            self._picker.set_colors(self.extracted, sel, self.custom)
            self._on_colors_change(sel)
        self.app.pick_color(cols[i], _("Change this color"), done, sent_fn=self._sent_fn())

    def _toggle_layout(self):
        self._layout_open = not self._layout_open
        self._update_preview()

    def _on_stops(self, stops):
        self._params["stops"] = stops
        self._save_params({"stops": stops})
        self._update_split()

    def _split_leds(self) -> int:
        """LEDs the segments are spread over: half the strip when it's mirrored."""
        n = self._count()
        return (n + 1) // 2 if self._params.get("mirror") and n > 1 else n

    def _update_split(self):
        cols = len(self._current_colors())
        show = self._layout_open and self._anim is None and self._pattern_key() == "segments" and cols > 1
        self._split_row.set_visible(show)
        self._split_warn.set_visible(False)
        if not show:
            return
        leds = self._split_leds()
        sizes = segment_sizes(self._stops_for_edit(), cols, leds)
        even = segment_sizes(led_even_boundaries(cols, leds), cols, leds)
        self._split_lbl.set_text(_("{leds} LEDs: {sizes}").format(leds=leds, sizes=" + ".join(map(str, sizes))))
        self._split_btn.set_sensitive(sizes != even)
        spread = max(sizes) - min(sizes)
        warn = ""
        if sizes != even and 0 < spread <= 2:
            # close enough to look even, but not: easy to miss on the strip itself
            warn = ngettext("The parts are {n} LED apart. Space evenly makes them match.",
                            "The parts are {n} LEDs apart. Space evenly makes them match.", spread).format(n=spread)
        elif sizes == even and leds % cols:
            warn = ngettext("{leds} LEDs don't split into {parts} evenly, so the first part gets 1 more LED.",
                            "{leds} LEDs don't split into {parts} evenly, so the first {extra} parts get 1 more LED.",
                            leds % cols).format(leds=leds, parts=cols, extra=leds % cols)
        self._split_warn.set_text(warn)
        self._split_warn.set_visible(bool(warn))

    def _space_evenly(self):
        stops = led_even_boundaries(len(self._current_colors()), self._split_leds())
        self._strip.set_layout(True, stops)
        self._strip.queue_draw()
        self._on_stops(stops)
        self._update_preview()

    def _on_paint(self, paint):
        self._params["paint"] = paint
        self._save_params({"paint": paint}, 500)

    def _on_reverse(self, v):
        self._params["reverse"] = v
        self._save_params({"reverse": v}, 0)
        self._update_preview()

    def _on_mirror(self, v):
        self._params["mirror"] = v
        self._save_params({"mirror": v}, 0)
        self._update_preview()

    def _save_params(self, params, delay=250):
        key = "params:" + ",".join(sorted(params))

        def run():
            self._call(self.client.set_zone_pattern_params, self.device_name, self.zone_name, params)
        self._autosave(key, run, delay)

    def _set_tool(self, tool):
        self._strip.tool = tool
        self._strip.reset_gradient_anchor()

    def _set_well(self, which, h):
        if which == "a":
            self._strip.color_a = h
        else:
            self._strip.color_b = h
        self._wells[which].set_state(hex6=h)

    def _pick_well(self, which):
        cur = self._strip.color_a if which == "a" else self._strip.color_b

        def done(h):
            if h:
                self._set_well(which, h)
        self.app.pick_color(cur, _("Paint color"), done, sent_fn=self._sent_fn())

    # ------------------------------------------------------------ actions
    def _call(self, fn, *args):
        self._hold_until = time.time() + 2.5
        serial.send(fn, *args)

    def _autosave(self, key, fn, delay=400):
        self._hold_until = time.time() + 3.0
        old = self._jobs.pop(key, None)
        if old:
            GLib.source_remove(old)

        def run():
            self._jobs.pop(key, None)
            fn()
            return False
        if delay <= 0:
            run()
        else:
            self._jobs[key] = GLib.timeout_add(delay, run)

    def _on_enabled(self, v):
        self._call(self.client.set_zone_enabled, self.device_name, self.zone_name, v)

    def _on_led_change(self, v):
        count = int(v)
        self._call(self.client.set_zone_led_count, self.device_name, self.zone_name, count)
        self.cfg = dict(self.cfg, led_count=count)
        if self._sections is not None:
            self._sections.rescale(count)
        self._refresh_summary()
        self._update_preview()

    # ------------------------------------------------------------ effects
    def _on_kind(self, kind):
        if (kind == "animated") == (self._anim is not None):
            return
        self._mixed.discard("animation")
        self._anim = animations.defaults(self._last_effect) if kind == "animated" else None
        self._send_animation()
        self._pattern.set_items(self._menu_items(), self._menu_value())
        self._fx.set_effect(self._anim)
        self._after_effect_change()

    def _on_effect_params(self, params):
        if self._anim is None:
            return
        self._anim = params
        self._send_animation()
        self._update_preview()

    def _send_animation(self):
        self.cfg = dict(self.cfg, animation=self._anim)
        self._call(self.client.set_zone_animation, self.device_name, self.zone_name, self._anim)

    def _after_effect_change(self):
        self._refresh_summary()
        self._apply_color_limit()
        self._update_preview()

    def _preview_wanted(self) -> bool:
        moving = self._anim is not None or (self._sections is not None and self._sections.animated())
        return moving and self.expanded and self.get_mapped()

    def _after_sections_change(self):
        self._update_preview()
        self._ensure_preview()

    def _tick_preview(self):
        if not self._preview_wanted():
            return False
        count = self._count()
        params = dict(self._params)
        base = self.patterns.generate(PatternGenerator.normalize(self.cfg.get("pattern", "solid")),
                                      self._current_colors(), count, params=params)
        pos = animations.strip_positions(count, bool(params.get("reverse")), bool(params.get("mirror")))
        key = f"{self.device_name}|{self.zone_name}"
        status = self.app._status if isinstance(self.app._status, dict) else {}
        if self._anim is not None:
            frame = fx.preview(status, key, self._anim, self._current_colors(), base, count, positions=pos)
        else:
            frame = base                        # only parts of the strip move
        own = frame
        if self._sections is not None and self._sections.active():
            frame = self._sections.frame(frame, status)
        if frame != self._preview_last or self._strip.led_count != count:
            self._preview_last = frame          # slow effects often show the same frame: no repaint
            if not self._layout_open:
                self._strip.set_state(count, frame, "solid" if self._anim is not None else self._pattern_key())
            if self._sections is not None:
                self._sections.refresh(own, frame)
        return True

    def _ensure_preview(self):
        if self._preview_wanted() and not fx.ticking(self):
            self._preview_last = None
            fx.tick(self, self._tick_preview)

    def _on_pattern_change(self, name):
        if self._anim is not None:
            effect = fx.EFFECT_KEYS.get(name)
            if not effect or effect == self._anim["effect"]:
                return
            self._mixed.discard("animation")
            keep = {k: self._anim[k] for k in ("follow_layout", "angle", "sync")}
            self._anim = animations.clean(dict(animations.defaults(effect), **keep))
            self._last_effect = effect
            self._send_animation()
            self._fx.set_effect(self._anim)
            self._after_effect_change()
            return
        pat = PATTERN_KEYS.get(name, "solid")
        self._mixed.discard("pattern")
        self._call(self.client.set_zone_pattern, self.device_name, self.zone_name, pat)
        self._params.pop("stops", None)
        self.cfg = dict(self.cfg, pattern=pat)
        self._refresh_summary()
        self._apply_color_limit()
        self._update_preview()

    def _apply_color_limit(self):
        solid = self._pattern_key() == "solid" and self._anim is None
        changed = self._picker.set_max_select(1 if solid else 8)
        if changed and solid:
            self._on_colors_change(list(self._picker.selected))
        return changed

    def _on_mode(self, mode):
        self._mixed.discard("mode")
        self._mode_val = mode
        self._call(self.client.set_zone_mode, self.device_name, self.zone_name, mode)
        self.cfg = dict(self.cfg, mode=mode)
        self._apply_mode_ui()
        self._refresh_summary()

    def _on_profile(self, name):
        self._call(self.client.set_zone_calibration_profile, self.device_name, self.zone_name, name)

    def _on_colors_change(self, entries):
        self._call(self.client.set_zone_colors, self.device_name, self.zone_name, entries)
        self._update_preview()

    def _add_custom(self):
        cols = resolve_colors(self._picker.selected, self.extracted)

        def done(h):
            if not h:
                return
            if h not in self.custom:
                self.custom.append(h)
            self._call(self.client.add_custom_color, h)
            sel = list(self._picker.selected)
            if self._picker.max_select == 1:
                sel = [h]
            elif h not in [e for e in sel if isinstance(e, str)] and len(sel) < self._picker.max_select:
                sel.append(h)
            self._picker.set_colors(self.extracted, sel, self.custom)
            self._on_colors_change(sel)
        self.app.pick_color(cols[0] if cols else "ff8800", _("Save a new color"), done, sent_fn=self._sent_fn())

    def _remove_custom(self, h):
        self.custom = [c for c in self.custom if c != h]
        self._call(self.client.remove_custom_color, h)
        sel = [e for e in self._picker.selected if e != h] or [0]
        self._picker.set_colors(self.extracted, sel, self.custom)
        self._update_preview()

    def _on_sync(self, v):
        self._call(self.client.set_zone_brightness_sync, self.device_name, self.zone_name, v)
        self._sync_note.set_visible(bool(v) and not self._follow_ok)

    def set_monitors(self, items, current, show: bool):
        """The Everything card's monitor list (the one in Settings, kept in step)."""
        if hasattr(self, "_mon_dd"):
            self._mon_dd.set_items(list(items), current)
            self._mon_row.set_visible(show)

    def set_follow_ok(self, ok: bool):
        """Whether there's a monitor brightness to follow (the note says Manual is used otherwise)."""
        self._follow_ok = ok
        self._sync_note.set_visible(self._sync.get_active() and not ok)

    def _on_manual(self, v):
        self._call(self.client.set_zone_manual_brightness, self.device_name, self.zone_name, int(v))

    def _on_range(self):
        self._call(self.client.set_zone_brightness_range, self.device_name, self.zone_name, self._range.lo,
                   self._range.hi)

    def _on_session_ignore(self, v):
        self._strip_set(session_ignore=bool(v))

    def _on_invert(self, v):
        self._call(self.client.set_zone_invert, self.device_name, self.zone_name, v)

    def _on_gamma(self, v):
        self._call(self.client.set_zone_gamma, self.device_name, self.zone_name, v)

    def _on_identify(self):
        self._identifying = not self._identifying
        set_button_text(self._identify_btn, _("Done") if self._identifying else _("Identify"),
                        "check" if self._identifying else "flare")
        if self._identifying:
            self._identify_btn.add_css_class("toggled")
            self._call(self.client.identify, self.device_name, self.zone_name, 60)
            GLib.timeout_add(60000, lambda: (self._identifying and self._on_identify(), False)[1])
        else:
            self._identify_btn.remove_css_class("toggled")
            self._call(self.client.identify_off)

    def _on_count(self):
        def done(n):
            self._led_spin.set_value(n)
            self._on_led_change(n)
        self.app.count_leds(self.device_name, self.zone_name, int(self.cfg.get("led_count", 20)), done)

    # ------------------------------------------------------------ sync
    def set_hw(self, real_size, single_color):
        """What OpenRGB says about this zone: no size yet, or one colour for the whole device."""
        if real_size == 0:
            t = _("OpenRGB doesn't know how many LEDs this zone has yet, so nothing lights up. Click "
                  "Count LEDs and set the size there.")
        elif single_color:
            t = _("This device has no Direct mode, so it shows one color for the whole device "
                  "(the first one of the pattern).")
        else:
            t = ""
        if t != self._hw_note.get_label():
            self._hw_note.set_label(t)
            self._hw_note.set_visible(bool(t))

    def sync_from_status(self, zcfg, extracted, custom, mixed=None):
        self.cfg = dict(zcfg)
        if hasattr(self, "_title_lbl") and self._title_lbl.get_label() != self._display_title():
            self._title_lbl.set_label(self._display_title())
        self._mixed = set(mixed or ())
        holding = time.time() < self._hold_until or bool(self._jobs)
        if not holding and not self.global_mode and hasattr(self, "_stype_dd"):
            self._stype_dd.set_value(STRIP_NAMES.get(zcfg.get("strip_type") or "auto"))
            self._order_dd.set_value(dict(ORDERS).get(zcfg.get("color_order", "RGB")))
            if not self._lpp.busy():
                self._lpp.set_quiet(zcfg.get("leds_per_pixel", 1))
            if not self._plimit.busy():
                self._plimit.set_quiet(zcfg.get("power_limit", 0))
        if not holding:
            self._enabled.set_value(zcfg.get("enabled", True))
            if self._sections is not None:
                self._sections.set_config(zcfg)
            if self._led_spin is not None and not self._led_spin.busy():
                self._led_spin.set_quiet(zcfg.get("led_count", 20))
            anim = animations.clean(zcfg.get("animation"))
            if anim != self._anim or ("animation" in self._mixed) != getattr(self, "_anim_mixed", False):
                self._anim_mixed = "animation" in self._mixed
                if anim is not None:
                    self._last_effect = anim["effect"]
                self._anim = anim
                self._fx.set_effect(None if self._anim_mixed else anim)
                self._kind.set_active(None if self._anim_mixed else ("animated" if anim else "static"))
                self._pattern.set_items(self._menu_items(), self._menu_value())
                self._refresh_summary()
                self._apply_color_limit()
                self._update_preview()
            else:
                self._pattern.set_value(self._menu_value())
        sel = list(zcfg.get("pattern_colors", [0]))
        custom = list(custom)
        colors_changed = False
        if not holding and (sel != self._picker.selected or list(extracted) != self._picker.extracted
                            or custom != self._picker.custom):
            self.extracted = list(extracted)
            self.custom = custom
            self._picker.set_colors(self.extracted, sel, custom)
            colors_changed = True
        if holding:
            return
        self._sync.set_value(zcfg.get("brightness_sync", False))
        self._sync_note.set_visible(self._sync.get_active() and not self._follow_ok)
        if not self._manual.busy():
            self._manual.set_quiet(zcfg.get("manual_brightness", 100))
        if not self._range.dragging():
            br = zcfg.get("brightness_range", [0, 100])
            self._range.set(br[0], br[1])
        self._invert.set_value(zcfg.get("invert_brightness", False))
        self._gamma.set_value(zcfg.get("gamma_correction", False))
        if hasattr(self, "_sess_ignore"):
            self._sess_ignore.set_value(bool(zcfg.get("session_ignore")))
        mode = zcfg.get("mode", "full")
        self._profile.set_items(self.PROFILES, zcfg.get("calibration_profile", "WS2812B"))
        if mode != self._mode_val or self._mixed != getattr(self, "_shown_mixed", set()):
            self._mode_val = mode
            self._shown_mixed = set(self._mixed)
            self._apply_mode_ui()
        self._refresh_summary()
        new_params = dict(zcfg.get("pattern_params") or {})
        if (new_params != self._params or colors_changed or self._strip.led_count != self._count()
                or self._pattern_key() != self._strip.pattern):
            self._params = new_params
            self._reverse.set_value(bool(new_params.get("reverse")))
            self._mirror.set_value(bool(new_params.get("mirror")))
            self._apply_color_limit()
            self._update_preview()
        elif self._sections is not None and self._sections.has_sensors() and not self._preview_wanted():
            self._update_preview()          # new sensor readings came with this status
