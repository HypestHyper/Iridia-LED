"""The Scenes tab: a different look for the lights while something is fullscreen, or while a chosen
app is in front. The daemon does the watching (iridia/focuswatch.py); this page only sets what it
does."""

from typing import Callable, Optional

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

    def __init__(self, app, look: Optional[dict], on_change: Callable, allow_none: bool = True,
                 on_try: Optional[Callable] = None):
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

    def get(self) -> Optional[dict]:
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
        self._apps_now = None
        self._ignore_now = None
        self._seen_now = None
        self._st = scenes.clean(app.config.get("scenes", {}) if hasattr(app, "config") else {})
        st = self._st
        page.append(section(_("Scenes"), _("A different look for the lights while a game or a film is fullscreen. "
                                           "They go back when it's gone, and your settings don't change."), top=4))
        c = card()
        row, self._enabled = switch_row(_("Change the lights for fullscreen apps"), st["enabled"],
                                        lambda v: self._send(enabled=v))
        c.append(row)
        self._now = label("", ("small", "dim"), wrap=True)
        c.append(self._now)
        c.append(label(_("When anything is fullscreen"), ("heading",)))
        self._look = LookEditor(app, st["look"], lambda look: self._send(look=look), on_try=self._try)
        c.append(self._look)
        page.append(c)

        c = card()
        c.append(label(_("Apps with their own look"), ("heading",)))
        c.append(label(_("While one of these is in front, fullscreen or not, it gets its own look instead."),
                       ("small", "dim"), wrap=True))
        self._apps = vbox(6)
        c.append(self._apps)
        self._entry = Gtk.Entry(placeholder_text=_("App name, like mpv or steam_app_1091500"), hexpand=True)
        c.append(self._entry)
        self._seen = wrap_row(6)
        c.append(self._seen)
        self._new_look = LookEditor(app, {"kind": "off"}, lambda _l: None, allow_none=False, on_try=self._try)
        c.append(self._new_look)
        c.append(hbox(8, button(_("Add"), "add", "tonal small", self._add_app),
                      button(_("Never for this app"), "block", "text small", self._add_ignore)))
        c.append(label(_("Never for these"), ("body",)))
        self._ignore = wrap_row(6)
        c.append(self._ignore)
        page.append(c)

        c = card()
        c.append(label(_("Timing"), ("heading",)))
        r = wrap_row(10)
        self._on = MiniSlider(_("Comes on after"), 0, 10, st["on_delay"], 0.5, "s",
                              lambda v: self._send(on_delay=v))
        self._off = MiniSlider(_("Goes back after"), 0, 10, st["off_delay"], 0.5, "s",
                               lambda v: self._send(off_delay=v))
        self._every = MiniSlider(_("Check every"), 1, 30, st["interval"], 1, "s",
                                 lambda v: self._send(interval=int(v)))
        for s in (self._on, self._off, self._every):
            s.set_size_request(300, -1)
            r.append(s)
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

    def _try(self, look):
        if not look:
            self.app.toast(_("Nothing to show: pick a look first."))
            return
        self.app.bg(lambda: self.app.client.scenes(test=look),
                    lambda r: self.app.toast(_("Showing it for 5 seconds.") if r.get("ok") else
                                             (r.get("error") or _("Couldn't show it"))))

    def _add_app(self):
        name = self._entry.get_text().strip()
        if not name:
            self.app.toast(_("Type the app's name, or pick one it has seen."))
            return
        self._entry.set_text("")
        self._send(set_app={"app": name, "look": self._new_look.get()})

    def _add_ignore(self):
        name = self._entry.get_text().strip()
        if not name:
            self.app.toast(_("Type the app's name, or pick one it has seen."))
            return
        self._entry.set_text("")
        self._send(ignore=name)

    # -- showing what's set
    def update_status(self, st):
        if st.get("scenes"):
            self._apply(st["scenes"])

    def _apply(self, s):
        self._st = s
        self._enabled.set_value(bool(s.get("enabled")))
        self._look.set(s.get("look"))
        self._on.set_quiet(s.get("on_delay", 1.0))
        self._off.set_quiet(s.get("off_delay", 2.0))
        self._every.set_quiet(s.get("interval", 3))
        method = s.get("method")
        self._every.set_visible(method in ("processes", "x11"))
        if not s.get("enabled"):
            self._now.set_label(_("Off."))
        elif not s.get("watching"):
            self._now.set_label(_("Nothing to watch for yet: pick a look for fullscreen apps, or add an app."))
        else:
            front = s.get("front") or ""
            parts = [HOW.get(method, "")]
            if method != "processes":
                parts.append(_("In front now: {app}{fs}.").format(
                    app=front or _("nothing"), fs=_(" (fullscreen)") if s.get("fullscreen") else ""))
            elif s.get("running"):
                parts.append(_("Running now: {apps}.").format(apps=", ".join(s["running"])))
            parts.append(_("Showing: {look}.").format(look=look_text(s.get("active"))))
            self._now.set_label(" ".join(p for p in parts if p))
        apps = s.get("apps") or []
        if apps != self._apps_now:
            self._apps_now = apps
            widgets.clear(self._apps)
            for r in apps:
                txt = label(f"{r['app']}: {look_text(r['look'])}", ("body",), wrap=True)
                txt.set_hexpand(True)
                rm = button(None, "close", "flat small", lambda a=r["app"]: self._send(remove_app=a),
                            tooltip=_("Remove"))
                self._apps.append(hbox(10, txt, rm))
            if not apps:
                self._apps.append(label(_("None yet."), ("small", "faint")))
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
            widgets.clear(self._seen)
            for a in seen[:16]:
                self._seen.append(button(a, None, "text small", lambda a=a: self._entry.set_text(a),
                                         tooltip=_("Use this name")))
            self._seen.set_visible(bool(seen))
