# Changelog

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
