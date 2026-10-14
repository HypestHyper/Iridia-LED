# Iridia wiki

Iridia syncs your RGB lighting with your wallpaper on Linux. It reads the colors of your current
wallpaper, sends them to your LEDs through [OpenRGB](https://openrgb.org/), and makes the LEDs follow
your monitor's brightness. A small background daemon does the work; a GTK 4 window lets you set it up.

This wiki explains everything Iridia can do and how it works.

## Start here

| Page | What's in it |
| --- | --- |
| [Installation](Installation.md) | Requirements, per-distro packages, the installer, OpenRGB and DDC setup, updating, uninstalling |
| [Getting started](Getting-Started.md) | The first run, a tour of the window, setting up your first strip |

## Using Iridia

| Page | What's in it |
| --- | --- |
| [Devices, patterns and colors](Devices-and-Patterns.md) | Zones, the Everything card, patterns, wallpaper colors, saved colors, painting, brightness |
| [Layout](Layout.md) | Drawing your strips where they really are: moving, bending, painting, finding LEDs |
| [Strip types](Strip-Types.md) | WS2812B, WS2811, plain 12V RGB, RGBW, color order and power limits |
| [Color correction](Color-Correction.md) | Off, Palette and Calibrated modes, exact colors, calibration profiles |
| [Keybinds](Keybinds.md) | Changing strips from a key: commands and config lines for every desktop |
| [Night mode, sleep and freeze](Night-Sleep-and-Freeze.md) | Brightness caps at night, LEDs off while the PC sleeps, freezing colors |
| [Setups and backups](Setups-and-Backups.md) | Saving everything under a name, automatic backups, moving to another PC |
| [Start at login](Start-at-Login.md) | systemd, compositor lines, XDG autostart |

## Reference

| Page | What's in it |
| --- | --- |
| [Command line](Command-Line.md) | Every `iridia` command |
| [Configuration](Configuration.md) | The files in `~/.config/iridia/` and the settings in them |
| [How it works](How-It-Works.md) | The daemon, the color pipeline, wallpaper detection, resilience |
| [Troubleshooting](Troubleshooting.md) | What to check when something doesn't work |
| [FAQ](FAQ.md) | Short answers to common questions |
| [Development](Development.md) | Project layout, running from source, the IPC protocol, contributing |
