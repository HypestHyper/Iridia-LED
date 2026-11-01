"""Material 3 Expressive look for GTK 4, generated from the wallpaper palette.

The whole style is one CSS string built from the palette. Changing the LED
colour only swaps the CSS (optionally blended over a few frames), so the window
recolours in place without rebuilding anything.
"""

import re

from gi.repository import Gdk, GLib, Gtk

from iridia import theme
from iridia.ui import fonts
from iridia.ui.widgets import load_css

EASE = "cubic-bezier(0.34, 1.36, 0.64, 1)"       # springy: slight overshoot (Expressive "spatial" motion)
EASE_STD = "cubic-bezier(0.2, 0, 0, 1)"

CSS = """
window.iridia, window.iridia-dialog {{ background: {SURFACE_DIM}; color: {ON_SURFACE}; font-family: {FONT}; }}
window.iridia-dialog {{ background: {SURFACE_CONTAINER}; }}
headerbar {{ background: {SURFACE_DIM}; box-shadow: none; border: none; min-height: 64px; padding: 0 12px; }}
headerbar > windowhandle > box button.small {{ margin-top: 12px; margin-bottom: 12px; }}
/* window buttons: flat icons, a round highlight only under the pointer; close turns red */
headerbar windowcontrols button {{ min-height: 28px; min-width: 28px; padding: 0; margin: 0 2px; border-radius: 14px;
  background: transparent; color: {ON_SURFACE_VARIANT}; }}
headerbar windowcontrols button:hover {{ background: alpha({ON_SURFACE}, 0.10); color: {ON_SURFACE}; }}
headerbar windowcontrols button:active {{ background: alpha({ON_SURFACE}, 0.16); border-radius: 14px; }}
headerbar windowcontrols button.close:hover {{ background: {ERROR_HOVER}; color: #ffffff; }}
headerbar windowcontrols button.close:active {{ background: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; }}
headerbar windowcontrols button image {{ -gtk-icon-size: 16px; }}
.winctl > button.circle {{ min-height: 32px; min-width: 32px; padding: 0; border-radius: 16px; background: transparent;
  color: {ON_SURFACE_VARIANT}; }}
.winctl > button .icon {{ font-size: 18px; }}
.winctl > button.circle:hover {{ background: alpha({ON_SURFACE}, 0.10); color: {ON_SURFACE}; }}
.winctl > button.circle:active {{ background: alpha({ON_SURFACE}, 0.16); border-radius: 16px; }}
.winctl > button.close:hover {{ background: {ERROR_HOVER}; color: #ffffff; }}
.winctl > button.close:active {{ background: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; }}
.app-title {{ font-size: 24px; font-weight: 700; color: {ON_SURFACE}; }}
.display {{ font-size: 28px; font-weight: 700; }}
.title {{ font-size: 20px; font-weight: 700; }}
.heading {{ font-size: 15px; font-weight: 700; }}
.subheading {{ font-size: 13px; font-weight: 600; }}
.body {{ font-size: 14px; }}
.small {{ font-size: 13px; }}
.tiny {{ font-size: 11.5px; }}
.dim {{ color: {ON_SURFACE_VARIANT}; }}
.faint {{ color: {OUTLINE}; }}
.accent {{ color: {PRIMARY}; }}
.ok-text {{ color: {PRIMARY}; }}
.error-text {{ color: {ERROR}; }}
.warn-text {{ color: {TERTIARY}; }}
.mono {{ font-family: monospace; font-size: 12.5px; }}
.tnum {{ font-feature-settings: "tnum"; }}
.icon {{ font-family: "{ICON}"; font-size: 20px; font-weight: 400; font-variation-settings: "FILL" 0, "wght" 400, "opsz" 24; }}
.icon.fill {{ font-variation-settings: "FILL" 1, "wght" 500, "opsz" 24; }}
.icon.big {{ font-size: 28px; }}
.icon.huge {{ font-size: 40px; }}

/* ---------- navigation: connected button group, selected item morphs ----------
   Radii are real half-heights (not 999px): GTK interpolates radius transitions per corner,
   and huge radii made pressed buttons swell oddly at one corner. */
.tabbar {{ background: {SURFACE_CONTAINER_LOW}; border-radius: 24px; padding: 4px; }}
.tabbar > button {{ background: transparent; color: {ON_SURFACE_VARIANT}; border: none; box-shadow: none;
  border-radius: 20px; padding: 0 18px; min-height: 40px; font-weight: 600;
  transition: background-color 220ms {EASE_STD}, border-radius 220ms {EASE_STD}, color 200ms; }}
.tabbar > button:hover {{ background: {SURFACE_CONTAINER_HIGH}; }}
.tabbar > button:checked {{ background: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER}; border-radius: 12px; }}
.tabbar > button:checked .icon {{ font-variation-settings: "FILL" 1, "wght" 500, "opsz" 24; }}

/* ---------- buttons ---------- */
button {{ border: none; box-shadow: none; background-image: none; outline: none; border-radius: 20px;
  min-height: 40px; padding: 0 20px; font-weight: 600; font-size: 14px; color: {ON_SURFACE};
  background: {SECONDARY_CONTAINER};
  transition: border-radius 200ms {EASE_STD}, background-color 200ms {EASE_STD}, color 200ms; }}
button:hover {{ background: {SECONDARY_CONTAINER_HOVER}; }}
/* some themes (or ~/.config/gtk-4.0/gtk.css) grow things on hover: nothing moves or grows here, and the
   text in a button keeps the button's own size and weight (a class on the label, .icon for one, still
   sets its own: plain element selectors, as Iridia's rules outrank a theme's whatever their detail) */
button, button:hover, button:checked, button:active, dropdown, switch, check, radio, row, row:hover {{
  transform: none; }}
button label {{ font-weight: inherit; font-size: inherit; letter-spacing: inherit; transform: none; }}
button:active {{ border-radius: 10px; }}
button:disabled {{ opacity: 0.45; }}
button.filled {{ background: {PRIMARY}; color: {ON_PRIMARY}; }}
button.filled:hover {{ background: {PRIMARY_HOVER}; }}
button.tonal {{ background: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER}; }}
button.text {{ background: transparent; color: {PRIMARY}; padding: 0 12px; }}
button.text:hover {{ background: {SURFACE_CONTAINER_HIGH}; }}
button.text.dim {{ color: {OUTLINE}; }}
button.outlined {{ background: transparent; color: {PRIMARY}; border: 1px solid {OUTLINE}; }}
button.danger {{ background: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; }}
button.danger:hover {{ background: {ERROR_HOVER}; }}
button.small {{ min-height: 32px; padding: 0 14px; font-size: 13px; border-radius: 16px; }}
button.small:active {{ border-radius: 8px; }}
button.circle {{ padding: 0; min-width: 40px; min-height: 40px; border-radius: 20px; }}
button.circle.small {{ min-width: 32px; min-height: 32px; border-radius: 16px; }}
button.circle:active {{ border-radius: 10px; }}
button.fab {{ min-height: 56px; padding: 0 24px; border-radius: 18px; font-size: 15px;
  box-shadow: 0 6px 18px rgba(0,0,0,0.4); }}
button.fab:active {{ border-radius: 12px; }}
button.toggled, button.filled.toggled {{ background: {PRIMARY}; color: {ON_PRIMARY}; border-radius: 10px; }}

/* connected button group (Expressive): inner corners small, outer round, selected item turns into a pill */
.group > button {{ border-radius: 6px; margin: 0 1px; background: {SECONDARY_CONTAINER};
  color: {ON_SECONDARY_CONTAINER}; min-height: 36px; padding: 0 14px; font-size: 13px;
  transition: border-radius 220ms {EASE_STD}, background-color 200ms {EASE_STD}; }}
.group > button:first-child {{ border-top-left-radius: 18px; border-bottom-left-radius: 18px; }}
.group > button:last-child {{ border-top-right-radius: 18px; border-bottom-right-radius: 18px; }}
.group > button:hover {{ background: {SECONDARY_CONTAINER_HOVER}; }}
.group > button:checked {{ background: {PRIMARY}; color: {ON_PRIMARY}; border-radius: 18px; }}
.group > button:checked:hover {{ background: {PRIMARY_HOVER}; }}
button.filter {{ border-radius: 8px; padding: 4px 12px; min-height: 24px; background: transparent;
  border: 1px solid {OUTLINE_VARIANT}; color: {ON_SURFACE_VARIANT}; font-weight: 500; box-shadow: none; }}
button.filter:hover {{ background: alpha({ON_SURFACE}, 0.08); }}
button.filter:checked {{ background: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER};
  border-color: {SECONDARY_CONTAINER}; }}
.group > button:checked .icon {{ font-variation-settings: "FILL" 1, "wght" 500, "opsz" 24; }}
.group > button:active {{ border-radius: 4px; }}

flowbox.wrap-row > flowboxchild {{ padding: 0; background: none; border-radius: 0; }}

/* ---------- surfaces ---------- */
.card {{ background: {SURFACE_CONTAINER}; border-radius: 28px; padding: 20px; }}
.card-inner {{ background: {SURFACE_CONTAINER_HIGH}; border-radius: 20px; padding: 16px; }}
.zone-header {{ border-radius: 20px; }}
.hero {{ background: {PRIMARY_CONTAINER}; color: {ON_PRIMARY_CONTAINER}; border-radius: 32px; padding: 20px 24px; }}
.hero .dim {{ color: {ON_PRIMARY_CONTAINER}; opacity: 0.8; }}
.panel {{ background: {SURFACE_CONTAINER}; border-radius: 24px; }}
.canvas-frame {{ background: {SURFACE_CONTAINER_LOW}; border-radius: 24px; }}
.floating-toolbar {{ background: {SURFACE_CONTAINER_HIGHEST}; border-radius: 28px; padding: 6px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.35); }}
.divider {{ background: {OUTLINE_VARIANT}; min-height: 1px; }}
separator {{ background: {OUTLINE_VARIANT}; min-height: 1px; }}

/* ---------- chips ---------- */
.chip {{ border-radius: 999px; padding: 6px 14px; font-weight: 600; font-size: 13px;
  background: {SURFACE_CONTAINER_HIGHEST}; color: {ON_SURFACE_VARIANT}; }}
.chip.ok {{ background: {PRIMARY_CONTAINER}; color: {ON_PRIMARY_CONTAINER}; }}
.chip.warn {{ background: {TERTIARY_CONTAINER}; color: {ON_TERTIARY_CONTAINER}; }}
.chip.error {{ background: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; }}

/* ---------- inputs ---------- */
switch {{ background: {SURFACE_CONTAINER_HIGHEST}; border: 2px solid {OUTLINE}; border-radius: 16px;
  min-width: 48px; min-height: 28px; padding: 0; box-shadow: none; transition: all 250ms {EASE_STD}; }}
switch:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
switch > slider {{ background: {OUTLINE}; border: none; box-shadow: none; border-radius: 12px;
  min-width: 16px; min-height: 16px; margin: 6px;
  transition: min-width 250ms {EASE_STD}, min-height 250ms {EASE_STD}, margin 250ms {EASE_STD},
  background-color 200ms {EASE_STD}; }}
switch:checked > slider {{ background: {ON_PRIMARY}; min-width: 24px; min-height: 24px; margin: 2px; }}
switch:hover > slider {{ background: {ON_SURFACE_VARIANT}; }}
switch:checked:hover > slider {{ background: {ON_PRIMARY}; }}
switch image {{ color: transparent; }}

entry, spinbutton, text, textview, textview text {{ background: {SURFACE_CONTAINER_HIGHEST}; color: {ON_SURFACE};
  caret-color: {PRIMARY}; }}
entry, spinbutton {{ border: none; border-radius: 12px; min-height: 38px; box-shadow: none; outline: none;
  padding: 0 10px; }}
entry:focus-within, spinbutton:focus-within {{ box-shadow: inset 0 0 0 2px {PRIMARY}; }}
spinbutton button {{ min-height: 30px; min-width: 26px; padding: 0; background: transparent; border-radius: 10px; }}
spinbutton button:hover {{ background: {SURFACE_BRIGHT}; }}
spinbutton > text {{ background: transparent; }}
textview.log, textview.log text {{ background: {SURFACE_CONTAINER_HIGHEST}; font-family: monospace; font-size: 12px; }}
textview.log {{ border-radius: 14px; padding: 10px; }}

dropdown > button, combobox > button {{ background: {SURFACE_CONTAINER_HIGHEST}; color: {ON_SURFACE}; border-radius: 12px;
  min-height: 38px; padding: 0 12px; font-weight: 500; }}
dropdown > button:hover {{ background: {SURFACE_BRIGHT}; }}
popover > contents, popover.menu > contents {{ background: {SURFACE_CONTAINER_HIGH}; color: {ON_SURFACE};
  border-radius: 16px; padding: 6px; box-shadow: 0 6px 18px rgba(0,0,0,0.4); }}
popover > arrow {{ background: {SURFACE_CONTAINER_HIGH}; }}
popover listview row, popover modelbutton {{ border-radius: 10px; padding: 6px 10px; }}
popover listview row:hover, popover modelbutton:hover {{ background: {SECONDARY_CONTAINER}; }}
popover listview row:selected {{ background: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER}; }}

scale {{ padding: 10px 6px; }}
scale trough {{ background: {SECONDARY_CONTAINER}; border-radius: 999px; min-height: 12px; border: none; }}
scale highlight {{ background: {PRIMARY}; border-radius: 999px; min-height: 12px; }}
scale slider {{ background: {PRIMARY}; border: none; box-shadow: 0 0 0 4px {SURFACE_CONTAINER}; border-radius: 3px;
  min-width: 4px; min-height: 36px; margin: -12px 0; transition: min-width 200ms {EASE_STD}; }}
scale slider:active {{ min-width: 2px; }}
.card-inner scale slider {{ box-shadow: 0 0 0 4px {SURFACE_CONTAINER_HIGH}; }}

checkbutton {{ padding: 4px 0; }}
checkbutton check, checkbutton radio {{ background: transparent; border: 2px solid {ON_SURFACE_VARIANT}; box-shadow: none;
  min-width: 16px; min-height: 16px; color: {ON_PRIMARY}; }}
checkbutton check:checked, checkbutton radio:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}

scrollbar {{ background: transparent; border: none; }}
/* margin too: some themes (Breeze) pull the slider out with a negative margin that only their own
   transparent border makes up for, and without it its size goes below zero (GTK warns on every redraw) */
scrollbar slider {{ background: {OUTLINE_VARIANT}; border-radius: 999px; min-width: 6px; min-height: 6px; border: none;
  margin: 0; }}
scrollbar slider:hover {{ background: {OUTLINE}; }}

tooltip {{ background: {INVERSE_SURFACE}; color: {INVERSE_ON_SURFACE}; border-radius: 8px; }}
tooltip * {{ color: {INVERSE_ON_SURFACE}; }}

.snackbar {{ background: {INVERSE_SURFACE}; color: {INVERSE_ON_SURFACE}; border-radius: 14px; padding: 12px 16px;
  margin: 18px; box-shadow: 0 6px 20px rgba(0,0,0,0.45); }}
.snackbar button {{ color: {INVERSE_PRIMARY}; background: transparent; min-height: 32px; }}
.snackbar label {{ color: {INVERSE_ON_SURFACE}; }}
"""

# Window size settings, as a factor on the sizes written above ("large" is how 1.2 looked).
SIZES = {"compact": 0.8, "default": 0.9, "large": 1.0}
AUTO_COMPACT_BELOW = 900        # "auto" is default size, compact in a window narrower than this
_PX = re.compile(r"(font-size: )?(?<![\w.])(\d+(?:\.\d+)?)px")


def scale_px(css: str, factor: float) -> str:
    """Scale every size in a stylesheet. Hairlines (2px and less) and 999px pills stay as they are, and
    text shrinks less than the rest (never below 10px) so it stays readable.

    Everything comes out in whole pixels: GTK 4.24 cuts off the tops of letters when text or the room
    around it has a fractional size (13.2px text, 5.4px padding), as the Default size had."""
    if factor == 1:
        return css

    def whole(x):
        return int(x + 0.5)

    def one(m):
        font, v = m.group(1), float(m.group(2))
        if v <= 2 or v >= 999:
            return m.group(0)
        if font:
            return f"{font}{max(min(whole(v), 10), whole(v * (1 - (1 - factor) * 0.6)))}px"
        return f"{max(1, whole(v * factor))}px"
    return _PX.sub(one, css)


# Without a compositor (some X11 window managers) a popup can't be see-through, so the room GTK keeps
# around it for the shadow shows up as a black frame: no shadows on popups there.
NO_COMPOSITOR = """
popover > contents, popover.menu > contents, tooltip { box-shadow: none; }
"""

MOTION_OFF = """
* { transition: none; }
"""


def _composited(display) -> bool:
    try:
        return bool(display.is_composited() and display.is_rgba())
    except Exception:                       # noqa: BLE001  (older GTK: assume a compositor)
        return True


class Style:
    def __init__(self, seed: str, font: str = "", reduce_motion: bool = False, scale: float = SIZES["default"]):
        self.font = font
        self.scale = scale
        self.reduce_motion = reduce_motion
        self.palette = theme.palette_for(seed)
        self._provider = Gtk.CssProvider()
        self._motion = Gtk.CssProvider()
        self._fade = None
        self.on_reload = None           # called after the stylesheet changed size, font or colours
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        Gtk.StyleContext.add_provider_for_display(display, self._motion, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        if not _composited(display):
            flat = Gtk.CssProvider()
            load_css(flat, NO_COMPOSITOR)
            Gtk.StyleContext.add_provider_for_display(display, flat, Gtk.STYLE_PROVIDER_PRIORITY_USER + 3)
        self._load(self.palette)
        self.set_reduce_motion(reduce_motion)

    def family(self) -> str:
        if self.font == "system":
            return "sans-serif"
        return f'"{self.font or fonts.TEXT_FAMILY}", sans-serif'

    def _load(self, pal: dict):
        css = CSS.format(FONT=self.family(), ICON=fonts.ICON_FAMILY, EASE=EASE, EASE_STD=EASE_STD, **pal)
        load_css(self._provider, scale_px(css, self.scale))

    def _reloaded(self):
        if self.on_reload:
            self.on_reload()

    def set_scale(self, scale: float):
        if scale != self.scale:
            self.scale = scale
            self._load(self.palette)
            self._reloaded()

    def set_font(self, font: str):
        self.font = font
        self._load(self.palette)
        self._reloaded()

    def set_reduce_motion(self, on: bool):
        self.reduce_motion = on
        css = MOTION_OFF if on else ""
        load_css(self._motion, css)
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-enable-animations", not on)

    def set_seed(self, seed: str, on_frame=None):
        """Recolour to a new seed. Blends over ~300 ms unless motion is reduced."""
        new = theme.palette_for(seed)
        old = self.palette
        self.palette = new
        if self._fade:
            GLib.source_remove(self._fade)
            self._fade = None
        if self.reduce_motion:
            self._load(new)
            if on_frame:
                on_frame()
            self._reloaded()
            return
        steps = {"i": 0}
        n = 8

        def frame():
            steps["i"] += 1
            t = steps["i"] / n
            self._load(theme.mix_palette(old, new, t) if t < 1 else new)
            if on_frame:
                on_frame()
            if t >= 1:
                self._fade = None
                self._reloaded()
                return False
            return True
        self._fade = GLib.timeout_add(36, frame)

    def color(self, role: str) -> str:
        return self.palette.get(role, "#888888")
