# Getting started

## Before the first run

1. **OpenRGB is installed** and your devices appear in it. Iridia starts its server for you (see
   [Installation](Installation.md#setting-up-openrgb)).
2. **The Iridia daemon is running.** The installer starts it, and it starts on its own at every login.
   `iridia daemon status` tells you, or look at the *Service* tab.

Open **Iridia** from your app launcher. The chip in the header says whether OpenRGB is connected.

## A tour of the window

<img alt="The Status tab" src="../screenshots/status.png" width="420">

| Tab | What it's for |
| --- | --- |
| **Status** | The current wallpaper and its colors. Click a color to put it on every LED, or *Custom color…* for any color. *Now playing* sums up what Iridia is doing. |
| **Devices** | The *Everything* card (changes all zones at once) and one card per zone: pattern, colors, strip preview, brightness, color correction, strip type. |
| **Layout** | Your strips drawn where they are in the room, live, to arrange, bend and paint. |
| **Keybinds** | Builds commands for keyboard shortcuts and the line for your desktop's config. |
| **Settings** | Appearance (font, language, reduce motion), night mode and sleep, setups and backups, color calibration, color extraction, logging. |
| **Service** | The background daemon, starting at login, the OpenRGB connection, diagnostics, uninstalling. |

Changes apply right away and are saved on their own; there's no Save button. The **Freeze colors**
button in the header keeps the current colors no matter what the wallpaper does.

The window only changes settings. The daemon keeps your lights in sync with the window closed.

## Setting up your first strip

Iridia adds every device OpenRGB reports, with sensible defaults, the first time it sees it. Each zone
(an ARGB header, a RAM stick, a keyboard...) gets its own card on the **Devices** tab.

1. **Find the strip.** Open a zone's card and click **Identify**. Only that zone lights up white, so you
   know which strip it is. Click the pencil next to its name to give it a name like "Desk back".
2. **Count the LEDs.** Click **Count LEDs**. One LED lights up; move it with the slider or the arrow keys
   until it's the last LED of the strip, then click *This is the last one*. If OpenRGB drives fewer LEDs
   than your strip has, set OpenRGB's size in the same dialog first. Unsized ARGB headers (zero LEDs)
   are switched off until you do this.
3. **Pick a pattern and colors.** *Solid* uses one color; the other patterns combine several. Click
   wallpaper colors or saved colors to choose them; with several, the numbers show their order.
4. **Check the direction.** If a gradient runs the wrong way, switch on **Reverse**.
5. **Optional:** set the **Strip type** if it isn't a WS2812B-style strip (see [Strip types](Strip-Types.md)),
   and draw it on the **Layout** tab (see [Layout](Layout.md)).

From now on the strip follows your wallpaper. Change the wallpaper and the colors change with it.

## Where to go next

- [Devices, patterns and colors](Devices-and-Patterns.md) explains every control on a zone card.
- [Color correction](Color-Correction.md) if the LEDs don't look like the colors on screen.
- [Keybinds](Keybinds.md) to switch strips from your keyboard.
