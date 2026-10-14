"""Material 3 Expressive look for GTK 4, generated from the wallpaper palette.

The whole style is one CSS string built from the palette. Changing the LED
colour only swaps the CSS (optionally blended over a few frames), so the window
recolours in place without rebuilding anything.
"""

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
headerbar windowcontrols button {{ min-height: 28px; min-width: 28px; padding: 2px; background: {SURFACE_CONTAINER_HIGH};
  color: {ON_SURFACE_VARIANT}; }}
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
.mono {{ font-family: monospace; font-size: 12.5px; }}
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
button.toggled, button.filled.toggled {{ background: {PRIMARY}; color: {ON_PRIMARY}; border-radius: 10px; }}

/* connected button group (Expressive): inner corners small, outer round, selected item turns into a pill */
.group > button {{ border-radius: 6px; margin: 0 1px; background: {SECONDARY_CONTAINER};
  color: {ON_SECONDARY_CONTAINER}; min-height: 36px; padding: 0 14px; font-size: 13px;
  transition: border-radius 220ms {EASE_STD}, background-color 200ms {EASE_STD}; }}
.group > button:first-child {{ border-top-left-radius: 18px; border-bottom-left-radius: 18px; }}
.group > button:last-child {{ border-top-right-radius: 18px; border-bottom-right-radius: 18px; }}
.group > button:checked {{ background: {PRIMARY}; color: {ON_PRIMARY}; border-radius: 18px; }}
button.filter {{ border-radius: 8px; padding: 4px 12px; min-height: 24px; background: transparent;
  border: 1px solid {OUTLINE_VARIANT}; color: {ON_SURFACE_VARIANT}; font-weight: 500; box-shadow: none; }}
button.filter:hover {{ background: alpha({ON_SURFACE}, 0.08); }}
button.filter:checked {{ background: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER};
  border-color: {SECONDARY_CONTAINER}; }}
.group > button:checked .icon {{ font-variation-settings: "FILL" 1, "wght" 500, "opsz" 24; }}
.group > button:active {{ border-radius: 4px; }}

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
  min-width: 4px; min-height: 36px; margin: -12px -2px; transition: min-width 200ms {EASE_STD}; }}
scale slider:active {{ min-width: 2px; }}
.card-inner scale slider {{ box-shadow: 0 0 0 4px {SURFACE_CONTAINER_HIGH}; }}

checkbutton {{ padding: 4px 0; }}
checkbutton check, checkbutton radio {{ background: transparent; border: 2px solid {ON_SURFACE_VARIANT}; box-shadow: none;
  min-width: 16px; min-height: 16px; color: {ON_PRIMARY}; }}
checkbutton check:checked, checkbutton radio:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}

scrollbar {{ background: transparent; border: none; }}
scrollbar slider {{ background: {OUTLINE_VARIANT}; border-radius: 999px; min-width: 6px; min-height: 6px; border: none; }}
scrollbar slider:hover {{ background: {OUTLINE}; }}

tooltip {{ background: {INVERSE_SURFACE}; color: {INVERSE_ON_SURFACE}; border-radius: 8px; }}
tooltip * {{ color: {INVERSE_ON_SURFACE}; }}

.snackbar {{ background: {INVERSE_SURFACE}; color: {INVERSE_ON_SURFACE}; border-radius: 14px; padding: 12px 16px;
  margin: 18px; box-shadow: 0 6px 20px rgba(0,0,0,0.45); }}
.snackbar button {{ color: {INVERSE_PRIMARY}; background: transparent; min-height: 32px; }}
.snackbar label {{ color: {INVERSE_ON_SURFACE}; }}
"""

MOTION_OFF = """
* { transition: none; }
"""


class Style:
    def __init__(self, seed: str, font: str = "", reduce_motion: bool = False):
        self.font = font
        self.reduce_motion = reduce_motion
        self.palette = theme.palette_for(seed)
        self._provider = Gtk.CssProvider()
        self._motion = Gtk.CssProvider()
        self._fade = None
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        Gtk.StyleContext.add_provider_for_display(display, self._motion, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        self._load(self.palette)
        self.set_reduce_motion(reduce_motion)

    def family(self) -> str:
        if self.font == "system":
            return "sans-serif"
        return f'"{self.font or fonts.TEXT_FAMILY}", sans-serif'

    def _load(self, pal: dict):
        css = CSS.format(FONT=self.family(), ICON=fonts.ICON_FAMILY, EASE=EASE, EASE_STD=EASE_STD, **pal)
        load_css(self._provider, css)

    def set_font(self, font: str):
        self.font = font
        self._load(self.palette)

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
                return False
            return True
        self._fade = GLib.timeout_add(36, frame)

    def color(self, role: str) -> str:
        return self.palette.get(role, "#888888")
