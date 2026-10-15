# Keybinds

Iridia doesn't listen to your keyboard; your desktop does. You give a key an `iridia` command in your
compositor's config (or your desktop's keyboard settings), and pressing the key runs the command. The
**Keybinds** tab builds the command and the config line for you.

## How strip keybinds behave

- **Temporary.** Nothing is saved. The change lasts until you undo it or restart the daemon.
- **Press again to undo.** Running exactly the same command again puts the strips back to normal, so one
  key switches both ways.
- **Several things at once.** One command can turn strips on, set a color and set a brightness, in any
  mix.
- **Several strips at once.** Name several strips, separated by commas, or use `all`.

## Commands

```bash
iridia zone list                                      # the names you can use
iridia zone "Desk back" off                           # off; run again: back to normal
iridia zone "Desk back" color ff0000                  # one color; run again: back to normal
iridia zone "Desk back" bright 30                     # 30% brightness
iridia zone "Desk back" on                            # light a strip that is switched off
iridia zone "Desk back" on color ff0000 bright 40     # several things at once
iridia zone "Desk back,Monitor" color 00ff88          # several strips
iridia zone all bright 20                             # every strip
iridia zone all normal                                # undo every keybind change
iridia zone "Desk back" off --set                     # always off, never switch back
iridia zone "Desk back" effect breathing --speed 3    # an effect; run again: back to normal
iridia zone all effect static                         # still colors; run again: animations back
```

Short forms work too: `iridia zone "Desk back" on ff0000 40%`.

| Action | Meaning |
| --- | --- |
| `on` | Show the strip even if it's switched off in Iridia |
| `off` | Dark |
| `color HEX` | One color on the whole strip (exact colors stay exact; others follow the zone's correction) |
| `bright N` | Brightness N% instead of the zone's own |
| `effect NAME` | An animated effect: `breathing`, `comet`, `fill`, `embers`, `rainbow`, `rainbow_vomit`, `color_cycle`, or `static` for the static pattern. Settings follow as `--speed`, `--min`, `--max` or `--param KEY=VALUE` |
| `normal` | Back to normal (alone) |

`off` can't be combined with a color or brightness, and `normal` can't be combined with anything. An
effect can't be combined with `off` or a color; with `bright` it runs at that brightness. Add `--save` to
make an effect the strip's own setting instead of a temporary change.
`color` and `bright` don't light a strip that is switched off; add `on` for that.

Other commands that work well on keys:

```bash
iridia lights toggle        # everything off / on
iridia freeze toggle        # stop / start following the wallpaper
iridia night toggle         # night mode on / off (this one is saved)
iridia animations toggle    # pause / resume every animation
iridia setup load Gaming    # load a saved setup (this one is permanent)
```

## Strip names

Use the name shown in the window (rename a strip with its pencil button), the zone name, a device name
(all its zones) or `all`. When two strips share a name, use `Device/Zone`; `iridia zone list` shows the
exact names. Names are not case sensitive.

## The Keybinds tab

1. Choose **Change strips** or **Other actions**.
2. For strips: pick the strips as chips (or *All strips*), choose the power (*Leave as is*, *Turn on*,
   *Turn off*, *Back to normal*), and switch on **Color** and/or **Brightness**.
3. The command appears below. **Try it** runs it right away; **Copy command** copies it.
4. Under **Add it to your desktop**, pick your desktop and a key. Paste the line into the file shown and
   reload your desktop's config.

**Changed by a keybind right now** lists every strip a keybind changed, with *Back to normal* buttons.

## Config lines per desktop

Desktops usually don't know where Iridia is installed, so the lines use the full path
`~/.local/share/iridia-venv/bin/iridia`. The tab fills in the real path for you.

**Hyprland** (`~/.config/hypr/hyprland.conf`)
```
bind = SUPER SHIFT, F9, exec, ~/.local/share/iridia-venv/bin/iridia zone 'Desk back' off
```

**Hyprland, Lua config** (`~/.config/hypr/hyprland.lua`)
```lua
hl.bind("SUPER + SHIFT + F9", hl.dsp.exec_cmd("~/.local/share/iridia-venv/bin/iridia zone 'Desk back' off"))
```

**Sway** (`~/.config/sway/config`) and **i3** (`~/.config/i3/config`)
```
bindsym Mod4+Shift+F9 exec ~/.local/share/iridia-venv/bin/iridia zone 'Desk back' off
```
(i3: `exec --no-startup-id`)

**niri** (`~/.config/niri/config.kdl`, inside `binds { }`)
```
Super+Shift+F9 { spawn "/home/you/.local/share/iridia-venv/bin/iridia" "zone" "Desk back" "off"; }
```

**river** (`~/.config/river/init`)
```
riverctl map normal Super+Shift F9 spawn "~/.local/share/iridia-venv/bin/iridia zone 'Desk back' off"
```

**KDE Plasma:** System Settings, Keyboard, Shortcuts, *Add New*, *Command or Script*. Paste the command
and press your key.

**GNOME:** Settings, Keyboard, *View and Customize Shortcuts*, *Custom Shortcuts*, **+**. Paste the
command and set your key.

**sxhkd** (bspwm and other X11 window managers, `~/.config/sxhkd/sxhkdrc`)
```
super + shift + F9
    ~/.local/share/iridia-venv/bin/iridia zone 'Desk back' off
```
