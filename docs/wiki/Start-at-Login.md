# Start at login

The daemon has to run for your lights to follow the wallpaper. It doesn't need the window.

Only one daemon ever runs: it takes a lock, so a second copy started by another method exits quietly.
More than one method is harmless, but one is enough; `iridia doctor` lists every method it finds and
shows how the running daemon was started.

The installer asks which method to use (`--autostart=systemd|xdg|compositor|none`). Its default is
systemd when your session reaches `graphical-session.target`, else your compositor's line when it
detects one, else XDG autostart. Everything works the same whichever method starts the daemon: it
inherits your session (`WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE`, `DBUS_SESSION_BUS_ADDRESS`),
sleep detection talks to logind directly, and outside systemd it keeps a log file in
`~/.local/share/iridia/iridia.log`, since there is no journal.

This page is about the Iridia daemon. What starts OpenRGB's server is a separate setting; see
[Setting up OpenRGB](Installation.md#setting-up-openrgb).

## systemd

The installer sets up a systemd user service, `iridia-daemon.service`, that starts with your graphical
session (`graphical-session.target`). That works out of the box on GNOME and KDE, and on Hyprland, Sway
and niri when they're started through [UWSM](https://github.com/Vladimir-csp/uwsm) or a display manager
that activates the target.

```bash
systemctl --user status iridia-daemon.service
journalctl --user -u iridia-daemon -f
iridia service install --autostart systemd    # write and enable the service (and the launcher)
iridia service remove
```

In the window: **Service, Start the daemon when I log in**.

If your session never activates `graphical-session.target`, the service is enabled but never starts;
`iridia doctor` warns about it. Use one of the methods below instead.

## Your compositor's autostart

If your compositor doesn't activate `graphical-session.target` (Hyprland started from a TTY without
UWSM, for example), add one line to its config. `iridia autostart` prints the right line for each, with
the real path; the *Service* tab shows the same.

| Compositor | File | Line |
| --- | --- | --- |
| Hyprland | `~/.config/hypr/hyprland.conf` | `exec-once = ~/.local/share/iridia-venv/bin/iridia-daemon` |
| Hyprland (Lua) | `~/.config/hypr/hyprland.lua` | `hl.exec_cmd("/home/you/.local/share/iridia-venv/bin/iridia-daemon")` inside `hl.on("hyprland.start", function() ... end)` |
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

The installer picks this method when your session doesn't reach `graphical-session.target` and it
doesn't recognize your compositor (`--autostart=xdg` picks it on purpose).

## Starting and stopping by hand

```bash
iridia daemon start     # uses systemd if the service is installed
iridia service install --autostart compositor   # change the method (prints your compositor's line)
iridia daemon stop      # however it was started
iridia daemon status
```
