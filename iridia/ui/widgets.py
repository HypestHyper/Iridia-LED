"""Material 3 Expressive building blocks for the GTK 4 window."""

import colorsys
import math
import time
import weakref
from typing import Callable, List, Optional

from gi.repository import Gdk, GLib, Gtk, Pango

from iridia.i18n import _
from iridia import theme
from iridia.colors import resolve_colors
from iridia.ui import fonts

STYLE = None                       # iridia.ui.style.Style, set by the app
_DRAWINGS = weakref.WeakSet()      # drawing areas to repaint when the theme changes


def color(role: str) -> str:
    return STYLE.color(role) if STYLE else "#888888"


def rgb(role: str):
    """cairo (r, g, b) for a palette role name like 'PRIMARY'."""
    return theme.hex_rgb(color(role))


def themed(area):
    _DRAWINGS.add(area)
    return area


# Colours marked "exact" (shown on the LEDs as picked, no correction). Swatches of these
# colours get a small dot; the window updates this from the daemon's status.
EXACT_COLORS = set()


def set_exact_colors(colors) -> bool:
    new = {str(c).lower() for c in colors or []}
    if new == EXACT_COLORS:
        return False
    EXACT_COLORS.clear()
    EXACT_COLORS.update(new)
    repaint_all()
    return True


def repaint_all():
    for a in list(_DRAWINGS):
        try:
            a.queue_draw()
        except Exception:
            pass


def motion() -> bool:
    return not (STYLE and STYLE.reduce_motion)


# ------------------------------------------------------------------ basics

def icon(name: str, fill: bool = False, classes=()) -> Gtk.Label:
    lbl = Gtk.Label(label=fonts.codepoint(name))
    lbl.add_css_class("icon")
    if fill:
        lbl.add_css_class("fill")
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def label(text: str = "", classes=(), wrap: bool = False, xalign: float = 0.0, selectable: bool = False,
          chars: int = 0, ellipsize: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=xalign)
    # A long line of help text wraps instead of holding the window wide.
    wrap = wrap or (len(text) > 60 and not ellipsize and not chars and bool({"small", "tiny", "faint"} & set(classes)))
    lbl.set_wrap(wrap)
    if wrap:
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if chars:
        lbl.set_max_width_chars(chars)
    if ellipsize:
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_selectable(selectable)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def hbox(spacing=8, *children, **kw) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing, **kw)
    for c in children:
        b.append(c)
    return b


def wrap_row(spacing=6, *children) -> Gtk.FlowBox:
    """A row of buttons that wraps onto a second line in a narrow window instead of making it wide."""
    fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False, column_spacing=spacing,
                     row_spacing=spacing, min_children_per_line=1, max_children_per_line=24,
                     halign=Gtk.Align.FILL, hexpand=True)
    fb.add_css_class("wrap-row")
    for c in children:
        fb.append(c)
    return fb


def vbox(spacing=8, *children, **kw) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing, **kw)
    for c in children:
        b.append(c)
    return b


def button(text: Optional[str] = None, icon_name: Optional[str] = None, style: str = "tonal",
           cb: Optional[Callable] = None, small: bool = False, tooltip: Optional[str] = None) -> Gtk.Button:
    b = Gtk.Button()
    if style:
        for s in style.split():
            b.add_css_class(s)
    if small:
        b.add_css_class("small")
    if icon_name and text:
        b.set_child(hbox(8, icon(icon_name), Gtk.Label(label=text)))
    elif icon_name:
        b.set_child(icon(icon_name))
        b.add_css_class("circle")
    else:
        b.set_label(text or "")
    if tooltip:
        b.set_tooltip_text(tooltip)
    if cb:
        b.connect("clicked", lambda _b: cb())
    return b


def set_button_text(b: Gtk.Button, text: str, icon_name: Optional[str] = None):
    if icon_name:
        b.set_child(hbox(8, icon(icon_name), Gtk.Label(label=text)))
    else:
        b.set_label(text)


def card(inner: bool = False, spacing: int = 10) -> Gtk.Box:
    b = vbox(spacing)
    b.add_css_class("card-inner" if inner else "card")
    return b


def section(title: str, sub: Optional[str] = None, top: int = 18) -> Gtk.Box:
    b = vbox(2)
    b.set_margin_top(top)
    b.set_margin_bottom(6)
    b.set_margin_start(4)
    b.append(label(title, ("title",)))
    if sub:
        b.append(label(sub, ("small", "dim"), wrap=True, chars=90))
    return b


def focus_within(widget) -> bool:
    root = widget.get_root()
    f = root.get_focus() if root is not None and hasattr(root, "get_focus") else None
    while f is not None:
        if f is widget:
            return True
        f = f.get_parent()
    return False


def divider() -> Gtk.Widget:
    s = Gtk.Box()
    s.add_css_class("divider")
    s.set_margin_top(6)
    s.set_margin_bottom(6)
    return s


class Toggle(Gtk.Switch):
    """Gtk.Switch whose callback only fires for user changes."""

    def __init__(self, active: bool, cb: Optional[Callable[[bool], None]] = None):
        super().__init__(active=active, valign=Gtk.Align.CENTER)
        self._cb = cb
        self._quiet = False
        self.connect("notify::active", self._changed)

    def _changed(self, *_a):
        if not self._quiet and self._cb:
            self._cb(self.get_active())

    def set_value(self, v: bool):
        if self.get_active() != bool(v):
            self._quiet = True
            self.set_active(bool(v))
            self._quiet = False


def switch_row(text: str, active: bool, cb: Optional[Callable[[bool], None]] = None, classes=("body",)):
    sw = Toggle(active, cb)
    lbl = label(text, classes)
    row = hbox(12, sw, lbl)
    return row, sw


class Dropdown(Gtk.DropDown):
    def __init__(self, items: List[str], selected: Optional[str] = None,
                 cb: Optional[Callable[[str], None]] = None, width_chars: int = 0, placeholder: Optional[str] = None):
        self._items = list(items)
        self._placeholder = _("Mixed") if placeholder is None else placeholder
        self._ph_shown = False
        super().__init__(model=Gtk.StringList.new(self._items))
        self._cb = cb
        self._quiet = False
        if selected in self._items:
            self.set_selected(self._items.index(selected))
        self.connect("notify::selected", self._changed)
        self.set_valign(Gtk.Align.CENTER)

    def _changed(self, *_a):
        if self._quiet:
            return
        v = self.value()
        if v is None:
            return                                 # "Mixed" itself isn't a choice
        if self._ph_shown:
            # Never swap the model inside GTK's own selection signal (that crashed the
            # window); drop the "Mixed" entry once GTK is done.
            GLib.idle_add(self._drop_placeholder)
        if self._cb:
            self._cb(v)

    def _drop_placeholder(self):
        if self._ph_shown:
            v = self.value()
            self._set_model(self._items)
            if v in self._items:
                self._quiet = True
                self.set_selected(self._items.index(v))
                self._quiet = False
        return False

    def _set_model(self, items, placeholder=False):
        self._quiet = True
        self._ph_shown = placeholder
        self.set_model(Gtk.StringList.new(list(items) + ([self._placeholder] if placeholder else [])))
        self._quiet = False

    def value(self) -> Optional[str]:
        i = self.get_selected()
        return self._items[i] if 0 <= i < len(self._items) else None

    def set_items(self, items: List[str], selected: Optional[str] = None):
        items = list(items)
        cur = selected if selected is not None else self.value()
        if items != self._items:
            self._items = items
            self._set_model(items)
        self.set_value(cur)

    def set_value(self, v: Optional[str]):
        if v in self._items:
            if self._ph_shown:
                self._set_model(self._items)
            self._quiet = True
            if self.get_selected() != self._items.index(v):
                self.set_selected(self._items.index(v))
            self._quiet = False
        else:
            if not self._ph_shown and self._placeholder:
                self._set_model(self._items, placeholder=True)
            self._quiet = True
            self.set_selected(len(self._items) if self._placeholder else Gtk.INVALID_LIST_POSITION)
            self._quiet = False


def no_scroll(widget: Gtk.Widget) -> Gtk.Widget:
    """The mouse wheel over this widget scrolls the page instead of changing its value: sliders and
    number boxes only change when you click, drag or type."""
    ctl = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
    ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_scroll(c, dx, dy):
        w = widget.get_parent()
        while w is not None and not isinstance(w, Gtk.ScrolledWindow):
            w = w.get_parent()
        if w is not None:
            adj = w.get_vadjustment()
            try:
                wheel = c.get_unit() == Gdk.ScrollUnit.WHEEL
            except AttributeError:          # GTK before 4.8: always wheel steps
                wheel = True
            step = dy * (max(40.0, adj.get_page_size() ** (2 / 3)) if wheel else 1.0)
            adj.set_value(max(adj.get_lower(), min(adj.get_upper() - adj.get_page_size(), adj.get_value() + step)))
        return True                         # never let the widget itself see the wheel
    ctl.connect("scroll", on_scroll)
    widget.add_controller(ctl)
    return widget


class Spin(Gtk.SpinButton):
    def __init__(self, lo: float, hi: float, value: float, cb: Optional[Callable[[float], None]] = None,
                 step: float = 1, digits: int = 0, delay: int = 450):
        adj = Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=step, page_increment=step * 10)
        super().__init__(adjustment=adj, digits=digits, numeric=True, valign=Gtk.Align.CENTER)
        no_scroll(self)
        self._cb = cb
        self._quiet = False
        self._job = None
        self._delay = delay
        self.connect("value-changed", self._changed)

    def _changed(self, *_a):
        if self._quiet or not self._cb:
            return
        if self._job:
            GLib.source_remove(self._job)
        self._job = GLib.timeout_add(self._delay, self._fire)

    def _fire(self):
        self._job = None
        self._cb(self.get_value())
        return False

    def busy(self) -> bool:
        return self._job is not None or focus_within(self)

    def set_quiet(self, v: float):
        if abs(self.get_value() - v) > 1e-9 and self._job is None:
            self._quiet = True
            self.set_value(v)
            self._quiet = False


class Group(Gtk.Box):
    """Connected button group (Material 3 Expressive). Exactly one item checked, or none for 'mixed'."""

    def __init__(self, items, active: Optional[str] = None, cb: Optional[Callable[[str], None]] = None,
                 small: bool = True):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add_css_class("group")
        self._cb = cb
        self._quiet = False
        self.buttons = {}
        first = None
        for item in items:
            key, text = item[0], item[1]
            ico = item[2] if len(item) > 2 else None
            b = Gtk.ToggleButton()
            if ico and text:
                b.set_child(hbox(6, icon(ico), Gtk.Label(label=text)))
            elif ico:
                b.set_child(icon(ico))
            else:
                b.set_label(text)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._toggled, key)
            self.append(b)
            self.buttons[key] = b
        self.set_active(active)

    def _toggled(self, b, key):
        if b.get_active() and not self._quiet and self._cb:
            self._cb(key)

    def set_active(self, key: Optional[str]):
        self._quiet = True
        if key in self.buttons:
            self.buttons[key].set_active(True)
        else:
            for b in self.buttons.values():
                b.set_active(False)
        self._quiet = False

    def active(self) -> Optional[str]:
        for k, b in self.buttons.items():
            if b.get_active():
                return k
        return None


class Chip(Gtk.Box):
    def __init__(self, text: str = "", kind: str = "neutral"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
        self.add_css_class("chip")
        self._icon = icon("info", fill=True)
        self._lbl = Gtk.Label(label=text)
        self.append(self._icon)
        self.append(self._lbl)
        self._kind = None
        self.set(text, kind)

    def set(self, text: str, kind: str = "neutral"):
        self._lbl.set_label(text)
        if kind != self._kind:
            for k in ("ok", "warn", "error"):
                self.remove_css_class(k)
            if kind in ("ok", "warn", "error"):
                self.add_css_class(kind)
            self._icon.set_label(fonts.codepoint({"ok": "check_circle", "warn": "bedtime", "error": "error"}
                                                 .get(kind, "info")))
            self._kind = kind


# ------------------------------------------------------------ shapes

def _r_circle(a):
    return 1.0


def _r_squircle(a):
    c, s = abs(math.cos(a)), abs(math.sin(a))
    return (c ** 4 + s ** 4) ** -0.25 / 1.19


def _r_cookie(n, depth):
    def f(a):
        return (1 + depth * math.cos(n * a)) / (1 + depth)
    return f


def _r_clover(a):
    return (0.72 + 0.28 * abs(math.cos(2 * a)) ** 0.6)


SHAPES = {
    "circle": _r_circle,
    "squircle": _r_squircle,
    "cookie4": _r_cookie(4, 0.12),
    "cookie6": _r_cookie(6, 0.09),
    "cookie9": _r_cookie(9, 0.065),
    "cookie12": _r_cookie(12, 0.05),
    "sunny": _r_cookie(8, 0.09),
    "flower": _r_cookie(6, 0.17),
    "clover": _r_clover,
}


def shape_path(cr, cx: float, cy: float, r: float, shape: str = "circle", to: Optional[str] = None,
               t: float = 0.0, rotate: float = 0.0, steps: int = 96):
    """Polar outline of an Expressive shape, optionally morphing toward another."""
    fa = SHAPES.get(shape, _r_circle)
    fb = SHAPES.get(to, fa) if to else fa
    for i in range(steps + 1):
        a = 2 * math.pi * i / steps
        rr = r * (fa(a) * (1 - t) + fb(a) * t)
        x, y = cx + rr * math.cos(a + rotate), cy + rr * math.sin(a + rotate)
        if i == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)
    cr.close_path()


def spring(t: float) -> float:
    """0..1 with a little overshoot, for morphs."""
    if t >= 1:
        return 1.0
    return 1 - math.exp(-6 * t) * math.cos(9 * t)


class Animator:
    """Runs a 0..1 value over `ms` on a widget's frame clock; instant when motion is reduced."""

    def __init__(self, widget, on_value: Callable[[float], None]):
        self.widget = widget
        self.on_value = on_value
        self._tick = None
        self._start = 0.0
        self._ms = 300

    def run(self, ms: int = 320):
        if not motion() or not self.widget.get_mapped():
            self.on_value(1.0)
            return
        self._ms = ms
        self._start = time.monotonic()
        if self._tick is None:
            self._tick = self.widget.add_tick_callback(self._frame)

    def _frame(self, _w, _clock):
        p = (time.monotonic() - self._start) * 1000 / self._ms
        self.on_value(min(1.0, p))
        if p >= 1.0:
            self._tick = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE


def _lum(hex6: str) -> float:
    return (int(hex6[0:2], 16) * 299 + int(hex6[2:4], 16) * 587 + int(hex6[4:6], 16) * 114) / 1000


class Swatch(Gtk.DrawingArea):
    """A colour swatch: rounded square, morphing into a scalloped 'cookie' when selected."""

    def __init__(self, hex6: str, size: int = 44, selected: bool = False, badge: str = "",
                 on_click: Optional[Callable] = None, on_right: Optional[Callable] = None, tooltip: str = "",
                 add: bool = False):
        super().__init__()
        themed(self)
        self.hex = hex6
        self.size = size
        self.selected = selected
        self.badge = badge
        self.add = add
        self._t = 1.0 if selected else 0.0
        self._from = self._t
        self._target = self._t
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)
        if tooltip:
            self.set_tooltip_text(tooltip)
        self._anim = Animator(self, self._step)
        if on_click or on_right:
            self.set_cursor(Gdk.Cursor.new_from_name("pointer"))
            g = Gtk.GestureClick(button=0)
            g.connect("pressed", self._pressed, on_click, on_right)
            self.add_controller(g)

    def _pressed(self, g, _n, _x, _y, on_click, on_right):
        btn = g.get_current_button()
        if btn == 3 and on_right:
            on_right()
        elif btn == 1 and on_click:
            on_click()

    def _step(self, p):
        self._t = self._from + (self._target - self._from) * spring(p)
        self.queue_draw()

    def set_state(self, hex6: Optional[str] = None, selected: Optional[bool] = None, badge: Optional[str] = None):
        changed = False
        if hex6 is not None and hex6 != self.hex:
            self.hex = hex6
            changed = True
        if badge is not None and badge != self.badge:
            self.badge = badge
            changed = True
        if selected is not None and selected != self.selected:
            self.selected = selected
            self._from, self._target = self._t, (1.0 if selected else 0.0)
            self._anim.run(380)
            return
        if changed:
            self.queue_draw()

    def _draw(self, _a, cr, w, h):
        cx, cy, r = w / 2, h / 2, min(w, h) / 2
        t = max(0.0, min(1.2, self._t))
        if self.add:
            cr.set_source_rgb(*rgb("SECONDARY_CONTAINER"))
            shape_path(cr, cx, cy, r * 0.9, "squircle")
            cr.fill()
            cr.set_source_rgb(*rgb("ON_SECONDARY_CONTAINER"))
            cr.set_line_width(2.4)
            cr.move_to(cx - r * 0.32, cy)
            cr.line_to(cx + r * 0.32, cy)
            cr.move_to(cx, cy - r * 0.32)
            cr.line_to(cx, cy + r * 0.32)
            cr.stroke()
            return
        if t > 0.01:
            cr.set_source_rgb(*rgb("PRIMARY"))
            shape_path(cr, cx, cy, r * (0.86 + 0.14 * min(t, 1.0)), "squircle", "cookie9", min(1.0, t))
            cr.fill()
            cr.set_source_rgb(*rgb("SURFACE_CONTAINER"))
            shape_path(cr, cx, cy, r * 0.80, "squircle", "cookie9", min(1.0, t))
            cr.fill()
        cr.set_source_rgb(*theme.hex_rgb(self.hex))
        shape_path(cr, cx, cy, r * (0.86 - 0.12 * t), "squircle", "cookie9", min(1.0, t))
        cr.fill()
        if self.badge:
            cr.set_source_rgb(*((0, 0, 0) if _lum(self.hex) > 150 else (1, 1, 1)))
            cr.select_font_face(fonts.TEXT_FAMILY, 0, 1)
            cr.set_font_size(r * 0.62)
            ext = cr.text_extents(self.badge)
            cr.move_to(cx - ext.width / 2 - ext.x_bearing, cy - ext.height / 2 - ext.y_bearing)
            cr.show_text(self.badge)
        if self.hex in EXACT_COLORS:
            # exact colour: a small dot in the corner
            dx, dy, dr = cx + r * 0.6, cy - r * 0.6, max(3.0, r * 0.2)
            cr.arc(dx, dy, dr + 1.5, 0, 2 * math.pi)
            cr.set_source_rgb(*rgb("SURFACE"))
            cr.fill()
            cr.arc(dx, dy, dr, 0, 2 * math.pi)
            cr.set_source_rgb(*rgb("ON_SURFACE"))
            cr.fill()


class QuickColors(Gtk.Box):
    """Your saved and recently used colors, for painting: click = first color, right-click = second.

    get_saved/get_recent return lists of hex; on_save() keeps the current first color.
    Every live instance refreshes on QuickColors.refresh_all() (after a pick or a save)."""

    _live: "weakref.WeakSet" = None

    def __init__(self, get_saved: Callable[[], List[str]], get_recent: Callable[[], List[str]],
                 on_a: Callable[[str], None], on_b: Optional[Callable[[str], None]] = None,
                 on_save: Optional[Callable[[], None]] = None, size: int = 26, per_line: int = 8):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._get_saved, self._get_recent = get_saved, get_recent
        self._on_a, self._on_b, self._on_save = on_a, on_b, on_save
        self._size, self._per_line = size, per_line
        if QuickColors._live is None:
            QuickColors._live = weakref.WeakSet()
        QuickColors._live.add(self)
        self.refresh()

    @classmethod
    def refresh_all(cls):
        for q in list(cls._live or ()):
            q.refresh()

    def _flow(self, colors, add=False):
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=self._per_line,
                           min_children_per_line=min(self._per_line, max(1, len(colors) + (1 if add else 0))),
                           column_spacing=2, row_spacing=2, halign=Gtk.Align.START, homogeneous=True)
        tip = (_("#{hex}: click for the first color, right-click for the second") if self._on_b
               else _("#{hex}: click for the first color"))
        for c in colors:
            flow.append(Swatch(c, self._size, tooltip=tip.format(hex=c), on_click=lambda c=c: self._on_a(c),
                               on_right=(lambda c=c: self._on_b(c)) if self._on_b else None))
        if add:
            flow.append(Swatch("000000", self._size, add=True, on_click=self._on_save,
                               tooltip=_("Save the first color to your saved colors")))
        return flow

    def refresh(self):
        c = self.get_first_child()
        while c:
            n = c.get_next_sibling()
            self.remove(c)
            c = n
        saved = [c for c in (self._get_saved() or []) if isinstance(c, str) and len(c) == 6]
        recent = [c for c in (self._get_recent() or []) if isinstance(c, str) and len(c) == 6 and c not in saved]
        self.append(label(_("Saved colors"), ("tiny", "dim")))
        if saved or self._on_save:
            self.append(self._flow(saved[:32], add=bool(self._on_save)))
        if recent:
            self.append(label(_("Recently used"), ("tiny", "dim")))
            self.append(self._flow(recent[:self._per_line * 2]))


class SwatchPicker(Gtk.Box):
    """Pattern colour picker: wallpaper colours (by index) + saved custom colours (by hex), ordered."""

    def __init__(self, extracted: List[str], selected: list, on_change: Callable[[list], None],
                 custom: Optional[List[str]] = None, on_add: Optional[Callable] = None,
                 on_remove_custom: Optional[Callable[[str], None]] = None, max_select: int = 8, size: int = 40,
                 hint: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.extracted = list(extracted)
        self.custom = list(custom or [])
        self.selected = list(selected)
        self.on_change = on_change
        self.on_add = on_add
        self.on_remove_custom = on_remove_custom
        self.max_select = max_select
        self.size = size
        self.hint = hint
        self._build()

    @staticmethod
    def _key(entry):
        return entry if isinstance(entry, int) else str(entry).lstrip("#").lower()

    def _keys(self):
        return [self._key(e) for e in self.selected]

    def _build(self):
        child = self.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.remove(child)
            child = nxt
        keys = self._keys()
        self.append(label(_("Wallpaper colors"), ("small", "dim")))
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12, column_spacing=4,
                           row_spacing=4, homogeneous=False, halign=Gtk.Align.START)
        flow.set_min_children_per_line(max(1, min(10, len(self.extracted))))
        for i, c in enumerate(self.extracted):
            sel = i in keys
            flow.append(Swatch(c, self.size, sel, str(keys.index(i) + 1) if sel and self.max_select > 1 else "",
                               on_click=lambda i=i: self._toggle(i), tooltip=_('Wallpaper color {n}  #{hex}').format(n=i + 1, hex=c)))
        self.append(flow)
        self.append(label(_("Saved colors"), ("small", "dim")))
        flow2 = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12, column_spacing=4,
                            row_spacing=4, halign=Gtk.Align.START)
        shown = list(self.custom)
        for e in self.selected:          # a picked hex that isn't saved any more still shows
            if isinstance(e, str) and self._key(e) not in [self._key(c) for c in shown]:
                shown.append(self._key(e))
        for c in shown:
            k = self._key(c)
            sel = k in keys
            flow2.append(Swatch(k, self.size, sel, str(keys.index(k) + 1) if sel and self.max_select > 1 else "",
                                on_click=lambda k=k: self._toggle(k),
                                on_right=(lambda k=k: self.on_remove_custom(k)) if self.on_remove_custom else None,
                                tooltip=_('#{k}  (right-click to delete)').format(k=k)))
        flow2.set_min_children_per_line(max(1, min(10, len(shown) + (1 if self.on_add else 0))))
        if self.on_add:
            flow2.append(Swatch("000000", self.size, add=True, on_click=self.on_add, tooltip=_("Save a new color")))
        self.append(flow2)
        if self.hint:
            self.append(label(_("Click to use. Right-click a saved color to delete it.") if self.max_select == 1 else
                              _("Click to use, numbers show the order. Right-click a saved color to delete it."),
                              ("tiny", "faint"), wrap=True))

    def _toggle(self, key):
        keys = self._keys()
        if self.max_select == 1:
            self.selected = [key]
        elif key in keys:
            if len(keys) == 1:
                return
            self.selected = [e for e in self.selected if self._key(e) != key]
        else:
            if len(keys) >= self.max_select:
                return
            self.selected.append(key)
        self._build()
        self.on_change(list(self.selected))

    def set_max_select(self, n: int) -> bool:
        if n == self.max_select:
            return False
        self.max_select = n
        if len(self.selected) > n:
            self.selected = self.selected[:n]
        self._build()
        return True

    def set_colors(self, extracted, selected, custom=None):
        self.extracted = list(extracted)
        self.selected = list(selected)
        if custom is not None:
            self.custom = list(custom)
        self._build()

    def current_hex(self) -> List[str]:
        return resolve_colors(self.selected, self.extracted)


# --------------------------------------------------------------- strip editor

def _mix_hex(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2[i:i + 2], 16) for i in (0, 2, 4)]
    return "%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


RULER_H = 15


def _ruler(cr, x0, x1, n, y):
    """LED numbers under a strip: 1, every few LEDs (as many as fit) and the last one, which is the
    strip's real LED count."""
    cw = (x1 - x0) / max(1, n)
    step = next((s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000) if s * cw >= 30), 1000)
    marks = [1] + [k for k in range(step, n, step) if (n - k) * cw >= 22] + ([n] if n > 1 else [])
    cr.select_font_face(fonts.TEXT_FAMILY, 0, 0)
    cr.set_font_size(10)
    for k in marks:
        cx = x0 + (k - 0.5) * cw
        cr.set_source_rgb(*rgb("OUTLINE_VARIANT"))
        cr.rectangle(cx - 0.5, y, 1, 3)
        cr.fill()
        txt = str(k)
        ext = cr.text_extents(txt)
        tx = min(max(cx - ext.width / 2 - ext.x_bearing, x0 - 4), x1 + 4 - ext.width)
        cr.set_source_rgb(*rgb("ON_SURFACE" if k == n else "OUTLINE"))
        cr.move_to(tx, y + 13)
        cr.show_text(txt)


class StripEditor(Gtk.DrawingArea):
    """Full-width LED strip: shows the colours, layout handles for stops, painting, and LED numbers
    under it."""

    STRIP_H = 28
    HANDLE_H = 22

    def __init__(self, render=None, on_stops=None, on_paint=None):
        super().__init__()
        themed(self)
        self.set_hexpand(True)
        self._render, self._on_stops, self._on_paint = render, on_stops, on_paint
        self.led_count = 20
        self.colors = ["000000"] * 20
        self.pattern = "solid"
        self.stops: List[float] = []
        self.layout_mode = False
        self.reverse = self.mirror = False
        self.paint_mode = False
        self.paint: List[Optional[str]] = []
        self.base_color: Optional[str] = None      # what erased LEDs show (the zone's own colour)
        self.tool = "paint"
        self.color_a, self.color_b = "ff8800", "3355ff"
        self._grad_anchor = None
        self._last_led = None
        self._drag = None
        self._painting = False
        self._x0 = 0.0
        self.ruler = RULER_H                  # 0: no LED numbers (a preview that isn't a real strip)
        self.set_content_height(self.STRIP_H + 8 + RULER_H)
        self.set_draw_func(self._draw)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._begin)
        g.connect("drag-update", self._update)
        g.connect("drag-end", self._end)
        self.add_controller(g)

    # state
    def set_state(self, led_count, colors, pattern):
        self.led_count = max(1, led_count)
        self.colors = list(colors)
        self.pattern = pattern
        self.queue_draw()

    def set_flags(self, reverse, mirror):
        self.reverse, self.mirror = bool(reverse), bool(mirror)

    def _twin(self):
        return self.pattern in ("center_out", "edges_in") or self.mirror

    def set_ruler(self, on):
        self.ruler = RULER_H if on else 0
        self.set_content_height(self.STRIP_H + 8 + (self.HANDLE_H if self.layout_mode else 0) + self.ruler)

    def set_layout(self, on, stops):
        self.layout_mode = on
        self.stops = list(stops)
        self.set_content_height(self.STRIP_H + 8 + (self.HANDLE_H if on else 0) + self.ruler)
        self.queue_draw()

    def set_paint(self, on, paint):
        self.paint_mode = on
        self.paint = (list(paint) + [None] * self.led_count)[: self.led_count]
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair") if on else None)
        self.queue_draw()

    def fill_all(self, c):
        self.paint = [c] * self.led_count
        self._commit()

    def reset_gradient_anchor(self):
        self._grad_anchor = None

    # geometry
    def _xr(self):
        w = self.get_width()
        return 8.0, max(60.0, w - 8.0)

    def _led_at(self, x):
        x0, x1 = self._xr()
        return max(0, min(self.led_count - 1, int((x - x0) / (x1 - x0) * self.led_count)))

    def _v_to_x(self, v):
        x0, x1 = self._xr()
        f = 0.5 + v / 2 if self.pattern == "center_out" else 0.5 + (1 - v) / 2 if self.pattern == "edges_in" else v
        if self.mirror:
            f = f / 2
        if self.reverse:
            f = 1 - f
        return x0 + f * (x1 - x0)

    def _x_to_v(self, x):
        x0, x1 = self._xr()
        f = max(0.0, min(1.0, (x - x0) / (x1 - x0)))
        if self.reverse:
            f = 1 - f
        if self.mirror:
            return max(0.0, min(1.0, min(f, 1 - f) * 2))
        if self.pattern == "center_out":
            return max(0.0, min(1.0, 2 * f - 1))
        if self.pattern == "edges_in":
            return max(0.0, min(1.0, 2 - 2 * f))
        return f

    # drawing
    def _draw(self, _a, cr, w, h):
        x0, x1 = self._xr()
        n = self.led_count
        cw = (x1 - x0) / n
        gap = 1.0 if cw >= 5 else 0.0
        y0 = 4
        cr.set_source_rgb(*rgb("SURFACE_CONTAINER_HIGHEST"))
        _rounded(cr, x0 - 4, y0 - 2, (x1 - x0) + 8, self.STRIP_H + 4, 10)
        cr.fill()
        cols = self.paint if self.paint_mode else self.colors
        for i in range(n):
            c = cols[i] if i < len(cols) else None
            if self.paint_mode and not c:
                base = self.base_color or (self.colors[i] if i < len(self.colors) else None)
                cr.set_source_rgb(*(theme.hex_rgb(base) if base else rgb("SURFACE_BRIGHT")))
            else:
                cr.set_source_rgb(*theme.hex_rgb(c or "000000"))
            r = min(4.0, cw / 2.5)
            _rounded(cr, x0 + i * cw, y0, max(1.0, cw - gap), self.STRIP_H, r)
            cr.fill()
        if self.ruler:
            _ruler(cr, x0, x1, n, h - RULER_H)
        if self.layout_mode and not self.paint_mode:
            for v in self.stops:
                x = self._v_to_x(v)
                xs = [x] + ([x0 + x1 - x] if self._twin() else [])
                cr.set_source_rgba(1, 1, 1, 0.85)
                cr.set_line_width(1)
                cr.set_dash([3, 2])
                for xx in xs:
                    cr.move_to(xx, y0)
                    cr.line_to(xx, y0 + self.STRIP_H)
                cr.stroke()
                cr.set_dash([])
                top = y0 + self.STRIP_H + 4
                for j, xx in enumerate(xs):
                    cr.set_source_rgb(*rgb("PRIMARY" if j == 0 else "OUTLINE_VARIANT"))
                    _rounded(cr, xx - 3, top, 6, self.HANDLE_H - 6, 3)
                    cr.fill()

    # events
    def _nearest(self, x):
        best, bd = None, 14
        x0, x1 = self._xr()
        for k, v in enumerate(self.stops):
            d = abs(self._v_to_x(v) - x)
            if self._twin():
                d = min(d, abs((x0 + x1 - self._v_to_x(v)) - x))
            if d < bd:
                best, bd = k, d
        return best

    def _begin(self, g, x, y):
        self._start = (x, y)
        if self.paint_mode:
            self._painting = True
            self._apply(self._led_at(x), start=True)
        elif self.layout_mode:
            self._drag = self._nearest(x)

    def _update(self, g, ox, oy):
        x = self._start[0] + ox
        if self.paint_mode and self._painting and self.tool != "gradient":
            self._apply(self._led_at(x))
            return
        if self._drag is None:
            return
        v = self._x_to_v(x)
        k = self._drag
        lo = self.stops[k - 1] if k > 0 else 0.0
        hi = self.stops[k + 1] if k + 1 < len(self.stops) else 1.0
        self.stops[k] = max(lo, min(hi, v))
        if self._render:
            self.colors = self._render(list(self.stops))
        self.queue_draw()

    def _end(self, g, ox, oy):
        if self.paint_mode and self._painting:
            self._painting = False
            self._last_led = None
            if self.tool != "gradient":
                self._commit()
            return
        if self._drag is not None:
            self._drag = None
            if self._on_stops:
                self._on_stops(list(self.stops))

    def _apply(self, i, start=False):
        if self.tool in ("paint", "erase"):
            val = self.color_a if self.tool == "paint" else None
            last = i if start or self._last_led is None else self._last_led
            for j in range(min(last, i), max(last, i) + 1):
                self.paint[j] = val
            self._last_led = i
        elif self.tool == "gradient" and start:
            if self._grad_anchor is None:
                self._grad_anchor = i
                self.paint[i] = self.color_a
            else:
                a, b = sorted((self._grad_anchor, i))
                ca, cb = (self.color_a, self.color_b) if self._grad_anchor <= i else (self.color_b, self.color_a)
                for j in range(a, b + 1):
                    self.paint[j] = _mix_hex(ca, cb, (j - a) / (b - a) if b > a else 0.0)
                self._grad_anchor = None
                self._commit()
                return
        self.queue_draw()

    def _commit(self):
        self.queue_draw()
        if self._on_paint:
            self._on_paint(list(self.paint))


class SectionStrip(Gtk.DrawingArea):
    """A strip split into parts: the LEDs, each part's number above it, a handle under every divider
    (drag it, it snaps to whole LEDs) and a dot under LEDs set by hand. In pick mode, clicking or
    dragging over LEDs calls on_led(index) for each one."""

    STRIP_H = 26
    NUM_H = 16
    HANDLE_H = 18

    def __init__(self, on_drag=None, on_moved=None, on_led=None):
        super().__init__()
        themed(self)
        self.set_hexpand(True)
        self.n = 20
        self.colors = ["000000"] * 20
        self.starts: List[int] = []           # first LED of every part but the first
        self.marked = set()                   # LEDs set by hand
        self.pick_mode = False
        self._on_drag, self._on_moved, self._on_led = on_drag, on_moved, on_led
        self._drag = None
        self._last_led = None
        self.set_content_height(self.NUM_H + self.STRIP_H + self.HANDLE_H + 6 + RULER_H)
        self.set_draw_func(self._draw)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._begin)
        g.connect("drag-update", self._update)
        g.connect("drag-end", self._end)
        self.add_controller(g)

    def set_state(self, n, colors, starts, marked):
        self.n = max(1, n)
        self.colors = list(colors)
        if self._drag is None:
            self.starts = list(starts)
        self.marked = set(marked)
        self.queue_draw()

    def set_pick(self, on):
        self.pick_mode = on
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair") if on else None)

    def _xr(self):
        return 8.0, max(60.0, self.get_width() - 8.0)

    def _x_of(self, led):
        x0, x1 = self._xr()
        return x0 + led * (x1 - x0) / self.n

    def _led_at(self, x):
        x0, x1 = self._xr()
        return max(0, min(self.n - 1, int((x - x0) / (x1 - x0) * self.n)))

    def _draw(self, _a, cr, w, h):
        x0, x1 = self._xr()
        n = self.n
        cw = (x1 - x0) / n
        gap = 1.0 if cw >= 5 else 0.0
        y0 = self.NUM_H + 2
        cr.set_source_rgb(*rgb("SURFACE_CONTAINER_HIGHEST"))
        _rounded(cr, x0 - 4, y0 - 2, (x1 - x0) + 8, self.STRIP_H + 4, 10)
        cr.fill()
        for i in range(n):
            c = self.colors[i] if i < len(self.colors) else "000000"
            cr.set_source_rgb(*theme.hex_rgb(c or "000000"))
            _rounded(cr, x0 + i * cw, y0, max(1.0, cw - gap), self.STRIP_H, min(4.0, cw / 2.5))
            cr.fill()
        # part numbers
        cr.select_font_face(fonts.TEXT_FAMILY, 0, 1)
        cr.set_font_size(11)
        edges = [0] + list(self.starts) + [n]
        for k in range(len(edges) - 1):
            mid = (self._x_of(edges[k]) + self._x_of(edges[k + 1])) / 2
            txt = str(k + 1)
            ext = cr.text_extents(txt)
            cr.set_source_rgb(*rgb("ON_SURFACE_VARIANT"))
            cr.move_to(mid - ext.width / 2 - ext.x_bearing, self.NUM_H - 4)
            cr.show_text(txt)
        # LEDs set by hand
        cr.set_source_rgb(*rgb("ON_SURFACE"))
        for i in self.marked:
            if 0 <= i < n:
                cr.arc(x0 + (i + 0.5) * cw, y0 + self.STRIP_H + 4, 2.2, 0, 2 * math.pi)
                cr.fill()
        _ruler(cr, x0, x1, n, h - RULER_H)
        # dividers
        for k, s in enumerate(self.starts):
            x = self._x_of(s)
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.set_line_width(2)
            cr.move_to(x, y0 - 3)
            cr.line_to(x, y0 + self.STRIP_H + 3)
            cr.stroke()
            cr.set_source_rgb(*rgb("PRIMARY" if self._drag == k else "OUTLINE"))
            _rounded(cr, x - 4, y0 + self.STRIP_H + 7, 8, self.HANDLE_H - 6, 4)
            cr.fill()

    def _nearest(self, x):
        best, bd = None, 12
        for k, s in enumerate(self.starts):
            d = abs(self._x_of(s) - x)
            if d < bd:
                best, bd = k, d
        return best

    def _begin(self, g, x, y):
        self._start = (x, y)
        on_handles = y >= self.NUM_H + self.STRIP_H
        self._drag = self._nearest(x) if (on_handles or not self.pick_mode) else None
        if self._drag is None and self.pick_mode:
            self._last_led = self._led_at(x)
            if self._on_led:
                self._on_led(self._last_led)
        self.queue_draw()

    def _update(self, g, ox, oy):
        x = self._start[0] + ox
        if self._drag is None:
            if self.pick_mode and self._last_led is not None:
                i = self._led_at(x)
                if i != self._last_led and self._on_led:
                    for j in range(min(i, self._last_led), max(i, self._last_led) + 1):
                        if j != self._last_led:
                            self._on_led(j)
                    self._last_led = i
            return
        x0, x1 = self._xr()
        led = int(round((x - x0) / (x1 - x0) * self.n))
        k = self._drag
        lo = self.starts[k - 1] + 1 if k > 0 else 1
        hi = self.starts[k + 1] - 1 if k + 1 < len(self.starts) else self.n - 1
        led = max(lo, min(hi, led))
        if led != self.starts[k]:
            self.starts[k] = led
            if self._on_drag:
                self._on_drag(list(self.starts))
        self.queue_draw()

    def _end(self, g, ox, oy):
        self._last_led = None
        if self._drag is not None:
            self._drag = None
            self.queue_draw()
            if self._on_moved:
                self._on_moved(list(self.starts))


def _rounded(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


rounded_rect = _rounded


# ------------------------------------------------------------ dual range

class DualRange(Gtk.DrawingArea):
    """Two-handle 0..100 range slider with Expressive bar handles."""

    def __init__(self, lo: int, hi: int, on_change: Optional[Callable[[int, int], None]] = None, width: int = 260):
        super().__init__()
        themed(self)
        self.lo, self.hi = lo, hi
        self.on_change = on_change
        self._drag = None
        self.set_content_width(width)
        self.set_content_height(52)
        self.set_draw_func(self._draw)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._begin)
        g.connect("drag-update", self._update)
        g.connect("drag-end", lambda *_a: setattr(self, "_drag", None))
        self.add_controller(g)

    def dragging(self) -> bool:
        return self._drag is not None

    def _x(self, v):
        w = self.get_width()
        return 14 + (w - 28) * v / 100

    def _v(self, x):
        w = self.get_width()
        return int(round(max(0, min(100, (x - 14) / max(1, w - 28) * 100))))

    def _draw(self, _a, cr, w, h):
        y = 18
        x0, x1 = self._x(0), self._x(100)
        a, b = self._x(self.lo), self._x(self.hi)
        cr.set_source_rgb(*rgb("SECONDARY_CONTAINER"))
        _rounded(cr, x0, y - 6, x1 - x0, 12, 6)
        cr.fill()
        cr.set_source_rgb(*rgb("PRIMARY"))
        _rounded(cr, a, y - 6, max(2, b - a), 12, 6)
        cr.fill()
        for x in (a, b):
            cr.set_source_rgb(*rgb("SURFACE_CONTAINER_HIGH"))
            _rounded(cr, x - 5, y - 18, 10, 36, 4)
            cr.fill()
            cr.set_source_rgb(*rgb("PRIMARY"))
            _rounded(cr, x - 2, y - 16, 4, 32, 2)
            cr.fill()
        cr.set_source_rgb(*rgb("ON_SURFACE_VARIANT"))
        cr.select_font_face(fonts.TEXT_FAMILY, 0, 0)
        cr.set_font_size(11.5)
        for x, v in ((a, self.lo), (b, self.hi)):
            t = f"{v}%"
            ext = cr.text_extents(t)
            cr.move_to(min(max(0, x - ext.width / 2), w - ext.width), 50)
            cr.show_text(t)

    def _begin(self, g, x, y):
        self._sx = x
        self._drag = "lo" if abs(x - self._x(self.lo)) <= abs(x - self._x(self.hi)) else "hi"
        self._move(x)

    def _update(self, g, ox, oy):
        self._move(self._sx + ox)

    def _move(self, x):
        v = self._v(x)
        if self._drag == "lo":
            self.lo = min(v, self.hi - 1)
        else:
            self.hi = max(v, self.lo + 1)
        self.queue_draw()
        if self.on_change:
            self.on_change(self.lo, self.hi)

    def set(self, lo, hi):
        if (lo, hi) != (self.lo, self.hi) and self._drag is None:
            self.lo, self.hi = lo, hi
            self.queue_draw()


# ------------------------------------------------------------ loading indicator

class LoadingIndicator(Gtk.DrawingArea):
    """Material 3 Expressive loading indicator: a shape that morphs through the Expressive set.

    It only animates while visible and started, so it costs nothing otherwise."""

    SEQ = ["cookie9", "clover", "sunny", "cookie4", "flower", "squircle"]

    def __init__(self, size: int = 48):
        super().__init__()
        themed(self)
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)
        self._tick = None
        self._t0 = time.monotonic()

    def start(self):
        if self._tick is None and motion():
            self._t0 = time.monotonic()
            self._tick = self.add_tick_callback(lambda *_a: (self.queue_draw(), GLib.SOURCE_CONTINUE)[1])
        self.set_visible(True)

    def stop(self):
        if self._tick is not None:
            self.remove_tick_callback(self._tick)
            self._tick = None
        self.set_visible(False)

    def _draw(self, _a, cr, w, h):
        el = time.monotonic() - self._t0
        per = 0.75
        i = int(el / per)
        p = (el % per) / per
        a, b = self.SEQ[i % len(self.SEQ)], self.SEQ[(i + 1) % len(self.SEQ)]
        cr.set_source_rgb(*rgb("PRIMARY"))
        shape_path(cr, w / 2, h / 2, min(w, h) * 0.42, a, b, min(1.0, spring(p)), rotate=el * 1.6)
        cr.fill()


# ------------------------------------------------------------ wavy bar

class WavyBar(Gtk.DrawingArea):
    """Expressive 'wavy' linear indicator showing a static value (e.g. brightness)."""

    def __init__(self, width: int = 220, on_dark: bool = False):
        super().__init__()
        themed(self)
        self.value = 0.0
        self.on_dark = on_dark
        self.set_content_width(width)
        self.set_content_height(16)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def set_value(self, v: float):
        v = max(0.0, min(1.0, v))
        if abs(v - self.value) > 0.001:
            self.value = v
            self.queue_draw()

    def _draw(self, _a, cr, w, h):
        mid = h / 2
        end = 4 + (w - 8) * self.value
        cr.set_line_width(4)
        cr.set_line_cap(1)
        cr.set_source_rgb(*rgb("ON_PRIMARY_CONTAINER" if self.on_dark else "PRIMARY"))
        x = 4.0
        cr.move_to(x, mid)
        while x < end:
            x = min(end, x + 1.5)
            cr.line_to(x, mid + 3.2 * math.sin(x / 5.0))
        cr.stroke()
        if end + 8 < w - 4:
            cr.set_source_rgba(*rgb("ON_PRIMARY_CONTAINER" if self.on_dark else "SECONDARY_CONTAINER"),
                               0.35 if self.on_dark else 1.0)
            cr.move_to(end + 8, mid)
            cr.line_to(w - 4, mid)
            cr.stroke()


# ------------------------------------------------------------ snackbar

class Snackbar(Gtk.Revealer):
    def __init__(self):
        super().__init__(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=220,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        self._box = hbox(12)
        self._box.add_css_class("snackbar")
        self._lbl = label("", wrap=True, chars=60)
        self._btn = Gtk.Button()
        self._btn.connect("clicked", self._act)
        self._box.append(self._lbl)
        self._box.append(self._btn)
        self.set_child(self._box)
        self._action = None
        self._job = None
        self.set_can_target(True)

    def show(self, text: str, action_label: Optional[str] = None, action: Optional[Callable] = None,
             seconds: float = 3.5):
        self._lbl.set_label(text)
        self._action = action
        self._btn.set_visible(bool(action_label))
        if action_label:
            self._btn.set_label(action_label)
        self.set_transition_duration(220 if motion() else 0)
        self.set_reveal_child(True)
        if self._job:
            GLib.source_remove(self._job)
        self._job = GLib.timeout_add(int(seconds * 1000), self._hide)

    def _hide(self):
        self._job = None
        self.set_reveal_child(False)
        return False

    def _act(self, _b):
        self._hide()
        if self._action:
            self._action()


# ------------------------------------------------------------ colour helpers

def hsv_hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360, s, v)
    return f"{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def copy_text(widget: Gtk.Widget, text: str):
    cb = widget.get_clipboard()
    try:
        cb.set(text)                    # PyGObject >= 3.44
    except (AttributeError, TypeError):
        cb.set_content(Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8",
                                                         GLib.Bytes.new(text.encode("utf-8"))))


def clear(container: Gtk.Widget):
    """Remove every child (FlowBox/ListBox.remove_all needs GTK 4.12)."""
    c = container.get_first_child()
    while c is not None:
        n = c.get_next_sibling()
        container.remove(c)
        c = n


def restyle_all():
    """Make every widget work out its style again, on hidden pages too. After the stylesheet
    changes, GTK 4.24 leaves values a hidden widget inherits (the text size in a button) as they
    were until something else changes on that widget, so text on a tab you weren't looking at
    kept its old size until you hovered it."""
    for top in Gtk.Window.list_toplevels():
        for w in _walk(top):
            w.add_css_class("restyle")
            w.remove_css_class("restyle")


def _walk(w):
    stack = [w]
    while stack:
        w = stack.pop()
        yield w
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()


def load_css(provider, css: str):
    """CssProvider loading that works from GTK 4.6 to 4.20 (the binding changed twice)."""
    if hasattr(provider, "load_from_string"):          # 4.12+
        provider.load_from_string(css)
        return
    try:
        provider.load_from_data(css, -1)                # 4.9 .. 4.11
    except TypeError:
        provider.load_from_data(css.encode("utf-8"))    # 4.0 .. 4.8
