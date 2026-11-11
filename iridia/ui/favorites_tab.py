"""The Favourites tab: a quick panel you build yourself.

It holds cards (a title, some strips or all of them, and the controls you want for them: on/off,
brightness, colours with a picker in a popup, follow the monitor, stay lit when locked, an effect, look
chips, switch chips), single looks, setups and switches, in a grid of square cells: each item is small
(1x1), wide (2x1), tall (1x2) or large (2x2), and the grid fits the window's width. Arrange moves them by
drag and drop. Everything lives in the daemon's config (iridia/looks.py), so setups and backups keep it.
"""


from gi.repository import Gdk, GLib, GObject, Gtk

from iridia import animations
from iridia.i18n import _
from iridia.looks import CONTROLS, SPAN, SWITCHES
from iridia.ui import widgets
from iridia.ui.effects import EFFECT_KEYS, EFFECT_NAMES
from iridia.ui.layout_notify import MiniSlider
from iridia.ui.scenes_tab import LookEditor, look_text, strip_list
from iridia.ui.widgets import (Dropdown, Group, Swatch, Toggle, button, card, hbox, icon, label, section, vbox,
                               wrap_row)

SWITCH_NAMES = {
    "lights": (_("All lights"), "lightbulb"),
    "freeze": (_("Freeze colours"), "ac_unit"),
    "night": (_("Night mode"), "bedtime"),
    "animations": (_("Animations"), "motion_photos_on"),
    "scenes": (_("Scenes"), "sports_esports"),
    "notify": (_("Notification flashes"), "bolt"),
    "netlights": (_("Network lights"), "wifi"),
}
CONTROL_NAMES = {
    # what a card can show: (name, icon)
    "power": (_("On and off"), "power_settings_new"),
    "brightness": (_("Brightness"), "light_mode"),
    "colors": (_("Colours"), "palette"),
    "effect": (_("Effect"), "auto_awesome"),
    "follow": (_("Follow the monitor"), "monitor"),
    "control": (_("Iridia controls it"), "sync"),
    "stay_lit": (_("Stay lit when locked"), "lock"),
    "looks": (_("Looks"), "palette"),
    "scenes": (_("Scenes"), "sports_esports"),
    "switches": (_("Switches"), "tune"),
}
DEFAULT_SWITCHES = ("lights", "night", "freeze")
# a card's switch rows have room for a word or two (the full name is the tooltip)
SHORT_NAMES = {
    "follow": _("Monitor"), "stay_lit": _("Stay lit"), "control": _("Control"),
    "lights": _("Lights"), "freeze": _("Freeze"), "night": _("Night"), "animations": _("Effects"),
    "scenes": _("Scenes"), "notify": _("Flashes"), "netlights": _("Network"),
}    # a card with Switches but none picked
SIZE_NAMES = {"s": _("Small"), "w": _("Wide"), "t": _("Tall"), "l": _("Large")}
STATIC = _("Static")


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


class Board(Gtk.Grid):
    """Square cells, as many columns as fit; items span 1 or 2 cells each way and fill gaps in order."""

    CELL = 150
    ROW = 120               # a row's height
    GAP = 12

    def __init__(self):
        super().__init__(column_homogeneous=True, row_homogeneous=True, column_spacing=self.GAP,
                         row_spacing=self.GAP, hexpand=True)
        self._items: list = []
        self._cols = 2          # until it knows its width: few columns never squeeze a card
        self._width = 0
        self._cellmin = 0       # the narrowest a one-column card can be
        self._job = None
        self.add_tick_callback(self._tick)

    def set_items(self, items):
        """items: [(widget, size)], in order."""
        self._items = list(items)
        self._pack()

    def _avail(self) -> int:
        """The width there is to fill: the visible area (not the board's own width, which grows with
        its columns), less the page's margins on both sides."""
        sw = self.get_ancestor(Gtk.ScrolledWindow)
        if sw is None:
            return self.get_width()
        r = self.translate_coordinates(sw, 0, 0)       # (ok, x, y) or (x, y), by PyGObject version
        x = r[-2] if r and (len(r) == 2 or r[0]) else 0
        return sw.get_width() - 2 * int(x)

    def _tick(self, _w, _clock):
        """Each frame: the width there is now. A change in columns (or a big change in width, which
        changes how tall a card needs to be) repacks it, after this frame's layout."""
        width = self._avail()
        if width > 0 and self._job is None:
            cell = max(self.CELL, self._cellmin)
            cols = max(1, min(8, (width + self.GAP) // (cell + self.GAP)))
            if cols != self._cols or abs(width - self._width) > 40:
                self._cols, self._width = cols, width
                self._job = GLib.idle_add(self._repack)     # never change children while being laid out
        return True

    def _repack(self):
        self._job = None
        self._pack()
        return False

    def _pack(self):
        c = self.get_first_child()
        while c is not None:
            n = c.get_next_sibling()
            self.remove(c)
            c = n
        cols = self._cols
        used: set = set()
        for w, _size in self._items:
            w.set_size_request(-1, -1)
        self._cellmin = max([w.measure(Gtk.Orientation.HORIZONTAL, -1)[0] for w, size in self._items
                             if SPAN.get(size, (1, 1))[0] == 1] or [0])
        if self._width:
            # no more columns than fit with the narrowest a card can be
            cols = self._cols = max(1, min(cols, (self._width + self.GAP) // (max(self.CELL, self._cellmin)
                                                                              + self.GAP)))
        colw = max(self.CELL, (self._width - self.GAP * (cols - 1)) // cols) if self._width else self.CELL
        for w, size in self._items:
            sw, sh = SPAN.get(size, (1, 1))
            sw = min(sw, cols)
            # taller than its size when what's on it needs the room: nothing you picked is left out
            width = max(colw * sw + self.GAP * (sw - 1), w.measure(Gtk.Orientation.HORIZONTAL, -1)[0])
            need = w.measure(Gtk.Orientation.VERTICAL, width)[0]
            sh = max(sh, -(-(need + self.GAP) // (self.ROW + self.GAP)))
            row = 0
            while True:
                spot = next((col for col in range(cols - sw + 1)
                             if all((col + dx, row + dy) not in used for dx in range(sw) for dy in range(sh))), None)
                if spot is not None:
                    break
                row += 1
            for dx in range(sw):
                for dy in range(sh):
                    used.add((spot + dx, row + dy))
            w.set_size_request(-1, sh * self.ROW + (sh - 1) * self.GAP)
            self.attach(w, spot, row, sw, sh)
        # a gap of an empty row or column keeps every cell square-ish even with few items
        for col in range(cols):
            if not any(x == col for x, _y in used):
                filler = Gtk.Box()
                self.attach(filler, col, 0, 1, 1)


class FavoritesPage:
    def __init__(self, app, page: Gtk.Box):
        self.app = app
        self._st: dict = {}
        self._shown = None              # what the board shows (rebuilt when it changes)
        self._editing = False
        self._live = {}                 # item id -> function(status) refreshing it in place
        self._setups: list[str] | None = None
        page.append(section(_("Favourites"), _("Your quick panel: cards for the strips you choose with just the "
                                               "controls you want, looks, setups and switches. Drag them where you "
                                               "like in Arrange."), top=4))
        bar = wrap_row(8)
        bar.append(button(_("New card"), "add", "filled small", lambda: self._open_card(None)))
        bar.append(button(_("New look"), "palette", "tonal small", lambda: self._open_look(None)))
        bar.append(button(_("Add"), "add", "tonal small", self._toggle_add))
        self._edit_btn = button(_("Arrange"), "edit", "tonal small", self._toggle_edit)
        bar.append(self._edit_btn)
        page.append(bar)
        self._editor = card()           # the card or look being made or changed
        self._editor.set_visible(False)
        page.append(self._editor)
        self._add_card = card()
        self._add_card.set_visible(False)
        page.append(self._add_card)
        self._empty = card()
        self._empty.append(label(_("Nothing here yet"), ("heading",)))
        self._empty.append(label(_("Make a card for some strips (or all of them) with the controls you want on it: "
                                   "on and off, brightness, colours, follow the monitor, an effect, your looks, "
                                   "switches. Or add a look, a setup or a switch on its own. A strip's ★ on the "
                                   "Devices tab makes a card for it."), ("small", "dim"), wrap=True))
        self._empty.append(hbox(8, button(_("New card"), "add", "filled small", lambda: self._open_card(None)),
                                button(_("New look"), "palette", "tonal small", lambda: self._open_look(None))))
        page.append(self._empty)
        self._board = Board()
        page.append(self._board)

    # ---------------------------------------------------------------- status
    def update_status(self, st):
        if not st or "_error" in st:
            return
        self._st = st
        tiles = st.get("favorites") or []
        key = (repr(tiles), self._editing, repr([(lk["id"], lk["name"], lk["look"]) for lk in st.get("looks") or []]),
               repr(self._strips()),
               repr([(x["id"], x["name"]) for x in (st.get("scenes") or {}).get("scenes") or []]))
        if key != self._shown:
            self._shown = key
            self._rebuild(tiles)
        for fn in self._live.values():
            fn(st)
        self._empty.set_visible(not tiles)

    def favorites(self) -> list:
        return [dict(t) for t in self._st.get("favorites") or []]

    def has_device(self, key: str) -> bool:
        return any(t.get("type") == "card" and t.get("targets") == [key] for t in self.favorites())

    def toggle_device(self, key: str):
        """The ★ on a strip's card: a card for that strip, or away with it."""
        card_t = next((t for t in self.favorites() if t.get("type") == "card" and t.get("targets") == [key]), None)
        if card_t:
            self._send(remove=f"card:{card_t['id']}")
        else:
            self._send(add={"type": "card", "targets": [key], "controls": ["power", "brightness", "colors"],
                            "size": "w"})

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
        def done(r):
            if isinstance(r, dict) and r.get("ok") is False:
                self.app.toast(r.get("error") or _("Couldn't do that"))
            elif msg:
                self.app.toast(msg)
            self.app._poll_once()
        self.app.bg(fn, done)

    def _zones(self, targets, **changes):
        self._do(lambda: self.app.client.raw({"cmd": "set_zones", "targets": targets, "set": changes}))

    # ---------------------------------------------------------------- strips
    def _strips(self, with_hidden: bool = False) -> list:
        """[(zone key, name)] for every strip, without the hidden ones unless asked."""
        return strip_list(self._st, with_hidden)

    def _zone_cfg(self, key, st=None) -> dict | None:
        dev, _s, zone = key.partition("|")
        dc = ((st or self._st).get("device_configs") or {}).get(dev)
        if not isinstance(dc, dict):
            return None
        zones = dc.get("zones")
        if zone:
            z = zones.get(zone) if isinstance(zones, dict) else None
            return z if isinstance(z, dict) else None
        return None if isinstance(zones, dict) and zones else dc

    def _keys(self, targets, st=None) -> list:
        if targets == ["*"]:
            return [k for k, _n in self._strips()]
        return [k for k in targets if self._zone_cfg(k, st) is not None]

    def _title(self, t) -> str:
        if t.get("title"):
            return t["title"]
        if t["targets"] == ["*"]:
            return _("Everything")
        if len(t["targets"]) == 1:
            zc = self._zone_cfg(t["targets"][0]) or {}
            dev, _s, zone = t["targets"][0].partition("|")
            return zc.get("display_name") or zone or dev
        return _("{n} strips").format(n=len(t["targets"]))

    # ---------------------------------------------------------------- the board
    def _rebuild(self, tiles):
        self._live = {}
        looks = {lk["id"]: lk for lk in self._st.get("looks") or []}
        items = []
        for i, t in enumerate(tiles):
            w = self._item(t, looks)
            if w is None:
                continue
            if self._editing:
                w.append(self._edit_bar(i, t))
                self._dnd(w, i)
            items.append((w, t.get("size", "s")))
        self._board.set_items(items)

    def _item(self, t, looks):
        typ = t["type"]
        if typ == "card":
            return self._card(t, looks)
        if typ == "look":
            lk = looks.get(t["id"])
            return self._look_tile(t, lk) if lk else None
        if typ == "setup":
            return self._setup_tile(t)
        return self._switch_tile(t)

    def _frame(self, ico, title, sub=""):
        c = card()
        c.add_css_class("tile")
        head = hbox(8, icon(ico, classes=("dim",)))
        txt = vbox(0, hexpand=True)
        txt.append(label(title, ("heading",), ellipsize=True))
        if sub:
            txt.append(label(sub, ("small", "dim"), ellipsize=True))
        head.append(txt)
        c.append(head)
        return c, head

    # -- a card
    def _card(self, t, looks):
        small = t.get("size") == "s"
        keys = self._keys(t["targets"])
        sub = "" if small or t["targets"] == ["*"] or len(t["targets"]) == 1 else \
            ", ".join(n for k, n in self._strips(True) if k in t["targets"])[:60]
        c, head = self._frame("tune", self._title(t), sub)
        updaters = []
        tg = t["targets"]
        ctl = t["controls"]
        if not keys:
            c.append(label(_("Its strips aren't there any more."), ("small", "faint"), wrap=True))
        if not self._editing:
            # change it right here: the pencil, or a right-click where a small card has no room for one
            head.append(button(None, "edit", "text small", lambda: self._open_card(t),
                               tooltip=_("Change this card (or right-click it)")))
            rc = Gtk.GestureClick(button=3)
            rc.connect("released", lambda *_a: self._open_card(t))
            c.add_controller(rc)
        if "power" in ctl and keys:
            # the same round on/off button as on the Devices tab: pastel green on, red off
            pw = button(None, "power_settings_new", "text small power on", None)
            pw.set_valign(Gtk.Align.CENTER)
            pw.set_halign(Gtk.Align.CENTER)
            state = {"on": True}

            def show(on, pw=pw, state=state):
                state["on"] = on
                pw.remove_css_class("on" if not on else "off")
                pw.add_css_class("on" if on else "off")
                pw.set_tooltip_text(_("On: click to turn off") if on else _("Off: click to turn on"))

            def press(_b, state=state, show=show):
                show(not state["on"])
                self._zones(tg, enabled=state["on"])
            pw.connect("clicked", press)
            head.append(pw)
            updaters.append(lambda st, z, show=show: show(any(x.get("enabled", True) for x in z)))
        narrow = t.get("size") in ("s", "t")       # one column wide
        if "brightness" in ctl and keys:
            self._brightness_row(c, tg, narrow, updaters)
        if "colors" in ctl and keys:
            updaters.append(self._colours(c, tg, small, t))
        if "effect" in ctl and keys:
            self._effect_rows(c, tg, updaters)

        # everything that is on or off: a row each, its name and a switch, so it's plain which is which
        rows = []
        for key, field, invert in (("follow", "brightness_sync", False), ("stay_lit", "session_ignore", False),
                                   ("control", "hands_off", True)):
            if key in ctl and keys:
                name, ico = CONTROL_NAMES[key]

                def get(st, z, field=field, invert=invert):
                    v = all(bool(x.get(field)) for x in z)
                    return not any(bool(x.get(field)) for x in z) if invert else v
                rows.append((ico, SHORT_NAMES[key], name, get,
                             lambda v, field=field, invert=invert: self._zones(tg, **{field: (not v) if invert else v})))
        if "looks" in ctl:
            for lk in self._card_looks_of(t, looks):
                rows.append(("palette", lk["name"], lk["name"],
                             lambda st, z, lid=lk["id"]: any(x.get("active") for x in st.get("looks") or []
                                                             if x["id"] == lid),
                             lambda v, lid=lk["id"]: self._looks_send(apply={"look": lid, "on": v})))
        if "scenes" in ctl:
            for sc in self._card_scenes_of(t):
                rows.append(("sports_esports", sc["name"], sc["name"],
                             lambda st, z, sid=sc["id"]: any(x.get("on") for x in (st.get("scenes") or {}).get(
                                 "scenes") or [] if x["id"] == sid),
                             lambda v, sid=sc["id"]: self.app.bg(
                                 lambda: self.app.client.scenes(scene_on={"id": sid, "on": v}), self._done_scenes)))
        if "switches" in ctl:
            for w in t.get("switches") or DEFAULT_SWITCHES:
                text, ico = SWITCH_NAMES[w]
                rows.append((ico, SHORT_NAMES[w], text, lambda st, z, w=w: switch_state(w, st),
                             lambda v, w=w: self._switch(w, v)))
        if rows:
            grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=16,
                               row_spacing=2, min_children_per_line=1 if narrow else 2,
                               max_children_per_line=1 if narrow else 2)
            c.append(grid)
            for ico, short, name, get, put in rows:
                sw = Toggle(False, put)
                lbl = label(short, ("body",), ellipsize=True)      # short: a word or two fits any size
                lbl.set_hexpand(True)
                lbl.set_tooltip_text(name)
                sw.set_tooltip_text(name)
                grid.append(hbox(10, icon(ico, classes=("dim",)), lbl, sw))
                updaters.append(lambda st, z, sw=sw, get=get: sw.set_value(get(st, z)))

        def live(st):
            z = [self._zone_cfg(k, st) or {} for k in self._keys(tg, st)] or [{}]
            for u in updaters:
                u(st, z)
        self._live[f"card:{t['id']}"] = live
        live(self._st)
        return c

    def _brightness_row(self, c, tg, narrow, updaters):
        """Brightness: a slider with its value. While the strips follow the monitor it shows the monitor's
        level (Auto); moving it sets their own brightness and stops following, as on a phone."""
        row = hbox(10, icon("light_mode", classes=("dim",)))
        row.set_tooltip_text(_("Brightness"))
        sl = MiniSlider("", 0, 100, 100, 5, "%", lambda v: self._zones(tg, brightness=int(v), brightness_sync=False))
        sl.set_hexpand(True)
        sl.scale.set_size_request(60 if narrow else 110, -1)
        sl._lbl.set_width_chars(5)
        row.append(sl)
        c.append(row)
        note = label(_("Follows the monitor: move it to set your own"), ("small", "faint"), wrap=True)
        c.append(note)

        def upd(st, z):
            auto = all(x.get("brightness_sync") for x in z)
            level = st.get("brightness") if auto and isinstance(st.get("brightness"), (int, float)) else \
                round(sum(int(x.get("manual_brightness", 100)) for x in z) / len(z))
            sl.set_quiet(int(level))
            note.set_visible(auto)
        updaters.append(upd)

    def _effect_rows(self, c, tg, updaters):
        """The effect (or Static), and its speed, slow to fast, while there is one."""
        names = [STATIC] + list(EFFECT_NAMES.values())
        dd = Dropdown(names, STATIC, lambda v: self._zones(tg, effect=EFFECT_KEYS.get(v)))
        dd.set_hexpand(True)
        row = hbox(10, icon("auto_awesome", classes=("dim",)), dd)
        row.set_tooltip_text(_("Effect"))
        c.append(row)
        spd = MiniSlider("", 0, 100, 50, 5, "%", lambda v: self._zones(tg, speed=int(v)))
        spd.set_hexpand(True)
        spd.scale.set_size_request(60, -1)
        spd._lbl.set_width_chars(5)
        srow = hbox(10, icon("timer", classes=("dim",)), spd)
        srow.set_tooltip_text(_("Speed: slow to fast"))
        c.append(srow)

        def upd(st, z):
            a = animations.clean(z[0].get("animation"))
            dd.set_value(EFFECT_NAMES.get((a or {}).get("effect"), STATIC))
            srow.set_visible(a is not None)
            if a is not None:
                spd.set_quiet(animations.speed_level(a["effect"], a.get("speed", 0)))
        updaters.append(upd)

    def _card_looks_of(self, t, looks) -> list:
        """The looks a card shows: the ones picked, or every look when none are."""
        ids = t.get("looks") or list(looks)
        return [looks[i] for i in ids if i in looks]

    def _card_scenes_of(self, t) -> list:
        allsc = (self._st.get("scenes") or {}).get("scenes") or []
        ids = t.get("scenes") or [x["id"] for x in allsc]
        by = {x["id"]: x for x in allsc}
        return [by[i] for i in ids if i in by]

    def _colours(self, c, tg, small, t):
        """Swatches for the wallpaper's colours (a few), the current one ringed, and 🎨 for the rest."""
        row = hbox(6)
        outer = hbox(10, icon("palette", classes=("dim",)), row)
        outer.set_tooltip_text(_("Colour"))
        c.append(outer)
        shown = [None]
        pick = button(None, "palette", "tonal small", lambda: self._colour_popup(pick, tg, t), tooltip=_("All colours"))

        def upd(st, z):
            ext = list(st.get("extracted_colors") or [])
            n = 6 if t.get("size") in ("w", "l") else 3
            cur = (z[0].get("pattern_colors") or [0])[0]
            sig = (tuple(ext[:n]), repr(cur), n)
            if sig == shown[0]:
                return
            shown[0] = sig
            widgets.clear(row)
            for i, h in enumerate(ext[:n]):
                row.append(Swatch(h, 26, selected=cur == i, tooltip=_("Wallpaper colour {n}").format(n=i + 1),
                                  on_click=lambda i=i: self._zones(tg, color=i)))
            row.append(pick)
        return upd

    def _colour_popup(self, anchor, tg, t):
        """Every colour in a popup: the wallpaper's, your saved ones, and the colour wheel."""
        pop = Gtk.Popover()
        pop.set_parent(anchor)
        box = vbox(8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        def choose(col):
            pop.popdown()
            self._zones(tg, color=col)
        ext = list(self._st.get("extracted_colors") or [])
        if ext:
            box.append(label(_("Wallpaper colours"), ("small", "dim")))
            r = wrap_row(6)
            for i, h in enumerate(ext):
                r.append(Swatch(h, 30, on_click=lambda i=i: choose(i)))
            box.append(r)
        saved = list(self._st.get("custom_colors") or [])
        if saved:
            box.append(label(_("Saved colours"), ("small", "dim")))
            r = wrap_row(6)
            for h in saved:
                r.append(Swatch(h, 30, on_click=lambda h=h: choose(h)))
            box.append(r)

        def wheel():
            pop.popdown()

            def done(h):
                if h:
                    self._zones(tg, color=h)
            self.app.pick_color("ffffff", _("Colour for {name}").format(name=self._title(t)), done)
        box.append(button(_("Colour wheel…"), "palette", "tonal small", wheel))
        pop.set_child(box)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _done_scenes(self, r):
        if not r.get("ok"):
            self.app.toast(r.get("error") or _("Couldn't save"))

    def _look_tile(self, t, lk):
        small = t.get("size") == "s"
        c, _head = self._frame("palette", lk["name"], "" if small else self._look_where(lk) + " · " + look_text(lk["look"]))
        btn = button(_("Turn on"), None, "tonal small",
                     lambda: self._looks_send(apply={"look": lk["id"], "on": "toggle"}))
        btn.set_vexpand(True)
        c.append(btn)

        def live(st):
            on = next((x.get("active") for x in st.get("looks") or [] if x["id"] == lk["id"]), False)
            widgets.set_button_text(btn, (_("On") if small else _("On: tap to go back")) if on else _("Turn on"))
            for cls in ("filled", "tonal"):
                btn.remove_css_class(cls)
            btn.add_css_class("filled" if on else "tonal")
        self._live[f"look:{lk['id']}"] = live
        live(self._st)
        return c

    def _look_where(self, lk) -> str:
        return self._title({"targets": lk["targets"]})

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
        self._shown = None
        self.update_status(self._st)

    def _edit_bar(self, i, t):
        bar = vbox(4)
        bar.set_vexpand(True)
        bar.set_valign(Gtk.Align.END)
        size = button(None, "open_in_full", "flat small", None, tooltip=_("Size: {size}").format(
            size=SIZE_NAMES[t.get("size", "s")]))
        size.connect("clicked", lambda b: self._size_popup(b, i, t.get("size", "s")))
        row = hbox(2, icon("open_with", classes=("dim",)), size)
        row.append(Gtk.Box(hexpand=True))
        if t["type"] == "card":
            row.append(button(None, "edit", "flat small", lambda: self._open_card(t), tooltip=_("Change this card")))
        if t["type"] == "look":
            lk = next((x for x in self._st.get("looks") or [] if x["id"] == t["id"]), None)
            if lk:
                row.append(button(None, "edit", "flat small", lambda: self._open_look(lk), tooltip=_("Change this look")))
        row.append(button(None, "close", "flat small", lambda: self._remove(i), tooltip=_("Take off Favourites")))
        bar.append(row)
        return bar

    def _size_popup(self, anchor, i, now):
        """Small, wide, tall or large, in a popup so the bar fits on a small card."""
        pop = Gtk.Popover()
        pop.set_parent(anchor)

        def pick(k):
            pop.popdown()
            if k != now:
                self._resize(i, k)
        box = vbox(2)
        for k in ("s", "w", "t", "l"):
            b = button(SIZE_NAMES[k], "check" if k == now else None, "flat small", lambda k=k: pick(k))
            box.append(b)
        pop.set_child(box)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _dnd(self, w, i):
        """In Arrange, drag an item onto another to put it there."""
        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        src.connect("prepare", lambda *_a: Gdk.ContentProvider.new_for_value(str(i)))
        src.connect("drag-begin", lambda s, drag: s.set_icon(Gtk.WidgetPaintable.new(w), 20, 20))
        w.add_controller(src)
        dst = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        dst.connect("drop", lambda _t, value, _x, _y: self._move(int(value), i))
        dst.connect("enter", lambda *_a: (w.add_css_class("drop"), Gdk.DragAction.MOVE)[1])
        dst.connect("leave", lambda *_a: w.remove_css_class("drop"))
        w.add_controller(dst)

    def _move(self, frm, to):
        tiles = self.favorites()
        if frm == to or not (0 <= frm < len(tiles) and 0 <= to < len(tiles)):
            return False
        tiles.insert(to, tiles.pop(frm))
        self._send(set=tiles)
        return True

    def _resize(self, i, size):
        tiles = self.favorites()
        if 0 <= i < len(tiles):
            tiles[i]["size"] = size
            self._send(set=tiles)

    def _remove(self, i):
        tiles = self.favorites()
        if 0 <= i < len(tiles):
            del tiles[i]
            self._send(set=tiles)

    # ---------------------------------------------------------------- adding single items
    def _toggle_add(self):
        show = not self._add_card.get_visible()
        self._add_card.set_visible(show)
        if show:
            self.app.bg(lambda: self.app.client.setup("list"),
                        lambda r: (setattr(self, "_setups", [s["name"] for s in r.get("setups") or []]),
                                   self._fill_add()))
            self._fill_add()

    def _fill_add(self):
        from iridia.looks import tile_id
        c = self._add_card
        widgets.clear(c)
        have = {tile_id(t) for t in self.favorites()}
        head = hbox(8, _grow(label(_("Add to Favourites"), ("heading",))))
        head.append(button(None, "close", "flat small", self._toggle_add, tooltip=_("Close")))
        c.append(head)

        def group(title, items, note=None):
            c.append(label(title, ("body",)))
            if note:
                c.append(label(note, ("small", "dim"), wrap=True))
            row = wrap_row(6)
            for text, tile in items:
                b = button(text, "add", "tonal small", lambda tile=tile: self._send(add=tile))
                b.set_sensitive(tile_id(tile) not in have)
                row.append(b)
            if not items:
                row.append(label(_("None yet."), ("small", "faint")))
            c.append(row)
        group(_("A card for one strip"), [(n, {"type": "card", "targets": [k],
                                               "controls": ["power", "brightness", "colors"], "size": "w"})
                                          for k, n in self._strips()],
              _("On and off, brightness and colours; change it later. New card makes one for several strips."))
        group(_("A look on its own"), [(lk["name"], {"type": "look", "id": lk["id"], "size": "s"})
                                       for lk in self._st.get("looks") or []])
        group(_("Setups"), [(n, {"type": "setup", "name": n, "size": "s"}) for n in (self._setups or [])])
        group(_("A switch on its own"), [(SWITCH_NAMES[w][0], {"type": "switch", "what": w, "size": "s"})
                                         for w in SWITCH_NAMES])

    # ---------------------------------------------------------------- the card editor
    @staticmethod
    def _chip(text, ico=None, active=False) -> Gtk.ToggleButton:
        b = Gtk.ToggleButton(active=active)
        b.add_css_class("filter")
        b.set_child(hbox(6, icon(ico), Gtk.Label(label=text)) if ico else Gtk.Label(label=text))
        return b

    def _chip_row(self, items, chosen) -> tuple:
        """A wrapping row of filter chips: (row, {key: chip})."""
        row = wrap_row(6)
        chips = {}
        for key, text, ico in items:
            chips[key] = self._chip(text, ico, key in chosen)
            row.append(chips[key])
        return row, chips

    def _open_card(self, t: dict | None):
        """The card editor: its strips, what's on it, and its size, all as chips you tap."""
        c = self._editor
        widgets.clear(c)
        self._editing_card = dict(t) if t else None
        c.append(label(_("Change this card") if t else _("New card"), ("heading",)))
        self._card_title = Gtk.Entry(placeholder_text=_("Title (optional), like Desk or Room"), hexpand=True)
        self._card_title.set_text((t or {}).get("title", ""))
        c.append(self._card_title)

        c.append(label(_("Which strips"), ("body", "dim")))
        targets = set((t or {}).get("targets") or ["*"])
        row, chips = self._chip_row([("*", _("Everything"), "lightbulb")] + [(k, n, None) for k, n in self._strips()],
                                    targets)
        self._card_all = chips.pop("*")
        self._card_strips = chips

        def everything(b):
            if b.get_active():
                for x in self._card_strips.values():
                    x.set_active(False)

        def one(b):
            if b.get_active():
                self._card_all.set_active(False)
        self._card_all.connect("toggled", everything)
        for x in self._card_strips.values():
            x.connect("toggled", one)
        c.append(row)

        c.append(label(_("On the card"), ("body", "dim")))
        chosen = set((t or {}).get("controls") or ["power", "brightness", "colors"])
        row, self._card_ctl = self._chip_row([(k, *CONTROL_NAMES[k]) for k in CONTROLS], chosen)
        c.append(row)

        # what the Looks, Scenes and Switches chips are for: shown only when those are on the card
        def picker(ctl_key, title, items, picked, empty, defaults=None):
            box = vbox(6)
            box.set_margin_start(12)
            box.append(label(title, ("small", "dim")))
            if items:
                r, chips = self._chip_row(items, picked)
                box.append(r)
            else:
                chips = {}
                box.append(label(empty, ("small", "faint"), wrap=True))
            rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=180,
                               reveal_child=self._card_ctl[ctl_key].get_active())
            rev.set_child(box)

            def on_toggle(b):
                rev.set_reveal_child(b.get_active())
                if b.get_active() and chips and not any(x.get_active() for x in chips.values()):
                    for k, x in chips.items():          # never an empty list: these to start with
                        x.set_active(defaults is None or k in defaults)
            self._card_ctl[ctl_key].connect("toggled", on_toggle)
            c.append(rev)
            return chips
        self._card_looks = picker("looks", _("Which looks"),
                                  [(lk["id"], lk["name"], None) for lk in self._st.get("looks") or []],
                                  set((t or {}).get("looks") or []), _("None yet: New look makes one."))
        self._card_scenes = picker("scenes", _("Which scenes"),
                                   [(sc["id"], sc["name"], None)
                                    for sc in (self._st.get("scenes") or {}).get("scenes") or []],
                                   set((t or {}).get("scenes") or []), _("None yet: make them on the Scenes tab."))
        self._card_sw = picker("switches", _("Which switches"),
                               [(w, SWITCH_NAMES[w][0], SWITCH_NAMES[w][1]) for w in SWITCHES],
                               set((t or {}).get("switches") or []), "", defaults=DEFAULT_SWITCHES)

        self._card_size = Group([(k, SIZE_NAMES[k]) for k in ("s", "w", "t", "l")], (t or {}).get("size", "w"))
        c.append(hbox(10, label(_("Size"), ("body", "dim")), self._card_size))
        c.append(label(_("A card grows taller when what's on it needs the room."), ("small", "faint"), wrap=True))
        bar = hbox(8, button(_("Save"), "check", "filled small", self._save_card),
                   button(_("Cancel"), None, "text small", lambda: c.set_visible(False)))
        if t:
            bar.append(Gtk.Box(hexpand=True))
            bar.append(button(_("Delete"), "delete", "danger small",
                              lambda: (c.set_visible(False), self._send(remove=f"card:{t['id']}"))))
        c.append(bar)
        c.set_visible(True)

    def _save_card(self):
        targets = ["*"] if self._card_all.get_active() else [k for k, cb in self._card_strips.items() if cb.get_active()]
        controls = [k for k, cb in self._card_ctl.items() if cb.get_active()]
        if not targets and any(k in controls for k in ("power", "brightness", "colors", "follow", "stay_lit", "effect")):
            self.app.toast(_("Pick the strips it's for, or Everything."))
            return
        if not controls:
            self.app.toast(_("Pick what goes on the card."))
            return
        t = {"type": "card", "title": self._card_title.get_text().strip(), "targets": targets or ["*"],
             "controls": controls, "size": self._card_size.active() or "w",
             "looks": [k for k, cb in self._card_looks.items() if cb.get_active()],
             "scenes": [k for k, cb in self._card_scenes.items() if cb.get_active()],
             "switches": [k for k, cb in self._card_sw.items() if cb.get_active()]}
        self._editor.set_visible(False)
        if self._editing_card is None:
            self._send(add=t)
            return
        t["id"] = self._editing_card["id"]
        self._send(set=[t if (x.get("type") == "card" and x.get("id") == t["id"]) else x for x in self.favorites()])

    # ---------------------------------------------------------------- the look editor
    def _open_look(self, lk: dict | None):
        self._look_edit = dict(lk) if lk else None
        c = self._editor
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
        for k, n in self._strips():
            cb = Gtk.CheckButton(label=n, active=k in targets)
            self._look_checks[k] = cb
            row.append(cb)
        c.append(row)
        self._look_all.connect("toggled", lambda *_a: row.set_sensitive(not self._look_all.get_active()))
        row.set_sensitive(not self._look_all.get_active())
        c.append(label(_("What they do"), ("body",)))
        self._look_editor = LookEditor(self.app, (lk or {}).get("look") or {"kind": "dim", "bright": 20},
                                       lambda _l: None, allow_none=False, on_try=self._try_look)
        c.append(self._look_editor)
        bar = hbox(8, button(_("Save"), "check", "filled small", self._save_look),
                   button(_("Cancel"), None, "text small", lambda: c.set_visible(False)))
        if lk:
            bar.append(Gtk.Box(hexpand=True))
            bar.append(button(_("Delete"), "delete", "danger small",
                              lambda: (c.set_visible(False), self._looks_send(remove=lk["id"]))))
        c.append(bar)
        c.set_visible(True)
        self._look_name.grab_focus()

    def _look_targets(self):
        return ["*"] if self._look_all.get_active() else [k for k, cb in self._look_checks.items() if cb.get_active()]

    def _try_look(self, look):
        targets = self._look_targets()
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
        targets = self._look_targets()
        if not targets:
            self.app.toast(_("Pick the strips it's for, or Everything."))
            return
        lk = {"name": name, "targets": targets, "look": self._look_editor.get()}
        new = self._look_edit is None
        if not new:
            lk["id"] = self._look_edit["id"]

        def after(r):
            self._editor.set_visible(False)
            if new:                                     # a new look goes onto Favourites, small
                made = next((x for x in r.get("looks") or [] if x["name"].lower() == name.lower()), None)
                if made:
                    self._send(add={"type": "look", "id": made["id"], "size": "s"})
        self._looks_send(after, set=lk)


def _grow(w):
    w.set_hexpand(True)
    return w
