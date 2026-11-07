"""The Favourites tab: the controls you use most, from all over Iridia, as tiles you arrange yourself.

A tile is a strip (on/off, brightness, colour), a look (one tap on, one tap back), a saved setup, or a
switch (all lights, freeze, night mode, animations, scenes, notification flashes, network lights). The
tiles and the looks live in the daemon's config (iridia/looks.py), so setups and backups keep them.
"""

from typing import Optional

from gi.repository import Gtk

from iridia.i18n import _
from iridia.ui import widgets
from iridia.ui.layout_notify import MiniSlider
from iridia.ui.scenes_tab import LookEditor, look_text
from iridia.ui.widgets import (Swatch, Toggle, button, card, hbox, icon, label, section, vbox, wrap_row)

SWITCH_NAMES = {
    "lights": (_("All lights"), "lightbulb"),
    "freeze": (_("Freeze colours"), "ac_unit"),
    "night": (_("Night mode"), "bedtime"),
    "animations": (_("Animations"), "motion_photos_on"),
    "scenes": (_("Scenes (fullscreen)"), "sports_esports"),
    "notify": (_("Notification flashes"), "bolt"),
    "netlights": (_("Network lights"), "wifi"),
}
TILE_W = {"s": 250, "w": 520}


def switch_state(what: str, st: dict) -> bool:
    if what == "lights":
        return not st.get("lights_off")
    if what == "freeze":
        return bool(st.get("frozen"))
    if what == "night":
        return bool((st.get("night") or {}).get("enabled"))
    if what == "animations":
        return not (st.get("animations") or {}).get("paused")
    return bool((st.get(what) or {}).get("enabled"))


class FavoritesPage:
    def __init__(self, app, page: Gtk.Box):
        self.app = app
        self._st: dict = {}
        self._tiles_now = None          # what the grid shows (rebuilt when it changes)
        self._editing = False
        self._look_edit: Optional[dict] = None
        self._live = {}                 # tile id -> function(status) that refreshes it in place
        page.append(section(_("Favourites"), _("The controls you use most, from everywhere in Iridia: strips, your own "
                                               "looks, setups and switches. Add them, then arrange them as you like."),
                            top=4))
        bar = wrap_row(8)
        bar.append(button(_("Add"), "add", "filled small", self._toggle_add))
        bar.append(button(_("New look"), "palette", "tonal small", lambda: self._open_look(None)))
        self._edit_btn = button(_("Arrange"), "edit", "tonal small", self._toggle_edit)
        bar.append(self._edit_btn)
        page.append(bar)

        # the look editor (a new look, or one being changed)
        self._look_card = card()
        self._look_card.set_visible(False)
        page.append(self._look_card)
        # what can be added
        self._add_card = card()
        self._add_card.set_visible(False)
        page.append(self._add_card)

        self._empty = card()
        self._empty.append(label(_("Nothing here yet"), ("heading",)))
        self._empty.append(label(_("Add a strip to switch it and set its brightness and colour from here, your own "
                                   "looks (like \"Movie: everything at 15%\") to switch with one tap, setups, and "
                                   "switches like all lights or night mode. A strip's ★ on the Devices tab adds it "
                                   "too."), ("small", "dim"), wrap=True))
        self._empty.append(hbox(8, button(_("Add"), "add", "filled small", self._toggle_add),
                                button(_("New look"), "palette", "tonal small", lambda: self._open_look(None))))
        page.append(self._empty)
        self._grid = wrap_row(12)
        self._grid.set_max_children_per_line(8)
        page.append(self._grid)

    # ---------------------------------------------------------------- status
    def update_status(self, st):
        if not st or "_error" in st:
            return
        self._st = st
        tiles = st.get("favorites") or []
        key = (repr(tiles), self._editing, repr([(lk["id"], lk["name"], lk["look"]) for lk in st.get("looks") or []]),
               repr(sorted((st.get("device_configs") or {}).keys())))
        if key != self._tiles_now:
            self._tiles_now = key
            self._rebuild(tiles)
        for fn in self._live.values():
            fn(st)
        self._empty.set_visible(not tiles)
        if self._add_card.get_visible():
            self._fill_add()

    def favorites(self) -> list:
        return list(self._st.get("favorites") or [])

    def has_device(self, key: str) -> bool:
        return any(t.get("type") == "device" and t.get("key") == key for t in self.favorites())

    def toggle_device(self, key: str):
        """The ★ on a strip's card."""
        if self.has_device(key):
            self._send(remove=f"device:{key}")
        else:
            self._send(add={"type": "device", "key": key})

    # ---------------------------------------------------------------- talking to the daemon
    def _send(self, **kw):
        def done(r):
            if not r.get("ok"):
                self.app.toast(r.get("error") or _("Couldn't save"))
            if r.get("favorites") is not None:
                self.update_status(dict(self._st, favorites=r["favorites"], looks=r.get("looks", self._st.get("looks"))))
        self.app.bg(lambda: self.app.client.favorites(**kw), done)

    def _looks_send(self, after=None, **kw):
        def done(r):
            if not r.get("ok"):
                self.app.toast(r.get("error") or _("Couldn't save"))
                return
            self.update_status(dict(self._st, looks=r.get("looks"), favorites=r.get("favorites")))
            if after:
                after(r)
        self.app.bg(lambda: self.app.client.looks(**kw), done)

    def _do(self, fn, msg=None):
        """A switch or a load: run it, then show the new state."""
        def done(r):
            if isinstance(r, dict) and r.get("ok") is False:
                self.app.toast(r.get("error") or _("Couldn't do that"))
            elif msg:
                self.app.toast(msg)
            self.app._poll_once()
        self.app.bg(fn, done)

    # ---------------------------------------------------------------- the grid
    def _rebuild(self, tiles):
        widgets.clear(self._grid)
        self._live = {}
        looks = {lk["id"]: lk for lk in self._st.get("looks") or []}
        for i, t in enumerate(tiles):
            w = self._tile(t, looks)
            if w is None:
                continue
            w.set_size_request(TILE_W[t.get("size", "s")], -1)
            if self._editing:
                w.append(self._edit_bar(i, t, len(tiles)))
            self._grid.append(w)

    def _tile(self, t, looks):
        typ = t["type"]
        if typ == "device":
            return self._device_tile(t)
        if typ == "look":
            lk = looks.get(t["id"])
            return self._look_tile(t, lk) if lk else None
        if typ == "setup":
            return self._setup_tile(t)
        return self._switch_tile(t)

    def _frame(self, ico, title, sub=""):
        c = card()
        c.add_css_class("tile")
        head = hbox(10, icon(ico, classes=("dim",)))
        txt = vbox(0, hexpand=True)
        txt.append(label(title, ("heading",), ellipsize=True))
        if sub:
            txt.append(label(sub, ("small", "dim"), ellipsize=True))
        head.append(txt)
        c.append(head)
        return c, head

    def _device_tile(self, t):
        dev, _sep, zone = t["key"].partition("|")
        zc = self._zone_cfg(dev, zone)
        if zc is None:
            c, _h = self._frame("lightbulb", t["key"].rstrip("|"), _("Not there any more"))
            return c
        name = zc.get("display_name") or zone or dev
        c, head = self._frame("lightbulb", name, dev if zone else "")
        sw = Toggle(bool(zc.get("enabled", True)),
                    lambda v: self._do(lambda: self.app.client.set_zone_enabled(dev, zone, v)))
        head.append(sw)
        bright = MiniSlider("", 0, 100, int(zc.get("manual_brightness", 100)), 5, "%",
                            lambda v: self._do(lambda: self.app.client.set_zone_manual_brightness(dev, zone, int(v))))
        c.append(bright)
        note = label("", ("small", "faint"))
        c.append(note)
        sw_row = hbox(6)
        c.append(sw_row)
        shown = [None]

        def colours(st):
            z = self._zone_cfg(dev, zone, st) or {}
            sw.set_value(bool(z.get("enabled", True)))
            bright.set_quiet(int(z.get("manual_brightness", 100)))
            note.set_label(_("Follows the monitor's brightness") if z.get("brightness_sync") else "")
            note.set_visible(bool(z.get("brightness_sync")))
            ext = list(st.get("extracted_colors") or [])[: (6 if t.get("size") == "w" else 4)]
            saved = list(st.get("custom_colors") or [])[: (5 if t.get("size") == "w" else 2)]
            cur = (z.get("pattern_colors") or [0])[0]
            sig = (tuple(ext), tuple(saved), repr(cur))
            if sig == shown[0]:
                return
            shown[0] = sig
            widgets.clear(sw_row)
            for i, h in enumerate(ext):
                sw_row.append(Swatch(h, 28, selected=cur == i, tooltip=_("Wallpaper colour {n}").format(n=i + 1),
                                     on_click=lambda i=i: self._set_colour(dev, zone, i)))
            for h in saved:
                sw_row.append(Swatch(h, 28, selected=cur == h, tooltip=_("Saved colour"),
                                     on_click=lambda h=h: self._set_colour(dev, zone, h)))
            sw_row.append(Swatch("444444", 28, add=True, tooltip=_("Pick a colour"),
                                 on_click=lambda: self._pick_colour(dev, zone, name)))
        self._live[f"device:{t['key']}"] = colours
        colours(self._st)
        return c

    def _set_colour(self, dev, zone, c):
        self._do(lambda: self.app.client.set_zone_colors(dev, zone, [c]))

    def _pick_colour(self, dev, zone, name):
        def done(h):
            if h:
                self._set_colour(dev, zone, h)
        self.app.pick_color("ffffff", _("Colour for {name}").format(name=name), done)

    def _look_tile(self, t, lk):
        c, head = self._frame("palette", lk["name"], self._look_where(lk) + " · " + look_text(lk["look"]))
        btn = button(_("Turn on"), "play_arrow", "tonal small",
                     lambda: self._looks_send(apply={"look": lk["id"], "on": "toggle"}))
        c.append(btn)

        def live(st):
            on = next((x.get("active") for x in st.get("looks") or [] if x["id"] == lk["id"]), False)
            widgets.set_button_text(btn, _("On: tap to go back") if on else _("Turn on"))
            for cls in ("filled", "tonal"):
                btn.remove_css_class(cls)
            btn.add_css_class("filled" if on else "tonal")
        self._live[f"look:{lk['id']}"] = live
        live(self._st)
        return c

    def _look_where(self, lk) -> str:
        if lk["targets"] == ["*"]:
            return _("Everything")
        n = len(lk["targets"])
        if n == 1:
            dev, _s, zone = lk["targets"][0].partition("|")
            zc = self._zone_cfg(dev, zone) or {}
            return zc.get("display_name") or zone or dev
        return _("{n} strips").format(n=n)

    def _setup_tile(self, t):
        c, _h = self._frame("settings_backup_restore", t["name"], _("Setup"))
        c.append(button(_("Load"), "upload", "tonal small",
                        lambda: self._do(lambda: self.app.client.setup("load", name=t["name"]),
                                         _("Loaded {name} (the settings before were backed up)").format(name=t["name"]))))
        return c

    def _switch_tile(self, t):
        what = t["what"]
        text, ico = SWITCH_NAMES[what]
        c, head = self._frame(ico, text)
        sw = Toggle(switch_state(what, self._st), lambda v: self._switch(what, v))
        head.append(sw)
        self._live[f"switch:{what}"] = lambda st: sw.set_value(switch_state(what, st))
        return c

    def _switch(self, what, v):
        cl = self.app.client
        fn = {"lights": lambda: cl.lights(v), "freeze": lambda: cl.freeze(v),
              "night": lambda: cl.set_night(enabled=v),
              "animations": lambda: cl.animations(action="resume" if v else "pause"),
              "scenes": lambda: cl.scenes(enabled=v), "notify": lambda: cl.notify(enabled=v),
              "netlights": lambda: cl.netlights(enabled=v)}[what]
        self._do(fn)

    # ---------------------------------------------------------------- arranging
    def _toggle_edit(self):
        self._editing = not self._editing
        widgets.set_button_text(self._edit_btn, _("Done") if self._editing else _("Arrange"))
        self._tiles_now = None
        self.update_status(self._st)

    def _edit_bar(self, i, t, n):
        bar = hbox(4)
        bar.set_margin_top(6)
        left = button(None, "chevron_left", "flat small", lambda: self._move(i, -1), tooltip=_("Move left"))
        right = button(None, "chevron_right", "flat small", lambda: self._move(i, 1), tooltip=_("Move right"))
        left.set_sensitive(i > 0)
        right.set_sensitive(i < n - 1)
        wide = t.get("size") == "w"
        size = button(None, "close_fullscreen" if wide else "open_in_full", "flat small", lambda: self._resize(i),
                      tooltip=_("Smaller") if wide else _("Wider"))
        bar.append(left)
        bar.append(right)
        bar.append(size)
        if t["type"] == "look":
            lk = next((x for x in self._st.get("looks") or [] if x["id"] == t["id"]), None)
            if lk:
                bar.append(button(None, "edit", "flat small", lambda: self._open_look(lk), tooltip=_("Change this look")))
        bar.append(Gtk.Box(hexpand=True))
        bar.append(button(None, "close", "flat small", lambda: self._remove(i), tooltip=_("Take off Favourites")))
        return bar

    def _move(self, i, d):
        tiles = self.favorites()
        j = i + d
        if 0 <= j < len(tiles):
            tiles[i], tiles[j] = tiles[j], tiles[i]
            self._send(set=tiles)

    def _resize(self, i):
        tiles = self.favorites()
        tiles[i] = dict(tiles[i], size="s" if tiles[i].get("size") == "w" else "w")
        self._send(set=tiles)

    def _remove(self, i):
        tiles = self.favorites()
        del tiles[i]
        self._send(set=tiles)

    # ---------------------------------------------------------------- adding
    def _toggle_add(self):
        show = not self._add_card.get_visible()
        self._add_card.set_visible(show)
        if show:
            self._setups = None
            self.app.bg(lambda: self.app.client.setup("list"),
                        lambda r: (setattr(self, "_setups", [s["name"] for s in r.get("setups") or []]),
                                   self._fill_add()))
            self._fill_add()

    def _fill_add(self):
        from iridia.looks import tile_id
        c = self._add_card
        widgets.clear(c)
        have = {tile_id(t) for t in self.favorites()}
        head = hbox(8, label(_("Add to Favourites"), ("heading",)))
        head.append(Gtk.Box(hexpand=True))
        head.append(button(None, "close", "flat small", self._toggle_add, tooltip=_("Close")))
        c.append(head)

        def group(title, items):
            c.append(label(title, ("body",)))
            row = wrap_row(6)
            for text, tile in items:
                b = button(text, "add", "tonal small", lambda tile=tile: self._send(add=tile))
                b.set_sensitive(tile_id(tile) not in have)
                row.append(b)
            if not items:
                row.append(label(_("None yet."), ("small", "faint")))
            c.append(row)
        strips = []
        for dev, dc in sorted((self._st.get("device_configs") or {}).items()):
            zones = dc.get("zones") if isinstance(dc, dict) else None
            for zn, zc in (zones.items() if isinstance(zones, dict) and zones else [("", dc)]):
                if isinstance(zc, dict):
                    nm = zc.get("display_name") or zn or dev
                    strips.append((nm if not zn or nm == dev else f"{dev} · {nm}", {"type": "device", "key": f"{dev}|{zn}"}))
        group(_("Strips and lights"), strips)
        looks = [(lk["name"], {"type": "look", "id": lk["id"]}) for lk in self._st.get("looks") or []]
        group(_("Your looks"), looks)
        c.append(button(_("New look"), "palette", "text small", lambda: self._open_look(None)))
        group(_("Setups"), [(n, {"type": "setup", "name": n}) for n in (getattr(self, "_setups", None) or [])])
        group(_("Switches"), [(SWITCH_NAMES[w][0], {"type": "switch", "what": w}) for w in SWITCH_NAMES])

    # ---------------------------------------------------------------- the look editor
    def _open_look(self, lk: Optional[dict]):
        self._look_edit = dict(lk) if lk else None
        c = self._look_card
        widgets.clear(c)
        c.append(label(_("Change this look") if lk else _("New look"), ("heading",)))
        c.append(label(_("One tap puts it on its strips, one more tap puts them back; your settings don't change. "
                         "From a key: iridia look \"NAME\"."), ("small", "dim"), wrap=True))
        self._look_name = Gtk.Entry(placeholder_text=_("Name, like Movie or Gaming"), hexpand=True)
        self._look_name.set_text(lk["name"] if lk else "")
        c.append(self._look_name)
        c.append(label(_("Which strips"), ("body",)))
        targets = set(lk["targets"]) if lk else {"*"}
        self._look_all = Gtk.CheckButton(label=_("Everything"), active="*" in targets)
        c.append(self._look_all)
        row = wrap_row(6)
        self._look_checks = {}
        for dev, dc in sorted((self._st.get("device_configs") or {}).items()):
            zones = dc.get("zones") if isinstance(dc, dict) else None
            for zn, zc in (zones.items() if isinstance(zones, dict) and zones else [("", dc)]):
                key = f"{dev}|{zn}"
                nm = (zc.get("display_name") if isinstance(zc, dict) else None) or zn or dev
                cb = Gtk.CheckButton(label=nm if not zn else f"{dev} · {nm}", active=key in targets)
                self._look_checks[key] = cb
                row.append(cb)
        c.append(row)

        def sync(*_a):
            row.set_sensitive(not self._look_all.get_active())
        self._look_all.connect("toggled", sync)
        sync()
        c.append(label(_("What they do"), ("body",)))
        self._look_editor = LookEditor(self.app, (lk or {}).get("look") or {"kind": "dim", "bright": 20},
                                       lambda _l: None, allow_none=False,
                                       on_try=self._try_look)
        c.append(self._look_editor)
        bar = hbox(8, button(_("Save"), "check", "filled small", self._save_look),
                   button(_("Cancel"), None, "text small", lambda: c.set_visible(False)))
        if lk:
            bar.append(Gtk.Box(hexpand=True))
            bar.append(button(_("Delete"), "delete", "danger small", lambda: self._delete_look(lk)))
        c.append(bar)
        c.set_visible(True)
        self._look_name.grab_focus()

    def _targets(self):
        return ["*"] if self._look_all.get_active() else [k for k, cb in self._look_checks.items() if cb.get_active()]

    def _try_look(self, look):
        targets = self._targets()
        if not targets:
            self.app.toast(_("Pick the strips it's for, or Everything."))
            return
        self.app.bg(lambda: self.app.client.looks(**{"try": {"targets": targets, "look": look}}),
                    lambda r: self.app.toast(_("Showing it for 5 seconds.") if r.get("ok") else
                                             (r.get("error") or _("Couldn't show it"))))

    def _save_look(self):
        name = self._look_name.get_text().strip()
        if not name:
            self.app.toast(_("Give the look a name."))
            return
        targets = self._targets()
        if not targets:
            self.app.toast(_("Pick the strips it's for, or Everything."))
            return
        lk = {"name": name, "targets": targets, "look": self._look_editor.get()}
        new = self._look_edit is None
        if not new:
            lk["id"] = self._look_edit["id"]

        def after(r):
            self._look_card.set_visible(False)
            if new:                                     # a new look goes straight onto Favourites
                made = next((x for x in r.get("looks") or [] if x["name"].lower() == name.lower()), None)
                if made:
                    self._send(add={"type": "look", "id": made["id"]})
        self._looks_send(after, set=lk)

    def _delete_look(self, lk):
        self._look_card.set_visible(False)
        self._looks_send(remove=lk["id"])

    # ---------------------------------------------------------------- helpers
    def _zone_cfg(self, dev, zone, st=None) -> Optional[dict]:
        dc = ((st or self._st).get("device_configs") or {}).get(dev)
        if not isinstance(dc, dict):
            return None
        zones = dc.get("zones")
        if zone:
            z = zones.get(zone) if isinstance(zones, dict) else None
            return z if isinstance(z, dict) else None
        return None if isinstance(zones, dict) and zones else dc
