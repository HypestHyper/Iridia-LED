# Troubleshooting

**Start with `iridia doctor`.** It checks the daemon, OpenRGB, your devices and zones, monitor
brightness, wallpaper detection and the window, and explains what's wrong. The *Service, Diagnostics*
section of the window runs the same checks.

To see what the daemon is doing: `iridia log -n 40`, or *Settings, Recent log* in the window. For a full
log file, switch on file logging in *Settings, Logging*; for every detail, set `"level": "debug"` under
`logging` in `config.json` (`iridia config edit`).

## Nothing lights up

1. `iridia status`: is OpenRGB connected? If not, `iridia openrgb status` shows what is supposed to
   start its server, and `iridia openrgb start-method daemon` lets Iridia do it (see
   [Installation](Installation.md#setting-up-openrgb)). Iridia keeps retrying and sends colors as soon as
   it connects.
2. Do your devices show up and change color in OpenRGB itself? If not, the problem is between OpenRGB and
   the hardware (permissions, udev rules, `i2c-dev`); see OpenRGB's documentation.
3. Is the zone switched on and its LED count right? Zones without a size (ARGB headers OpenRGB hasn't
   sized) are switched off until you use *Count LEDs*.
4. Is the lights switch off (`iridia lights on`), night mode capping to 0%, or a keybind holding the strip
   off (`iridia zone all normal`)?

## Only part of the strip lights up

The LED count is too low. Use *Count LEDs* on the zone; it can also set OpenRGB's size for ARGB headers.

## Colors are wrong

- **Swapped colors** (red shows as green): the strip expects another channel order. Use *Strip type and
  wiring, Test colors* and change *Color order*. See [Strip types](Strip-Types.md#color-order).
- **Colors drift along the strip:** probably an RGBW strip sent as RGB; see
  [Strip types](Strip-Types.md#rgbw-strips-experimental).
- **Colors differ from the wallpaper:** that's color correction (Palette or Calibrated). Set it to *Off*,
  or mark a color as exact. See [Color correction](Color-Correction.md).
- **Washed out or too strong:** tune the calibration profile, or its saturation floor.
- **The far end turns orange or pink at full brightness:** voltage drop. Set a *Power limit*, or inject
  power at both ends of the strip.

## LEDs show random colors after boot

Usually two things went wrong at once:

- **OpenRGB started too early.** An OpenRGB started before your session could reach the USB and I2C
  devices finds none, and never looks again. `iridia doctor` then says *OpenRGB is running but has
  reported no devices*. Iridia restarts an OpenRGB it started itself (after 30 seconds, then once more
  after 2 minutes). An OpenRGB that something else started, Iridia leaves alone: restart it yourself.
  1.1.0's `iridia-openrgb.service` had this problem; updating removes it.
- **Two OpenRGB instances.** A second one (often OpenRGB's own entry in `~/.config/autostart`) takes the
  controller, and when it exits the LEDs keep whatever it left: a few in random colors. `iridia doctor`
  shows *Other OpenRGB starters*. Keep one: turn off OpenRGB's entry
  (`iridia openrgb hide-autostart`, or the button in the *Service* tab), or let it do the job and run
  `iridia openrgb start-method off`.

To fix it now: `iridia openrgb restart`. OpenRGB's own output, when Iridia started it, is in
`~/.local/share/iridia/openrgb.log`; OpenRGB also keeps logs in `~/.config/OpenRGB/logs/`.

## A device shows as missing

When a device OpenRGB used to report disappears, Iridia restarts OpenRGB's server to bring it back, at
most twice, if Iridia started that server. If it's still missing (unplugged, or renamed by an OpenRGB
update), switch it off on the Devices tab so it stops being reported.

## The wallpaper isn't detected

- `iridia status` shows the wallpaper and which tool found it; `iridia doctor` lists what was tried.
- After changing wallpaper tools: *Settings, Reset wallpaper detection cache* (or
  `iridia wallpaper --reset-detection`).
- As a service, the daemon may not see your session. Iridia looks for it by itself; if it still fails,
  add `systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP` to your
  compositor's startup, use [UWSM](https://github.com/Vladimir-csp/uwsm), or start the daemon from your
  compositor instead (see [Start at login](Start-at-Login.md)).
- Fallbacks: point `wallpaper.watch_folder` at the folder your wallpaper tool uses, or set
  `wallpaper.manual_path` (`iridia wallpaper PATH`).

## Brightness doesn't follow the monitor

Run `ddcutil detect`. If it finds nothing, your monitor or cable may not support DDC/CI (laptop panels and
many docks don't), DDC/CI may be off in the monitor's menu, or you need to be in the `i2c` group:
`sudo usermod -aG i2c $USER`, then log out and in.

## The window doesn't open

GTK 4 for Python is missing, or belongs to another Python. `iridia doctor` has a *Window (GTK 4)* line.
Install the packages for your distribution (see [Installation](Installation.md#installing-the-dependencies-yourself))
and run the installer again. GTK 4.6 or newer is needed.

## The daemon doesn't start at login

`iridia doctor` shows how the running daemon was started and what is set up to start it. If
`iridia-daemon.service` is enabled but never starts, your session doesn't activate
`graphical-session.target` (Hyprland without UWSM, for example); doctor says so. Add the daemon to your
compositor's autostart instead (see [Start at login](Start-at-Login.md)) and disable the service:
`systemctl --user disable iridia-daemon.service`.

## LEDs stay on when the PC sleeps

Sleep detection needs systemd-logind (or elogind) and `gdbus` or `dbus-monitor`. It works however the
daemon was started. Check `iridia log` for a line about sleep detection.

## Animations lag behind, or keep going after a change

With OpenRGB 1.0, Iridia sends animation frames over a second connection and waits for OpenRGB to
write each one, so a slow controller gets fewer frames instead of falling behind. The log says so:
`iridia log | grep -i frame` shows "Animation frames go over their own OpenRGB connection", and a
controller that can't keep up gets a line like "can't keep up with 60 fps ..., using 30".

- `iridia animations status` shows the frames per second each device really gets and how long a frame
  takes. If it warns that the daemon runs older code than what's installed, run `iridia restart`.
- If the log says OpenRGB doesn't speak SDK protocol 6, OpenRGB is older than 1.0. Frames then go over
  the main connection; updating OpenRGB is the fix if a slow controller still lags.
- A lower frame rate (Settings, Animations) helps slow controllers too: a Razer Chroma ARGB controller
  with 480 LEDs needs about 19 ms per frame, so 30 is its limit.

## Reporting a bug

Please include the output of `iridia doctor` and `iridia log -n 100`, your distribution and desktop, and
your devices as `iridia status` lists them.
