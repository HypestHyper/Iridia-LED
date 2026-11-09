"""The Scenes tab: scenes you make, each "when this happens, these strips look like this": anything
fullscreen, or some apps in front. The daemon does the watching (iridia/focuswatch.py); this page
only sets what it does."""

from collections.abc import Callable

from gi.repository import Gtk

from iridia import scenes
from iridia.i18n import _
from iridia.ui import widgets
from iridia.ui.effects import EFFECT_KEYS, EFFECT_NAMES
from iridia.ui.layout_notify import MiniSlider
from iridia.ui.widgets import (Dropdown, Group, Swatch, button, card, hbox, label, section, switch_row, vbox,
                               wrap_row)

KIND_NAMES = {"none": _("Nothing"), "off": _("Off"), "dim": _("Dimmer"), "color": _("One colour"),
              "effect": _("Effect")}
HOW = {"hyprland": _("Hyprland says which window is in front."),
       "sway": _("Sway says which window is in front."),
       "kde": _("KDE Plasma says which window is in front (through a small KWin script Iridia loads while this "
                "is on)."),
       "x11": _("The X server says which window is in front."),
       "processes": _("This desktop doesn't tell other apps which window is in front, so Iridia looks at the "
                      "programs running instead: the apps below get their look while they run, and "
                      "\"anything fullscreen\" can't be told.")}


WHEN_NAMES = {"fullscreen": _("Anything fullscreen"), "apps": _("These apps")}


def strip_list(st: dict, with_hidden: bool = False) -> list[tuple]:
    """[(zone key, name)] for every strip in a status, without the hidden ones unless asked."""
    out = []
    for dev, dc in sorted((st.get("device_configs") or {}).items()):
        zones = dc.get("zones") if isinstance(dc, dict) else None
        for zn, zc in (zones.items() if isinstance(zones, dict) and zones else [("", dc)]):
            if not isinstance(zc, dict) or (zc.get("hidden") and not with_hidden):
                continue
            nm = zc.get("display_name") or zn or dev
            out.append((f"{dev}|{zn}", nm if not zn or nm == dev else f"{dev} · {nm}"))
    return out


def look_text(look) -> str:
    if not look:
        return _("Nothing")
    k = look["kind"]
    if k == "off":
        return _("Off")
    if k == "dim":
        return _("Dimmer, {n}%").format(n=look["bright"])
    if k == "color":
        return _("#{hex}, {n}%").format(hex=look["hex"], n=look["bright"])
    return _("{effect}, {n}%").format(effect=EFFECT_NAMES.get(look["effect"], look["effect"]), n=look["bright"])


class LookEditor(Gtk.Box):
    """What the lights do: nothing (only where that's a choice), off, dimmer, one colour or an effect,
    with a brightness; on_change(look or None) when it's changed."""

    def __init__(self, app, look: dict | None, on_change: Callable, allow_none: bool = True,
                 on_try: Callable | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._app, self._cb, self._quiet = app, on_change, False
        self._look = scenes.clean_look(look) or ({"kind": "dim", "bright": 20} if not allow_none else None)
        kinds = [k for k in KIND_NAMES if allow_none or k != "none"]
        self.kind = Group([(k, KIND_NAMES[k]) for k in kinds], self._look["kind"] if self._look else "none",
                          self._kind)
        row = wrap_row(10, self.kind)
        if on_try:
            row.append(button(_("Try it"), "play_arrow", "tonal small", lambda: on_try(self.get())))
        self.append(row)
        r = wrap_row(10)
        self.bright = MiniSlider(_("Brightness"), 0, 100, (self._look or {}).get("bright", 20), 5, "%",
                                 lambda v: self._set(bright=int(v)))
        self.bright.set_size_request(300, -1)
        r.append(self.bright)
        self.swatch = Swatch((self._look or {}).get("hex", "ff0000"), 32, on_click=self._pick,
                             tooltip=_("Pick a colour"))
        r.append(self.swatch)
        self.effect = Dropdown(list(EFFECT_NAMES.values()),
                               EFFECT_NAMES.get((self._look or {}).get("effect", "breathing")),
                               lambda v: self._set(effect=EFFECT_KEYS.get(v, "breathing")))
        r.append(self.effect)
        self.append(r)
        self._shown()

    def get(self) -> dict | None:
        return dict(self._look) if self._look else None

    def set(self, look):
        look = scenes.clean_look(look)
        if look == self._look:
            return
        self._quiet = True
        self._look = look
        self.kind.set_active(look["kind"] if look else "none")
        if look:
            self.bright.set_quiet(look.get("bright", self.bright.scale.get_value()))
            if look.get("hex"):
                self.swatch.set_state(hex6=look["hex"])
            if look.get("effect"):
                self.effect.set_value(EFFECT_NAMES.get(look["effect"]))
        self._shown()
        self._quiet = False

    def _shown(self):
        k = self._look["kind"] if self._look else "none"
        self.bright.set_visible(k in ("dim", "color", "effect"))
        self.swatch.set_visible(k == "color")
        self.effect.set_visible(k == "effect")

    def _kind(self, k):
        if self._quiet:
            return
        if k == "none":
            self._look = None
        else:
            base = {"kind": k, "bright": int(self.bright.scale.get_value()), "hex": self.swatch.hex,
                    "effect": EFFECT_KEYS.get(self.effect.value() or "", "breathing")}
            if k == "dim" and (self._look or {}).get("kind") != "dim":
                base["bright"] = 20                    # dimmer starts dim, the others bright
                self.bright.set_quiet(20)
            elif k in ("color", "effect") and (self._look or {}).get("kind") in (None, "off", "dim"):
                base["bright"] = 100
                self.bright.set_quiet(100)
            self._look = scenes.clean_look(base)
        self._shown()
        self._cb(self.get())

    def _set(self, **kw):
        if self._quiet or not self._look:
            return
        self._look = scenes.clean_look(dict(self._look, **kw))
        self._cb(self.get())

    def _pick(self):
        def done(h):
            if h:
                self.swatch.set_state(hex6=h)
                self._set(hex=h)
        self._app.pick_color(self.swatch.hex, _("Scene colour"), done)


class ScenesPage:
    def __init__(self, app, page: Gtk.Box):
        self.app = app
        self._st: dict = {}                 # the whole status (for the strips)
        self._sc: dict = scenes.clean(app.config.get("scenes", {}) if hasattr(app, "config") else {})
        self._list_now = None
        self._ignore_now = None
        self._seen_now = None
        self._editing: dict | None = None
        page.append(section(_("Scenes"), _("A different look for the lights while a game or a film is fullscreen, or "
                                           "while an app you pick is in front. They go back when it's gone, and "
                                           "your settings don't change."), top=4))
        c = card()
        row, self._enabled = switch_row(_("Use scenes"), self._sc["enabled"],
                                        lambda v: self._send(enabled=v))
        c.append(row)
        self._now = label("", ("small", "dim"), wrap=True)
        c.append(self._now)
        page.append(c)

        bar = wrap_row(8)
        bar.append(button(_("New scene"), "add", "filled small", lambda: self._open(None)))
        page.append(bar)
        self._editor = card()
        self._editor.set_visible(False)
        page.append(self._editor)
        self._list = vbox(8)
        page.append(self._list)

        c = card()
        c.append(label(_("Never for these"), ("heading",)))
        c.append(label(_("Apps that never count as fullscreen: a browser playing a video, say."), ("small", "dim"),
                       wrap=True))
        self._ignore = wrap_row(6)
        c.append(self._ignore)
        self._ign_entry = Gtk.Entry(placeholder_text=_("App name, like firefox"), hexpand=True)
        self._ign_entry.connect("activate", lambda *_a: self._add_ignore())
        c.append(hbox(8, self._ign_entry, button(_("Add"), "block", "tonal small", self._add_ignore)))
        self._ign_seen = wrap_row(6)
        c.append(self._ign_seen)
        page.append(c)

        c = card()
        c.append(label(_("Timing"), ("heading",)))
        r = wrap_row(10)
        st = self._sc
        self._on = MiniSlider(_("Comes on after"), 0, 10, st["on_delay"], 0.5, "s",
                              lambda v: self._send(on_delay=v))
        self._off = MiniSlider(_("Goes back after"), 0, 10, st["off_delay"], 0.5, "s",
                               lambda v: self._send(off_delay=v))
        self._every = MiniSlider(_("Check every"), 1, 30, st["interval"], 1, "s",
                                 lambda v: self._send(interval=int(v)))
        for sl in (self._on, self._off, self._every):
            sl.set_size_request(300, -1)
            r.append(sl)
        c.append(r)
        c.append(label(_("A short wait keeps the lights steady when you switch away from a game for a moment."),
                       ("small", "faint"), wrap=True))
        page.append(c)
        self._apply(st)

    # -- talking to the daemon
    def _send(self, **kw):
        self.app.bg(lambda: self.app.client.scenes(**kw), self._done)

    def _done(self, r):
        if not r.get("ok"):
            self.app.toast(r.get("error") or _("Couldn't save"))
        if r.get("scenes"):
            self._apply(r["scenes"])

    def _try(self, sc):
        if not sc or not sc.get("look"):
            self.app.toast(_("Nothing to show: pick a look first."))
            return
        self.app.bg(lambda: self.app.client.scenes(test=sc),
                    lambda r: self.app.toast(_("Showing it for 5 seconds.") if r.get("ok") else
                                             (r.get("error") or _("Couldn't show it"))))

    def _add_ignore(self):
        name = self._ign_entry.get_text().strip()
        if not name:
            self.app.toast(_("Type the app's name, or pick one it has seen."))
            return
        self._ign_entry.set_text("")
        self._send(ignore=name)

    # -- the list
    def _where(self, sc) -> str:
        if sc["targets"] == ["*"]:
            return _("Everything")
        names = dict(strip_list(self._st, True))
        shown = [names.get(k, k.partition("|")[2] or k.partition("|")[0]) for k in sc["targets"]]
        return shown[0] if len(shown) == 1 else _("{n} strips").format(n=len(shown))

    def _when(self, sc) -> str:
        if sc["when"] == "fullscreen":
            return _("When anything is fullscreen")
        return _("When {apps} is in front").format(apps=", ".join(sc["apps"]))

    def _row(self, i, sc, n, active):
        c = card(spacing=6)
        top = hbox(10)
        sw = widgets.Toggle(sc["on"], lambda v, sid=sc["id"]: self._send(scene_on={"id": sid, "on": v}))
        top.append(sw)
        txt = vbox(2)
        txt.set_hexpand(True)
        name = hbox(8, label(sc["name"], ("heading",)))
        if active:
            name.append(label(_("On now"), ("chip", "ok")))
        txt.append(name)
        txt.append(label(f"{self._when(sc)} · {look_text(sc['look'])} · {self._where(sc)}", ("small", "dim"),
                         wrap=True))
        top.append(txt)
        up = button(None, "expand_less", "flat small", lambda: self._send(move_scene={"id": sc["id"], "to": i - 1}),
                    tooltip=_("Up: wins over the ones below"))
        down = button(None, "expand_more", "flat small",
                      lambda: self._send(move_scene={"id": sc["id"], "to": i + 1}), tooltip=_("Down"))
        up.set_sensitive(i > 0)
        down.set_sensitive(i < n - 1)
        for b in (up, down,
                  button(None, "play_arrow", "flat small", lambda: self._try(sc), tooltip=_("Try it")),
                  button(None, "edit", "flat small", lambda: self._open(sc), tooltip=_("Change this scene"))):
            top.append(b)
        c.append(top)
        if not sc["on"]:
            c.set_opacity(0.6)
        return c

    # -- the editor
    def _open(self, sc: dict | None):
        c = self._editor
        widgets.clear(c)
        self._editing = dict(sc) if sc else None
        sc = sc or {"name": "", "when": "fullscreen", "apps": [], "targets": ["*"],
                    "look": {"kind": "dim", "bright": 20}}
        c.append(label(_("Change this scene") if self._editing else _("New scene"), ("heading",)))
        self._name = Gtk.Entry(placeholder_text=_("Name, like Games or Films"), hexpand=True)
        self._name.set_text(sc["name"])
        c.append(self._name)

        c.append(label(_("When"), ("body",)))
        self._apps_box = vbox(6)
        self._when_grp = Group([(k, WHEN_NAMES[k]) for k in scenes.WHEN], sc["when"],
                               lambda v: self._apps_box.set_visible(v == "apps"))
        c.append(self._when_grp)
        self._apps_sel = list(sc["apps"])
        self._apps_row = wrap_row(6)
        self._apps_box.append(label(_("While one of these is in front, fullscreen or not. Names are the app's "
                                      "own (its window class), like mpv or steam_app_1091500."), ("small", "dim"),
                                    wrap=True))
        self._apps_box.append(self._apps_row)
        self._app_entry = Gtk.Entry(placeholder_text=_("App name, like mpv or steam_app_1091500"), hexpand=True)
        self._app_entry.connect("activate", lambda *_a: self._add_app())
        self._apps_box.append(hbox(8, self._app_entry, button(_("Add"), "add", "tonal small", self._add_app)))
        seen = self._sc.get("seen") or []
        if seen:
            self._apps_box.append(label(_("Seen fullscreen lately"), ("small", "faint")))
            sr = wrap_row(6)
            for a in seen[:16]:
                sr.append(button(a, "add", "text small", lambda a=a: self._add_app(a), tooltip=_("Add it")))
            self._apps_box.append(sr)
        self._apps_box.set_visible(sc["when"] == "apps")
        c.append(self._apps_box)
        self._show_apps()

        c.append(label(_("Which strips"), ("body",)))
        targets = set(sc["targets"])
        self._all = Gtk.CheckButton(label=_("Everything"), active="*" in targets)
        c.append(self._all)
        srow = wrap_row(6)
        self._strips = {}
        for k, n in strip_list(self._st):
            cb = Gtk.CheckButton(label=n, active=k in targets)
            self._strips[k] = cb
            srow.append(cb)
        c.append(srow)
        self._all.connect("toggled", lambda *_a: srow.set_sensitive(not self._all.get_active()))
        srow.set_sensitive(not self._all.get_active())

        c.append(label(_("What they do"), ("body",)))
        self._look = LookEditor(self.app, sc["look"], lambda _l: None, allow_none=False,
                                on_try=lambda look: self._try(dict(self._gather() or {}, look=look)))
        c.append(self._look)

        bar = hbox(8, button(_("Save"), "check", "filled small", self._save),
                   button(_("Cancel"), None, "text small", lambda: c.set_visible(False)))
        if self._editing:
            bar.append(Gtk.Box(hexpand=True))
            bar.append(button(_("Delete"), "delete", "danger small",
                              lambda: (c.set_visible(False), self._send(remove_scene=self._editing["id"]))))
        c.append(bar)
        c.set_visible(True)

    def _show_apps(self):
        widgets.clear(self._apps_row)
        for a in self._apps_sel:
            self._apps_row.append(button(a, "close", "tonal small", lambda a=a: self._drop_app(a), tooltip=_("Remove")))
        if not self._apps_sel:
            self._apps_row.append(label(_("None yet."), ("small", "faint")))

    def _add_app(self, name: str | None = None):
        name = (name or self._app_entry.get_text()).strip()
        if not name:
            self.app.toast(_("Type the app's name, or pick one it has seen."))
            return
        self._app_entry.set_text("")
        if scenes.app_key(name) not in {scenes.app_key(a) for a in self._apps_sel}:
            self._apps_sel.append(name)
        self._show_apps()

    def _drop_app(self, name):
        self._apps_sel = [a for a in self._apps_sel if a != name]
        self._show_apps()

    def _gather(self) -> dict | None:
        targets = ["*"] if self._all.get_active() else [k for k, cb in self._strips.items() if cb.get_active()]
        return {"name": self._name.get_text().strip(), "when": self._when_grp.active() or "fullscreen",
                "apps": list(self._apps_sel), "targets": targets, "look": self._look.get()}

    def _save(self):
        sc = self._gather()
        if not sc["targets"]:
            self.app.toast(_("Pick the strips it's for, or Everything."))
            return
        if sc["when"] == "apps" and not sc["apps"]:
            self.app.toast(_("Add the apps it's for."))
            return
        if self._editing:
            sc["id"], sc["on"] = self._editing["id"], self._editing.get("on", True)
        self._editor.set_visible(False)
        self._send(set_scene=sc)

    # -- showing what's set
    def update_status(self, st):
        if not st or "_error" in st:
            return
        self._st = st
        if st.get("scenes"):
            self._apply(st["scenes"])

    def _apply(self, s):
        self._sc = s
        self._enabled.set_value(bool(s.get("enabled")))
        self._on.set_quiet(s.get("on_delay", 1.0))
        self._off.set_quiet(s.get("off_delay", 2.0))
        self._every.set_quiet(s.get("interval", 3))
        method = s.get("method")
        self._every.set_visible(method in ("processes", "x11"))
        lst = s.get("scenes") or []
        active = list(s.get("active") or [])
        names = {sc["id"]: sc["name"] for sc in lst}
        if not s.get("enabled"):
            self._now.set_label(_("Off."))
        elif not s.get("watching"):
            self._now.set_label(_("Nothing to watch for yet: make a scene, or switch one on."))
        else:
            front = s.get("front") or ""
            parts = [HOW.get(method, "")]
            if method != "processes":
                parts.append(_("In front now: {app}{fs}.").format(
                    app=front or _("nothing"), fs=_(" (fullscreen)") if s.get("fullscreen") else ""))
            elif s.get("running"):
                parts.append(_("Running now: {apps}.").format(apps=", ".join(s["running"])))
            on = [names[i] for i in active if i in names]
            parts.append(_("Showing: {look}.").format(look=", ".join(on) if on else _("Nothing")))
            self._now.set_label(" ".join(p for p in parts if p))
        key = (repr(lst), tuple(active), repr(strip_list(self._st, True)))
        if key != self._list_now:
            self._list_now = key
            widgets.clear(self._list)
            for i, sc in enumerate(lst):
                self._list.append(self._row(i, sc, len(lst), sc["id"] in active))
            if not lst:
                c = card()
                c.append(label(_("No scenes yet"), ("heading",)))
                c.append(label(_("A scene is \"when this happens, these strips look like this\": anything "
                                 "fullscreen dims the room, a game gets embers on the desk, a film turns "
                                 "everything off."), ("small", "dim"), wrap=True))
                self._list.append(c)
        ign = s.get("ignore") or []
        if ign != self._ignore_now:
            self._ignore_now = ign
            widgets.clear(self._ignore)
            for a in ign:
                self._ignore.append(button(a, "close", "tonal small", lambda a=a: self._send(unignore=a),
                                           tooltip=_("Remove")))
            if not ign:
                self._ignore.append(label(_("None."), ("small", "faint")))
        seen = s.get("seen") or []
        if seen != self._seen_now:
            self._seen_now = seen
            widgets.clear(self._ign_seen)
            for a in seen[:16]:
                self._ign_seen.append(button(a, None, "text small", lambda a=a: self._ign_entry.set_text(a),
                                             tooltip=_("Use this name")))
            self._ign_seen.set_visible(bool(seen))
