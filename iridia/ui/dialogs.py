"""Dialogs. GTK 4 dialogs never block, so every one reports back through a callback."""

import threading
from typing import Callable, List, Optional

from gi.repository import Gio, GLib, Gtk

from iridia.i18n import _
from iridia.ui.widgets import (Spin, button, card, focus_within, hbox, icon, label, no_scroll, vbox)

PAUSE = None      # set by the app: callable(+1/-1) that pauses UI refreshes while a dialog previews


class Dialog(Gtk.Window):
    def __init__(self, parent: Gtk.Window, title: str, width: int = 460, height: int = -1,
                 resizable: bool = False, on_close: Optional[Callable] = None):
        super().__init__(title=title, modal=True, resizable=resizable)
        if parent is not None:
            self.set_transient_for(parent)
        self.add_css_class("iridia-dialog")
        self.set_default_size(width, height)
        self.body = vbox(10)
        self.body.set_margin_top(22)
        self.body.set_margin_bottom(20)
        self.body.set_margin_start(24)
        self.body.set_margin_end(24)
        self.set_child(self.body)
        self._on_close = on_close
        self._closed = False
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self.connect("close-request", lambda *_a: (self._fire_close(), False)[1])

    def _key(self, _c, keyval, _code, _state):
        from gi.repository import Gdk
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and hasattr(self, "on_enter"):
            self.on_enter()
            return True
        return False

    def _fire_close(self):
        if not self._closed:
            self._closed = True
            if self._on_close:
                self._on_close()

    def buttons(self, *btns) -> Gtk.Box:
        row = hbox(8)
        row.set_halign(Gtk.Align.END)
        row.set_margin_top(10)
        for b in btns:
            row.append(b)
        self.body.append(row)
        return row


def message(parent, title: str, text: str, error: bool = False):
    d = Dialog(parent, title)
    d.body.append(hbox(10, icon("error" if error else "info", fill=True, classes=("big",
                                                                                  "error-text" if error else "accent")),
                       label(title, ("title",))))
    d.body.append(label(text, ("body", "dim"), wrap=True, chars=56))
    d.buttons(button(_("OK"), style="filled", cb=d.close))
    d.on_enter = d.close
    d.present()
    return d


def confirm(parent, title: str, text: str, on_yes: Callable, yes: Optional[str] = None, danger: bool = False,
            no: Optional[str] = None, on_no: Optional[Callable] = None):
    d = Dialog(parent, title)
    d.body.append(label(title, ("title",)))
    d.body.append(label(text, ("body", "dim"), wrap=True, chars=56))

    def ok():
        d.close()
        on_yes()

    def cancel():
        d.close()
        if on_no:
            on_no()
    d.buttons(button(no or _("Cancel"), style="text", cb=cancel),
              button(yes or _("OK"), style="danger" if danger else "filled", cb=ok))
    d.on_enter = ok
    d.present()
    return d


def ask_text(parent, title: str, prompt: str, initial: str, on_done: Callable[[str], None],
             check: Optional[Callable[[str], Optional[str]]] = None, ok_label: Optional[str] = None):
    d = Dialog(parent, title)
    d.body.append(label(title, ("title",)))
    d.body.append(label(prompt, ("small", "dim"), wrap=True, chars=52))
    entry = Gtk.Entry(text=initial or "")
    d.body.append(entry)
    err = label("", ("small", "error-text"), wrap=True)
    d.body.append(err)

    def ok():
        t = entry.get_text().strip()
        msg = check(t) if check else (None if t else _("Type a name."))
        if msg:
            err.set_label(msg)
            return
        d.close()
        on_done(t)
    entry.connect("activate", lambda *_a: ok())
    d.buttons(button(_("Cancel"), style="text", cb=d.close), button(ok_label or _("OK"), style="filled", cb=ok))
    d.present()
    entry.grab_focus()
    return d


_keep = set()       # FileChooserNative must stay referenced until it answers


def _native(parent, title, action, accept, on_done, initial_name=None, flt=None):
    """GTK 4.6 .. 4.9 fallback for Gtk.FileDialog."""
    dlg = Gtk.FileChooserNative.new(title, parent, action, accept, _("Cancel"))
    dlg.set_modal(True)
    if flt is not None:
        dlg.add_filter(flt)
    if initial_name:
        dlg.set_current_name(initial_name)

    def resp(d, r):
        _keep.discard(d)
        gf = d.get_file() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if gf is not None and gf.get_path():
            on_done(gf.get_path())
    dlg.connect("response", resp)
    _keep.add(dlg)
    dlg.show()


def open_file(parent, title: str, on_done: Callable[[str], None], patterns=("*.json",)):
    f = Gtk.FileFilter()
    f.set_name("JSON")
    for p in patterns:
        f.add_pattern(p)
    if not hasattr(Gtk, "FileDialog"):
        _native(parent, title, Gtk.FileChooserAction.OPEN, _("Open"), on_done, flt=f)
        return
    dlg = Gtk.FileDialog(title=title)
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(f)
    dlg.set_filters(store)

    def done(d, res):
        try:
            gf = d.open_finish(res)
        except GLib.Error:
            return
        if gf is not None and gf.get_path():
            on_done(gf.get_path())
    dlg.open(parent, None, done)


def save_file(parent, title: str, initial_name: str, on_done: Callable[[str], None]):
    if not hasattr(Gtk, "FileDialog"):
        _native(parent, title, Gtk.FileChooserAction.SAVE, _("Save"), on_done, initial_name=initial_name)
        return
    dlg = Gtk.FileDialog(title=title, initial_name=initial_name)

    def done(d, res):
        try:
            gf = d.save_finish(res)
        except GLib.Error:
            return
        if gf is not None and gf.get_path():
            on_done(gf.get_path())
    dlg.save(parent, None, done)


def run_bg(fn, done: Optional[Callable] = None):
    """Run fn() in a thread; done(result) back on the GTK thread."""
    def work():
        try:
            r = fn()
        except Exception as e:      # noqa: BLE001 - surfaced to the caller as a dict
            r = {"ok": False, "error": str(e)}
        if done:
            GLib.idle_add(lambda: (done(r), False)[1], priority=GLib.PRIORITY_DEFAULT)
    threading.Thread(target=work, daemon=True).start()


class CountLedsDialog(Dialog):
    """Light one LED at a time so you can find the last one on the strip."""

    def __init__(self, parent, client, device: str, zone: str, current: int, on_done: Callable[[int], None]):
        super().__init__(parent, _("Count LEDs: {name}").format(name=zone or device), width=520, on_close=self._closing)
        self.client, self.device, self.zone, self.on_done = client, device, zone, on_done
        if PAUSE:
            PAUSE(1)
        self._size = None
        b = self.body
        b.append(label(_('Count LEDs: {name}').format(name=zone or device), ("title",)))
        b.append(label(_("Only one LED is lit. Move it with the slider, the buttons or the arrow keys until it is the "
                       "last LED of the strip, then click “This is the last one”."), ("small", "dim"),
                       wrap=True, chars=60))
        self._num = label("", ("display", "accent"), xalign=0.5)
        b.append(self._num)
        self._adj = Gtk.Adjustment(value=max(1, current), lower=1, upper=max(current, 60), step_increment=1,
                                   page_increment=10)
        self._scale = no_scroll(Gtk.Scale(adjustment=self._adj, draw_value=False, hexpand=True))
        self._adj.connect("value-changed", lambda *_a: self._send())
        b.append(self._scale)
        steps = hbox(6)
        steps.set_halign(Gtk.Align.CENTER)
        for text, d in (("− 10", -10), ("− 1", -1), ("+ 1", 1), ("+ 10", 10)):
            steps.append(button(text, small=True, cb=lambda d=d: self._step(d)))
        b.append(steps)
        self._info = label("", ("small", "faint"), wrap=True, chars=60)
        b.append(self._info)
        rs = hbox(8)
        rs.append(label(_("Strip is longer? Set OpenRGB's size to"), ("small", "dim")))
        self._resize = Spin(1, 1000, max(1, current), None)
        rs.append(self._resize)
        rs.append(button(_("Resize"), style="text", small=True, cb=self._do_resize))
        b.append(rs)
        self.buttons(button(_("Cancel"), style="text", cb=self.close),
                     button(_("This is the last one"), style="filled", cb=self._done))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._arrows)
        self.add_controller(keys)
        self.on_enter = self._done
        self.present()
        self._send()

    def _arrows(self, _c, keyval, _code, state):
        from gi.repository import Gdk
        if focus_within(self._resize):
            return False
        big = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if keyval == Gdk.KEY_Left:
            self._step(-10 if big else -1)
            return True
        if keyval == Gdk.KEY_Right:
            self._step(10 if big else 1)
            return True
        return False

    def _step(self, d):
        self._adj.set_value(max(1, min(self._adj.get_upper(), self._adj.get_value() + d)))

    def _send(self):
        n = int(self._adj.get_value())
        self._num.set_label(_('LED {n}').format(n=n))
        run_bg(lambda: self.client.led_probe(self.device, self.zone, n - 1), self._got)

    def _got(self, r):
        if self._closed:
            return
        if not r.get("ok"):
            self._info.set_label(r.get("error", _("The daemon didn't answer.")))
            return
        size = r.get("zone_size")
        if size and size != self._size:
            self._size = size
            self._adj.set_upper(max(size, 1))
        if size:
            t = _("OpenRGB drives {n} LEDs on this zone, so the light can't go further than LED {n}. "
                  "If your strip has more, set the size below first.").format(n=size)
        elif size == 0:
            t = _("OpenRGB doesn't have a size for this zone yet, so nothing can light up. Set the size below to "
                  "the number of LEDs on your strip (more is fine), click Resize, then count.")
        else:
            t = _("OpenRGB isn't connected, so the strip can't light up right now.")
        self._info.set_label(t)

    def _do_resize(self):
        n = int(self._resize.get_value())
        run_bg(lambda: self.client.resize_zone(self.device, self.zone, n),
               lambda r: self._got(r) if r.get("ok") else self._info.set_label(r.get("error", _("Resize failed"))))

    def _done(self):
        n = int(self._adj.get_value())
        self.close()
        self.on_done(n)

    def _closing(self):
        run_bg(self.client.led_probe_off)
        if PAUSE:
            PAUSE(-1)


def diagnostics_window(parent, checks: List):
    d = Dialog(parent, _("Diagnostics"), width=640, height=560, resizable=True)
    d.body.append(label(_("Diagnostics"), ("title",)))
    sc = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    box = vbox(10)
    for c in checks:
        row = vbox(2)
        name = "help" if c.ok is None else ("check_circle" if c.ok else "error")
        cls = "dim" if c.ok is None else ("ok-text" if c.ok else "error-text")
        row.append(hbox(8, icon(name, fill=True, classes=(cls,)), label(c.label, ("subheading",))))
        det = label(c.detail, ("small", "dim"), wrap=True, chars=70, selectable=True)
        det.set_margin_start(30)
        row.append(det)
        if c.ok is False and c.hint:
            h = label(f"→ {c.hint}", ("small", "faint"), wrap=True, chars=70, selectable=True)
            h.set_margin_start(30)
            row.append(h)
        box.append(row)
    sc.set_child(box)
    d.body.append(sc)
    d.buttons(button(_("Close"), style="filled", cb=d.close))
    d.present()
    return d


__all__ = ["Dialog", "message", "confirm", "ask_text", "open_file", "save_file", "run_bg", "CountLedsDialog",
           "diagnostics_window", "card"]
