# Favourites and looks

The *Favourites* tab (the star, right after Status) holds the controls you use most, from everywhere
in Iridia, as tiles you arrange yourself.

## Cards

A card is a few controls for the strips you choose: one strip, a few, or *Everything*. *New card*: a
title, then tap the strips it's for and what goes on it:

| | |
| --- | --- |
| On and off | The round ⏻ button in the card's header, for all its strips at once (pastel green on, red off) |
| Brightness | A slider with its value. While the strips follow the monitor it shows the monitor's level; moving it sets their own brightness and stops following, as on a phone |
| Colours | The wallpaper's colours as swatches, and 🎨 for a popup with your saved colours and the colour wheel; the card's strips all take that one colour |
| Effect | An effect for its strips (or *Static*), and its speed, slow to fast: each strip's own effect at that speed |
| Follow the monitor, Stay lit when locked, Iridia controls it | A switch each, for its strips |
| Looks, Scenes | A switch per look or scene: on or off |
| Switches | A switch each for all lights, freeze colours, night mode, animations, scenes, notification flashes, network lights |

Every on/off setting is a row with a short name and a switch (hover it for the full name), one per line
on a small or tall card and two on a wide or large one. For Looks, Scenes and Switches, the editor then asks which ones (all looks and scenes, and a few common switches, to start with). Changes on a card are its strips' own
settings, the same as on the Devices tab.

The ★ on a strip's card on the Devices tab makes a card for just that strip (or takes it off).

## Other tiles

| | |
| --- | --- |
| A look | One tap puts it on, one more tap puts things back (see below) |
| A setup | Loads it (the settings before are backed up first) |
| A switch | One of the switches above, on its own |

*Add* lists everything that can go on the tab (what's already there is greyed out).

## Sizes and order

Tiles sit on a grid of squares that fits the window: *small* (one square), *wide* (two across), *tall*
(two down) or *large* (two by two). A card grows taller when what's on it needs the room, so a small card
still shows everything you ticked. The pencil on a card changes it (on a small card, right-click it).
*Arrange* shows, on each tile, a handle to drag it onto another one's place, the size, a pencil, and ✕
to take it off. *Done* when you're finished.

## Hiding strips

Iridia can't tell a channel with nothing plugged in from one with a strip, so it shows every channel
the controller has. The eye on a strip's card (Devices tab) hides it: it goes into *Hidden* at the
bottom of the Devices tab, and it's left out of the lists elsewhere (cards, keybinds, notifications).
It keeps its settings and still gets its colours. The eye again shows it.

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
