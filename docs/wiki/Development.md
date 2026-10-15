# Development

## Running from source

```bash
git clone https://github.com/HypestHyper/Iridia-LED.git
cd Iridia-LED
python3 -m venv --system-site-packages .venv   # sees your distribution's GTK 4 bindings
.venv/bin/pip install -e .
.venv/bin/iridia-daemon      # terminal 1 (stop the installed daemon first: iridia daemon stop)
.venv/bin/iridia-gui         # terminal 2
```

Python 3.8 or newer. Only one daemon can run per user, so stop an installed one before starting yours.

## Project layout

```
iridia/
  daemon.py          the daemon: main loop, rendering, every IPC command
  openrgb_ctl.py     OpenRGB connection, device modes, sending colors
  wallpaper.py       wallpaper detection backends
  colors.py          color extraction engines
  patterns.py        the static patterns (pure functions)
  calibration.py     calibration profiles
  palette.py         the 48 color palette
  ddc.py             monitor brightness through ddcutil
  sleepwatch.py      suspend and resume through logind
  config.py          config.json with defaults and repair
  layout.py          the Layout tab's model (layout.json)
  setups.py          setups and automatic backups
  wallcache.py       extracted colors and picks per wallpaper
  customcolors.py    saved and exact colors
  ipc.py, client.py  the Unix socket protocol and its client
  cli.py             the iridia command
  diagnostics.py     iridia doctor
  autostart.py       autostart lines per compositor
  theme.py           Material color scheme from a seed color
  gui.py             entry point of the window
  i18n.py            gettext setup and the language list
  ui/                the GTK 4 window
    app.py             window, tabs, status polling, Status/Settings/Service
    zonecard.py        Devices tab cards
    layout_tab.py      Layout tab
    keybinds_tab.py    Keybinds tab
    colorpicker.py     color picker
    calibration_editor.py
    widgets.py         Material 3 Expressive building blocks
    style.py           CSS generated from the color scheme
    dialogs.py, fonts.py, serial.py, icon_names.py
  data/              icons, bundled fonts, compiled translations (locale/)
scripts/
  build_fonts.py     rebuilds the bundled font subsets
  build_locales.py   extracts strings and compiles the translations
po/                  translation sources (iridia.pot and one .po per language)
tests/               unit tests (pytest)
install.sh, uninstall.sh
docs/wiki/           this wiki
systemd/             reference user service (the installer writes its own)
```

## The IPC protocol

The daemon listens on `$XDG_RUNTIME_DIR/iridia-UID.sock` (mode 600). Each connection sends one JSON
object ending in a newline and gets one JSON object back:

```bash
echo '{"cmd": "status"}' | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/iridia-$(id -u).sock
echo '{"cmd": "zone_action", "target": "Desk back", "actions": ["color", "ff0000"]}' \
  | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/iridia-$(id -u).sock
```

Every reply has `"ok": true` or `"ok": false` with an `"error"`. From Python, use `iridia.client.Client`.
The commands are dispatched in `Daemon.handle_command()` in `daemon.py`; the main groups are:

| Group | Commands |
| --- | --- |
| Info | `ping`, `status`, `get_log`, `zone_targets` |
| Zones | `set_zone_enabled`, `set_zone_pattern`, `set_zone_pattern_params`, `set_zone_mode`, `set_zone_name`, `set_zone_colors`, `set_zone_led_count`, `set_zone_brightness_*`, `set_zone_invert`, `set_zone_gamma`, `set_zone_calibration_profile`, `set_zone_strip`, `set_all` |
| Colors | `set_wallpaper_color`, `clear_wallpaper_color`, `forget_all_wallpaper_colors`, `add_custom_color`, `remove_custom_color`, `set_color_exact`, `preview_color` |
| Tools | `identify`, `led_probe`, `test_colors`, `resize_zone`, `zone_action`, `lights`, `freeze`, `set_night`, `set_sleep` |
| Setups | `setup_list`, `setup_save`, `setup_load`, `setup_delete`, `setup_rename`, `setup_export`, `setup_import`, `setup_restore_backup` |
| Daemon | `refresh_wallpaper`, `reset_detection`, `reload_config`, `reload_calibration`, `restart`, `reconnect_openrgb`, `restart_openrgb_server`, `shutdown` |

## The window

GTK 4 through PyGObject, drawn in a Material 3 Expressive style: the color scheme is generated from the
current LED color (`theme.py`) and applied as CSS (`style.py`); custom widgets draw with cairo
(`widgets.py`). Calls to the daemon from the window go through one worker thread (`ui/serial.py`) so
they arrive in order.

The icon font is a subset of Material Symbols Rounded and the text font is Google Sans Flex, both in
`iridia/data/fonts/`. To use another icon, add its name to `iridia/ui/icon_names.py` and rebuild the
subset with `scripts/build_fonts.py` (instructions inside).

## Translations

Every string in the window goes through `_()` from `iridia/i18n.py` (`ngettext()` for plurals,
`pgettext()` when one English word needs different translations). The command line, the daemon and
`iridia doctor` are not translated.

The sources are in `po/`; the compiled `.mo` files in `iridia/data/locale/` are committed, so users
need nothing extra. After changing strings in the window:

```bash
pip install babel
python scripts/build_locales.py --update   # refresh po/iridia.pot and merge new strings into each .po
# translate the new entries in po/*.po
python scripts/build_locales.py            # check placeholders and compile the .mo files
```

The strings in the code are American English; Proper English (`en_GB`, the default) only changes the spelling. Untranslated strings fall back to the American text. A placeholder like `{n}` may be left out of a
translation, but a translation can't add one that the English string doesn't have; the build script
checks this. To add a language, copy `po/iridia.pot` to `po/<code>.po`, set its `Language:` header,
and add the code and its name to `LANGUAGES` in `iridia/i18n.py`. Language names are shown in their
own language and are not translated.

## Tests and checks

The pure parts (patterns, colors, layout geometry, config repair, calibration, IPC) and the daemon's
command handling and rendering (with OpenRGB and DDC replaced by fakes) have unit tests
that need no hardware or GTK. `tests/fakes/` holds stand-ins for `openrgb` (a real process that answers
the SDK handshake with zero devices, stays silent, or crashes) and `systemctl`, so starting, supervising
and restarting OpenRGB is tested end to end. CI runs everything on Python 3.8 to 3.13, along with ruff
and shellcheck:

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/ruff check iridia scripts tests
shellcheck install.sh uninstall.sh
```

## Testing without hardware

The daemon runs without OpenRGB (it keeps retrying), and the window works against it, so most of the
interface can be developed without LEDs. To run the window without a display, use Xvfb:

```bash
GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a .venv/bin/iridia-gui
```

## Contributing

Bug reports and pull requests are welcome. For a bug, please include `iridia doctor`,
`iridia log -n 100`, your distribution and desktop. Keep text in the app and docs plain and short, and
keep the daemon light: it runs all day.
