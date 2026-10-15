# Start at login

The daemon has to run for your lights to follow the wallpaper. It doesn't need the window.

Only one daemon ever runs: it takes a lock, so a second copy started by another method exits quietly.
You can safely enable more than one method.

## systemd (recommended)

The installer sets up a systemd user service, `iridia-daemon.service`, that starts with your graphical
session (`graphical-session.target`). That works out of the box on GNOME and KDE, and on Hyprland, Sway
and niri when they're started through [UWSM](https://github.com/Vladimir-csp/uwsm) or a display manager
that activates the target.

```bash
systemctl --user status iridia-daemon.service
journalctl --user -u iridia-daemon -f
iridia service install     # write and enable the service (and the launcher)
iridia service remove
```

In the window: **Service, Start the daemon when I log in**.

`iridia service install` also sets up `iridia-openrgb.service`, which starts OpenRGB's server at login,
unless something else already starts OpenRGB. See
[Setting up OpenRGB](Installation.md#setting-up-openrgb).

## Your compositor's autostart

If your compositor doesn't activate `graphical-session.target` (Hyprland started from a TTY without
UWSM, for example), add one line to its config. `iridia autostart` prints the right line for each, with
the real path; the *Service* tab shows the same.

| Compositor | File | Line |
| --- | --- | --- |
| Hyprland | `~/.config/hypr/hyprland.conf` | `exec-once = ~/.local/share/iridia-venv/bin/iridia-daemon` |
| Hyprland (UWSM) | `~/.config/hypr/hyprland.conf` | `exec-once = uwsm app -- ~/.local/share/iridia-venv/bin/iridia-daemon` |
| Sway | `~/.config/sway/config` | `exec ~/.local/share/iridia-venv/bin/iridia-daemon` |
| i3 | `~/.config/i3/config` | `exec --no-startup-id ~/.local/share/iridia-venv/bin/iridia-daemon` |
| niri | `~/.config/niri/config.kdl` | `spawn-at-startup "/home/you/.local/share/iridia-venv/bin/iridia-daemon"` |
| river | `~/.config/river/init` | `riverctl spawn "~/.local/share/iridia-venv/bin/iridia-daemon"` |
| labwc, Openbox | `~/.config/labwc/autostart`, `~/.config/openbox/autostart` | `~/.local/share/iridia-venv/bin/iridia-daemon &` |
| bspwm, dwm, X11 | `bspwmrc`, `~/.xinitrc`, `~/.xprofile` | `~/.local/share/iridia-venv/bin/iridia-daemon &` |

## XDG autostart

GNOME, KDE, XFCE, Cinnamon, MATE and LXQt start programs from `~/.config/autostart/`:

```bash
iridia autostart xdg-install
iridia autostart xdg-remove
```

On systems without a systemd user session, the installer uses this method automatically.

## Starting and stopping by hand

```bash
iridia daemon start     # uses systemd if the service is installed
iridia daemon stop      # however it was started
iridia daemon status
```
