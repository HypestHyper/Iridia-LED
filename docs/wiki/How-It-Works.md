# How it works

## The pieces

```
 wallpaper tools      monitor (DDC/CI)        you
       |                    |              /      \
       v                    v         window    iridia CLI / keybinds
 +------------------------------------------+      |
 |               iridia-daemon              | <----+  Unix socket, JSON
 |  detect -> extract -> pattern -> correct |
 +------------------------------------------+
                     |  OpenRGB SDK (TCP)
                     v
                  OpenRGB  ->  your LEDs
```

- **The daemon** (`iridia-daemon`) does all the work. It runs in the background, with or without the
  window, and is the only part that talks to OpenRGB.
- **The window** (`iridia-gui`, GTK 4) and **the command line** (`iridia`) only send it requests over a
  Unix socket in `$XDG_RUNTIME_DIR`. Closing the window changes nothing.
- **OpenRGB** talks to the hardware. Iridia connects to its SDK server and sends colors.

## Wallpaper detection

Iridia asks the tools that set wallpapers, in this order, and remembers the first one that answers so
later checks ask only that one:

1. Caelestia and Noctalia (their state files)
2. Hyprland: swww or awww, hyprpaper, swaybg
3. Sway: swww or awww, swaybg
4. GNOME (light and dark wallpaper), KDE Plasma, XFCE, Cinnamon, MATE
5. feh, nitrogen, xwallpaper, waypaper
6. The newest image in `wallpaper.watch_folder`

A fixed `wallpaper.manual_path` skips all of this. File watchers (inotify) notice changes right away;
tools that need a command are asked every few seconds, and when nothing answers at all Iridia backs off
to every 30 seconds instead of running every tool over and over.

When the daemon runs as a systemd service it may not get the session's variables. It finds
`WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE` and `SWAYSOCK` in `$XDG_RUNTIME_DIR` by itself, and
looks again if the compositor restarts.

## Color engines

Colors are extracted once per image and cached by file, modification time and engine.

| Engine | How |
| --- | --- |
| **Caelestia scheme** | When Caelestia set the wallpaper, its own up-to-date color scheme is used |
| **Material** | Material Color Utilities' prominent colors (optional package `material-color-utilities`) |
| **Pillow** | Median cut on a small copy of the image; no extra dependencies |

`auto` uses the first that applies, in that order. Similar colors are merged and dull ones dropped, so
you get distinct, usable colors with the most important first. A black-and-white wallpaper gives its
greys instead.

## The color pipeline

For every zone, every time something changes:

1. **Overrides first.** Lights off or the PC asleep (black), Identify (one zone white), Find LEDs or Count
   LEDs (one LED), Test colors (red, green, blue), keybind changes.
2. **Colors.** The zone's color choices resolved against the current wallpaper colors (or a color
   preview while the picker is open).
3. **Pattern.** One color per LED (Solid, Gradient, Segments...). One-color strips are always solid.
4. **Correction.** Palette snaps each LED, Calibrated maps it through the profile; exact colors skip
   this step.
5. **Brightness.** From the monitor (mapped onto the zone's range, inverted for bias lighting) or the
   manual value, capped by night mode, or a keybind's brightness. Gamma, when on.
6. **Power limit**, **color order** and **RGBW packing** for the strip type.
7. **Send**, only if the result differs from what was sent last.

Nothing animates, so the daemon is idle most of the time: it wakes twice a second, and does real work
only when something changed.

## Brightness

ddcutil reads the monitor's brightness every few seconds on a background thread, so a slow monitor never
holds up the colors. Without DDC, the manual brightness is used.

## Resilience

- **OpenRGB not running:** Iridia keeps tracking the wallpaper and retries every few seconds; colors
  are sent as soon as it connects. The port is found automatically.
- **Connection lost:** detected on the next send, followed by a fresh connection.
- **Devices that vanish** (often after sleep or a USB hiccup): if a device stays missing, Iridia restarts
  OpenRGB's server, at most twice per device.
- **Devices without Direct mode** fall back to another per-LED mode, or a one-color mode.
- **New devices and zones** are added to the config automatically; zones without a size are added
  switched off.
- **Broken config files** are repaired value by value, or moved aside and replaced.
- **One broken zone** never stops the others.
- **Single instance:** a lock in `$XDG_RUNTIME_DIR` makes sure only one daemon runs, however many
  autostart methods fire.
- **Sleep:** LEDs go dark before suspend (with a short inhibitor lock) and colors are re-sent twice after
  resume.

## Privacy

Iridia makes no network connections other than to the OpenRGB server (local by default). Nothing is sent
anywhere.
