"""Iridia window (GTK 4, Material 3 Expressive)."""

import json
import os
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_foreign("cairo")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from iridia.i18n import _, ngettext  # noqa: F401
from iridia import assets, diagnostics, i18n, theme  # noqa: E402
from iridia.calibration import DEFAULT_NAME, valid_name  # noqa: E402
from iridia.client import Client  # noqa: E402
from iridia.config import Config  # noqa: E402
from iridia.ui import dialogs, fonts, widgets  # noqa: E402
from iridia.ui.calibration_editor import ProfileEditor  # noqa: E402
from iridia.ui.colorpicker import pick_color as _pick_color  # noqa: E402
from iridia.ui.layout_tab import LayoutTab  # noqa: E402
from iridia.ui.style import Style  # noqa: E402
from iridia.ui.widgets import (Animator, Chip, Dropdown, Group, LoadingIndicator, QuickColors, Snackbar, Spin, Swatch,  # noqa: E402
                               WavyBar, button, card, divider, hbox, icon, label, rgb, section, set_button_text,
                               shape_path, spring, switch_row, vbox)
from iridia.ui.keybinds_tab import KeybindsPage  # noqa: E402
from iridia.ui.zonecard import MODE_LABELS, GlobalClient, ZoneCard, merge_zone_cfgs  # noqa: E402

APP_ID = assets.APP_ID
PREFS_PATH = os.path.expanduser("~/.config/iridia/gui.json")


def _iridia_cli_path() -> str:
    cand = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "iridia")
    return cand if os.path.exists(cand) else "iridia"


def load_prefs() -> dict:
    try:
        with open(PREFS_PATH) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_prefs(p: dict):
    try:
        os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
        tmp = PREFS_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(p, f, indent=1)
        os.replace(tmp, PREFS_PATH)
    except OSError:
        pass


class PreviewSender:
    """Streams a colour to the daemon (throttled, with a heartbeat) while a picker is open."""

    def __init__(self, raw: bool = False):
        self._client = Client()
        self._raw = raw
        self.exact = False
        self._latest = None
        self._ev = threading.Event()
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def send(self, hex_color):
        self._latest = hex_color
        self._ev.set()

    def _run(self):
        while not self._stop:
            self._ev.wait(30)
            if self._stop:
                break
            self._ev.clear()
            if self._latest:
                try:
                    self._client.preview_color(self._latest, raw=self._raw, exact=self.exact)
                except Exception:
                    pass
            time.sleep(0.08)

    def close(self):
        self._stop = True
        self._ev.set()

        def end():
            self._t.join(1.0)
            try:
                self._client.preview_color(None)
            except Exception:
                pass
        threading.Thread(target=end, daemon=True).start()


class HeroShape(Gtk.DrawingArea):
    """The LED colour as a big Expressive shape that morphs with the state (normal, frozen, night)."""

    SHAPES = {"normal": "cookie9", "frozen": "squircle", "night": "flower", "off": "circle"}

    def __init__(self):
        super().__init__()
        widgets.themed(self)
        self.set_content_width(92)
        self.set_content_height(92)
        self.hex = "53dbb0"
        self.state = "normal"
        self._from = self._to = "cookie9"
        self._t = 1.0
        self._anim = Animator(self, self._step)
        self.set_draw_func(self._draw)

    def _step(self, p):
        self._t = spring(p)
        self.queue_draw()

    def set_value(self, hex6, state):
        if hex6 != self.hex:
            self.hex = hex6
            self.queue_draw()
        if state != self.state:
            self.state = state
            self._from, self._to = self._to, self.SHAPES.get(state, "cookie9")
            self._t = 0.0
            self._anim.run(520)

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgb(*rgb("ON_PRIMARY_CONTAINER"))
        shape_path(cr, w / 2, h / 2, min(w, h) / 2 - 1, self._from, self._to, min(1.0, max(0.0, self._t)))
        cr.fill()
        cr.set_source_rgb(*theme.hex_rgb(self.hex))
        shape_path(cr, w / 2, h / 2, min(w, h) / 2 - 6, self._from, self._to, min(1.0, max(0.0, self._t)))
        cr.fill()


class IridiaWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        from iridia import get_version
        self.set_title(_('Iridia {version}').format(version=get_version()))
        self.set_default_size(1040, 860)
        self.add_css_class("iridia")
        self.client = Client()
        self.config = Config()
        self.prefs = load_prefs()
        self._status = {}
        self._running = True
        self._pause_n = 0
        self._poll_count = 0
        self._zone_cards = {}
        self._global_card = None
        self._last_device_keys = None
        self._last_swatch_key = None
        self._down = False
        self._last_activity = 0.0
        self._seed = self._load_seed()
        self._pending_seed, self._pending_count, self._last_reseed = None, 0, 0.0
        self._palette = None
        self._profiles = None

        widgets.STYLE = Style(self._seed, self.prefs.get("font", ""), bool(self.prefs.get("reduce_motion", False)))
        dialogs.PAUSE = self.pause
        self._build()
        for ctl in (Gtk.EventControllerMotion(), Gtk.EventControllerKey()):
            ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            if isinstance(ctl, Gtk.EventControllerMotion):
                ctl.connect("motion", lambda *_a: self.note_activity())
            else:
                ctl.connect("key-pressed", lambda *_a: (self.note_activity(), False)[1])
            self.add_controller(ctl)
        self.connect("close-request", self._on_close)
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ============================================================ helpers for children
    def note_activity(self):
        self._last_activity = time.time()

    def pause(self, d: int):
        self._pause_n = max(0, self._pause_n + d)

    def palette(self):
        if self._palette is None:
            from iridia.palette import Palette
            self._palette = Palette()
        return self._palette

    def profiles(self):
        if self._profiles is None:
            from iridia.calibration import Profiles
            self._profiles = Profiles()
            try:
                self._profiles.ensure_default()
            except OSError:
                pass
        return self._profiles

    def pick_color(self, initial, title, on_done, sent_fn=None, raw=False, target=None):
        """Colour picker with live LED preview; the saved look comes back when it closes."""
        self.pause(1)
        sender = PreviewSender(raw=raw)
        extra = (_("Target"), lambda _h: target) if target else ((_("Sent to strip"), sent_fn) if sent_fn else None)

        exact_colors = [str(c).lower() for c in self._status.get("exact_colors", [])]
        h0 = (initial or "").lstrip("#").lower()
        state = {"picker": None}

        def done(h):
            sender.close()
            self.pause(-1)
            pk = state["picker"]
            if h:
                self.remember_color(h)
                if pk is not None and not raw:
                    want = bool(pk.exact)
                    if want != (h in exact_colors):
                        self._set_exact(h, want)
            on_done(h)

        def on_exact(v):
            sender.exact = v
            sender.send(sender._latest or h0)      # re-send so the strip shows the change now
        state["picker"] = _pick_color(self, initial, self._status.get("custom_colors", []), title, done,
                                      on_change=sender.send, extra=extra, recent=self.recent_colors(),
                                      on_save=self.save_color, exact=None if raw else (h0 in exact_colors),
                                      exact_colors=exact_colors, on_exact=on_exact)
        sender.exact = bool(state["picker"].exact)

    def _set_exact(self, h, on):
        """Mark a colour exact (LEDs show it as picked) or not, right away in the window too."""
        cur = [c for c in self._status.get("exact_colors", []) if c != h] + ([h] if on else [])
        self._status["exact_colors"] = cur
        widgets.set_exact_colors(cur)
        self.bg(lambda: self.client.set_color_exact(h, on),
                lambda r: self.toast(_('#{h} is shown exactly as picked').format(h=h) if on else
                                     _('#{h} follows color correction again').format(h=h)) if r.get("ok") else None)

    # ---- colours you used / saved
    def recent_colors(self):
        return [c for c in self.prefs.get("recent_colors", []) if isinstance(c, str) and len(c) == 6]

    def remember_color(self, h):
        h = h.lstrip("#").lower()
        rec = [h] + [c for c in self.recent_colors() if c != h]
        self.prefs["recent_colors"] = rec[:16]
        save_prefs(self.prefs)
        QuickColors.refresh_all()

    def saved_colors(self):
        return list(self._status.get("custom_colors", []))

    def save_color(self, h):
        """Keep a colour in your saved colors (the same list the Status and Devices tabs show)."""
        h = h.lstrip("#").lower()
        if h in self._status.get("custom_colors", []):
            self.toast(_('#{h} is already in your saved colors').format(h=h))
            return
        self._status.setdefault("custom_colors", []).append(h)
        QuickColors.refresh_all()
        self.bg(lambda: self.client.add_custom_color(h), lambda r: self.toast(_('Saved #{h}').format(h=h)))

    def count_leds(self, device, zone, current, on_done):
        dialogs.CountLedsDialog(self, self.client, device, zone, current, on_done)

    def rename_zone(self, device, zone, current, after=None):
        """One rename for a strip, used by the Devices and Layout tabs (stored in the daemon's config)."""
        def done(name):
            def finished(r):
                if not r.get("ok"):
                    dialogs.message(self, _("Rename"), r.get("error", _("Couldn't rename")), True)
                    return
                if after:
                    after(name)
                self._poll_once()
            self.bg(lambda: self.client.set_zone_name(device, zone, name), finished)
        dialogs.ask_text(self, _("Rename strip"),
                         (_('A name for {zone} on {device}.').format(zone=zone, device=device) if zone else _('A name for {device}.').format(device=device)) + ' ' + _('It shows on the Devices and Layout tabs. Leave it empty to use the original name.'), current or "", done,
                         check=lambda t: None if len(t) <= 40 else _("Keep it under 40 characters."), ok_label=_("Rename"))

    def toast(self, text, action_label=None, action=None):
        self._snack.show(text, action_label, action)

    def bg(self, fn, done=None):
        dialogs.run_bg(fn, done)

    # ============================================================ layout
    def _build(self):
        hb = Gtk.HeaderBar()
        title = hbox(12)
        logo = Gtk.Image.new_from_file(assets.logo_png_path())
        logo.set_pixel_size(40)
        title.append(logo)
        title.append(label(_("Iridia"), ("app-title",)))
        hb.pack_start(title)
        hb.set_title_widget(Gtk.Box())
        self._chip = Chip(_("Connecting…"))
        hb.pack_end(self._chip)
        self._freeze_btn = button(_("Freeze colors"), "ac_unit", "tonal small", self._toggle_freeze)
        self._freeze_btn.set_valign(Gtk.Align.CENTER)
        hb.pack_end(self._freeze_btn)
        self._spinner = LoadingIndicator(30)
        hb.pack_end(self._spinner)
        self._spinner.start()
        self.set_titlebar(hb)
        self._frozen = False

        overlay = Gtk.Overlay()
        root = vbox(10)
        for m in ("start", "end"):
            getattr(root, f"set_margin_{m}")(20)
        root.set_margin_bottom(14)
        root.set_margin_top(4)

        bar = hbox(2)
        bar.add_css_class("tabbar")
        bar.set_halign(Gtk.Align.START)
        self._stack = Gtk.Stack(vexpand=True, hexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE,
                                transition_duration=180)
        self._tabs = {}
        first = None
        for key, text, ico in (("status", _("Status"), "home"), ("devices", _("Devices"), "developer_board"),
                               ("layout", _("Layout"), "polyline"), ("keybinds", _("Keybinds"), "keyboard"),
                               ("settings", _("Settings"), "settings"), ("service", _("Service"), "build")):
            b = Gtk.ToggleButton()
            b.set_child(hbox(8, icon(ico), Gtk.Label(label=text)))
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._tab_toggled, key)
            bar.append(b)
            self._tabs[key] = b
        root.append(bar)

        self._layout_tab = LayoutTab(self)
        pages = {}
        for key in ("status", "devices", "layout", "keybinds", "settings", "service"):
            if key == "layout":
                self._stack.add_named(self._layout_tab, key)
                continue
            sc, body = self._scroll_page()
            pages[key] = body
            self._stack.add_named(sc, key)
        self._status_page, self._devices_page = pages["status"], pages["devices"]
        self._settings_page, self._service_page = pages["settings"], pages["service"]
        self._keybinds = KeybindsPage(self, pages["keybinds"])
        root.append(self._stack)

        bot = hbox(8)
        bot.append(button(_("Refresh"), "refresh", "tonal", self._do_refresh))
        bot.append(button(_("Restart daemon"), "restart_alt", "tonal", self._do_restart))
        bot.append(button(_("Config folder"), "folder_open", "text", lambda: self._xdg_open("~/.config/iridia")))
        bot.append(button(_("Log folder"), "description", "text", lambda: self._xdg_open("~/.local/share/iridia")))
        bot.append(Gtk.Box(hexpand=True))
        bot.append(button(_("Quit"), "power_settings_new", "danger", self.close))
        root.append(bot)

        overlay.set_child(root)
        self._snack = Snackbar()
        overlay.add_overlay(self._snack)
        self.set_child(overlay)

        self._build_status()
        self._build_devices()
        self._build_settings()
        self._build_service()
        self._tabs["status"].set_active(True)

    def _scroll_page(self):
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        body = vbox(8)
        body.set_margin_end(10)
        body.set_margin_bottom(16)
        sc.set_child(body)
        return sc, body

    def _tab_toggled(self, b, key):
        if not b.get_active():
            return
        self._stack.set_transition_duration(180 if widgets.motion() else 0)
        self._stack.set_visible_child_name(key)
        self._layout_tab.set_visible_tab(key == "layout")

    def _xdg_open(self, path):
        path = os.path.expanduser(path)
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
            return
        except GLib.Error:
            pass
        try:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.toast(_("Couldn't open a file manager. The folder is {path}").format(path=path))

    # ============================================================ status tab
    def _build_status(self):
        p = self._status_page
        hero = hbox(20)
        hero.add_css_class("hero")
        hero.set_margin_top(10)
        self._hero_shape = HeroShape()
        hero.append(self._hero_shape)
        hv = vbox(4, hexpand=True)
        self._hero_title = label(_("Waiting for the daemon…"), ("title",))
        self._hero_sub = label("", ("small", "dim"), ellipsize=True)
        hv.append(self._hero_title)
        hv.append(self._hero_sub)
        brow = hbox(10)
        brow.append(icon("light_mode", classes=("dim",)))
        self._hero_wave = WavyBar(260, on_dark=True)
        brow.append(self._hero_wave)
        self._hero_bright = label("", ("subheading",))
        brow.append(self._hero_bright)
        hv.append(brow)
        hero.append(hv)
        p.append(hero)

        p.append(section(_("Now playing")))
        info = card()
        grid = Gtk.Grid(column_spacing=24, row_spacing=8)
        self._rows = {}
        for i, (key, text, ico) in enumerate([("wallpaper", _("Wallpaper"), "wallpaper"), ("dominant", _("Main color"), "palette"),
                                              ("openrgb", "OpenRGB", "cable"), ("ddc", _("Monitor sync (DDC)"), "monitor"),
                                              ("mode", _("Color correction"), "tune"), ("freeze", _("Wallpaper colors"), "ac_unit"),
                                              ("night", _("Night mode"), "bedtime"), ("lights", _("Lights"), "lightbulb"),
                                              ("backend", _("Extraction backend"), "auto_awesome")]):
            grid.attach(icon(ico, classes=("dim",)), 0, i, 1, 1)
            grid.attach(label(text, ("body", "dim")), 1, i, 1, 1)
            v = label("-", ("body",), selectable=True, ellipsize=True)
            v.set_hexpand(True)
            grid.attach(v, 2, i, 1, 1)
            self._rows[key] = v
        info.append(grid)
        p.append(info)

        p.append(section(_("Color for this wallpaper"),
                         _("Click a color to use it on all your LEDs. Your picks, for all zones or single zones, are "
                         "remembered for this image and come back when you return to it. A wallpaper you haven't "
                         "picked for follows its own colors.")))
        c = card()
        self._sw_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=10, column_spacing=6,
                                    halign=Gtk.Align.START)
        c.append(self._sw_flow)
        self._corr_exp = Gtk.Expander(label=_("Color correction preview"))
        self._corr_exp.add_css_class("accent")
        self._corr_box = vbox(6)
        self._corr_exp.set_child(self._corr_box)
        c.append(self._corr_exp)
        c.append(label(_("Your saved colors"), ("small", "dim")))
        self._custom_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12,
                                        column_spacing=6, halign=Gtk.Align.START)
        c.append(self._custom_flow)
        self._choice_lbl = label("", ("body",))
        c.append(self._choice_lbl)
        btns = hbox(8)
        btns.append(button(_("Custom color…"), "colorize", "filled", self._pick_custom_color))
        btns.append(button(_("Reset saved colors for this wallpaper"), "history", "tonal",
                           lambda: self._set_color_choice(clear=True)))
        c.append(btns)
        p.append(c)

    @staticmethod
    def _all_zone_cfgs(devices):
        out = []
        for dc in devices.values():
            zones = dc.get("zones", {})
            out.extend(zones.values() if zones else [dc])
        return out

    @staticmethod
    def _everything_choice(devices):
        entries = {tuple(z.get("pattern_colors", [0])) for z in IridiaWindow._all_zone_cfgs(devices)}
        if len(entries) == 1:
            e = next(iter(entries))
            if len(e) == 1:
                return {"index": e[0]} if isinstance(e[0], int) else {"hex": str(e[0]).lstrip("#").lower()}
        return None

    def _render_swatches(self, colors, choice, custom):
        for flow in (self._sw_flow, self._custom_flow):
            widgets.clear(flow)
        self._sw_flow.set_min_children_per_line(max(1, min(8, len(colors))))
        self._custom_flow.set_min_children_per_line(max(1, min(10, len(custom) + 1)))
        for i, c in enumerate(colors[:8]):
            self._sw_flow.append(Swatch(c, 52, bool(choice) and choice.get("index") == i,
                                        on_click=lambda i=i: self._set_color_choice(index=i),
                                        tooltip=_('Wallpaper color {n}  #{hex}').format(n=i + 1, hex=c)))
        for c in custom:
            self._custom_flow.append(Swatch(c, 46, bool(choice) and choice.get("hex") == c,
                                            on_click=lambda c=c: self._set_color_choice(hex_color=c),
                                            on_right=lambda c=c: self._delete_custom(c),
                                            tooltip=_('#{c}  (right-click to delete)').format(c=c)))
        if choice and "hex" in choice and choice["hex"] not in custom:
            self._custom_flow.append(Swatch(choice["hex"], 46, True))
        if not custom and not (choice and "hex" in choice):
            self._custom_flow.append(label(_("None yet. Pick one with “Custom color…” below."),
                                           ("small", "faint")))
        if not choice:
            t = _("Your zones use different colors (see the Devices tab)")
        elif "hex" in choice:
            t = _("All zones use #{hex}").format(hex=choice['hex'])
        else:
            t = _("All zones use wallpaper color {n}").format(n=choice.get('index', 0) + 1)
        self._choice_lbl.set_label(t)

    def _render_correction(self, corr):
        key = repr(corr)
        if key == getattr(self, "_corr_key", None):
            return
        self._corr_key = key
        c = self._corr_box.get_first_child()
        while c:
            n = c.get_next_sibling()
            self._corr_box.remove(c)
            c = n
        mode = corr.get("mode", "full")
        note = {"palette": _("Palette is on. Top: the wallpaper color. Bottom: the closest palette color your LEDs show."),
                "calibrated": _("Calibrated ({profile}). Top: the wallpaper color. Bottom: the color sent to the "
                                "strip so it looks right.").format(profile=corr.get('profile', '')),
                "mixed": _("Zones use different corrections, so this shows the colors as they are.")}.get(
            mode, _("Color correction is off, so the strip gets the wallpaper colors as they are."))
        self._corr_box.append(label(note, ("small", "dim"), wrap=True))
        row = hbox(8)
        for m in corr.get("items", []):
            col = vbox(2)
            col.append(Swatch(m["from"], 30, on_click=lambda h=m["from"]: self._set_color_choice(hex_color=h)))
            col.append(Swatch(m["to"], 44))
            col.append(label(m.get("name") or f"#{m['to']}", ("tiny", "faint"), xalign=0.5))
            row.append(col)
        self._corr_box.append(row)

    def _set_color_choice(self, index=None, hex_color=None, clear=False, save=False):
        def work():
            if clear:
                r = self.client.clear_wallpaper_color()
            else:
                r = self.client.set_wallpaper_color(index=index, hex_color=hex_color)
                if r.get("ok") and hex_color and save:
                    self.client.add_custom_color(hex_color)
            if r.get("ok"):
                r["_status"] = self.client.status()
            return r

        def done(r):
            if not r.get("ok"):
                dialogs.message(self, _("Color"), r.get("error", "failed"), error=True)
                return
            self._status = r["_status"]
            self._update_ui()
            if clear:
                self.toast(_("Saved colors for this wallpaper were reset."))
        self.bg(work, done)

    def _pick_custom_color(self):
        ch = self._everything_choice(self._status.get("device_configs", {}))
        cols = self._status.get("extracted_colors") or ["ff8800"]
        cur = (ch.get("hex") if ch else None) or cols[0]
        self.pick_color(cur, _("Color for this wallpaper"),
                        lambda h: h and self._set_color_choice(hex_color=h, save=True))

    def _delete_custom(self, h):
        self.bg(lambda: (self.client.remove_custom_color(h), self.client.status())[1],
                lambda st: (setattr(self, "_status", st), self._update_ui(),
                            self.toast(_('Deleted #{h} from your saved colors.').format(h=h))))

    # ============================================================ devices tab
    def _build_devices(self):
        self._dev_box = self._devices_page

    def _clear(self, box):
        c = box.get_first_child()
        while c:
            n = c.get_next_sibling()
            box.remove(c)
            c = n

    def _show_daemon_down(self):
        if self._down:
            return
        self._down = True
        self._clear(self._dev_box)
        self._zone_cards, self._global_card, self._last_device_keys = {}, None, None
        b = vbox(10)
        b.set_margin_top(60)
        b.set_halign(Gtk.Align.CENTER)
        li = LoadingIndicator(64)
        li.start()
        b.append(li)
        b.append(label(_("The daemon isn't running."), ("title",), xalign=0.5))
        b.append(label(_("Your devices show up here once it runs. Start it here or from the Service tab."),
                       ("small", "dim"), xalign=0.5))
        st = button(_("Start daemon"), "play_arrow", "filled", self._daemon_start)
        st.set_halign(Gtk.Align.CENTER)
        b.append(st)
        self._dev_box.append(b)

    def _device_keys(self, devices):
        keys = []
        for d, dc in devices.items():
            zones = dc.get("zones", {})
            keys += [(d, z) for z in zones] if zones else [(d, "")]
        return tuple(keys)

    def _rebuild_devices(self, devices, extracted, custom):
        expanded = {k: c.expanded for k, c in self._zone_cards.items()}
        if self._global_card is not None:
            expanded["*"] = self._global_card.expanded
        self._clear(self._dev_box)
        self._zone_cards, self._global_card = {}, None
        self._hw_cards = {}
        if not devices:
            b = vbox(6)
            b.set_margin_top(50)
            b.append(label(_("No devices configured."), ("title",), xalign=0.5))
            b.append(label(_("Devices appear here once OpenRGB reports them. Start OpenRGB's SDK server (SDK Server "
                           "tab, Start Server) and make sure it lists your devices."), ("small", "dim"), xalign=0.5,
                           wrap=True))
            self._dev_box.append(b)
            return
        cfgs = self._all_zone_cfgs(devices)
        merged, mixed = merge_zone_cfgs(cfgs)
        self._dev_box.append(section(_("All devices"), ngettext('Changes here apply to {n} zone.', 'Changes here apply to all {n} zones at once.', len(cfgs)).format(n=len(cfgs)), 10))
        self._global_card = ZoneCard(self, "*", "*", merged, extracted, custom, GlobalClient(self.client),
                                     global_mode=True, expanded=expanded.get("*", True), title=_("Everything"))
        self._global_card.sync_from_status(merged, extracted, custom, mixed)
        self._dev_box.append(self._global_card)
        for d, dc in devices.items():
            self._dev_box.append(section(d, None if dc.get("enabled", True) else _("Disabled")))
            if self._status.get("hardware_effects"):
                from iridia.ui.effects import HardwareEffectCard
                hw = HardwareEffectCard(self, d, lambda eff, d=d: self.bg(
                    lambda: self.client.set_device_hardware_effect(d, eff),
                    lambda r: (self.toast(r.get("error")) if not r.get("ok") else None, self.refresh_soon())))
                self._hw_cards[d] = hw
                self._dev_box.append(hw)
            zones = dc.get("zones", {})
            for z, zc in (zones.items() if zones else [("", dc)]):
                key = f"{d}|{z}"
                cardw = ZoneCard(self, d, z or _("Whole device"), zc, extracted, custom, self.client,
                                 expanded=expanded.get(key, False))
                cardw.zone_name = z
                self._dev_box.append(cardw)
                self._zone_cards[key] = cardw

    def _apply_hw(self, hw):
        """Hints from what OpenRGB reports (unsized zones, single-colour devices) on the zone cards."""
        for d in hw:
            single = bool(d.get("single_color"))
            zones = d.get("zones") or []
            sizes = {z.get("name", ""): z.get("led_count") for z in zones} if zones else {"": d.get("led_count")}
            for z, n in sizes.items():
                c = self._zone_cards.get(f"{d.get('name')}|{z}")
                if c is not None:
                    c.set_hw(n, single)

    def _sync_devices(self, devices, extracted, custom):
        if self._global_card is not None:
            merged, mixed = merge_zone_cfgs(self._all_zone_cfgs(devices))
            self._global_card.sync_from_status(merged, extracted, custom, mixed)
        for d, dc in devices.items():
            zones = dc.get("zones", {})
            for z, zc in (zones.items() if zones else [("", dc)]):
                c = self._zone_cards.get(f"{d}|{z}")
                if c is not None:
                    c.sync_from_status(zc, extracted, custom)

    def _sync_animation_settings(self, st):
        a = st.get("animations")
        if not a or not hasattr(self, "_anim_sw"):
            return
        self._anim_sw.set_value(bool(a.get("enabled", True)))
        self._fps.set_active(str(a.get("fps", 30)))
        self._anim_night_pause.set_value(bool(a.get("night_pause", False)))
        self._anim_night_slow.set_value(bool(a.get("night_slow", False)))
        self._hw_sw.set_value(bool(st.get("hardware_effects", False)))

    def _build_animation_settings(self, p):
        p.append(section(_("Animations"), _("Animated effects are picked per zone on the Devices tab.")))
        c = card()
        a = self.config.get("animations", {}) or {}
        row, self._anim_sw = switch_row(_("Run animations"), bool(a.get("enabled", True)),
                                        lambda v: self.bg(lambda: self.client.animations(enabled=v)))
        c.append(row)
        c.append(label(_("Off: animated zones show their first color, still."), ("small", "faint")))
        r = hbox(10)
        r.append(label(_("Frame rate"), ("body", "dim")))
        self._fps = Group([("15", "15"), ("30", "30"), ("60", "60")], str(a.get("fps", 30)),
                          lambda v: self.bg(lambda: self.client.animations(fps=int(v))))
        r.append(self._fps)
        r.append(label(_("frames per second"), ("body", "dim")))
        c.append(r)
        c.append(label(_("30 looks smooth on most strips. A device that can't keep up gets a lower rate by itself."),
                       ("small", "faint"), wrap=True))
        row, self._anim_night_pause = switch_row(_("Pause animations during night mode"),
                                                 bool(a.get("night_pause", False)),
                                                 lambda v: self.bg(lambda: self.client.animations(night_pause=v)))
        c.append(row)
        row, self._anim_night_slow = switch_row(_("Slow animations during night mode"), bool(a.get("night_slow", False)),
                                                lambda v: self.bg(lambda: self.client.animations(night_slow=v)))
        c.append(row)
        c.append(divider())
        row, self._hw_sw = switch_row(_("Controller effects"), bool(self.config.get("hardware_effects.enabled", False)),
                                      lambda v: self.bg(lambda: self.client.set_hardware_effects(v),
                                                        lambda r: self.refresh_soon()))
        c.append(row)
        c.append(label(_("Lets a device run one of its own effects (the ones OpenRGB lists for it, like Breathing or "
                         "Spectrum Cycle). They run on the controller, so they're always smooth, but they don't follow "
                         "the wallpaper, your colors or the layout. Pick them per device on the Devices tab."),
                       ("small", "faint"), wrap=True))
        p.append(c)

    # ============================================================ settings tab
    def _build_settings(self):
        p = self._settings_page
        # appearance
        p.append(section(_("Appearance"), None, 10))
        c = card()
        r = hbox(10)
        r.append(label(_("Font"), ("body", "dim")))
        fams = [_("Google Sans Flex (built in)"), _("System font")]
        try:
            fams += sorted({f.get_name() for f in self.get_pango_context().list_families()} - {fonts.TEXT_FAMILY,
                                                                                               fonts.ICON_FAMILY})
        except Exception:
            pass
        cur_font = self.prefs.get("font", "")
        cur_label = _("System font") if cur_font == "system" else (cur_font or _("Google Sans Flex (built in)"))
        r.append(Dropdown(fams, cur_label, self._set_font))
        c.append(r)
        r = hbox(10)
        # Never translated, so this row can be found again from any language.
        r.append(icon("language", classes=("dim",)))
        r.append(label("Language", ("body", "dim")))
        self._langs = list(i18n.available().items())
        names = dict(self._langs)
        cur_lang = self.prefs.get("language", "") or i18n.DEFAULT
        r.append(Dropdown([n for _c, n in self._langs], names.get(cur_lang, names.get(i18n.DEFAULT, "")),
                          self._set_language))
        c.append(r)
        row, _u = switch_row(_("Reduce motion"), bool(self.prefs.get("reduce_motion", False)), self._set_reduce_motion)
        c.append(row)
        c.append(label(_("Turns off shape morphs, sliding panels and the color cross-fade."), ("small", "faint")))
        p.append(c)

        # night + sleep
        p.append(section(_("Night mode and sleep"), _("Dim the LEDs at night, and turn them off while the PC sleeps.")))
        c = card()
        night = self.config.get("night", {}) or {}
        row, self._night_sw = switch_row(_("Night mode"), bool(night.get("enabled", False)), lambda v: self._save_night())
        c.append(row)
        nr = hbox(10)
        self._night_start = Gtk.Entry(text=night.get("start", "23:00"), width_chars=6, max_width_chars=6,
                                      hexpand=False)
        self._night_end = Gtk.Entry(text=night.get("end", "07:00"), width_chars=6, max_width_chars=6, hexpand=False)
        for lbl_text, e in ((_("From"), self._night_start), (_("to"), self._night_end)):
            nr.append(label(lbl_text, ("body", "dim")))
            nr.append(e)
            e.connect("activate", lambda *_a: self._save_night())
            fc = Gtk.EventControllerFocus()
            fc.connect("leave", lambda *_a: self._save_night())
            e.add_controller(fc)
        nr.append(label(_("brightness at most"), ("body", "dim")))
        self._night_cap = Spin(0, 100, int(night.get("cap", 20)), lambda v: self._save_night())
        nr.append(self._night_cap)
        nr.append(label("%", ("body", "dim")))
        c.append(nr)
        self._night_msg = label(_("Times are 24 hour, like 23:00. The window can cross midnight."), ("small", "faint"))
        c.append(self._night_msg)
        row, self._sleep_sw = switch_row(_("Turn the LEDs off while the PC sleeps"),
                                         bool(self.config.get("sleep.lights_off", True)),
                                         lambda v: self.bg(lambda: self.client.set_sleep(v)))
        c.append(row)
        p.append(c)
        self._build_animation_settings(p)

        # setups
        p.append(section(_("Setups and backups"),
                         _("Save everything (devices, zones, layout, night mode, calibration, your colors for each "
                         "wallpaper and your saved colors) under a name, and load it again later.")))
        c = card()
        r1 = hbox(10)
        r1.append(label(_("Setup"), ("body", "dim")))
        self._setup_dd = Dropdown([], None, placeholder=_("No setups yet"))
        r1.append(self._setup_dd)
        c.append(r1)
        r2 = hbox(6)
        for text, ico, cb, style in ((_("Save current as…"), "save", self._setup_save, "filled"),
                                     (_("Load"), "upload", self._setup_load, "tonal"),
                                     (_("Rename"), "edit", self._setup_rename, "tonal"),
                                     (_("Export"), "download", self._setup_export, "tonal"),
                                     (_("Import"), "upload", self._setup_import, "tonal"),
                                     (_("Delete"), "delete", self._setup_delete, "danger")):
            r2.append(button(text, ico, f"{style} small", cb))
        c.append(r2)
        r3 = hbox(10)
        r3.append(label(_("Automatic backups"), ("body", "dim")))
        self._backup_dd = Dropdown([], None, placeholder=_("No backups yet"))
        r3.append(self._backup_dd)
        r3.append(button(_("Restore"), "settings_backup_restore", "tonal small", self._setup_restore_backup))
        c.append(r3)
        c.append(label(_("Loading a setup first saves what you have now as an automatic backup, so you can always go "
                       "back."), ("small", "faint"), wrap=True))
        p.append(c)
        GLib.timeout_add(1200, lambda: (self._setup_refresh(), False)[1])

        # calibration
        p.append(section(_("Color calibration"), _("Profiles that correct colors for your kind of LED strip. Pick one per "
                                              "zone with Color correction: Calibrated on the Devices tab.")))
        c = card()
        r = hbox(10)
        r.append(label(_("Profile"), ("body", "dim")))
        self._cal_dd = Dropdown(self.profiles().list(), DEFAULT_NAME)
        r.append(self._cal_dd)
        c.append(r)
        r = hbox(6)
        r.append(button(_("Edit"), "edit", "filled small", self._cal_edit))
        r.append(button(_("Add"), "add", "tonal small", self._cal_add))
        r.append(button(_("Import"), "upload", "tonal small", self._cal_import))
        r.append(button(_("Export"), "download", "tonal small", self._cal_export))
        r.append(button(_("Delete"), "delete", "danger small", self._cal_delete))
        c.append(r)
        p.append(c)

        # extraction
        p.append(section(_("Color extraction"), _("How Iridia picks colors from your wallpaper.")))
        c = card()
        cur = self.config.get("color.backend", "auto")
        cur = "auto" if cur == "caelestia" else cur
        group = None
        for val, desc in (("auto", _("Automatic (recommended): Caelestia's own colors if Caelestia set the wallpaper, "
                                     "otherwise Material, otherwise Pillow")),
                          ("material", _("Material: prominent colors from the image (needs material-color-utilities)")),
                          ("pillow", _("Pillow: median-cut dominant colors, no extra dependencies"))):
            cb = Gtk.CheckButton(label=desc, active=cur == val)
            if group is None:
                group = cb
            else:
                cb.set_group(group)
            cb.connect("toggled", lambda b, v=val: b.get_active() and self._on_backend(v))
            c.append(cb)
        r = hbox(8)
        r.append(button(_("Reset wallpaper detection cache"), "refresh", "tonal small", self._reset_detection))
        r.append(button(_("Forget all saved wallpaper colors"), "delete", "tonal small", self._forget_all_picks))
        c.append(r)
        c.append(label(_("Once a way of finding your wallpaper works, Iridia remembers it instead of trying every "
                       "method. Reset this after changing wallpaper tool or shell."), ("small", "faint"), wrap=True))
        self._extract_live = label("", ("small", "accent"), wrap=True)
        c.append(self._extract_live)
        p.append(c)

        # logging
        p.append(section(_("Logging")))
        c = card()
        row, _u = switch_row(_("Write a log file"), bool(self.config.get("logging.enabled", False)), self._toggle_log)
        c.append(row)
        c.append(label(os.path.expanduser(self.config.get("logging.file_path", "~/.local/share/iridia/iridia.log")),
                       ("small", "dim"), selectable=True))
        p.append(c)
        p.append(section(_("Recent log"), _("The daemon's latest messages. Works even with the log file switched off.")))
        c = card()
        r = hbox(8)
        r.append(label(_("Lines"), ("body", "dim")))
        self._log_lines = Dropdown(["10", "20", "40", "67"], "20")
        r.append(self._log_lines)
        r.append(button(_("Show"), "description", "filled small", self._show_log))
        r.append(button(_("Copy"), "content_copy", "tonal small",
                        lambda: (widgets.copy_text(self, self._log_buf.get_text(self._log_buf.get_start_iter(),
                                                                                self._log_buf.get_end_iter(), False)),
                                 self.toast(_("Log copied")))))
        c.append(r)
        sc = Gtk.ScrolledWindow(min_content_height=240)
        tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.add_css_class("log")
        self._log_buf = tv.get_buffer()
        self._log_buf.set_text(_("Press Show to load the latest lines."))
        sc.set_child(tv)
        c.append(sc)
        p.append(c)

    # ---- settings actions
    def _save_night(self):
        req = {"enabled": self._night_sw.get_active(), "start": self._night_start.get_text().strip(),
               "end": self._night_end.get_text().strip(), "cap": int(self._night_cap.get_value())}
        self.bg(lambda: self.client.set_night(**req),
                lambda r: self._night_msg.set_label(_("Saved.") if r.get("ok") else r.get("error", _("Couldn't save"))))

    def _setup_refresh(self):
        def done(r):
            if not r.get("ok"):
                return
            names = [s["name"] for s in r.get("setups", [])]
            self._setup_dd.set_items(names, self._setup_dd.value() if self._setup_dd.value() in names else
                                     (names[0] if names else None))
            self._keybinds.set_setups(names)
            self._backups = r.get("backups", [])
            labels = [f"{b['saved']}  ({b['reason']})" if b.get("reason") else b["saved"] for b in self._backups]
            self._backup_dd.set_items(labels, labels[0] if labels else None)
        self.bg(lambda: self.client.setup("list"), done)

    def _setup_save(self):
        def done(name):
            self.bg(lambda: self.client.setup("save", name=name),
                    lambda r: (self.toast(_('Saved “{name}”.').format(name=name)) if r.get("ok") else
                               dialogs.message(self, _("Setup"), r.get("error", _("Couldn't save")), True),
                               self._setup_refresh()))
        dialogs.ask_text(self, _("Save setup"), _("Name for this setup. Saving under an existing name replaces it."),
                         self._setup_dd.value() or "", done,
                         lambda t: None if valid_name(t) else
                         _("Use letters, numbers, spaces, dashes, underscores and brackets (up to 40 characters)."))

    def _after_setup_loaded(self, r, what):
        if not r.get("ok"):
            dialogs.message(self, _("Setup"), r.get("error", _("Couldn't load")), True)
            return
        self.config.reload()
        self._layout_tab.reload()
        self._setup_refresh()
        self._do_refresh()
        self.toast(_('Loaded {what}. The previous state is in Automatic backups.').format(what=what))

    def _setup_load(self):
        name = self._setup_dd.value()
        if not name:
            return
        dialogs.confirm(self, _("Load setup"), _('Load “{name}”? Your current settings are backed up first.').format(name=name),
                        lambda: self.bg(lambda: self.client.setup("load", name=name),
                                        lambda r: self._after_setup_loaded(r, f"“{name}”")), yes=_("Load"))

    def _setup_restore_backup(self):
        i = self._backup_dd.get_selected()
        bl = getattr(self, "_backups", [])
        if not 0 <= i < len(bl):
            return
        b = bl[i]
        dialogs.confirm(self, _("Restore backup"), _('Restore the backup from {date}? Your current settings are backed up first.').format(date=b['saved']),
                        lambda: self.bg(lambda: self.client.setup("restore_backup", id=b["id"]),
                                        lambda r: self._after_setup_loaded(r, _("the backup from {date}").format(date=b['saved']))),
                        yes=_("Restore"))

    def _setup_rename(self):
        old = self._setup_dd.value()
        if not old:
            return

        def done(new):
            if new == old:
                return
            self.bg(lambda: self.client.setup("rename", name=old, new=new),
                    lambda r: (self.toast(r.get("error") or _("Renamed to “{name}”.").format(name=new)), self._setup_refresh()))
        dialogs.ask_text(self, _("Rename setup"), _('New name for “{old}”.').format(old=old), old, done,
                         lambda t: None if valid_name(t) else _("Use letters, numbers, spaces, dashes and brackets."))

    def _setup_delete(self):
        name = self._setup_dd.value()
        if name:
            dialogs.confirm(self, _("Delete setup"), _('Delete the setup “{name}”?').format(name=name),
                            lambda: self.bg(lambda: self.client.setup("delete", name=name),
                                            lambda r: (self.toast(r.get("error") or _("Deleted “{name}”.").format(name=name)),
                                                       self._setup_refresh())), yes=_("Delete"), danger=True)

    def _setup_export(self):
        name = self._setup_dd.value()
        if not name:
            self.toast(_("Save a setup first, then export it."))
            return
        dialogs.save_file(self, _("Export setup"), f"iridia-{name}.json",
                          lambda path: self.bg(lambda: self.client.setup("export", name=name, dest=path),
                                               lambda r: self.toast(r.get("error") or _("Saved {path}").format(path=path))))

    def _setup_import(self):
        dialogs.open_file(self, _("Import setup"), lambda path: self.bg(
            lambda: self.client.setup("import", src=path),
            lambda r: (self.toast(_('Imported as “{name}”. Select it and click Load.').format(name=r.get('name'))
                                  if r.get("ok") else r.get("error", _("Couldn't import"))), self._setup_refresh())))

    # calibration
    def _cal_host(self):
        win = self

        class Host:
            def pick(self, initial, title, target, done):
                win.pick_color(initial, title, done, raw=True, target=target)

            def sender(self, raw):
                return PreviewSender(raw=raw)

            def changed(self):
                win.bg(win.client.reload_calibration)

            def pause(self, d):
                win.pause(d)
        return Host()

    def _cal_refresh(self, select=None):
        self._cal_dd.set_items(self.profiles().list(), select)

    def _cal_edit(self):
        ProfileEditor(self, self.profiles(), self._cal_dd.value() or DEFAULT_NAME, self._cal_host())

    def _cal_add(self):
        base = self._cal_dd.value() or DEFAULT_NAME

        def check(t):
            if not valid_name(t):
                return _("Use letters, numbers, spaces, dashes, underscores and brackets (up to 40 characters).")
            return _("A profile called “{name}” already exists.").format(name=t) if t in self.profiles().list() else None

        def done(name):
            err = self.profiles().add(name, base)
            if err:
                dialogs.message(self, _("Calibration"), err, True)
                return
            self._cal_refresh(name)
            self.bg(self.client.reload_calibration)
            self._cal_edit()
        dialogs.ask_text(self, _("Add a profile"), _('A new profile that starts as a copy of {base}. Give it a name, for example the strip it is for.').format(base=base), "", done, check)

    def _cal_import(self):
        def done(path):
            name, err = self.profiles().import_from(path)
            if err:
                dialogs.message(self, _("Calibration"), err, True)
                return
            self._cal_refresh(name)
            self.bg(self.client.reload_calibration)
            self.toast(_('Imported as “{name}”.').format(name=name))
        dialogs.open_file(self, _("Import a calibration profile"), done)

    def _cal_export(self):
        name = self._cal_dd.value() or DEFAULT_NAME
        dialogs.save_file(self, _("Export profile"), f"{name}.json",
                          lambda path: self.toast(self.profiles().export_to(name, path) or _("Saved {path}").format(path=path)))

    def _cal_delete(self):
        name = self._cal_dd.value()
        if not name or name == DEFAULT_NAME:
            self.toast(_("WS2812B can't be deleted. Open Edit and use Reset to defaults."))
            return

        def yes():
            err = self.profiles().delete(name)
            if err:
                dialogs.message(self, _("Calibration"), err, True)
                return
            self._cal_refresh(DEFAULT_NAME)
            self.bg(self.client.reload_calibration)
            self.toast(_('Deleted “{name}”.').format(name=name))
        dialogs.confirm(self, _("Delete profile"), _('Delete “{name}”? Zones using it fall back to WS2812B.').format(name=name),
                        yes, yes=_("Delete"), danger=True)

    def _on_backend(self, v):
        self.config.set("color.backend", v)
        self.bg(self.client.refresh)

    def _reset_detection(self):
        self.bg(self.client.reset_detection, lambda r: self.toast(_("Wallpaper detection will start over.")))

    def _forget_all_picks(self):
        dialogs.confirm(self, _("Forget saved colors"), _("Forget the colors you picked for every wallpaper? Zones will "
                                                     "follow each wallpaper's own colors again."),
                        lambda: self.bg(lambda: (self.client.forget_all_wallpaper_colors(),
                                                 self.client.clear_wallpaper_color()),
                                        lambda r: self.toast(_("Saved wallpaper colors forgotten."))),
                        yes=_("Forget"), danger=True)

    def _set_font(self, choice):
        font = "" if choice == _("Google Sans Flex (built in)") else ("system" if choice == _("System font") else choice)
        self.prefs["font"] = font
        save_prefs(self.prefs)
        widgets.STYLE.set_font(font)

    def _set_language(self, name):
        code = next((c for c, n in self._langs if n == name), i18n.DEFAULT)
        if code == (self.prefs.get("language", "") or i18n.DEFAULT):
            return
        self.prefs["language"] = code
        save_prefs(self.prefs)
        self.toast(_("The language changes when the window restarts."), _("Restart"), self._restart_window)

    def _restart_window(self):
        global RESTART
        RESTART = True
        app = self.get_application()
        self.close()
        if app is not None:
            app.quit()

    def _set_reduce_motion(self, on):
        self.prefs["reduce_motion"] = on
        save_prefs(self.prefs)
        widgets.STYLE.set_reduce_motion(on)
        if on:
            self._spinner.stop()

    def _toggle_log(self, on):
        self.config.set("logging.enabled", on)
        self.bg(self.client.reload_config)

    def _show_log(self):
        n = int(self._log_lines.value() or 20)

        def work():
            r = self.client.get_log(n)
            return "\n".join(r.get("lines", [])) if r.get("ok") else _("Couldn't read the log: {error}").format(error=r.get('error'))
        self.bg(work, lambda text: self._log_buf.set_text(text if isinstance(text, str) else
                                                           _("Daemon not reachable: {error}").format(error=text.get('error'))))

    # ============================================================ service tab
    def _build_service(self):
        p = self._service_page
        p.append(section(_("Background daemon"), _("The daemon is the part of Iridia that keeps your lights in sync. It "
                                              "runs in the background and keeps working when this window is closed. "
                                              "This window only changes its settings."), 10))
        c = card()
        self._svc_status = label(_("Checking…"), ("heading",))
        c.append(self._svc_status)
        r = hbox(8)
        r.append(button(_("Start daemon"), "play_arrow", "filled", self._daemon_start))
        r.append(button(_("Kill daemon"), "stop", "danger", self._daemon_kill))
        c.append(r)
        c.append(label(_("Killing the daemon stops it completely. Your lights stay on their last colors until you start "
                       "it again."), ("small", "faint"), wrap=True))
        p.append(c)

        p.append(section(_("Start the daemon when I log in"), _("Pick one method. If you enable more than one, nothing "
                                                           "breaks, since only one daemon ever runs.")))
        c = card()
        c.append(label(_("systemd service"), ("subheading",)))
        self._unit_status = label(_("Checking…"), ("small", "dim"), wrap=True)
        c.append(self._unit_status)
        r = hbox(8)
        r.append(button(_("Enable at login"), "check", "tonal", self._svc_install))
        r.append(button(_("Disable"), "close", "tonal", self._svc_disable))
        r.append(button(_("Remove completely"), "delete", "text", self._svc_remove))
        c.append(r)
        c.append(divider())
        c.append(label(_("Other ways"), ("subheading",)))
        c.append(label(_("Add one of these to your compositor or desktop's own startup config instead of (or as well as) "
                       "systemd."), ("small", "dim"), wrap=True))
        from iridia import autostart
        self._as_snips = [x for x in autostart.snippets() if x["id"] != "systemd"]
        r = hbox(10)
        r.append(label(_("Environment"), ("body", "dim")))
        self._as_dd = Dropdown([x["title"] for x in self._as_snips], self._as_snips[0]["title"],
                               lambda v: self._show_autostart())
        r.append(self._as_dd)
        c.append(r)
        self._as_file = label("", ("small", "dim"), wrap=True, selectable=True)
        c.append(self._as_file)
        tv = Gtk.TextView(editable=False, monospace=True)
        tv.add_css_class("log")
        self._as_buf = tv.get_buffer()
        c.append(tv)
        r = hbox(8)
        r.append(button(_("Copy"), "content_copy", "filled small",
                        lambda: (widgets.copy_text(self, self._as_text), self.toast(_("Copied")))))
        self._as_xdg = button(_("Install XDG autostart"), "add", "tonal small", self._toggle_xdg)
        r.append(self._as_xdg)
        c.append(r)
        p.append(c)
        self._show_autostart()

        p.append(section(_("OpenRGB connection"), _("OpenRGB is a separate program that talks to your LEDs. Iridia needs it "
                                               "running.")))
        c = card()
        self._orgb_status = label(_("Checking…"), ("body",), wrap=True)
        c.append(self._orgb_status)
        r = hbox(10)
        r.append(label(_("Start OpenRGB"), ("body",)))
        self._orgb_method_dd = Dropdown(list(self._orgb_method_labels().values()), None, self._set_orgb_method)
        r.append(self._orgb_method_dd)
        c.append(r)
        self._orgb_login_lbl = label(_("Checking…"), ("small", "dim"), wrap=True)
        c.append(self._orgb_login_lbl)
        self._orgb_others_lbl = label("", ("small", "error-text"), wrap=True)
        self._orgb_others_lbl.set_visible(False)
        c.append(self._orgb_others_lbl)
        self._orgb_hide_btn = button(_("Turn off OpenRGB's own autostart"), "visibility_off", "tonal small",
                                     self._hide_orgb_autostart)
        self._orgb_hide_btn.set_visible(False)
        c.append(hbox(8, self._orgb_hide_btn))
        c.append(divider())
        r = hbox(8)
        r.append(button(_("Reconnect"), "sync", "tonal", lambda: self.bg(self.client.reconnect_openrgb,
                                                                       lambda r: self.toast(_("Reconnecting…")))))
        r.append(button(_("Restart OpenRGB server"), "restart_alt", "danger", self._openrgb_restart))
        c.append(r)
        c.append(label(_("Reconnect is quick and safe to try first. Restart stops and relaunches OpenRGB's SDK server (or "
                       "its systemd service); use it when a device stops responding and Reconnect doesn't bring it "
                       "back. It won't touch an OpenRGB window."), ("small", "faint"), wrap=True))
        p.append(c)

        p.append(section(_("Diagnostics")))
        c = card()
        c.append(button(_("Run diagnostics"), "troubleshoot", "filled", self._run_diagnostics))
        c.append(label(_("Checks the daemon, OpenRGB, zones, DDC and wallpaper detection in one go, the same thing "
                       "“iridia doctor” prints."), ("small", "faint"), wrap=True))
        p.append(c)

        p.append(section(_("Uninstall")))
        c = card()
        c.append(button(_("Uninstall Iridia…"), "delete", "danger", self._uninstall))
        c.append(label(_("Stops the daemon and removes the service, launcher, icons and program files. You choose whether "
                       "to keep your settings. Same as running “iridia uninstall”."), ("small", "faint"),
                       wrap=True))
        p.append(c)
        self._refresh_orgb_login()

    def _show_autostart(self):
        from iridia import autostart
        title = self._as_dd.value()
        snip = next((x for x in self._as_snips if x["title"] == title), self._as_snips[0])
        warn = ""
        if os.path.sep not in autostart.daemon_command():
            warn = "\n" + _("Couldn't find the iridia-daemon launcher next to Python, so this uses the bare name and "
                             "relies on your login PATH. If it doesn't start, replace it with the full path (run: "
                             "which iridia-daemon).")
        self._as_file.set_label(_('Add this to: {file}').format(file=snip['file']) + warn)
        self._as_text = snip["text"]
        self._as_buf.set_text(snip["text"])
        self._as_xdg.set_visible(snip["id"] == "xdg")
        if snip["id"] == "xdg":
            set_button_text(self._as_xdg, _("Remove XDG autostart") if autostart.xdg_installed() else
                            _("Install XDG autostart"), "delete" if autostart.xdg_installed() else "add")

    def _toggle_xdg(self):
        from iridia import autostart
        if autostart.xdg_installed():
            autostart.xdg_remove()
            self.toast(_("XDG autostart removed"))
        else:
            autostart.xdg_install()
            self.toast(_("XDG autostart installed"))
        self._show_autostart()

    def _cli(self, *args, done=None):
        self.bg(lambda: subprocess.run([_iridia_cli_path(), *args], capture_output=True, text=True), done)

    def _daemon_start(self):
        def done(r):
            if getattr(r, "returncode", 1) != 0:
                dialogs.message(self, _("Daemon"), (r.stderr or r.stdout or "").strip() if hasattr(r, "stderr") else
                                str(r), True)
            GLib.timeout_add(1200, lambda: (self._poll_once(), False)[1])
        self._spinner.start()
        self._cli("daemon", "start", done=done)

    def _daemon_kill(self):
        def done(r):
            if getattr(r, "returncode", 1) != 0:
                dialogs.message(self, _("Daemon"), (getattr(r, "stderr", "") or "").strip() or _("Couldn't stop it."), True)
            GLib.timeout_add(800, lambda: (self._poll_once(), False)[1])
        self._cli("daemon", "stop", done=done)

    def _svc_install(self):
        self._cli("service", "install", "--autostart", "systemd", done=lambda r: (
            self.toast(_("Enabled. The daemon now starts at login.")) if getattr(r, "returncode", 1) == 0 else
            dialogs.message(self, _("Service"), _('Install failed:') + '\n' + (getattr(r, 'stderr', '') or '').strip(), True),
            self._render_service_status_now()))

    def _svc_disable(self):
        self.bg(lambda: subprocess.run(["systemctl", "--user", "disable", "iridia-daemon.service"], capture_output=True,
                                       text=True), lambda r: self._render_service_status_now())

    def _svc_remove(self):
        dialogs.confirm(self, _("Remove service"), _("Stop, disable and delete the systemd service (and the app "
                                                "launcher)? Your settings are kept."),
                        lambda: self._cli("service", "remove", done=lambda r: (self.toast(_("Removed.")),
                                                                               self._render_service_status_now())),
                        yes=_("Remove"), danger=True)

    def _check_orgb_login(self):
        from iridia import openrgb_server
        try:
            return openrgb_server.status()
        except Exception as e:
            return {"error": str(e)}

    def _refresh_orgb_login(self):
        self.bg(self._check_orgb_login, lambda st: (setattr(self, "_orgb_login", st), self._render_orgb_login()))

    @staticmethod
    def _orgb_method_labels():
        return {"daemon": _("With Iridia"), "systemd": _("systemd service"), "off": _("I start it myself")}

    def _render_orgb_login(self):
        st = getattr(self, "_orgb_login", None)
        if not st or not hasattr(self, "_orgb_method_dd"):
            return
        labels = self._orgb_method_labels()
        if st.get("error"):
            self._orgb_login_lbl.set_label(st["error"])
            return
        method = st.get("method", "daemon")
        shown = {k: v for k, v in labels.items() if k != "systemd" or st.get("systemd") or method == "systemd"}
        self._orgb_method_dd.set_items(list(shown.values()), labels.get(method))
        live = self._status if "_error" not in self._status else {}
        lines = []
        if not st.get("command") and method != "off":
            lines.append(_("OpenRGB isn't installed, so there is nothing to start."))
        elif method == "daemon":
            lines.append(_("The Iridia daemon starts OpenRGB's server inside your session, and starts it again if "
                           "it stops. Works with or without systemd."))
            ours = live.get("openrgb_ours_pid") or st.get("ours")
            if ours:
                lines.append(_("Running (pid {pid}).").format(pid=ours))
            elif live.get("openrgb_connected"):
                lines.append(_("Running, but not started by Iridia, so Iridia won't restart it."))
        elif method == "systemd":
            lines.append(_("A systemd user service (iridia-openrgb.service) starts it with your graphical "
                           "session."))
            if st.get("graphical_session") is False:
                lines.append(_("Your session doesn't start graphical-session.target, so this service won't start "
                               "at login. Pick “With Iridia” instead."))
            elif st.get("active"):
                lines.append(_("Service: {state}").format(state=st["active"]))
        else:
            lines.append(_("Iridia never starts or restarts OpenRGB. Start its server yourself: the OpenRGB "
                           "window with its SDK server on, or a service."))
        if st.get("window_without_server") and not live.get("openrgb_connected"):
            lines.append(_("The OpenRGB window is open, but its SDK server is off. In OpenRGB: SDK Server tab, "
                           "Start Server."))
        self._orgb_login_lbl.set_label("\n".join(lines))
        others = st.get("others") or []
        warn = method != "off" and bool(others)
        self._orgb_others_lbl.set_visible(warn)
        if warn:
            self._orgb_others_lbl.set_label(_("Also started by: {what}. Two OpenRGB instances fight over the "
                                              "hardware, so Iridia won't start one while that is set up.")
                                            .format(what=", ".join(others)))
        self._orgb_hide_btn.set_visible(warn and bool(st.get("xdg_entries")))

    def _set_orgb_method(self, text):
        method = next((k for k, v in self._orgb_method_labels().items() if v == text), None)
        st = getattr(self, "_orgb_login", None) or {}
        if method is None or method == st.get("method"):
            return

        def run(stop):
            def done(r):
                out = ((getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or "")).strip()
                if getattr(r, "returncode", 1) != 0:
                    dialogs.message(self, _("OpenRGB"), out or _("That didn't work"), True)
                else:
                    self.toast(_("OpenRGB start method changed"))
                self._refresh_orgb_login()
            self._orgb_method_dd.set_sensitive(False)
            self._cli("openrgb", "start-method", method, *(["--stop"] if stop else []),
                      done=lambda r: (self._orgb_method_dd.set_sensitive(True), done(r)))
        ours = (self._status.get("openrgb_ours_pid") if "_error" not in self._status else None) or st.get("ours")
        if st.get("method") == "daemon" and method == "off" and ours:
            dialogs.confirm(self, _("OpenRGB"), _("Also stop the OpenRGB server Iridia started? Other programs may "
                                                 "be using it. If you keep it, it runs until you log out."),
                            lambda: run(True), yes=_("Stop it"), no=_("Keep it running"), on_no=lambda: run(False))
        else:
            run(False)

    def _hide_orgb_autostart(self):
        st = getattr(self, "_orgb_login", None) or {}
        files = st.get("xdg_entries") or []
        if not files:
            return
        dialogs.confirm(self, _("Turn off OpenRGB's own autostart"),
                        _("Add “Hidden=true” to {files}, so your desktop no longer starts OpenRGB at login? The file "
                          "stays; delete that line to undo.").format(files=", ".join(files)),
                        lambda: self._cli("openrgb", "hide-autostart",
                                          done=lambda r: (self.toast(_("OpenRGB's autostart is off")),
                                                          self._refresh_orgb_login())),
                        yes=_("Turn off"))

    def _openrgb_restart(self):
        dialogs.confirm(self, _("Restart OpenRGB server"), _("This stops and relaunches the OpenRGB SDK server (about 4 "
                                                        "seconds), which briefly interrupts any other software using it."),
                        lambda: self.bg(self.client.restart_openrgb_server), yes=_("Restart"), danger=True)

    def _run_diagnostics(self):
        reachable = "_error" not in self._status
        dialogs.diagnostics_window(self, diagnostics.run_checks(self._status if reachable else {}, reachable))

    def _uninstall(self):
        d = dialogs.Dialog(self, _("Uninstall Iridia"))
        d.body.append(label(_("Uninstall Iridia"), ("title",)))
        d.body.append(label(_("Remove Iridia from this computer? The daemon stops, so your LEDs keep their last colors "
                            "until something else changes them."), ("body", "dim"), wrap=True, chars=56))

        def go(keep):
            d.close()
            args = [_iridia_cli_path(), "uninstall", "--yes"] + (["--keep-settings"] if keep else [])
            try:
                subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as e:
                dialogs.message(self, _("Uninstall"), _("Couldn't start the uninstaller: {e}").format(e=e), True)
                return
            self.close()
        d.buttons(button(_("Cancel"), style="text", cb=d.close),
                  button(_("Remove, keep my settings"), style="tonal", cb=lambda: go(True)),
                  button(_("Remove everything"), style="danger", cb=lambda: go(False)))
        d.present()

    def _check_service_status(self):
        try:
            r = subprocess.run(["systemctl", "--user", "is-enabled", "iridia-daemon.service"], capture_output=True,
                               text=True, timeout=3)
            out = (r.stdout or r.stderr).strip().lower()
            if "not-found" in out or "no such file" in out or "not found" in out:
                return "not installed"
            return out.split()[0] if out else "unknown"
        except Exception:
            return "unknown"

    def _render_service_status_now(self):
        self.bg(self._check_service_status, lambda st: (self._status.__setitem__("_service_status", st),
                                                        self._render_daemon_status()))

    def _render_daemon_status(self):
        if "_error" in self._status:
            self._svc_status.set_label(_("Daemon stopped"))
            self._svc_status.remove_css_class("ok-text")
            self._svc_status.add_css_class("error-text")
        else:
            who = self._status.get("started_by")
            if who:
                text = _("Running (pid {pid}, started by {who})").format(pid=self._status.get("pid", "?"), who=who)
            else:
                by = _("by systemd") if self._status.get("managed_by") == "systemd" else _("without systemd")
                text = _('Running (pid {pid}, started {by})').format(pid=self._status.get('pid', '?'), by=by)
            self._svc_status.set_label(text)
            self._svc_status.remove_css_class("error-text")
            self._svc_status.add_css_class("ok-text")
        self._render_orgb_login()
        st = self._status.get("_service_status", "checking…")
        self._unit_status.set_label({"enabled": _("Enabled. The daemon starts automatically when you log in."),
                                     "disabled": _("Installed but not enabled. It won't start at login."),
                                     "not installed": _("Not installed. Click “Enable at login” to set it up.")
                                     }.get(st, _("systemd status: {status}").format(status=st))
                                    + ("\n" + _("Your session doesn't start graphical-session.target, so the service "
                                                 "won't start the daemon at login. Use one of the other ways below.")
                                       if st == "enabled" and (getattr(self, "_orgb_login", None) or {})
                                       .get("graphical_session") is False else ""))

    # ============================================================ header actions
    def _toggle_freeze(self):
        want = not self._frozen
        self.bg(lambda: (self.client.freeze(want), self.client.status())[1],
                lambda st: (setattr(self, "_status", st), self._update_ui(),
                            self.toast(_("Colors frozen. Wallpaper changes are ignored.") if want else
                                       _("Colors follow the wallpaper again."))))

    def refresh_soon(self):
        """Ask the daemon for a fresh status now (after a change), instead of waiting for the poll."""
        self.bg(self.client.status, lambda st: self._apply_status(st) if isinstance(st, dict) and st.get("ok") else None)

    def _do_refresh(self):
        self.bg(self.client.refresh, lambda r: self._poll_once())

    def _do_restart(self):
        self.bg(self.client.restart, lambda r: self.toast(_("Daemon restarting…")))

    # ============================================================ seed / theme
    @staticmethod
    def _seed_cache_path():
        return os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "iridia", "gui_seed")

    def _load_seed(self):
        try:
            with open(self._seed_cache_path()) as f:
                return theme.clean_seed(f.read().strip())
        except OSError:
            return theme.DEFAULT_SEED

    def _save_seed(self, h):
        try:
            p = self._seed_cache_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(h)
        except OSError:
            pass

    def _maybe_reseed(self, led_hex):
        if not led_hex or len(led_hex) != 6:
            return
        if theme.seed_distance(led_hex, self._seed) < 45:
            self._pending_seed, self._pending_count = None, 0
            return
        if led_hex == self._pending_seed:
            self._pending_count += 1
        else:
            self._pending_seed, self._pending_count = led_hex, 1
        idle = time.time() - self._last_activity > 2
        if self._pending_count >= 2 and time.time() - self._last_reseed > 8 and idle:
            self._last_reseed = time.time()
            self._seed = led_hex
            self._pending_seed, self._pending_count = None, 0
            self._save_seed(led_hex)
            widgets.STYLE.set_seed(led_hex, on_frame=widgets.repaint_all)

    # ============================================================ polling
    def _poll_loop(self):
        while self._running:
            try:
                resp = self.client.status()
                if resp.get("ok"):
                    if self._poll_count % 15 == 0:
                        self._orgb_login = self._check_orgb_login()
                    if self._poll_count % 5 == 0:
                        resp["_service_status"] = self._check_service_status()
                    else:
                        resp["_service_status"] = self._status.get("_service_status", "checking…")
                    self._poll_count += 1
                    st = resp
                else:
                    st = {"_error": resp.get("error", "daemon not running")}
            except Exception:
                st = {"_error": "daemon not running"}
            GLib.idle_add(self._apply_status, st)
            time.sleep(2)

    def _apply_status(self, st):
        if self._pause_n == 0:
            self._status = st
            self._update_ui()
        return False

    def _poll_once(self):
        def work():
            try:
                r = self.client.status()
                st = r if r.get("ok") else {"_error": r.get("error", "daemon not running")}
            except Exception:
                st = {"_error": "daemon not running"}
            st["_service_status"] = self._check_service_status()
            return st
        self.bg(work, lambda st: (setattr(self, "_status", st), self._update_ui()))

    def _update_ui(self):
        if self._pause_n:
            return
        st = self._status
        if "_error" in st:
            self._chip.set(_("Daemon not running"), "error")
            self._spinner.stop()
            self._show_daemon_down()
            self._render_daemon_status()
            self._hero_title.set_label(_("The daemon isn't running"))
            self._hero_sub.set_label(_("Start it from the Service tab."))
            return
        self._spinner.stop()
        if self._down:
            self._down = False
            self._clear(self._dev_box)
            self._last_device_keys = None
        colors = list(st.get("extracted_colors", []))
        wallpaper = st.get("wallpaper") or ""
        brightness = st.get("brightness", 0)
        dominant = st.get("led_color") or (colors[0] if colors else "00aa66")
        self._maybe_reseed(dominant)
        missing = st.get("openrgb_missing_devices", [])
        night = st.get("night") or {}
        if not st.get("openrgb_connected"):
            self._chip.set(_("OpenRGB not connected"), "error")
        elif missing:
            self._chip.set(_("Can't see: {devices}").format(devices=', '.join(missing)), "error")
        elif night.get("active"):
            self._chip.set(_('Night mode until {time}').format(time=night.get('end')), "warn")
        else:
            self._chip.set(f"#{dominant}  ·  {brightness}%", "ok")
        frozen = bool(st.get("frozen"))
        if frozen != self._frozen:
            self._frozen = frozen
            set_button_text(self._freeze_btn, _("Frozen") if frozen else _("Freeze colors"), "ac_unit")
            (self._freeze_btn.add_css_class if frozen else self._freeze_btn.remove_css_class)("toggled")
        # hero
        wp = os.path.basename(wallpaper) if wallpaper else _("No wallpaper detected yet")
        self._hero_title.set_label(f"#{dominant}")
        self._hero_sub.set_label(wp)
        self._hero_wave.set_value((brightness or 0) / 100)
        self._hero_bright.set_label(f"{brightness}%")
        state = "off" if (st.get("lights_off") or st.get("asleep")) else "frozen" if frozen else \
            "night" if night.get("active") else "normal"
        self._hero_shape.set_value(dominant, state)
        # rows
        r = self._rows
        r["wallpaper"].set_label(wp)
        r["dominant"].set_label(f"#{colors[0]}" if colors else "-")
        r["openrgb"].set_label(_("Connected") if st.get("openrgb_connected") else _("Not connected"))
        r["ddc"].set_label(_("Available") if st.get("ddc_available") else _("Not available"))
        modes = {z.get("mode", "full") for z in self._all_zone_cfgs(st.get("device_configs", {}))}
        r["mode"].set_label(MODE_LABELS.get(next(iter(modes)), MODE_LABELS["full"]) if len(modes) == 1 else _("Mixed") if modes else MODE_LABELS["full"])
        r["freeze"].set_label(_("Frozen (wallpaper changes are ignored)") if frozen else _("Following the wallpaper"))
        if not night.get("enabled"):
            nt = _("Off")
        elif night.get("active"):
            nt = _("On until {end}, brightness capped at {cap}%").format(end=night.get('end'), cap=night.get('cap'))
        else:
            nt = _("Scheduled {start} to {end} (cap {cap}%)").format(start=night.get('start'), end=night.get('end'), cap=night.get('cap'))
        r["night"].set_label(nt)
        nov = len(st.get("overlays") or {})
        r["lights"].set_label((_("Off (PC asleep)") if st.get("asleep") else
                               _("Off (turned off by command)") if st.get("lights_off") else _("On"))
                              + (', ' + ngettext('{n} strip changed by a keybind (see Keybinds)', '{n} strips changed by a keybind (see Keybinds)', nov).format(n=nov)
                                 if nov else ""))
        r["backend"].set_label(st.get("color_backend", "auto"))
        self._extract_live.set_label(
            _('Right now: wallpaper found via “{found}”{cached}, colors extracted via “{engine}”.').format(found=st.get('wallpaper_backend') or _('nothing yet'), cached=_(' (cached)') if st.get('wallpaper_backend_cached') else '', engine=st.get('color_backend_used') or _('n/a (cached or not yet run)')))
        profs = st.get("calibration_profiles")
        if profs:
            ZoneCard.PROFILES = list(profs)
        devices = st.get("device_configs", {})
        choice = self._everything_choice(devices)
        custom = list(st.get("custom_colors", []))
        widgets.set_exact_colors(st.get("exact_colors", []))
        sk = (tuple(colors), repr(choice), tuple(custom))
        if sk != self._last_swatch_key:
            if self._last_swatch_key is not None and tuple(custom) != self._last_swatch_key[2]:
                QuickColors.refresh_all()
            self._last_swatch_key = sk
            self._render_swatches(colors, choice, custom)
        self._render_correction(st.get("correction") or {})
        keys = (self._device_keys(devices), bool(st.get("hardware_effects")))
        if keys != self._last_device_keys:
            self._last_device_keys = keys
            self._rebuild_devices(devices, colors, custom)
        else:
            self._sync_devices(devices, colors, custom)
        self._apply_hw(st.get("devices") or [])
        real = {x.get("name"): x for x in st.get("devices") or []}
        for d, card_w in getattr(self, "_hw_cards", {}).items():
            card_w.update((real.get(d) or {}).get("hardware_modes") or [], (devices.get(d) or {}).get("hardware_effect"))
        for key, zc_card in self._zone_cards.items():
            spec = (devices.get(key.split("|", 1)[0]) or {}).get("hardware_effect")
            zc_card.set_controller_effect(spec.get("mode") if spec and st.get("hardware_effects") else None)
        self._sync_animation_settings(st)
        for k, info in (st.get("strip_info") or {}).items():
            c = self._zone_cards.get(k)
            if c is not None:
                c.set_strip_info(info)
        self._layout_tab.update_status(st)
        self._keybinds.update_status(st)
        self._render_daemon_status()
        if st.get("openrgb_connected"):
            self._orgb_status.set_label(_('Connected, but not seeing: {devices}').format(devices=', '.join(missing)) if missing else
                                        _("Connected. All configured devices visible."))
        else:
            self._orgb_status.set_label(_("Not connected.") + " " + (st.get("openrgb_last_error") or ""))

    def _on_close(self, *_a):
        self._running = False
        return False


class IridiaApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=getattr(Gio.ApplicationFlags, "DEFAULT_FLAGS", Gio.ApplicationFlags.FLAGS_NONE))
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(assets.ICON_NAME)
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)

    def do_activate(self):
        if self.win is None:
            self.win = IridiaWindow(self)
        self.win.present()


RESTART = False


def main():
    GLib.set_prgname(APP_ID)          # X11 WM_CLASS, so launchers group the window with Iridia
    GLib.set_application_name("Iridia")
    fonts.register()
    app = IridiaApp()
    rc = app.run(sys.argv[:1])
    if RESTART:
        # language changed: start a fresh window process (the strings are loaded at start)
        os.execv(sys.executable, [sys.executable, "-m", "iridia.gui"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
