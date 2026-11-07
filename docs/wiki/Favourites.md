# Favourites and looks

The *Favourites* tab (the star, right after Status) holds the controls you use most, from everywhere
in Iridia, as tiles you arrange yourself.

## Tiles

| | |
| --- | --- |
| A strip or light | On and off, its brightness, and its colour: a wallpaper colour, a saved colour, or any colour (+). Changes are its own settings, like on its card |
| A look | One tap puts it on, one more tap puts things back (see below) |
| A setup | Loads it (the settings before are backed up first) |
| A switch | All lights, freeze colours, night mode, animations, scenes (fullscreen), notification flashes, network lights |

*Add* lists everything that can go on the tab (what's already there is greyed out). The ★ on a strip's
card on the Devices tab adds or removes it too. *Arrange* shows, on each tile, arrows to move it, a
button to make it wider or smaller, ✕ to take it off, and for a look, a pencil to change it. *Done*
when you're finished.

## Looks

A look is a change you name yourself: *Movie*, everything at 15%; *Gaming*, the desk strip with a
rainbow; *Reading*, the lamp warm white and the rest off. *New look*: a name, which strips (or
*Everything*), and what they do: off, dimmer, one colour or an effect, at a brightness. *Try it*
shows it on those strips for 5 seconds. A new look goes straight onto Favourites.

Turning a look on puts it over its strips the way a keybind does: their settings don't change, and
turning it off (its tile again, `iridia look NAME off`, or a keybind's *normal*) puts them back. A
look turned on after another one wins on the strips they share. Looks are temporary: after a restart
of the daemon, none is on.

From a key: the Keybinds tab, *Turn a look on or off*, or a command like `iridia look "Movie"` (the
same key turns it on, then back off).

## Command line

```sh
iridia looks                 # your looks; * = on now
iridia look "Movie"          # on, or back off
iridia look "Movie" on       # or off
```
