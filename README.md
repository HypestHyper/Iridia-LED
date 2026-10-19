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
  <img alt="Version 1.3.4" src="https://img.shields.io/badge/version-1.3.4-7c5cff">
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

Iridia takes the colors of your wallpaper and puts them on your RGB devices (LED strips, RAM,
keyboards, fans and so on) through [OpenRGB](https://openrgb.org/). Change the wallpaper and the lights
follow.

A small background service does the work; a GTK 4 window and an `iridia` command change its settings.

> **Note:** This project was written almost entirely by an AI assistant, with direction and testing by the author. It has been tested mainly on CachyOS with Hyprland,
> and a Razer Chroma ARGB controller driving WS2812B strips. Other hardware,
> strip types and desktops are supported in the code but have seen less real-world testing.

<p align="center">
  <img alt="Status tab" src="docs/screenshots/status.png" width="32%">
  <img alt="Devices tab" src="docs/screenshots/devices.png" width="32%">
  <img alt="Layout tab" src="docs/screenshots/layout.png" width="32%">
</p>

## Features

- **Works on most desktops:** GNOME, KDE Plasma, XFCE, Cinnamon, MATE, COSMIC, Hyprland, Sway, niri and
  more ([full list](docs/wiki/How-It-Works.md#wallpaper-detection)), or a folder you choose.
- **Each zone its own look:** a solid color, a gradient, segments and other patterns, with its own
  brightness. A strip can be split into parts, for example one that shows the CPU temperature.
- **Animations when you want them:** breathing, comet, rainbow and a few more, in the wallpaper's colors.
- **A map of your room:** draw where the strips are, and gradients and animations run across them.
- **Brightness that fits:** follows your monitor (DDC/CI) or laptop screen, dims at night, and goes
  off when the screen locks or the PC sleeps.
- **Most strip types:** WS2812B, WS2811, plain 12V RGB and RGBW, with color order and color correction.
- **Keyboard shortcuts and saved setups** through the `iridia` command.
- **Light:** about 0.1% of one CPU core and 30 MB of memory with static colors.

## Install

### Requirements

| | |
| --- | --- |
| **OpenRGB** 0.9+ (1.0 recommended) | talks to your hardware ([openrgb.org](https://openrgb.org/)); Iridia starts its server, with or without systemd |
| **Python 3.8+** with `venv` | Iridia installs into its own virtual environment |
| **GTK 4.6+, PyGObject, pycairo** | for the window (the daemon runs without them) |
| **ddcutil** *(optional)* | to follow your monitor's brightness |

### Quick install

```bash
git clone https://github.com/HypestHyper/Iridia-LED.git
cd Iridia-LED
bash install.sh
```

The installer finds what's missing and offers to install it with your package manager (pacman, apt,
dnf, zypper, xbps or apk), installs Iridia into `~/.local/share/iridia-venv`, links the `iridia` and
`iridia-gui` commands into `~/.local/bin`, sets up I2C access for monitor brightness, adds the app to
your launcher and starts it. It asks two things:

- **How OpenRGB's server is started:** by the Iridia daemon (the default, works with or without
  systemd), by a systemd service, or by you. Flag: `--openrgb=daemon|systemd|off`.
- **How the daemon starts at login:** a systemd service, XDG autostart, or a line in your compositor's
  config (it prints the line). Flag: `--autostart=systemd|xdg|compositor|none`.

Nothing of Iridia itself goes outside your home folder. Add `--yes` to skip the questions and use the
defaults, `--no-deps` to leave system packages alone.

**Updating:** from the window's *Updates* tab, with `iridia update`, or with `git pull && bash install.sh`.
Your settings are kept ([Updates](docs/wiki/Updates.md)).

<details>
<summary><b>Installing the dependencies by hand</b></summary>

| Distribution | Command |
| --- | --- |
| Arch, CachyOS, EndeavourOS, Manjaro | `sudo pacman -S --needed python gtk4 python-gobject python-cairo openrgb ddcutil` |
| Debian, Ubuntu, Mint, Pop!_OS | `sudo apt install python3 python3-venv gir1.2-gtk-4.0 python3-gi python3-gi-cairo ddcutil libglib2.0-bin` |
| Fedora | `sudo dnf install python3 gtk4 python3-gobject python3-cairo openrgb ddcutil` |
| openSUSE | `sudo zypper install python3 typelib-1_0-Gtk-4_0 python3-gobject python3-gobject-cairo python3-cairo OpenRGB ddcutil` |
| Void | `sudo xbps-install python3 gtk4 python3-gobject python3-cairo openrgb ddcutil` |
| Alpine | `sudo apk add python3 gtk4.0 py3-gobject3 py3-cairo ddcutil` (OpenRGB from source) |

Then run `bash install.sh --no-deps`. If your release has no OpenRGB package, get it from
[openrgb.org](https://openrgb.org/).

</details>

### Before the first run

1. **OpenRGB:** install it and check that your devices show up in it. Iridia starts OpenRGB's server
   for you; the installer asks how (see [Setting up OpenRGB](docs/wiki/Installation.md#setting-up-openrgb)).
   If OpenRGB also starts itself at login, keep only one of the two.
2. **For monitor brightness** (optional): the installer sets up I2C access for ddcutil (the `i2c` group,
   its udev rule and the `i2c-dev` module). Log out and in once afterwards, then check that
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
| [Animations](docs/wiki/Animations.md) | Animated effects, follow the layout, frame rate |
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
| [Development](docs/wiki/Development.md) | Project layout, running from source, the IPC protocol |

## License

[MIT](LICENSE).

Bundled fonts: [Material Symbols](https://github.com/google/material-design-icons) (Apache License 2.0)
and [Google Sans Flex](https://fonts.google.com/specimen/Google+Sans+Flex) (SIL Open Font License 1.1);
their licenses are in `iridia/data/fonts/`. Iridia is not affiliated with OpenRGB.
