# Setups and backups

A **setup** is everything Iridia knows, saved under a name:

- devices and zones (patterns, colors, brightness, correction, strip types, names)
- the Layout tab
- night mode and sleep
- calibration profiles and the palette
- your color picks for each wallpaper
- your saved colors (and which ones are exact)
- window preferences (font, size, reduce motion)

Use setups to switch between looks ("Gaming", "Work"), to experiment safely, or to move your settings to
another PC.

## In the window

**Settings, Setups and backups**: *Save current as…*, then pick a setup to **Load**, **Rename**,
**Export** (to a file) or **Delete**, or **Import** a file.

**Automatic backups:** loading a setup, restoring a backup, or updating Iridia first saves what you
have now as an automatic backup. The newest five are kept. Pick one under *Automatic backups* and click
**Restore** to go back.

Loading puts everything back exactly as it was when it was saved: files that didn't exist then (a
layout made later, a calibration profile added later) are removed. Setups saved by Iridia 1.2 and older
only write back what they hold.

## From the command line

```bash
iridia setup save "Desk"
iridia setup load "Desk"
iridia setup list
iridia setup delete "Desk"
iridia setup export "Desk" desk.json
iridia setup import desk.json
```

`iridia setup load NAME` also works on a key; see [Keybinds](Keybinds.md).

## Where they live

`~/.config/iridia/setups/NAME.json`, and the automatic backups in `~/.config/iridia/setups/.backups/`.
A setup file is plain JSON holding a copy of each settings file, so it can be moved to another machine
as it is. Devices with different names on the other PC are kept in the config but stay idle until such
a device shows up.
