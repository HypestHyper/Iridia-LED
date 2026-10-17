# Command line

Everything the window does can also be done with the `iridia` command. The installer links it into
`~/.local/bin` (the real one is in `~/.local/share/iridia-venv/bin/`); if your shell can't find it, see
[Installation](Installation.md#running-it). `iridia --help` and `iridia COMMAND --help` list every
option.

## Status and health

| Command | What it does |
| --- | --- |
| `iridia status` | Daemon, wallpaper, colors, OpenRGB, devices and zones |
| `iridia doctor` | A full health check that explains what's wrong, if anything |
| `iridia log [-n 40]` | The daemon's most recent log lines (works with file logging off) |
| `iridia --version` | The installed version |

## Daemon and service

| Command | What it does |
| --- | --- |
| `iridia daemon start` | Start the daemon (through systemd if the service is installed) |
| `iridia daemon stop` | Stop it, however it was started |
| `iridia daemon status` | Running or stopped, and who started it |
| `iridia restart` | Soft restart: reconnect and re-send everything |
| `iridia service install [--autostart METHOD] [--openrgb METHOD]` | Install the launcher and icons, and set up how the daemon starts at login (`systemd`, `xdg`, `compositor` or `none`) and how OpenRGB is started (`daemon`, `systemd` or `off`) |
| `iridia service remove` | Remove them |
| `iridia service status / start / stop / restart` | Control the systemd service |
| `iridia autostart` | Print the autostart line for every compositor |
| `iridia autostart xdg-install / xdg-remove` | Add or remove the XDG autostart entry |
| `iridia uninstall [--yes] [--keep-settings]` | Remove Iridia |

## OpenRGB

| Command | What it does |
| --- | --- |
| `iridia openrgb reconnect` | Drop the connection and connect again |
| `iridia openrgb restart` | Restart OpenRGB's server: the one Iridia started, or `iridia-openrgb.service`, or another user service or headless `openrgb --server` (never the OpenRGB window). Does nothing with the `off` method |
| `iridia openrgb start-method` | Show how OpenRGB's server is started |
| `iridia openrgb start-method daemon` | The Iridia daemon starts it (default) |
| `iridia openrgb start-method systemd` | `iridia-openrgb.service` starts it with your graphical session |
| `iridia openrgb start-method off [--stop]` | You start it; `--stop` also stops the one Iridia started (otherwise it asks, or keeps it running) |
| `iridia openrgb enable`, `disable` | The same as `start-method daemon` and `start-method off` |
| `iridia openrgb hide-autostart [FILE]` | Turn off OpenRGB's own entry in `~/.config/autostart` by adding `Hidden=true` (the file stays) |
| `iridia openrgb status` | The method, the command, whether Iridia started the running OpenRGB, and what else starts it |

## Animations

| Command | What it does |
| --- | --- |
| `iridia zone TARGET effect NAME [--speed N] [--min N] [--max N] [--param KEY=VALUE]` | Run an effect on strips (temporary; again: back) |
| `iridia zone TARGET effect NAME --save` | Make it the strips' own setting (`effect static --save` goes back) |
| `iridia animations pause / resume / toggle` | Pause every animation until resumed |
| `iridia animations status` | Which zones animate, and for each device the frames per second it gets and how long a frame takes; warns when the daemon runs older code than what's installed |

Effects: `breathing`, `comet`, `fill`, `embers`, `rainbow`, `rainbow_vomit`, `color_cycle`. See
[Animations](Animations.md) for their settings.

## Wallpaper and colors

| Command | What it does |
| --- | --- |
| `iridia refresh` | Check the wallpaper again now |
| `iridia wallpaper` | Show the current wallpaper |
| `iridia wallpaper PATH` | Always use this image |
| `iridia wallpaper --reset-detection` | Forget which wallpaper tool was found and look again |
| `iridia preview HEX` / `iridia preview off` | Show one color on every LED without saving it (ends by itself after 5 minutes) |
| `iridia freeze [toggle]` / `iridia unfreeze` | Ignore or follow wallpaper changes |
| `iridia palette list / reset / path` | The 48 color palette |

## Lights, night mode and keybinds

| Command | What it does |
| --- | --- |
| `iridia lights on / off / toggle` | Every LED on or off |
| `iridia night show` | Night mode settings |
| `iridia night on / off / toggle [--start 23:00] [--end 07:00] [--cap 20]` | Night mode |
| `iridia session` | Lock and idle: settings, what's happening now, and how Iridia sees it |
| `iridia session --lock off --idle dim --idle-minutes 10 --dim 20` | Change them (`keep`, `dim`, `off`) |
| `iridia session test` / `iridia session hooks` | Act as if locked for 5 seconds / lines for hypridle and swayidle |
| `iridia idle on / off`, `iridia lock on / off` | For idle daemons and screen lockers Iridia can't see by itself |
| `iridia zone list` | Strip names to use with `iridia zone` |
| `iridia zone NAME[,NAME] [on/off] [color HEX] [bright N] [--set]` | Temporary strip changes; see [Keybinds](Keybinds.md) |
| `iridia zone NAME normal` | Undo keybind changes |
| `iridia identify DEVICE [-z ZONE] [-s SECONDS]` / `iridia identify off` | Light only one zone |

## Parts and single LEDs

Saved settings, like the *Advanced* part of a zone card. LED and part numbers start at 1.

| Command | What it does |
| --- | --- |
| `iridia split NAME` | Show the strip's parts and single LEDs |
| `iridia split NAME even 3` | Split into 3 parts as evenly as whole LEDs allow (keeps what the parts show) |
| `iridia split NAME at 28 55` | New parts start at LEDs 28 and 55 |
| `iridia split NAME part 2 pattern gradient ff0000 0000ff` | Part 2 gets its own pattern; colors are hex or wallpaper color numbers (1 = first) |
| `iridia split NAME part 3 effect comet 1` | Part 3 gets its own effect |
| `iridia split NAME part 1 same` / `off` | Part 1 shows the strip's own look, or nothing |
| `iridia split NAME led 27 ffffff` / `off` / `normal` | Set one LED, turn it off, or give it back |
| `iridia split NAME join` / `clear-leds` | One part again / no single LEDs |

## Setups

| Command | What it does |
| --- | --- |
| `iridia setup list` | Saved setups and automatic backups |
| `iridia setup save NAME` | Save everything under a name |
| `iridia setup load NAME` | Load it (backs up the current state first) |
| `iridia setup delete NAME` | Delete it |
| `iridia setup export NAME FILE` / `iridia setup import FILE` | Move setups between machines |

## Devices and config

| Command | What it does |
| --- | --- |
| `iridia config show / edit / path` | The config file (`edit` uses `$EDITOR` and reloads the daemon) |
| `iridia device NAME ACTION [-z ZONE] [-v VALUE]` | Change a device or zone, see below |

`iridia device` actions:

| Action | Value |
| --- | --- |
| `enable`, `disable` | |
| `mode` | `full`, `palette` or `calibrated` (color correction) |
| `pattern`, `zone-pattern` | `solid`, `gradient`, `segments`, `center_out`, `edges_in`, `alternating`, `paint` |
| `zone-colors` | Comma list of wallpaper color numbers (from 0) and hex colors: `0,2,ff8800` |
| `brightness-sync`, `invert`, `gamma` | `on` or `off` |
| `manual-brightness` | 0 to 100 |
| `brightness-range` | `min,max`, like `20,80` |
| `led-count` | Number of LEDs |

Device and zone names are the ones OpenRGB reports; `iridia status` lists them. Quote names with spaces.
