# Changelog

## Unreleased

- **Sensors.** A part of a strip (or the whole strip) can show CPU or GPU temperature and load,
  memory use, disk temperature or any other temperature sensor: as a level bar, as a color, or as a
  bar in the reading's color, cool to hot or in your colors, with an optional flash above a reading.
  Several sensors fit on one strip as separate parts. Only sensors a strip shows are read, once a
  second, straight from the kernel, and smoothed; NVIDIA readings use one `nvidia-smi` process only
  while shown. `iridia sensors` lists them; `iridia split NAME part 2 sensor cpu_temp` sets one.

- **Lock and idle.** Settings, *Lock and idle*: keep, dim or turn off the LEDs when the screen locks,
  and after a number of minutes without input. They fade out over 2 seconds and back in half a second;
  *Try it* shows it for 5 seconds, and a strip can stay lit (*Stay lit when the screen locks or you're
  away*, under its Brightness). Iridia sees locking through logind, ScreenSaver signals and screen
  lockers such as hyprlock and swaylock, and idle time on GNOME, KDE and X11, with nothing to set up.
  For Hyprland, Sway and the like, `iridia idle on|off` from hypridle or swayidle (the window and
  `iridia session hooks` have the lines). `iridia session` shows and changes it all.

- **Window size.** Settings, Appearance, Size: Compact, Default, Large or Automatic. Default is about
  10% smaller than before and Large is the old size; Automatic is Compact in a window narrower than
  900 pixels. Ctrl+minus and Ctrl+plus change it, Ctrl+0 goes back to Automatic. Text shrinks less
  than the rest and never below 10 pixels.
- **Window buttons** in the same Material icons as the rest of the window: a round highlight under the
  pointer, close turns red, maximize turns into restore. They follow your desktop's button layout
  (side and order), and Settings, Appearance, *Window buttons* hides them.
- **Narrow windows.** Only the tab on show sets how narrow the window can be, long help text wraps,
  and rows of buttons wrap onto a second line. Below 760 pixels the tabs and the bottom buttons show
  only their icons (the words become tooltips), and if the tabs still don't fit they scroll sideways
  with arrows. The window now goes down to about 600 pixels wide.
  Below 960 pixels the Layout tab's side panel moves under the canvas.
- **LED numbers** under every strip preview (1, every few LEDs, and the last LED, which is the strip's
  real count), so you can see which LED is which.
- Popups no longer show a black frame on X11 without a compositor.
- **Split a strip into parts.** *Advanced: split this strip, set single LEDs* on a zone card: add
  dividers (drag them, they snap to whole LEDs) and let each part show the strip's own look, a static
  pattern of its own, an animated effect of its own, or nothing. A static strip can have one animated
  part, and an animated strip can keep static parts. **Space evenly** splits the parts in whole LEDs
  with the same notes and warnings as below. Changing the LED count moves the dividers along.
- **Single LEDs.** Set any LED to a color or off, over everything else (a fixed LED between two bars):
  click or drag over the strip in the same panel.
- `iridia split NAME ...` does both from the command line (`even 3`, `at 28 55`, `part 2 effect comet`,
  `led 27 ffffff`, `join`, ...).
- **Space evenly** for the Segments pattern: the layout editor shows how many LEDs each color gets,
  splits them evenly in whole LEDs, says when the count doesn't divide evenly, and warns when parts are
  only 1 or 2 LEDs apart.

## 1.2.1

**Iridia's own OpenRGB client.** With OpenRGB 1.0, Iridia now talks to OpenRGB entirely with SDK
protocol 6, through its own client, instead of openrgb-python plus a second connection for animation
frames.

- Every update waits until OpenRGB has applied it: static colors, mode changes and zone resizes too,
  not only animation frames. Nothing can pile up, and when OpenRGB refuses an update the log says so.
- One connection to OpenRGB instead of two.
- OpenRGB announces changes, and Iridia follows them at once: a new device list (a device plugged in
  or a rescan), and a device another program changed. If something switches a device out of Direct
  mode, Iridia puts it back on its next update.
- Zones whose size OpenRGB only uses for the controller's own effects count as one LED, as in OpenRGB.
- `iridia status` and `iridia doctor` say whether Iridia talks protocol 6 or, with OpenRGB before 1.0,
  uses openrgb-python as before.

## 1.2.0

**Animations.** Iridia is no longer static only. Static patterns stay as they were, and stay the default.

- Seven effects per zone: Breathing, Comet, Fill, Embers, Rainbow, Rainbow vomit and Color cycle. They use
  the zone's colors (wallpaper, saved or exact colors; the rainbows ignore them), and brightness, night
  mode, color correction, color order, RGBW and the power limit apply to every frame. Embers drift
  through the picked colors, or glow in fire colors. Colors blend as light does.
- On the Devices tab, Pattern switches between Static and Animated; each effect shows its settings with
  their values, changes apply live, and the strip preview animates. The Everything card sets an effect on
  every zone and keeps zones with the same effect in step (Sync). Picking a static pattern anywhere
  (the Layout tab, painting, the Everything card, the command line) stops the effect.
- Follow the layout: an effect runs through the room across every strip that follows it, using where the
  LEDs are on the Layout tab, in the direction set with a dial. The Layout tab animates live while open.
- Settings, Animations: run animations (off shows each animated zone's first color), frame rate (15, 30,
  60), pause or slow animations during night mode.
- Breathing's minimum and maximum are relative to the zone's brightness. When the monitor's brightness
  changes, LEDs glide to it over about 0.3 s, for static patterns too.
- Lights off, sleep, Identify, Count LEDs, Test colors, color previews and keybind colors pause the
  animation on that zone, and it resumes afterwards.
- `iridia zone TARGET effect NAME [--speed N --min N --max N --param KEY=VALUE] [--save]`,
  `iridia zone TARGET effect static`, `iridia animations pause|resume|toggle|status`; `iridia status`
  shows each zone's effect. The Keybinds tab has "Effect" for strips and "Pause / resume animations".

**Keeping up with the hardware.** OpenRGB 1.0 writes every colour update in turn at the controller's
pace and only tells SDK protocol 6 clients when one is done. Iridia sends animation frames over a second,
protocol 6 connection, one whole-device update at a time, each once the one before is written: a slow
controller gets fewer frames (the rate drops by itself, and the log says so) instead of a queue, so a
change shows at once. With OpenRGB before 1.0, frames go over the main connection.

- One animation thread, only while something animates (static setups stay as idle as before). Each
  device is paced on its own; unchanged frames aren't sent; frames are packed straight into SDK packets.
- `iridia animations status` shows each device's frames per second and frame time, and warns when the
  daemon still runs older code than what's installed. The log notes every effect change.
  `scripts/bench_animations.py` measures the CPU cost.
- Changes reach the LEDs right away instead of at the daemon's next half-second tick.
- Iridia puts each device in Direct mode once per connection even when OpenRGB already reports it,
  since another client or the controller's own effect can change it without OpenRGB noticing.

**Layout**

- Cuts for a strip that was cut and joined again with a wire: the wire is drawn dashed, the piece after
  a cut can be dragged anywhere (or its wire length set), and Join again removes the cut.
- Parts of a strip can be left out of the drawing. Clones can have their own names. A toolbar button
  hides strip names and LED numbers, and the bend knobs no longer carry B1, B2... tags.

**Window and install**

- Sliders and number boxes don't react to the mouse wheel (it scrolls the page), so scrolling past
  them never changes a setting.
- The installer links `iridia` and `iridia-gui` into `~/.local/bin` and says how to add that folder to
  the `PATH` when it's missing (fish included).
- When ddcutil is installed, the installer sets up I2C access for monitor brightness, doing only what's
  missing: the `i2c` group (created if needed) with you in it, a udev rule giving that group the I2C
  devices, and the `i2c-dev` module now and at every boot. It asks first (`--yes` doesn't, `--no-deps`
  leaves it alone) and reminds you to log out and in once.

## 1.1.1

**OpenRGB at boot.** On some machines the LEDs showed random colors after a reboot: 1.1.0's
`iridia-openrgb.service` started OpenRGB with the user manager, before the session could reach the
hardware, so it found no devices and never looked again, and a second OpenRGB from an autostart entry
then fought it over the controller.

- New setting `openrgb.start_method`, picked in the installer, in the window (*Service, Start OpenRGB*)
  or with `iridia openrgb start-method`: `daemon` (default: the Iridia daemon starts OpenRGB inside your
  session), `systemd` (`iridia-openrgb.service`, now started with the graphical session) or `off`.
  It replaces `openrgb.start_server`; `false` there becomes `off`. `iridia openrgb enable` and `disable`
  still work.
- Updating removes 1.1.0's `iridia-openrgb.service` (only if Iridia wrote it) unless you pick `systemd`.
- The daemon remembers the OpenRGB it started (`$XDG_RUNTIME_DIR/iridia-openrgb.pid`), reuses it after a
  daemon restart, starts it again if it exits (after 5 s, 15 s, 60 s, then it stops and says so), passes
  `openrgb.port` on as `--server-port`, and writes its output to `~/.local/share/iridia/openrgb.log`.
- When OpenRGB answers but reports no devices for 30 seconds, Iridia restarts it, then once more after
  2 minutes, if Iridia started it. It never restarts an OpenRGB it didn't start on its own, including
  for a missing device; *Restart OpenRGB server* can still replace a headless one when you click it.
- Iridia never starts OpenRGB while another one runs or is set to start. `iridia doctor` and the window
  name the other starter; *Turn off OpenRGB's own autostart* (`iridia openrgb hide-autostart`) adds
  `Hidden=true` to its autostart entry. Doctor also says when the OpenRGB window is open with its SDK
  server off.
- The port is probed once instead of on every retry (each probe left an error in OpenRGB's log).

**Without systemd, or started from your compositor.**

- The installer asks how the daemon starts at login: `--autostart=systemd|xdg|compositor|none`. The
  default is systemd only when your session reaches `graphical-session.target`, else your compositor's
  line (printed for you), else XDG autostart.
- `iridia doctor` shows how the daemon was started ("started by Hyprland", "systemd", ...), no longer
  shows an enabled but inactive `iridia-daemon.service` as a problem while the daemon runs, warns when
  that service can never start because the session doesn't reach `graphical-session.target`, and notes
  when the daemon is set to start from more than one place.
- A daemon started outside systemd turns on file logging, since there is no journal (unless you set
  `logging.enabled` yourself).
- `iridia openrgb status` shows the start method, whether Iridia started the running OpenRGB, and what
  else starts it.

**Other**

- A command naming a zone a device doesn't have (a keybind typo, a zone OpenRGB renamed) gets a plain
  "zone not found" reply instead of being logged as a failed command.
- The daemon's socket is created with mode 600 from the start, instead of being tightened right after
  it appears.
- Unit tests (`tests/`), including the daemon's commands and rendering, and OpenRGB's start and restart
  rules against a fake `openrgb` and `systemctl`. A GitHub Actions workflow runs them on Python 3.8 to
  3.13, with ruff and shellcheck. `pip install -e ".[dev]"` installs the tools.

## 1.1.0

- Iridia starts OpenRGB's server: with systemd through a user service, `iridia-openrgb.service`, set up by
  the installer; without systemd the daemon runs `openrgb --server` itself when it can't reach it. It
  leaves OpenRGB alone when something else already starts it, and never runs a second instance.
  `iridia openrgb enable`, `disable` and `status`, and a switch in the Service tab. Works with the
  Flatpak; `openrgb.server_command` for an AppImage.
- `iridia doctor` says what starts OpenRGB at login; it no longer shows a unit that doesn't exist as
  "inactive".
- The window uses British spelling by default. American English can be picked in Settings,
  Appearance, Language; switching restarts the window.
- The command line, the log and `iridia doctor` keep American spelling.
- `install.sh` and `uninstall.sh` moved from `scripts/` to the top folder: `bash install.sh`.
- The app id is now `io.github.HypestHyper.Iridia` (the window class for window rules). The old
  launcher is removed when the service is installed again.

## 1.0.0

The first public release.

- Wallpaper colors on your RGB devices through OpenRGB, with wallpaper detection for Hyprland, Sway,
  niri, GNOME, KDE, XFCE, Cinnamon, MATE, X11 window managers, Caelestia, Noctalia and waypaper.
- Monitor brightness sync over DDC/CI, night mode, LEDs off during sleep, freeze.
- Static patterns (solid, gradient, segments, center out, edges in, alternating, painted) with color
  stops, reverse and mirror; color picks remembered per wallpaper.
- GTK 4 window in the Material 3 Expressive style: Status, Devices, Layout, Keybinds, Settings and
  Service tabs.
- Layout tab: strips drawn at their real length with bends, clones, painting and Find LEDs.
- Strip types (addressable 5V, 12V grouped, one color, RGBW), color order, power limit.
- Color correction: palette, calibration profiles with an editor, exact colors.
- Keybind commands that combine actions and switch back on a second press.
- Setups with automatic backups, a full command line, `iridia doctor`.
