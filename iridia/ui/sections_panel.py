"""The zone card's "Advanced" part: split the strip into parts, and set single LEDs by hand.

Kept out of zonecard.py, which only calls set_config(), refresh(), frame() and rescale().
"""
import zlib
from typing import Dict, List

from gi.repository import GLib, Gtk

from iridia import animations
from iridia import sections as S
from iridia.colors import resolve_colors
from iridia.i18n import _, ngettext
from iridia.ui import effects as fx
from iridia.ui.widgets import (Dropdown, Group, SectionStrip, Spin, Swatch, SwatchPicker, button, card, hbox, label,
                               set_button_text, switch_row, vbox, wrap_row)

KIND_NAMES = {"same": _("Same as the strip"), "pattern": _("Its own pattern"), "effect": _("Its own effect"),
              "sensor": _("A sensor"), "off": _("Off")}
SENSOR_NAMES = {"cpu_temp": _("CPU temperature"), "cpu_load": _("CPU load"), "gpu_temp": _("GPU temperature"),
                "gpu_load": _("GPU load"), "gpu2_temp": _("Second GPU temperature"),
                "gpu2_load": _("Second GPU load"), "ram": _("Memory use"), "disk_temp": _("Disk temperature")}
KIND_KEYS = {v: k for k, v in KIND_NAMES.items()}
PART_PATTERNS = ["solid", "gradient", "segments", "center_out", "edges_in", "alternating"]


class SectionsPanel(Gtk.Box):
    def __init__(self, zcard):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card = zcard
        self.n = int(zcard.cfg.get("led_count", 20) or 20)
        self.secs: List[dict] = S.clean(zcard.cfg.get("sections"), self.n)
        self.ov: Dict[int, str] = S.clean_overrides(zcard.cfg.get("led_overrides"), self.n)
        self._base: List[str] = []
        self._comp = None
        self._comp_sig = None
        self._save_job = None
        self.tool = "color"
        self.paint = "ffffff"

        self.exp = Gtk.Expander(label=_("Advanced: split this strip, set single LEDs"))
        self.exp.add_css_class("strip-exp")
        self.exp.set_expanded(bool(self.secs or self.ov))
        box = card(inner=True)
        self.strip = SectionStrip(on_drag=self._dragging, on_moved=self._moved, on_led=self._on_led)
        box.append(self.strip)

        r = wrap_row(8)
        r.append(button(_("Add divider"), "add", "tonal small", self._add_divider))
        self._even_btn = button(_("Space evenly"), "linear_scale", "tonal small", self._space_evenly)
        r.append(self._even_btn)
        self._sizes = label("", ("small", "dim"), wrap=True)
        self._sizes.set_valign(Gtk.Align.CENTER)
        r.append(self._sizes)
        box.append(r)
        self._warn = label("", ("small", "warn-text"), wrap=True)
        box.append(self._warn)
        self._rows = vbox(6)
        box.append(self._rows)

        # single LEDs
        box.append(label(_("Single LEDs"), ("subheading",)))
        r = wrap_row(8)
        self._pick_btn = button(_("Set LEDs"), "colorize", "tonal small", self._toggle_pick)
        r.append(self._pick_btn)
        self._tools = Group([("color", _("Color")), ("off", _("Off")), ("clear", _("Back to normal"))],
                            "color", self._set_tool)
        r.append(self._tools)
        self._well = Swatch(self.paint, 30, on_click=self._pick_paint, tooltip=_("Color for single LEDs"))
        r.append(self._well)
        self._ov_lbl = label("", ("small", "dim"))
        self._ov_lbl.set_valign(Gtk.Align.CENTER)
        r.append(self._ov_lbl)
        self._clear_btn = button(_("Clear all"), "delete", "text small", self._clear_overrides)
        r.append(self._clear_btn)
        box.append(r)
        box.append(label(_("Set LEDs, then click or drag over LEDs on the strip above. A set LED shows its color over "
                           "everything else, like a fixed LED between two bars."), ("tiny", "faint"), wrap=True))
        self.exp.set_child(box)
        self.append(self.exp)
        self._rebuild_rows()

    # ------------------------------------------------------------ state from the zone card
    def active(self) -> bool:
        return bool(self.secs or self.ov)

    def animated(self) -> bool:
        """Parts that move between status updates: effects, and sensor parts that can blink."""
        return S.has_effects(self.secs) or any(s["type"] == "sensor" and s.get("flash_above") is not None
                                               for s in self.secs)

    def has_sensors(self) -> bool:
        return any(s["type"] == "sensor" for s in self.secs)

    def sensor_value(self, sid):
        st = self.card.app._status if isinstance(self.card.app._status, dict) else {}
        return (st.get("sensors") or {}).get(sid)

    def _parts(self) -> List[dict]:
        """The parts to list: the whole strip is one part until it's split."""
        return self.secs or [{"start": 0, "type": "same"}]

    def set_config(self, zcfg):
        """New settings from the daemon (only when nothing is being edited)."""
        if self._save_job or self.strip._drag is not None:
            return
        n = int(zcfg.get("led_count", 20) or 20)
        secs, ov = S.clean(zcfg.get("sections"), n), S.clean_overrides(zcfg.get("led_overrides"), n)
        if (secs, ov, n) != (self.secs, self.ov, self.n):
            self.n, self.secs, self.ov = n, secs, ov
            self._rebuild_rows()
            self.refresh(self._base)

    def rescale(self, new_n: int):
        """The LED count changed here; the daemon moves the dividers the same way."""
        if new_n != self.n:
            self.secs, self.ov = S.rescale(self.secs, self.ov, self.n, new_n)
            self.n = new_n
            self._rebuild_rows()

    def _resolve(self, entries):
        return resolve_colors(entries, self.card.extracted)

    def compose(self, base: List[str]) -> List[str]:
        if not self.active():
            return list(base)
        return S.compose_static(base, self.secs, self.ov, self._resolve, self.card.patterns, self.sensor_value,
                                fx.anim_clock(self.card.app._status if isinstance(self.card.app._status, dict)
                                              else {}))

    def frame(self, base: List[str], status: dict) -> List[str]:
        """An animated frame: base with the parts drawn on top, as the daemon draws them."""
        if not self.active():
            return list(base)
        key = f"{self.card.device_name}|{self.card.zone_name}"
        seed = zlib.crc32(key.encode()) ^ int((status.get("animations") or {}).get("seed") or 0)
        sig = repr((self.secs, self.ov, len(base), self.card.extracted, seed))
        if sig != self._comp_sig:
            self._comp_sig = sig
            self._comp = S.Composer(self.secs, self.ov, len(base), self._resolve, seed, self.card.patterns,
                                    self.sensor_value)
        out = self._comp.frame([animations.hex_to_rgb(c) for c in base], fx.anim_clock(status))
        return [animations.rgb_to_hex(c) for c in out]

    def refresh(self, base: List[str], shown=None):
        """Show base (the strip's own colors) with the parts on top; shown: an already composed frame."""
        self._base = list(base)
        cols = shown if shown is not None else self.compose(base)
        self.strip.set_state(self.n, cols, [s["start"] for s in self.secs[1:]], self.ov.keys())
        self._update_sizes()
        self._update_row_labels()

    # ------------------------------------------------------------ dividers
    def _starts(self) -> List[int]:
        return [s["start"] for s in self.secs] if self.secs else [0]

    def _add_divider(self):
        if self.n < 2:
            return
        if not self.secs:
            self.secs = [{"start": 0, "type": "same"}]
        # split the biggest part in half
        spans = S.spans(self.secs, self.n)
        a, b, sec = max(spans, key=lambda p: p[1] - p[0])
        if b - a < 2:
            return
        new = {"start": (a + b) // 2, "type": "same"}
        self.secs = sorted(self.secs + [new], key=lambda s: s["start"])
        self._changed(rows=True)

    def _space_evenly(self):
        if not self.secs:
            return
        starts = S.even_starts(len(self.secs), self.n)
        self.secs = [dict(s, start=st) for s, st in zip(self.secs, starts)]
        self._changed(rows=True)

    def _dragging(self, starts):
        for s, st in zip(self.secs[1:], starts):
            s["start"] = st
        self.refresh(self._base)
        self._update_row_labels()

    def _moved(self, starts):
        self._dragging(starts)
        self._changed()

    def _remove(self, k):
        """Join part k to the part before it (the first part joins the second)."""
        if len(self.secs) < 2:
            return
        if k == 0:
            nxt = self.secs[1]
            self.secs = [dict(nxt, start=0)] + self.secs[2:]
        else:
            self.secs = self.secs[:k] + self.secs[k + 1:]
        if len(self.secs) == 1 and self.secs[0]["type"] == "same":
            self.secs = []
        self._changed(rows=True)

    def _set_kind(self, k, name):
        kind = KIND_KEYS.get(name, "same")
        if not self.secs:
            self.secs = [{"start": 0, "type": "same"}]          # the whole strip becomes part 1
        if kind == self.secs[k]["type"]:
            return
        old = self.secs[k]
        self.secs[k] = S.clean_section({"start": old["start"], "type": kind,
                                        "colors": old.get("colors") or list(self.card._picker.selected),
                                        "pattern": old.get("pattern", "solid"), "animation": old.get("animation"),
                                        "sensor": old.get("sensor", "cpu_temp")})
        self.secs[k]["start"] = old["start"]
        if self.secs == [{"start": 0, "type": "same"}]:
            self.secs = []
        self._changed(rows=True)

    # ------------------------------------------------------------ part rows
    def _rebuild_rows(self):
        c = self._rows.get_first_child()
        while c:
            nxt = c.get_next_sibling()
            self._rows.remove(c)
            c = nxt
        self._row_labels = []
        parts = self._parts()
        for k, (_a, _b, sec) in enumerate(S.spans(parts, self.n)):
            r = hbox(8)
            num = label(str(k + 1), ("subheading", "accent"))
            num.set_size_request(18, -1)
            r.append(num)
            lbl = label("", ("small", "dim"))
            lbl.set_size_request(130, -1)
            self._row_labels.append(lbl)
            r.append(lbl)
            r.append(Dropdown(list(KIND_NAMES.values()), KIND_NAMES[sec["type"]], lambda v, k=k: self._set_kind(k, v)))
            if sec["type"] in ("pattern", "effect", "sensor"):
                b_set = button(_("Settings"), "tune", "text small")
                b_set.connect("clicked", lambda w, k=k: self._settings(w, k))
                r.append(b_set)
            spacer = Gtk.Box(hexpand=True)
            r.append(spacer)
            if len(parts) > 1:
                r.append(button(icon_name="close", style="text small", cb=lambda k=k: self._remove(k),
                                tooltip=_("Remove this part (it joins the one before it)")))
            self._rows.append(r)
        self._update_row_labels()
        self._update_sizes()

    def _update_row_labels(self):
        parts = self._parts()
        for lbl, (a, b, sec) in zip(self._row_labels, S.spans(parts, self.n)):
            if len(parts) == 1:
                txt = _("The whole strip")
            else:
                txt = _("LEDs {first} to {last}  ({n})").format(first=a + 1, last=b, n=b - a) if b - a > 1 \
                    else _("LED {first}").format(first=a + 1)
            if sec["type"] == "sensor":
                v = self.sensor_value(sec["sensor"])
                name = SENSOR_NAMES.get(sec["sensor"], sec["sensor"].replace("hwmon:", "").replace(":", " "))
                from iridia.sensors import unit_of
                txt += "\n" + name + (f": {v:g} {unit_of(sec['sensor'])}" if v is not None else "")
            if lbl.get_label() != txt:
                lbl.set_label(txt)

    def _update_sizes(self):
        split = len(self.secs) > 1
        self._even_btn.set_visible(split)
        sz = S.sizes(self.secs, self.n) if split else []
        self._sizes.set_label(_("{leds} LEDs: {sizes}").format(leds=self.n, sizes=" + ".join(map(str, sz)))
                              if split else _("Add a divider to split this strip into parts."))
        note = S.split_note(sz, self.n) if split else None
        txt = ""
        if note and note[0] == "near":
            txt = ngettext("The parts are {n} LED apart. Space evenly makes them match.",
                           "The parts are {n} LEDs apart. Space evenly makes them match.", note[1]).format(n=note[1])
        elif note and note[0] == "uneven":
            txt = ngettext("{leds} LEDs don't split into {parts} evenly, so the first part gets 1 more LED.",
                           "{leds} LEDs don't split into {parts} evenly, so the first {extra} parts get 1 more LED.",
                           note[1]).format(leds=self.n, parts=len(sz), extra=note[1])
        self._warn.set_label(txt)
        self._warn.set_visible(bool(txt))
        self._even_btn.set_sensitive(split and sorted(sz, reverse=True) != [
            self.n // len(sz) + (1 if i < self.n % len(sz) else 0) for i in range(len(sz))])
        n_ov = len(self.ov)
        self._ov_lbl.set_label(ngettext("{n} LED set", "{n} LEDs set", n_ov).format(n=n_ov) if n_ov else "")
        self._clear_btn.set_visible(bool(n_ov))

    def _settings(self, anchor, k):
        sec = self.secs[k]
        pop = Gtk.Popover()
        pop.set_parent(anchor)
        box = vbox(8)
        box.set_size_request(380, -1)
        box.append(label(_("Part {n}").format(n=k + 1), ("subheading",)))

        def picker(max_sel):
            return SwatchPicker(self.card.extracted, list(sec.get("colors") or [0]),
                                lambda sel: self._set_part(k, colors=list(sel)), custom=self.card.custom,
                                max_select=max_sel, size=28, hint=False)
        from iridia.ui.zonecard import PATTERN_NAMES
        if sec["type"] == "sensor":
            box.append(label(_("Finding sensors…"), ("small", "dim")))
            self.card.app.bg(lambda: self.card.client.sensors(),
                             lambda r: self._sensor_settings(box, k, r.get("sensors") or [] if r.get("ok") else []))
        elif sec["type"] == "pattern":
            names = [PATTERN_NAMES[p] for p in PART_PATTERNS]
            holder = vbox(6)

            def on_pattern(name):
                pat = next((p for p in PART_PATTERNS if PATTERN_NAMES[p] == name), "solid")
                self._set_part(k, pattern=pat, params={})
                _swap(holder, picker(1 if pat == "solid" else 8))
            box.append(hbox(8, label(_("Pattern"), ("small", "dim")),
                            Dropdown(names, PATTERN_NAMES[sec.get("pattern", "solid")], on_pattern)))
            holder.append(picker(1 if sec.get("pattern", "solid") == "solid" else 8))
            box.append(holder)
        else:
            anim = dict(sec.get("animation") or animations.defaults("breathing"))
            ctl = fx.EffectControls(lambda p: self._set_part(k, animation=p), show_layout=False)

            def on_effect(name):
                eff = fx.EFFECT_KEYS.get(name)
                if eff:
                    a = animations.defaults(eff)
                    self._set_part(k, animation=a)
                    ctl.set_effect(a)
            box.append(hbox(8, label(_("Effect"), ("small", "dim")),
                            Dropdown([fx.EFFECT_NAMES[e] for e in animations.ORDER], fx.EFFECT_NAMES[anim["effect"]],
                                     on_effect)))
            box.append(picker(8))
            ctl.set_effect(anim)
            box.append(ctl)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                max_content_height=520)
        sc.set_child(box)
        pop.set_child(sc)
        pop.connect("closed", lambda p: GLib.idle_add(lambda: (p.unparent(), False)[1]))
        pop.popup()

    def _sensor_settings(self, box, k, found):
        """The sensor popover, once the daemon said which sensors there are."""
        if k >= len(self.secs):
            return
        sec = self.secs[k]
        title = box.get_first_child()
        c = title.get_next_sibling()
        while c:                                    # drop "Finding sensors…"
            nxt = c.get_next_sibling()
            box.remove(c)
            c = nxt
        from iridia.sensors import default_range, unit_of
        names = {}
        for f in found:
            nm = SENSOR_NAMES.get(f["id"], f["name"])
            if f.get("value") is not None:
                nm += f"  ({f['value']:g} {f['unit']})"
            names[nm] = f["id"]
        if sec["sensor"] not in names.values():
            names[SENSOR_NAMES.get(sec["sensor"], sec["sensor"]) + "  " + _("(not found here)")] = sec["sensor"]
        cur = next(n for n, i in names.items() if i == sec["sensor"])
        unit = unit_of(sec["sensor"])
        lo_spin = Spin(-50, 200, sec["min"], lambda v: self._set_part(k, min=float(v)))
        hi_spin = Spin(-50, 200, sec["max"], lambda v: self._set_part(k, max=float(v)))

        def on_sensor(name):
            sid = names.get(name)
            if sid and sid != self.secs[k]["sensor"]:
                lo, hi = default_range(sid)
                self._set_part(k, sensor=sid, min=lo, max=hi)
                lo_spin.set_quiet(lo)
                hi_spin.set_quiet(hi)
        box.append(hbox(8, label(_("Sensor"), ("small", "dim")), Dropdown(list(names), cur, on_sensor)))
        if any(f.get("wakes_gpu") and f["id"] == sec["sensor"] for f in found):
            box.append(label(_("NVIDIA readings come from nvidia-smi, which keeps a laptop's GPU awake while a "
                               "strip shows them."), ("tiny", "faint")))
        box.append(hbox(8, label(_("Show"), ("small", "dim")),
                        Group([("level", _("Level")), ("color", _("Color")), ("both", _("Both"))], sec["show"],
                              lambda v: self._set_part(k, show=v))))
        box.append(label(_("Level fills the part like a bar, Color shows the reading as one color, Both is a bar in "
                           "the reading's color."), ("tiny", "faint")))
        box.append(hbox(8, label(_("From"), ("small", "dim")), lo_spin, label(_("to"), ("small", "dim")), hi_spin,
                        label(unit, ("small", "dim"))))
        holder = vbox(6)

        def show_picker(pal):
            _swap(holder, SwatchPicker(self.card.extracted, list(self.secs[k].get("colors") or [0]),
                                       lambda sel: self._set_part(k, colors=list(sel)), custom=self.card.custom,
                                       max_select=8, size=28, hint=False) if pal == "colors" else Gtk.Box())

        def on_palette(pal):
            self._set_part(k, palette=pal)
            show_picker(pal)
        box.append(hbox(8, label(_("Colors"), ("small", "dim")),
                        Group([("heat", _("Cool to hot")), ("colors", _("Picked colors"))], sec["palette"],
                              on_palette)))
        box.append(holder)
        show_picker(sec["palette"])
        box.append(hbox(8, label(_("Rest of the bar"), ("small", "dim")),
                        Group([("off", _("Off")), ("dim", _("Dim"))], sec["background"],
                              lambda v: self._set_part(k, background=v))))
        fl = sec.get("flash_above")
        fl_spin = Spin(-50, 200, fl if fl is not None else sec["max"] - 5,
                       lambda v: self._set_part(k, flash_above=float(v)) if self.secs[k].get("flash_above")
                       is not None else None)
        row, _sw = switch_row(_("Flash above"), fl is not None,
                              lambda on: self._set_part(k, flash_above=float(fl_spin.get_value()) if on else None))
        box.append(hbox(8, row, fl_spin, label(unit, ("small", "dim"))))
        row, _sw = switch_row(_("From the other end"), bool((sec.get("params") or {}).get("reverse")),
                              lambda on: self._set_part(k, params={"reverse": True} if on else {}))
        box.append(row)

    def _set_part(self, k, **fields):
        if k >= len(self.secs):
            return
        merged = dict(self.secs[k], **fields)
        start = merged["start"]
        self.secs[k] = dict(S.clean_section(merged), start=start)
        self._changed()
        self._update_row_labels()

    # ------------------------------------------------------------ single LEDs
    def _toggle_pick(self):
        on = not self.strip.pick_mode
        self.strip.set_pick(on)
        set_button_text(self._pick_btn, _("Done") if on else _("Set LEDs"), "check" if on else "colorize")
        (self._pick_btn.add_css_class if on else self._pick_btn.remove_css_class)("toggled")

    def _set_tool(self, tool):
        self.tool = tool
        if not self.strip.pick_mode:
            self._toggle_pick()

    def _pick_paint(self):
        def done(h):
            if h:
                self.paint = h
                self._well.set_state(hex6=h)
                self._tools.set_active("color")
                self.tool = "color"
        self.card.app.pick_color(self.paint, _("Color for single LEDs"), done, sent_fn=self.card._sent_fn())

    def _on_led(self, i):
        if self.tool == "clear":
            if self.ov.pop(i, None) is None:
                return
        else:
            h = "000000" if self.tool == "off" else self.paint
            if self.ov.get(i) == h:
                return
            self.ov[i] = h
        self._changed(delay=300)

    def _clear_overrides(self):
        self.ov = {}
        self._changed()

    # ------------------------------------------------------------ saving
    def _changed(self, rows=False, delay=150):
        if rows:
            self._rebuild_rows()
        self.card._after_sections_change()
        if self._save_job:
            GLib.source_remove(self._save_job)
        self._save_job = GLib.timeout_add(delay, self._save)

    def _save(self):
        self._save_job = None
        secs = [dict(s) for s in self.secs]
        ov = S.overrides_for_config(self.ov)
        c = self.card
        c._call(lambda: c.client.set_zone_sections(c.device_name, c.zone_name, sections=secs, led_overrides=ov))
        return False


def _swap(holder, child):
    c = holder.get_first_child()
    while c:
        nxt = c.get_next_sibling()
        holder.remove(c)
        c = nxt
    holder.append(child)
