# Troubleshooting

**Start with `iridia doctor`.** It checks the daemon, OpenRGB, your devices and zones, monitor
brightness, wallpaper detection and the window, and explains what's wrong. The *Service, Diagnostics*
section of the window runs the same checks.

To see what the daemon is doing: `iridia log -n 40`, or *Settings, Recent log* in the window. For a full
log file, switch on file logging in *Settings, Logging*; for every detail, set `"level": "debug"` under
`logging` in `config.json` (`iridia config edit`).

## Nothing lights up

1. `iridia status`: is OpenRGB connected? If not, start its SDK server (see
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

## A device shows as missing

When a device OpenRGB used to report disappears, Iridia restarts OpenRGB's server to bring it back, at
most twice. If it's still missing (unplugged, or renamed by an OpenRGB update), switch it off on the
Devices tab so it stops being reported.

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

`systemctl --user status iridia-daemon.service`. If the service is enabled but never starts, your
session doesn't activate `graphical-session.target`; add the daemon to your compositor's autostart
instead (see [Start at login](Start-at-Login.md)).

## LEDs stay on when the PC sleeps

Sleep detection needs systemd-logind and `gdbus`. Check `iridia log` for a line about sleep detection.

## Reporting a bug

Please include the output of `iridia doctor` and `iridia log -n 100`, your distribution and desktop, and
your devices as `iridia status` lists them.
