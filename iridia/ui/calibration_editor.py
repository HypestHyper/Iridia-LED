"""Calibration profile editor window (GTK 4)."""

from gi.repository import GLib, Gtk

from iridia.i18n import _
from iridia.calibration import DEFAULT_NAME, DEFAULT_PROFILE, HUE_NAMES, Profile, clean_hex, normalize
from iridia.ui import dialogs
from iridia.ui.widgets import (Spin, Swatch, Toggle, button, card, hbox, hsv_hex, label, vbox)


class ProfileEditor(dialogs.Dialog):
    """Edit one calibration profile; every change is saved right away.

    host: pick(initial, title, target, on_done), sender(raw) -> obj with send/close, changed(), pause(+1/-1)
    """

    def __init__(self, parent, profiles, name: str, host):
        super().__init__(parent, _("Edit profile: {name}").format(name=name), width=780, height=760, resizable=True,
                         on_close=self._closing)
        self.profiles, self.name, self.host = profiles, name, host
        data, _u = normalize(profiles.read_data(name))
        data = data or normalize(profiles.read_data(DEFAULT_NAME))[0]
        self.data = data
        self.anchors = [list(a) for a in data["anchors"] if a[0] != 360]
        self.grey = data["grey"]
        self.params = {k: data[k] for k in ("sat_exponent", "blue_nudge", "grey_sharpness", "min_out_sat")}
        self._save_job = None
        self._sender = None
        self._profile = Profile(data)
        host.pause(1)

        top = hbox(8)
        top.append(label(_('Profile: {name}').format(name=name), ("title",), xalign=0))
        top.append(Gtk.Box(hexpand=True))
        if name == DEFAULT_NAME:
            top.append(button(_("Reset to defaults"), "history", "tonal", self._reset))
        top.append(button(_("Done"), "check", "filled", self.close))
        self.body.append(top)
        self.body.append(label(_("Each row says which hex to send to the strip for a hue. Use Tune to change it while "
                               "the strip shows exactly what you pick. Colors between rows are blended. Changes save "
                               "automatically."), ("small", "dim"), wrap=True))
        sc = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._content = vbox(12)
        sc.set_child(self._content)
        self.body.append(sc)
        self._msg = label("", ("small", "faint"))
        self.body.append(self._msg)
        self._build()
        self.present()

    # -------------------------------------------------------------- data
    def _data_now(self):
        return dict(self.data, anchors=[list(a) for a in sorted(self.anchors)], grey=self.grey, **self.params)

    def _changed(self, rebuild=True):
        clean, _u = normalize(self._data_now())
        if clean:
            self._profile = Profile(clean)
        self._update_test()
        if self._save_job:
            GLib.source_remove(self._save_job)
        self._save_job = GLib.timeout_add(350, self._save)
        if rebuild:
            self._build()

    def _save(self):
        self._save_job = None
        err = self.profiles.save(self.name, self._data_now())
        self._msg.set_label(err or _("Saved"))
        if not err:
            self.host.changed()
        return False

    def _reset(self):
        data, _u = normalize(DEFAULT_PROFILE)
        self.anchors = [list(a) for a in data["anchors"] if a[0] != 360]
        self.grey = data["grey"]
        self.params = {k: data[k] for k in self.params}
        self._changed()

    def _closing(self):
        if self._save_job:
            GLib.source_remove(self._save_job)
            self._save()
        self._stop_leds()
        self.host.pause(-1)

    # -------------------------------------------------------------- UI
    def _build(self):
        c = self._content.get_first_child()
        while c:
            n = c.get_next_sibling()
            self._content.remove(c)
            c = n
        tbl = card(inner=True)
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        for col, t in enumerate((_("Hue"), _("Name"), _("Meant"), _("Sent"), _("Hex to send"), "", "")):
            grid.attach(label(t, ("tiny", "faint")), col, 0, 1, 1)
        rows = sorted(self.anchors)
        for i, (hue, hx) in enumerate(rows, start=1):
            self._anchor_row(grid, i, hue, hx)
        r = len(rows) + 1
        grid.attach(label("360", ("body", "faint")), 0, r, 1, 1)
        grid.attach(label(_("Wraps back to 0"), ("small", "faint")), 1, r, 4, 1)
        g = r + 1
        grid.attach(label(_("Grey"), ("body",)), 0, g, 1, 1)
        grid.attach(label(_("No color at all"), ("small", "dim")), 1, g, 1, 1)
        grid.attach(Swatch("808080", 28), 2, g, 1, 1)
        grid.attach(Swatch(self.grey, 28), 3, g, 1, 1)
        e = Gtk.Entry(text=self.grey, width_chars=8, max_length=7)
        e.connect("activate", lambda en: self._commit_grey(en))
        fc = Gtk.EventControllerFocus()
        fc.connect("leave", lambda *_a: self._commit_grey(e))
        e.add_controller(fc)
        grid.attach(e, 4, g, 1, 1)
        grid.attach(button(_("Tune"), style="tonal small", cb=self._tune_grey), 5, g, 1, 1)
        tbl.append(grid)
        tbl.append(button(_("Add a row"), "add", "text small", self._add_anchor))
        self._content.append(tbl)
        self._build_test()
        self._build_advanced()

    def _anchor_row(self, grid, i, hue, hx):
        if hue == 0:
            grid.attach(label("0", ("body",)), 0, i, 1, 1)
        else:
            sp = Spin(1, 359, hue, lambda v, h=hue: self._move_anchor(h, int(v)), delay=700)
            grid.attach(sp, 0, i, 1, 1)
        grid.attach(label(_(HUE_NAMES[hue]) if hue in HUE_NAMES else "", ("small", "dim")), 1, i, 1, 1)
        grid.attach(Swatch(hsv_hex(hue, 1, 1), 28), 2, i, 1, 1)
        grid.attach(Swatch(hx, 28), 3, i, 1, 1)
        e = Gtk.Entry(text=hx, width_chars=8, max_length=7)
        e.connect("activate", lambda en, h=hue: self._commit_anchor(h, en))
        fc = Gtk.EventControllerFocus()
        fc.connect("leave", lambda *_a, h=hue, en=e: self._commit_anchor(h, en))
        e.add_controller(fc)
        grid.attach(e, 4, i, 1, 1)
        grid.attach(button(_("Tune"), style="tonal small", cb=lambda h=hue: self._tune_anchor(h)), 5, i, 1, 1)
        if hue != 0:
            grid.attach(button(icon_name="close", style="text small", cb=lambda h=hue: self._remove_anchor(h),
                               tooltip=_("Remove this row")), 6, i, 1, 1)

    def _find(self, hue):
        return next((a for a in self.anchors if a[0] == hue), None)

    def _commit_anchor(self, hue, entry):
        a = self._find(hue)
        hx = clean_hex(entry.get_text())
        if a is None:
            return
        if hx is None:
            entry.set_text(a[1])
        elif hx != a[1]:
            a[1] = hx
            GLib.idle_add(lambda: (self._changed(), False)[1])

    def _tune_anchor(self, hue):
        a = self._find(hue)
        if a is None:
            return

        def done(hx):
            if hx and hx != a[1]:
                a[1] = hx
                self._changed()
        self.host.pick(a[1], _("Tune {name}").format(name=_(HUE_NAMES[hue]) if hue in HUE_NAMES else _("hue {n}").format(n=hue)), hsv_hex(hue, 1, 1), done)

    def _commit_grey(self, entry):
        hx = clean_hex(entry.get_text())
        if hx is None:
            entry.set_text(self.grey)
        elif hx != self.grey:
            self.grey = hx
            GLib.idle_add(lambda: (self._changed(), False)[1])

    def _tune_grey(self):
        def done(hx):
            if hx and hx != self.grey:
                self.grey = hx
                self._changed()
        self.host.pick(self.grey, _("Tune grey"), "808080", done)

    def _move_anchor(self, hue, new):
        a = self._find(hue)
        if a is None or new == hue:
            return
        if not 1 <= new <= 359 or self._find(new):
            self._msg.set_label(_("That hue is taken or out of range (1 to 359)."))
            self._build()
            return
        a[0] = new
        self._changed()

    def _remove_anchor(self, hue):
        if len(self.anchors) <= 2:
            self._msg.set_label(_("Keep at least two rows."))
            return
        self.anchors = [a for a in self.anchors if a[0] != hue]
        self._changed()

    def _add_anchor(self):
        def check(t):
            try:
                h = int(float(t))
            except ValueError:
                return _("Type a hue from 1 to 359.")
            if not 1 <= h <= 359:
                return _("Type a hue from 1 to 359.")
            return _("That hue already has a row.") if self._find(h) else None

        def done(t):
            hue = int(float(t))
            self.anchors.append([hue, self._profile.picker_to_led(hue, 1.0, 1.0)])
            self._changed()
        dialogs.ask_text(self, _("Add a row"), _("Which hue (degrees, 1 to 359)? It starts with the color the profile "
                                            "gives there now."), "", done, check)

    # -------------------------------------------------------------- test
    def _build_test(self):
        c = card(inner=True)
        c.append(label(_("Try a color"), ("heading",)))
        c.append(label(_("Move the sliders to check a color. The left swatch is the color you mean, the right one is "
                       "what this profile sends."), ("small", "dim"), wrap=True))
        self._tv = {}
        if not hasattr(self, "_test_vals"):
            self._test_vals = {"h": 30.0, "s": 100.0, "v": 100.0}
        for key, name, hi in (("h", _("Hue"), 359), ("s", _("Saturation"), 100), ("v", _("Value"), 100)):
            row = hbox(10)
            lab = label(name, ("small", "dim"))
            lab.set_width_chars(11)
            row.append(lab)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, hi, 1)
            sc.set_value(self._test_vals[key])
            sc.set_hexpand(True)
            sc.set_draw_value(True)
            sc.connect("value-changed", lambda s, k=key: (self._test_vals.__setitem__(k, s.get_value()),
                                                          self._update_test()))
            row.append(sc)
            c.append(row)
        sw = hbox(10)
        self._t_in = Swatch("000000", 52)
        self._t_out = Swatch("000000", 52)
        self._t_lbl = label("", ("mono", "dim"))
        sw.append(self._t_in)
        sw.append(self._t_out)
        sw.append(self._t_lbl)
        c.append(sw)
        row, self._leds = switch_row_local(_("Show on LEDs"), self._toggle_leds)
        c.append(row)
        self._content.append(c)
        self._update_test()

    def _update_test(self):
        if not hasattr(self, "_t_in"):
            return
        h, s, v = self._test_vals["h"], self._test_vals["s"] / 100, self._test_vals["v"] / 100
        want = hsv_hex(h, s, v)
        sent = self._profile.picker_to_led(h, s, v)
        self._t_in.set_state(hex6=want)
        self._t_out.set_state(hex6=sent)
        self._t_lbl.set_label(_('meant  #{want}\nsent   #{sent}').format(want=want, sent=sent))
        if self._sender is not None:
            self._sender.send(sent)

    def _toggle_leds(self, on):
        if on:
            self._sender = self.host.sender(True)
            self._update_test()
        else:
            self._stop_leds()

    def _stop_leds(self):
        if self._sender is not None:
            s, self._sender = self._sender, None
            s.close()

    # -------------------------------------------------------------- advanced
    def _build_advanced(self):
        exp = Gtk.Expander(label=_("Advanced"))
        exp.add_css_class("subheading")
        box = vbox(8)
        box.set_margin_top(8)
        spec = (("min_out_sat", _("Saturation floor"), 0.0, 1.0, 0.01,
                 _("Colors are never sent whiter than this. Raise it if colors look pale, lower it if they look too "
                   "strong. Near-greys are not affected.")),
                ("sat_exponent", _("Saturation curve"), 0.1, 3.0, 0.05,
                 _("How quickly pastel colors fade toward white. Lower is paler sooner.")),
                ("blue_nudge", _("Blue to sky blue"), 0.0, 1.0, 0.05,
                 _("Pushes pale blues toward sky blue instead of violet.")),
                ("grey_sharpness", _("Grey sharpness"), 1.0, 30.0, 0.5,
                 _("How close to no color a color must be before the grey takes over.")))
        for key, name, lo, hi, step, hint in spec:
            row = hbox(10)
            lab = label(name, ("small", "dim"))
            lab.set_width_chars(16)
            row.append(lab)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
            sc.set_value(self.params[key])
            sc.set_digits(2)
            sc.set_draw_value(True)
            sc.set_hexpand(True)
            sc.connect("value-changed", lambda s, k=key: self._param(k, s.get_value()))
            row.append(sc)
            box.append(row)
            box.append(label(hint, ("tiny", "faint"), wrap=True))
        exp.set_child(box)
        c = card(inner=True)
        c.append(exp)
        self._content.append(c)

    def _param(self, key, value):
        if abs(self.params[key] - value) > 1e-9:
            self.params[key] = float(value)
            self._changed(rebuild=False)


def switch_row_local(text, cb):
    sw = Toggle(False, cb)
    return hbox(12, sw, label(text, ("body",))), sw
