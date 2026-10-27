"""The Layout tab's Notifications tool: which LEDs flash for a notification, picked by clicking or
dragging over them on the map, and two points A and B that a moving flash runs between. Play shows
the flash on the map (with the same code the daemon uses) and on the real strips.

Mixed into LayoutTab; it uses the tab's canvas, handles, drag state and side panel."""

import math
import time
from typing import Dict, Optional, Set

from gi.repository import GLib

from iridia.i18n import _, ngettext
from iridia import notifyflash, theme
from iridia import sections as zone_sections
from iridia.layout import led_at_path, led_points, path_points, project, split_key
from iridia.ui.widgets import Dropdown, Spin, Toggle, button, divider, hbox, label, rgb

EFFECT_NAMES = {"pulse": _("Pulse"), "flash": _("Flash"), "sweep": _("Sweep"), "comet": _("Comet"),
                "fill": _("Fill"), "ripple": _("Ripple")}
DIRECTION_NAMES = {"ab": _("A to B"), "ba": _("B to A"), "abba": _("A to B and back"),
                   "out": _("From the middle out")}
HOLD_SEC = 3.0                  # local edits win over the daemon's status for this long


class NotifyLayer:
    def _nt_init(self):
        self._nt: dict = notifyflash.clean({})
        self._nt_hold = 0.0
        self._nt_paint: Dict[str, Set[int]] = {}        # zone key -> LEDs while dragging over them
        self._nt_preview: Optional[notifyflash.Flash] = None
        self._nt_job = None

    # ------------------------------------------------------------ state
    def _nt_update(self, status: dict):
        st = status.get("notify")
        if isinstance(st, dict) and time.time() >= self._nt_hold:
            self._nt = notifyflash.clean(st)

    def _nt_set(self, **kw):
        """Change settings here at once and in the daemon."""
        self._nt = notifyflash.clean(dict(self._nt, **kw))
        self._nt_hold = time.time() + HOLD_SEC
        self._send(lambda: self.app.client.notify(**kw))
        self.cv.queue_draw()

    def _nt_sections(self, key: str, n: int):
        return zone_sections.clean((self._cfg.get(key) or {}).get("sections"), n)

    def _nt_leds(self, key: str, n: int) -> Set[int]:
        """The LEDs of this zone that flash (0-based, as sent)."""
        if key in self._nt_paint:
            return self._nt_paint[key]
        d, z = split_key(key)
        out: Set[int] = set()
        for t in self._nt["targets"]:
            if (t["device"], t["zone"]) == (d, z):
                r = notifyflash.target_range(t, n, self._nt_sections(key, n), zone_sections.spans)
                if r:
                    out.update(range(*r))
        return out

    def _nt_count(self):
        leds = strips = 0
        for key in self._enabled:
            k = len(self._nt_leds(key, self._count(key)))
            if k:
                leds, strips = leds + k, strips + 1
        return leds, strips

    # ------------------------------------------------------------ drawing
    def _nt_draw(self, cr):
        z = self.layout.view["zoom"]
        pv = self._nt_preview
        if pv is not None and pv.done():
            pv = self._nt_preview = None
        for s in self._strips():
            key = s["zone"]
            n = self._count(key)
            if n <= 0:
                continue
            chosen = self._nt_leds(key, n)
            if not chosen:
                continue
            pts = [self.w2s(x, y) for x, y in led_points(s, n)]
            r = max(2.0, min(s["segments"][0]["spacing"] * 0.34, 6.0) * z)
            frame = None
            if pv is not None and key in pv.leds:
                base = [theme.hex_rgb(c) for c in self.zone_colors(key)]
                frame = pv.mix(key, [(int(a * 255), int(b * 255), int(c * 255)) for a, b, c in base])
            cr.set_line_width(2)
            for i in chosen:
                if i >= len(pts):
                    continue
                x, y = pts[i]
                if frame is not None:
                    cr.set_source_rgb(*(v / 255 for v in frame[i]))
                    cr.arc(x, y, r, 0, 2 * math.pi)
                    cr.fill()
                cr.set_source_rgb(*rgb("PRIMARY"))
                cr.arc(x, y, r + 2.5, 0, 2 * math.pi)
                cr.stroke()
        path = self._nt["path"]
        if path:
            ax, ay = self.w2s(*path["a"])
            bx, by = self.w2s(*path["b"])
            on = self._nt["spatial"]
            cr.set_source_rgb(*rgb("PRIMARY" if on else "OUTLINE"))
            cr.set_line_width(2)
            if not on:
                cr.set_dash([6, 6])
            cr.move_to(ax, ay)
            cr.line_to(bx, by)
            cr.stroke()
            cr.set_dash([])
            ang = math.atan2(by - ay, bx - ax)          # an arrowhead halfway, pointing to B
            mx, my = (ax + bx) / 2, (ay + by) / 2
            for side in (-1, 1):
                cr.move_to(mx + 8 * math.cos(ang), my + 8 * math.sin(ang))
                cr.line_to(mx - 6 * math.cos(ang) + side * 7 * math.sin(ang),
                           my - 6 * math.sin(ang) - side * 7 * math.cos(ang))
            cr.stroke()
            for name, (x, y) in (("A", (ax, ay)), ("B", (bx, by))):
                cr.set_source_rgb(*rgb("PRIMARY" if on else "SURFACE_CONTAINER_HIGHEST"))
                cr.arc(x, y, 13, 0, 2 * math.pi)
                cr.fill()
                self._text(cr, x, y + 5, name, "ON_PRIMARY" if on else "ON_SURFACE", 14, center=True, bold=True)
                self._handles.append(("nt_" + name.lower(), None, 0, x, y, 16))

    # ------------------------------------------------------------ pointer
    def _nt_press(self, s, n, k):
        """Click or drag over LEDs: adds them, or takes them out when the first one was chosen."""
        key = s["zone"]
        i = led_at_path(s, n, k)
        cur = set(self._nt_leds(key, n))
        mode = "remove" if i in cur else "add"
        self._nt_paint[key] = cur
        self._drag = {"kind": "ntpaint", "sid": s["id"], "mode": mode, "last": k}
        self._nt_apply(s, n, k, k)

    def _nt_apply(self, s, n, k0, k1):
        leds = self._nt_paint[s["zone"]]
        for k in range(min(k0, k1), max(k0, k1) + 1):
            i = led_at_path(s, n, k)
            if self._drag["mode"] == "add":
                leds.add(i)
            else:
                leds.discard(i)

    def _nt_motion(self, s, n, x, y):
        f, d = project([self.w2s(a, b) for a, b in path_points(s, n)], x, y)
        if d < 40:
            k = int(round(f))
            self._nt_apply(s, n, self._drag["last"], k)
            self._drag["last"] = k

    def _nt_release(self, s):
        key = s["zone"]
        leds = self._nt_paint.pop(key, None)
        if leds is None:
            return
        d, z = split_key(key)
        others = [t for t in self._nt["targets"] if (t["device"], t["zone"]) != (d, z)]
        self._nt_set(targets=others + notifyflash.targets_for(d, z, leds))
        self._nt_refresh_panel()

    def _nt_drag_point(self, which: str, x: float, y: float):
        wx, wy = self.s2w(x, y)
        path = dict(self._nt["path"] or {})
        path[which] = [round(wx, 1), round(wy, 1)]
        self._nt = dict(self._nt, path=path)
        self._nt_hold = time.time() + HOLD_SEC

    def _nt_drop_point(self):
        if self._nt["path"]:
            self._nt_set(path=self._nt["path"])

    # ------------------------------------------------------------ actions
    def _nt_place_points(self):
        """A and B at the two ends of the chosen LEDs (or of every strip), across their longer side."""
        xs, ys = [], []
        for s in self._strips():
            n = self._count(s["zone"])
            chosen = self._nt_leds(s["zone"], n)
            pts = led_points(s, n)
            for i, p in enumerate(pts):
                if i in chosen or not any(self._nt["targets"]):
                    xs.append(p[0])
                    ys.append(p[1])
        if not xs:
            return
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if x1 - x0 >= y1 - y0:
            a, b = [x0, (y0 + y1) / 2], [x1, (y0 + y1) / 2]
        else:
            a, b = [(x0 + x1) / 2, y0], [(x0 + x1) / 2, y1]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1:
            b = [a[0] + 100, a[1]]
        self._nt_set(path={"a": [round(v, 1) for v in a], "b": [round(v, 1) for v in b]}, spatial=True)
        self._nt_refresh_panel()

    def _nt_play(self):
        """The flash on the map, and on the real strips."""
        st = self._nt
        accent = self.status.get("led_color") or (self.status.get("extracted_colors") or ["ffffff"])[0]
        effect, color = notifyflash.style_for(st, "Iridia", False, accent)
        ranges, positions = {}, {}
        for s in self.layout.strips:
            if s.get("clone") or s["zone"] not in self._enabled:
                continue
            n = self._count(s["zone"])
            chosen = sorted(self._nt_leds(s["zone"], n))
            if chosen:
                ranges[s["zone"]] = [(i, i + 1) for i in chosen]
                positions[s["zone"]] = led_points(s, n)
        # ranges here are single LEDs; along a strip, t still has to run over the whole chosen run
        leds = notifyflash.led_places(self._nt_runs(ranges), positions, effect,
                                      st["path"] if st["spatial"] else None)
        if not leds:
            return
        self._nt_preview = notifyflash.Flash(leds, color, effect, st["duration"], direction=st["direction"],
                                             width=st["width"], repeat=st["repeat"], brightness=st["brightness"])
        if self._nt_job is None:
            self._nt_job = GLib.timeout_add(33, self._nt_tick)
        self._send(lambda: self.app.client.notify(test=True))

    @staticmethod
    def _nt_runs(ranges):
        out = {}
        for key, rs in ranges.items():
            leds = sorted(lo for lo, _hi in rs)
            runs, run = [], None
            for i in leds:
                if run and i == run[1]:
                    run[1] = i + 1
                else:
                    if run:
                        runs.append(tuple(run))
                    run = [i, i + 1]
            if run:
                runs.append(tuple(run))
            out[key] = runs
        return out

    def _nt_tick(self):
        self.cv.queue_draw()
        if self._nt_preview is None or self._nt_preview.done():
            self._nt_preview = None
            self._nt_job = None
            self.cv.queue_draw()
            return False
        return True

    # ------------------------------------------------------------ side panel
    def _nt_build_panel(self, p):
        st = self._nt
        self._ntw = {}
        p.append(label(_("Notifications"), ("heading",)))
        p.append(label(_("Click or drag over LEDs to flash them for a desktop notification; start on a chosen one "
                         "to take LEDs out. Drag A and B to set where a moving flash runs."), ("small", "dim"),
                       wrap=True))
        self._ntw["enabled"] = Toggle(st["enabled"], lambda v: self._nt_set(enabled=v))
        p.append(hbox(12, self._ntw["enabled"], label(_("Flash LEDs for notifications"), ("body",))))
        self._ntw["count"] = label("", ("small", "dim"))
        row = hbox(8, self._ntw["count"])
        self._ntw["count"].set_hexpand(True)
        row.append(button(_("Clear"), "close", "text small", lambda: (self._nt_set(targets=[]),
                                                                     self._nt_refresh_panel())))
        p.append(row)
        p.append(divider())
        eff = Dropdown(list(EFFECT_NAMES.values()), EFFECT_NAMES[st["effect"]],
                       lambda v: self._nt_set(effect=self._key_of(EFFECT_NAMES, v)))
        p.append(hbox(10, label(_("Effect"), ("body", "dim")), eff))
        self._ntw["effect"] = eff
        dr = Dropdown(list(DIRECTION_NAMES.values()), DIRECTION_NAMES[st["direction"]],
                      lambda v: self._nt_set(direction=self._key_of(DIRECTION_NAMES, v)))
        self._ntw["direction"] = dr
        p.append(hbox(10, label(_("Direction"), ("body", "dim")), dr))
        self._ntw["width"] = Spin(5, 100, st["width"], lambda v: self._nt_set(width=int(v)), step=5)
        p.append(hbox(10, label(_("Band"), ("body", "dim")), self._ntw["width"], label("%", ("body", "dim"))))
        self._ntw["duration"] = Spin(0.5, 5, st["duration"], lambda v: self._nt_set(duration=v), step=0.5, digits=1)
        p.append(hbox(10, label(_("Length"), ("body", "dim")), self._ntw["duration"],
                      label(_("seconds"), ("body", "dim"))))
        self._ntw["repeat"] = Spin(1, 5, st["repeat"], lambda v: self._nt_set(repeat=int(v)))
        p.append(hbox(10, label(_("Plays"), ("body", "dim")), self._ntw["repeat"], label(_("times"), ("body", "dim"))))
        p.append(divider())
        p.append(label(_("A and B"), ("subheading",)))
        self._ntw["spatial"] = Toggle(st["spatial"], lambda v: (self._nt_set(spatial=v) if self._nt["path"]
                                                                else self._nt_place_points()))
        p.append(hbox(12, self._ntw["spatial"], label(_("Run through the room from A to B"), ("body",))))
        p.append(label(_("The flash runs over your LEDs by where they are, across every strip, and only between A "
                         "and B (Ripple: out from A, as far as B). Off: along each strip."), ("tiny", "faint"),
                       wrap=True))
        p.append(button(_("Put A and B at the ends"), "open_with", "tonal small", self._nt_place_points))
        p.append(divider())
        p.append(button(_("Play"), "play_arrow", "filled small", self._nt_play))
        p.append(label(_("Colours, apps and quiet times are in Settings, Notifications."), ("tiny", "faint"), wrap=True))
        self._nt_refresh_panel()

    @staticmethod
    def _key_of(names: dict, text: str) -> str:
        return next((k for k, v in names.items() if v == text), next(iter(names)))

    def _nt_refresh_panel(self):
        w = getattr(self, "_ntw", None)
        if not w or self.tool != "notify":
            return
        st = self._nt
        leds, strips = self._nt_count()
        w["count"].set_label(ngettext("{n} LED", "{n} LEDs", leds).format(n=leds) + " · " +
                             ngettext("{n} strip", "{n} strips", strips).format(n=strips) if leds else
                             _("No LEDs chosen yet."))
        w["enabled"].set_value(st["enabled"])
        w["spatial"].set_value(st["spatial"])
        w["effect"].set_value(EFFECT_NAMES[st["effect"]])
        w["direction"].set_value(DIRECTION_NAMES[st["direction"]])
        moving = st["effect"] in notifyflash.MOVING
        w["direction"].set_sensitive(moving and st["effect"] != "ripple")
        w["width"].set_sensitive(moving)
        for k in ("width", "duration", "repeat"):
            w[k].set_quiet(st[k])
