<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/iridia-dark.svg">
    <img alt="Iridia" src="docs/iridia-light.svg" width="140">
  </picture>
</p>

<h1 align="center">Iridia</h1>

<p align="center">
  Sets RGB device colors from the current wallpaper on Linux, through OpenRGB.
</p>

<p align="center">
  <img alt="Version 1.1.0" src="https://img.shields.io/badge/version-1.1.0-7c5cff">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue">
  <img alt="Linux" src="https://img.shields.io/badge/platform-Linux-informational">
  <img alt="Python 3.8+" src="https://img.shields.io/badge/python-3.8%2B-3776AB">
  <img alt="GTK 4" src="https://img.shields.io/badge/GTK-4-4A86CF">
  <img alt="Works with OpenRGB" src="https://img.shields.io/badge/works%20with-OpenRGB-e0457b">
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#features">Features</a> ·
  <a href="docs/wiki/Home.md">Wiki</a> ·
  <a href="docs/wiki/Troubleshooting.md">Troubleshooting</a>
</p>

---

Iridia extracts colors from the current wallpaper and sends them to RGB devices (LED strips, RAM,
keyboards and so on) through [OpenRGB](https://openrgb.org/). LED brightness can follow the monitor's
brightness over DDC/CI.

It consists of a background daemon, a command line tool and a GTK 4 settings window. The daemon handles
wallpaper detection, color extraction and sending colors to OpenRGB; the window and the command line only
change its settings. Each OpenRGB zone can be configured separately (pattern, colors, brightness, color
correction). Patterns are static; nothing is animated.

> **Note:** This project was written almost entirely by an AI assistant, with direction and testing by the author. It has been tested mainly on CachyOS with Hyprland,
> and a Razer Chroma ARGB controller driving WS2812B strips. Other hardware,
> strip types and desktops are supported in the code but have seen less real-world testing.

## Features

**Wallpaper**

- Finds the wallpaper on Hyprland (hyprpaper, swww/awww, swaybg), Sway, niri, GNOME, KDE, XFCE,
  Cinnamon, MATE, feh, nitrogen, xwallpaper, waypaper, Caelestia and Noctalia, or uses a watched folder.
- Three color extraction methods (Caelestia's scheme, Material Color Utilities, Pillow).
- Color picks are stored per wallpaper and restored when that wallpaper is used again.

**Zones and patterns**

- Patterns: solid, gradient, segments, center out, edges in, alternating, and painted LED by LED.
- Strip preview with adjustable color stops; reverse and mirror.
- Saved colors, recently used colors, and colors marked as exact (sent without correction).
- An *Everything* card that changes all zones at once.

**Layout**

- A 2D drawing of the strips with their current colors, one dot per LED, scaled by LEDs per metre.
- Strips can be moved, bent, turned, flipped, cloned and hidden; LEDs can be painted on the drawing.
- *Find LEDs* lights a single LED on the physical strip, to locate corners.

**Brightness and time**

- Brightness from the monitor (DDC/CI) or set manually, with a range and an inverted mode.
- Night mode (a brightness cap between two times), LEDs off during suspend.
- Freeze: ignore wallpaper changes until unfrozen.

**Strip types and correction**

- Addressable 5V (WS2812B, SK6812), 12V grouped (WS2811, COB), plain 12V RGB, and RGBW (experimental).
- Color order setting with a test pattern, and an optional power limit.
- Color correction: a 48 color palette, or calibration profiles that can be edited.

**Other**

- `iridia zone` commands for keyboard shortcuts (on/off, color, brightness; running the same command
  again reverts it). The window shows the config line for several compositors and desktops.
- Setups: save and load the whole configuration under a name, with automatic backups.
- Starts OpenRGB's server at login when nothing else does.
- `iridia doctor` for diagnostics, and a log viewer in the window.

**Languages**

The window uses Proper English (British spelling) by default. Settings, Appearance, Language also
has American English and three joke languages: Posh English (Victorian), Pirate, and Français, which
is random French phrases with no relation to what the buttons do. The command line, the log and
`iridia doctor` use American spelling.

## Install

### Requirements

| | |
| --- | --- |
| **OpenRGB** | talks to your hardware ([openrgb.org](https://openrgb.org/)); Iridia starts its server |
| **Python 3.8+** with `venv` | Iridia installs into its own virtual environment |
| **GTK 4.6+, PyGObject, pycairo** | for the window (the daemon runs without them) |
| **ddcutil** *(optional)* | to follow your monitor's brightness |

### Quick install

```bash
git clone https://github.com/HypestHyper/Iridia-LED.git
cd Iridia-LED
bash scripts/install.sh
```

The installer finds what's missing and offers to install it with your package manager (pacman, apt,
dnf, zypper, xbps or apk), installs Iridia into `~/.local/share/iridia-venv`, adds the app to your
launcher, sets it up to start at login and starts it. Nothing of Iridia itself goes outside your home
folder. Add `--yes` to skip the questions, `--no-deps` to leave system packages alone.

<details>
<summary><b>Installing the dependencies by hand</b></summary>

| Distribution | Command |
| --- | --- |
| Arch, CachyOS, EndeavourOS, Manjaro | `sudo pacman -S --needed python gtk4 python-gobject python-cairo openrgb ddcutil` |
| Debian, Ubuntu, Mint, Pop!_OS | `sudo apt install python3 python3-venv gir1.2-gtk-4.0 python3-gi python3-gi-cairo openrgb ddcutil` |
| Fedora | `sudo dnf install python3 gtk4 python3-gobject python3-cairo openrgb ddcutil` |
| openSUSE | `sudo zypper install python3 typelib-1_0-Gtk-4_0 python3-gobject python3-gobject-cairo python3-cairo OpenRGB ddcutil` |
| Void | `sudo xbps-install python3 gtk4 python3-gobject python3-cairo openrgb ddcutil` |
| Alpine | `sudo apk add python3 gtk4.0 py3-gobject3 py3-cairo ddcutil` (OpenRGB from source) |

Then run `bash scripts/install.sh --no-deps`. If your release has no OpenRGB package, get it from
[openrgb.org](https://openrgb.org/).

</details>

### Before the first run

1. **OpenRGB:** install it and check that your devices show up in it. Iridia starts OpenRGB's server
   for you (see [Setting up OpenRGB](docs/wiki/Installation.md#setting-up-openrgb)).
2. **For monitor brightness** (optional): `sudo usermod -aG i2c $USER`, log out and in, and check that
   `ddcutil detect` finds your monitor.

Then open **Iridia** from your app launcher. The [installation guide](docs/wiki/Installation.md)
covers OpenRGB permissions, the optional Material engine, updating and uninstalling.

## Quick start

1. On the **Devices** tab, open a zone and click **Identify** to see which strip it is, then rename it.
2. **Count LEDs** to set its real length.
3. Pick a pattern and colors. From now on it follows your wallpaper.
4. Draw it on the **Layout** tab, and add a [keybind](docs/wiki/Keybinds.md) if you like.

```bash
iridia status                                      # what's going on
iridia doctor                                      # what's wrong, if anything
iridia zone "Desk back" on color ff0000 bright 40  # a keybind: run it again to switch back
iridia lights toggle                               # everything off and on
iridia setup save "Evening"                        # keep this look
```

The daemon runs in the background and starts at login; the window only changes its settings.

## Documentation

The [wiki](docs/wiki/Home.md) explains everything Iridia can do and how it works.

| | |
| --- | --- |
| [Installation](docs/wiki/Installation.md) | Requirements, distributions, OpenRGB and DDC setup, updating |
| [Getting started](docs/wiki/Getting-Started.md) | The first run and a tour of the window |
| [Devices, patterns and colors](docs/wiki/Devices-and-Patterns.md) | Zones, patterns, colors, painting, brightness |
| [Layout](docs/wiki/Layout.md) | Drawing and painting your strips |
| [Strip types](docs/wiki/Strip-Types.md) | WS2812B, WS2811, 12V RGB, RGBW, color order, power limit |
| [Color correction](docs/wiki/Color-Correction.md) | Palette, calibration profiles, exact colors |
| [Keybinds](docs/wiki/Keybinds.md) | Commands and config lines for every desktop |
| [Night mode, sleep and freeze](docs/wiki/Night-Sleep-and-Freeze.md) | Time-based dimming and sleep |
| [Setups and backups](docs/wiki/Setups-and-Backups.md) | Saving and switching whole setups |
| [Start at login](docs/wiki/Start-at-Login.md) | systemd, compositor lines, XDG autostart |
| [Command line](docs/wiki/Command-Line.md) | Every `iridia` command |
| [Configuration](docs/wiki/Configuration.md) | The settings files |
| [How it works](docs/wiki/How-It-Works.md) | The daemon, the color pipeline, resilience |
| [Troubleshooting](docs/wiki/Troubleshooting.md) and [FAQ](docs/wiki/FAQ.md) | When something isn't right |
| [Development](docs/wiki/Development.md) | Project layout, IPC protocol, contributing |

## Contributing

Bug reports and pull requests are welcome. For a bug, please include the output of `iridia doctor` and
`iridia log -n 100`, your distribution and desktop, and your devices as `iridia status` lists them. See
[Development](docs/wiki/Development.md) to run Iridia from source.

## License

[MIT](LICENSE).

Bundled fonts: [Material Symbols](https://github.com/google/material-design-icons) (Apache License 2.0)
and [Google Sans Flex](https://fonts.google.com/specimen/Google+Sans+Flex) (SIL Open Font License 1.1);
their licenses are in `iridia/data/fonts/`. Iridia is not affiliated with OpenRGB.
