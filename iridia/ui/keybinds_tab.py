"""The Keybinds tab: build an `iridia` command and show how to bind it to a key.

Iridia never listens to the keyboard itself. Your compositor or desktop owns the
keys and runs a command; this page writes that command and the line for your
config. Strip commands are temporary and switch back when run again.
"""

import os
import shlex
import shutil
import sys
from typing import List, Optional

from gi.repository import Gtk

from iridia.i18n import _
from iridia.layout import split_key
from iridia.ui import widgets
from iridia.ui.dialogs import run_bg
from iridia.ui.widgets import (Dropdown, Group, Spin, Swatch, Toggle, button, card, divider, hbox, label,
                               section, vbox)

OTHER = [
    # (label, kind)
    (_("All lights off / on"), "lights"),
    (_("Freeze colors / follow the wallpaper"), "freeze"),
    (_("Night mode on / off"), "night"),
    (_("Pause / resume animations"), "animations"),
    (_("Load a setup"), "setup"),
]
NO_MOD = _("No modifier")
ALL_STRIPS = _("All strips")
MODS = ["Super", "Super + Shift", "Super + Ctrl", "Super + Alt", "Ctrl + Alt", "Alt", NO_MOD]
DESKTOPS = ["Hyprland (hyprland.conf)", "Hyprland (hyprland.lua)", "Sway", "i3", "niri", "river",
            "KDE Plasma", "GNOME", _("sxhkd (X11 window managers)")]


def iridia_path() -> str:
    """Full path of the `iridia` command: desktops don't see the virtualenv in PATH."""
    cand = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "iridia")
    return cand if os.path.exists(cand) else "iridia"


def bind_line(desktop: str, mods: List[str], key: str, args: List[str]) -> tuple:
    """(where it goes, the text to paste) for one desktop."""
    exe = iridia_path()
    cmd = " ".join(shlex.quote(a) for a in [exe] + args)
    key = key.strip() or "F9"
    if desktop.startswith("Hyprland (hyprland.conf)"):
        return (_("~/.config/hypr/hyprland.conf (or a file it sources)"),
                f"bind = {' '.join(m.upper() for m in mods)}, {key}, exec, {cmd}")
    if desktop.startswith("Hyprland (hyprland.lua)"):
        combo = " + ".join([m.upper() for m in mods] + [key])
        inner = f"[[{cmd}]]" if '"' in cmd or "\\" in cmd else f'"{cmd}"'
        return "~/.config/hypr/hyprland.lua", f'hl.bind("{combo}", hl.dsp.exec_cmd({inner}))'
    sway_mods = {"Super": "Mod4", "Shift": "Shift", "Ctrl": "Ctrl", "Alt": "Mod1"}
    if desktop == "Sway":
        return "~/.config/sway/config", f"bindsym {'+'.join([sway_mods[m] for m in mods] + [key])} exec {cmd}"
    if desktop == "i3":
        return ("~/.config/i3/config",
                f"bindsym {'+'.join([sway_mods[m] for m in mods] + [key])} exec --no-startup-id {cmd}")
    if desktop == "niri":
        q = " ".join('"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"' for a in [exe] + args)
        return _("~/.config/niri/config.kdl, inside binds { }"), f"{'+'.join(mods + [key])} {{ spawn {q}; }}"
    if desktop == "river" and shutil.which("riverctl"):     # river-classic (0.3); 0.4 dropped riverctl
        return ("~/.config/river/init",
                f"riverctl map normal {'+'.join(mods) or 'None'} {key} spawn "
                + (f'"{cmd}"' if not any(ch in cmd for ch in '"$`\\') else shlex.quote(cmd)))
    if desktop == "river":
        return (_("river 0.4 and later leave keys to your window manager: bind this command in its "
                  "config:"), cmd)
    if desktop == "KDE Plasma":
        return (_("System Settings, Keyboard, Shortcuts, Add New, Command or Script. Paste this as the "
                  "command, then press your key:"), cmd)
    if desktop == "GNOME":
        return (_("Settings, Keyboard, View and Customize Shortcuts, Custom Shortcuts, +. Paste this as the "
                  "command, then set your key:"), cmd)
    sx = {"Super": "super", "Shift": "shift", "Ctrl": "ctrl", "Alt": "alt"}
    return "~/.config/sxhkd/sxhkdrc", " + ".join([sx[m] for m in mods] + [key]) + "\n    " + cmd


def _target_for(device: str, zone: str) -> str:
    """A target the daemon resolves to exactly this zone ('|' if the device name has a '/')."""
    if not zone:
        return device
    return f"{device}{'|' if '/' in device else '/'}{zone}"


class KeybindsPage:
    def __init__(self, app, page: Gtk.Box):
        self.app = app
        self.p = page
        self._targets = []          # [(shown name, target string)]
        self._target_sig = None
        self._overlay_sig = None
        self._setups: List[str] = []
        self._chips = {}            # shown name -> ToggleButton
        self._chip_quiet = False
        self.color = "ff0000"
        self.mode = "strips"
        self.power = "keep"
        self._build()

    # ---------------------------------------------------------------- UI
    def _build(self):
        p = self.p
        p.append(section(_("Keybinds"), _("Iridia doesn't listen to your keyboard. Your desktop does: you give a key a "
                                     "command, and pressing it runs that command. Build the command here, then "
                                     "add it to your desktop's config below.")))
        c = card()
        self._mode_group = Group([("strips", _("Change strips"), "polyline"), ("other", _("Other actions"), "bolt")],
                                 "strips", self._set_mode)
        self._mode_group.set_halign(Gtk.Align.START)
        c.append(self._mode_group)

        # ---- strips: any mix of on/off, a color and a brightness, for one or more strips
        self._strips_box = vbox(10)
        self._strips_box.append(label(_("Strips"), ("small", "dim")))
        self._chip_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                                      min_children_per_line=2, column_spacing=6, row_spacing=6,
                                      halign=Gtk.Align.FILL)
        self._strips_box.append(self._chip_flow)
        r = hbox(10)
        r.append(label(_("Power"), ("body", "dim")))
        self._power = Group([("keep", _("Leave as is")), ("on", _("Turn on")), ("off", _("Turn off")),
                             ("normal", _("Back to normal"))], "keep", self._set_power)
        r.append(self._power)
        self._strips_box.append(r)
        self._color_on = Toggle(True, lambda v: self._render())
        self._swatch = Swatch(self.color, 32, on_click=self._pick, tooltip=_("Pick the color"))
        self._hex = label(f"#{self.color}", ("body", "mono"))
        self._color_row = hbox(10, self._color_on, label(_("Color"), ("body",)), self._swatch, self._hex)
        self._strips_box.append(self._color_row)
        self._bright_on = Toggle(False, lambda v: self._render())
        self._bright = Spin(0, 100, 40, lambda v: self._render())
        self._bright_row = hbox(10, self._bright_on, label(_("Brightness"), ("body",)), self._bright,
                                label("%", ("body", "dim")))
        self._strips_box.append(self._bright_row)
        from iridia import animations as _anims
        from iridia.ui.effects import EFFECT_NAMES
        self._effect_names = [EFFECT_NAMES[e] for e in _anims.ORDER] + [_("Static pattern")]
        self._effect_keys = dict(zip(self._effect_names, _anims.ORDER + ["static"]))
        self._effect_on = Toggle(False, lambda v: self._render())
        self._effect_dd = Dropdown(self._effect_names, self._effect_names[0], lambda v: self._render())
        self._effect_row = hbox(10, self._effect_on, label(_("Effect"), ("body",)), self._effect_dd)
        self._strips_box.append(self._effect_row)
        c.append(self._strips_box)

        # ---- everything else
        self._other_box = vbox(10)
        r = hbox(10)
        r.append(label(_("Do"), ("body", "dim")))
        self._other = Dropdown([o[0] for o in OTHER], OTHER[0][0], lambda v: self._render())
        r.append(self._other)
        self._setup_dd = Dropdown([], None, lambda v: self._render(), placeholder=_("No setups yet"))
        self._setup_row = hbox(10, label(_("Setup"), ("body", "dim")), self._setup_dd)
        r.append(self._setup_row)
        self._other_box.append(r)
        c.append(self._other_box)

        c.append(divider())
        c.append(label(_("Command"), ("small", "dim")))
        self._cmd = label("", ("body", "mono"), wrap=True, selectable=True)
        c.append(self._cmd)
        self._note = label("", ("small", "faint"), wrap=True)
        c.append(self._note)
        r = hbox(8)
        r.append(button(_("Copy command"), "content_copy", "filled small", lambda: self._copy(self._cmd_text)))
        r.append(button(_("Try it"), "play_arrow", "tonal small", self._try))
        c.append(r)
        p.append(c)

        p.append(section(_("Add it to your desktop"), _("Pick your desktop and a key. Paste the line into the file shown, "
                                                   "then reload your desktop's config.")))
        c = card()
        r = hbox(10)
        r.append(label(_("Desktop"), ("body", "dim")))
        self._desk = Dropdown(DESKTOPS, self._guess_desktop(), lambda v: self._render())
        r.append(self._desk)
        c.append(r)
        r = hbox(10)
        r.append(label(_("Key"), ("body", "dim")))
        self._mods = Dropdown(MODS, "Super + Shift", lambda v: self._render())
        r.append(self._mods)
        r.append(label("+", ("body", "dim")))
        self._key = Gtk.Entry(text="F9", width_chars=8, max_width_chars=12, valign=Gtk.Align.CENTER,
                              hexpand=False)
        self._key.connect("changed", lambda *_a: self._render())
        r.append(self._key)
        c.append(r)
        c.append(label(_("Key names: F1 to F12, letters, numbers, or names like Print, Pause, XF86Tools. Pick a "
                       "combination your desktop doesn't use yet."), ("tiny", "faint"), wrap=True))
        self._where = label("", ("small", "dim"), wrap=True, selectable=True)
        c.append(self._where)
        tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        tv.add_css_class("log")
        self._line_buf = tv.get_buffer()
        c.append(tv)
        b = button(_("Copy line"), "content_copy", "filled small", lambda: self._copy(self._line_text))
        b.set_halign(Gtk.Align.START)
        c.append(b)
        p.append(c)

        p.append(section(_("Changed by a keybind right now"), _("Strip keybinds are temporary: nothing is saved, and they "
                                                          "end when you press the key again, run Back to normal, or "
                                                          "restart the daemon.")))
        self._active = card()
        p.append(self._active)

        exe = iridia_path()
        p.append(section(_("More examples"), _("Short form for reading. In your desktop's config write the full path, {exe}, as the command above does: desktops often don't know where Iridia is installed.").format(exe=exe)))
        c = card()
        tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        tv.add_css_class("log")
        examples = [
            ("zone list", _("the names you can use")),
            ("zone 'Desk back' off", _("off, again: back to normal")),
            ("zone 'Desk back' color ff0000", _("one color, again: back to normal")),
            ("zone all bright 20", _("every strip at 20%")),
            ("zone 'Desk back' on", _("light a strip that is switched off")),
            ("zone 'Desk back' on color ff0000 bright 40", _("several at once")),
            ("zone 'Desk back,Monitor' color 00ff88", _("several strips (commas)")),
            ("zone all normal", _("undo every keybind change")),
            ("zone 'Desk back' off --set", _("always off, never switch back")),
            ("lights toggle", _("everything off / on")),
            ("freeze toggle", _("stop / start following the wallpaper")),
            ("night toggle", _("night mode on / off")),
            ("zone 'Desk back' effect breathing --speed 3", _("an effect, again: back to normal")),
            ("zone all effect static", _("still colors until you press it again")),
            ("animations toggle", _("pause / resume every animation")),
            ("setup load Gaming", _("load a saved setup (this one is permanent)")),
        ]
        tv.get_buffer().set_text("\n".join(f"iridia {c:<46} # {t}" for c, t in examples))
        c.append(tv)
        c.append(label(_("Names are the ones shown in the window (rename a strip with its pencil button). When two "
                       "strips share a name, use Device/Zone, as `zone list` shows."), ("tiny", "faint"), wrap=True))
        p.append(c)
        self._render()

    @staticmethod
    def _guess_desktop() -> str:
        de = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or "hyprland" in de:
            return DESKTOPS[1] if os.path.exists(os.path.expanduser("~/.config/hypr/hyprland.lua")) else DESKTOPS[0]
        for key, name in (("sway", "Sway"), ("i3", "i3"), ("niri", "niri"), ("river", "river"),
                          ("kde", "KDE Plasma"), ("gnome", "GNOME")):
            if key in de:
                return name
        return DESKTOPS[0]

    # ------------------------------------------------------------- state
    def _set_mode(self, m):
        self.mode = m
        self._render()

    def _set_power(self, v):
        self.power = v
        self._render()

    def _chip_toggled(self, name):
        if self._chip_quiet:
            return
        self._chip_quiet = True
        if name == ALL_STRIPS and self._chips[name].get_active():
            for n, b in self._chips.items():
                if n != name:
                    b.set_active(False)
        elif name != ALL_STRIPS and self._chips[name].get_active() and ALL_STRIPS in self._chips:
            self._chips[ALL_STRIPS].set_active(False)
        if not any(b.get_active() for b in self._chips.values()) and ALL_STRIPS in self._chips:
            self._chips[ALL_STRIPS].set_active(True)
        self._chip_quiet = False
        self._render()

    def _target(self) -> str:
        chosen = [n for n, b in self._chips.items() if b.get_active()]
        if not chosen or ALL_STRIPS in chosen:
            return "all"
        by = dict(self._targets)
        return ",".join(by.get(n, n) for n in chosen)

    def _strip_actions(self) -> List[str]:
        if self.power == "normal":
            return ["normal"]
        acts = [self.power] if self.power in ("on", "off") else []
        effect = self._effect_on.get_active() and self.power != "off"
        if effect:
            acts += ["effect", self._effect_keys.get(self._effect_dd.value(), "breathing")]
        if self.power != "off":
            if self._color_on.get_active() and not effect:
                acts += ["color", self.color]
            if self._bright_on.get_active():
                acts += ["bright", str(int(self._bright.get_value()))]
        return acts

    def _args(self) -> Optional[List[str]]:
        if self.mode == "strips":
            acts = self._strip_actions()
            return ["zone", self._target()] + acts if acts else None
        kind = next((k for n, k in OTHER if n == self._other.value()), "lights")
        if kind in ("lights", "freeze", "night", "animations"):
            return [kind, "toggle"]
        name = self._setup_dd.value()
        return ["setup", "load", name] if name else None

    def _render(self):
        strips = self.mode == "strips"
        self._strips_box.set_visible(strips)
        self._other_box.set_visible(not strips)
        kind = next((k for n, k in OTHER if n == self._other.value()), "lights")
        self._setup_row.set_visible(kind == "setup")
        mix = self.power not in ("off", "normal")
        self._effect_row.set_sensitive(mix)
        self._color_row.set_sensitive(mix and not self._effect_on.get_active())
        self._bright_row.set_sensitive(mix)
        args = self._args()
        exe = iridia_path()
        self._cmd_text = " ".join(shlex.quote(a) for a in [exe] + args) if args else ""
        if args:
            self._cmd.set_label(self._cmd_text)
        elif strips:
            self._cmd.set_label(_("Pick at least one thing to change: Turn on or off, a color or a brightness."))
        else:
            self._cmd.set_label(_("Save a setup first (Settings, Setups and backups)."))
        if strips:
            if self.power == "normal":
                note = _("Undoes every keybind change on these strips.")
            elif self.power == "off":
                note = _("Turns the strips off; press the key again to bring them back.")
            else:
                bits = ([_("turns them on (even when switched off)")] if self.power == "on" else []) + \
                       ([_("runs an effect")] if self._effect_on.get_active() else []) + \
                       ([_("shows one color")] if self._color_on.get_active() and not self._effect_on.get_active()
                        else []) + \
                       ([_("sets the brightness")] if self._bright_on.get_active() else [])
                note = _("One press: {actions}. The next press puts everything back.").format(
                    actions=", ".join(bits)) if bits else ""
            self._note.set_label((note + " " if note else "") + _("Pick several strips to change them together."))
        else:
            self._note.set_label({
                "lights": _("Same key turns everything off, then back on."),
                "freeze": _("Same key freezes the current colors, then follows the wallpaper again."),
                "night": _("Switches night mode on or off (this one is saved)."),
                "animations": _("Same key pauses every animated effect, then lets them run again."),
                "setup": _("Loads the setup and keeps it (an automatic backup is made first)."),
            }[kind])
        mods_v = self._mods.value() or NO_MOD
        mods = [] if mods_v == NO_MOD else [m.strip() for m in mods_v.split("+")]
        if args:
            where, line = bind_line(self._desk.value() or DESKTOPS[0], mods, self._key.get_text(), args)
        else:
            where, line = "", ""
        self._line_text = line
        self._where.set_label(where)
        self._line_buf.set_text(line)

    def _pick(self):
        def done(h):
            if h:
                self.color = h
                self._swatch.set_state(hex6=h)
                self._hex.set_label(f"#{h}")
                self._color_on.set_value(True)
                self._render()
        self.app.pick_color(self.color, _("Keybind color"), done)

    def _copy(self, text):
        if text:
            widgets.copy_text(self.p, text)
            self.app.toast(_("Copied"))

    def _try(self):
        args = self._args()
        if not args:
            return
        c = self.app.client
        if args[0] == "zone":
            fn = lambda: c.zone_action(args[1], args[2:])
        elif args[0] == "setup":
            fn = lambda: c.setup("load", name=args[2])
        elif args[0] == "night":
            fn = lambda: c.set_night(toggle=True)
        elif args[0] == "animations":
            fn = lambda: c.animations(action="toggle")
        else:
            fn = lambda: c.raw({"cmd": args[0], "toggle": True})

        def done(r):
            if r.get("ok"):
                self.app.toast(r.get("message") or _("Done"))
                self.app.refresh_soon()
            else:
                self.app.toast(r.get("error") or _("That didn't work"))
        run_bg(fn, done)

    # ------------------------------------------------------------ status
    def update_status(self, st: dict):
        cfgs = st.get("device_configs") or {}
        zones = []
        for dev, cfg in cfgs.items():
            zs = cfg.get("zones") or {"": cfg}
            for zn, zc in zs.items():
                zones.append((dev, zn, (zc or {}).get("display_name") or zn or dev))
        counts = {}
        for _d, _z, n in zones:
            counts[n.lower()] = counts.get(n.lower(), 0) + 1
        targets = [(ALL_STRIPS, "all")]
        for d, z, n in zones:
            unique = counts[n.lower()] == 1 and "," not in n
            targets.append((n if counts[n.lower()] == 1 else f"{n} ({d})", n if unique else _target_for(d, z)))
        sig = tuple(targets)
        if sig != self._target_sig:
            self._target_sig = sig
            self._targets = targets
            chosen = {n for n, b in self._chips.items() if b.get_active()} or {ALL_STRIPS}
            widgets.clear(self._chip_flow)
            self._chips = {}
            for shown, _t in targets:
                b = Gtk.ToggleButton()
                lb = Gtk.Label(label=shown, max_width_chars=22, ellipsize=3)     # 3 = Pango END
                b.set_child(lb)
                b.set_tooltip_text(shown)
                b.add_css_class("filter")
                b.set_active(shown in chosen)
                b.connect("toggled", lambda _b, n=shown: self._chip_toggled(n))
                self._chips[shown] = b
                self._chip_flow.append(b)
            if not any(b.get_active() for b in self._chips.values()):
                self._chips[ALL_STRIPS].set_active(True)
            self._render()
        ov = st.get("overlays") or {}
        names = {f"{d}|{z}": n for d, z, n in zones}
        osig = tuple(sorted((k, repr(v)) for k, v in ov.items()))
        if osig != self._overlay_sig:
            self._overlay_sig = osig
            self._render_active(ov, names)

    def set_setups(self, names: List[str]):
        if names != self._setups:
            self._setups = list(names)
            self._setup_dd.set_items(self._setups, self._setup_dd.value() if self._setup_dd.value() in names
                                     else (names[0] if names else None))
            self._render()

    def _render_active(self, ov: dict, names: dict):
        widgets.clear(self._active)
        if not ov:
            self._active.append(label(_("Nothing: every strip shows its normal colors."), ("small", "dim")))
            return
        for key, o in sorted(ov.items(), key=lambda kv: names.get(kv[0], kv[0]).lower()):
            d, z = split_key(key)
            bits = ([{"on": _("on"), "off": _("off")}.get(o["power"], o["power"])] if o.get("power") else []) + \
                   ([f"#{o['hex']}"] if o.get("hex") else []) + \
                   ([_("{n}% brightness").format(n=o['bright'])] if o.get("bright") is not None else [])
            if "effect" in o:
                from iridia.ui.effects import EFFECT_NAMES
                bits.append(EFFECT_NAMES.get((o["effect"] or {}).get("effect"), _("Static pattern")))
            row = hbox(10)
            if o.get("hex"):
                row.append(Swatch(o["hex"], 22))
            row.append(label(f"{names.get(key, z or d)}: {', '.join(bits) or '?'}", ("body",), ellipsize=True))
            row.append(Gtk.Box(hexpand=True))
            row.append(button(_("Back to normal"), "undo", "text small", lambda key=key: self._normal(None, key)))
            self._active.append(row)
        self._active.append(divider())
        self._active.append(button(_("Everything back to normal"), "restart_alt", "tonal small",
                                   lambda: self._normal("all", None)))

    def _normal(self, target, key):
        if key:
            target = [_target_for(*split_key(key))]
        run_bg(lambda: self.app.client.zone_action(target, ["normal"]),
               lambda r: (self.app.toast(r.get("message") if r.get("ok") else r.get("error", _("Failed"))),
                          self.app.refresh_soon()))
