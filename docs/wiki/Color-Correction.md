# Color correction

Cheap LED strips rarely show the color you ask for: oranges come out yellow, purples come out blue,
pastels come out white. Every zone has a **Color correction** setting on its card (and on the Everything
card to set all zones):

| Mode | What it does |
| --- | --- |
| **Off** | Colors are sent as they are, with gamma (if on) and brightness. The default. |
| **Palette** | Every LED snaps to the nearest of 48 hand-picked colors that look right on typical strips. |
| **Calibrated** | Colors go through a calibration profile made for your kind of strip, which maps each hue to the hex the strip needs to look like that hue. Brightness is part of the mapping, so dim colors keep their hue. Gamma isn't used. |

The window and its accent color always follow the wallpaper or the color you chose, never the corrected
color. The *Color correction preview* on the Status tab shows what each wallpaper color becomes on your
strip.

## Exact colors

Sometimes you want one particular color to reach the LEDs untouched, even on a zone set to Palette or
Calibrated. Switch on **Exact color** in the color picker: the LEDs show that hex as it is, with no
snapping, no profile and no gamma, only brightness. While the picker is open, the strip previews it
the same way.

Exactness belongs to the color, not to one zone: wherever you use that color (zone colors, painted LEDs,
keybinds), it's exact. Exact colors have a small dot on their swatch. To make a color follow correction
again, pick it with the switch off. Deleting a saved color clears it too.

## The palette

Palette mode uses 48 colors kept in `~/.config/iridia/palette.json`. Each LED is snapped to the closest
one (after the pattern is built, so gradients snap per LED).

```bash
iridia palette list    # show it
iridia palette path    # where the file is
iridia palette reset   # back to the built-in palette
```

## Calibration profiles

A profile lists, for a set of hues, the hex to send so the strip looks like that hue, plus a grey and a
few curve settings. Hues between the rows are blended.

| Profile | What it is |
| --- | --- |
| **WS2812B** | Built in. Tuned by eye on a WS2812B strip behind an ARGB controller. A good start for most WS2812B strips. Can't be deleted, but the editor can reset it. |
| **Neutral** | Pure colors, no correction. The starting point for any other strip type. |

In **Settings, Color calibration** you can pick a profile, then **Edit**, **Add** (a copy under a new
name), **Import**, **Export** or **Delete** it. Pick the profile per zone with *Calibrated* on its card.

### Tuning a profile

1. Pick the profile and click **Edit**.
2. For a row (a hue), click **Tune**. The color picker opens and sends exactly what you pick to the
   strip, with the target color beside it. Change it until the strip looks like the target.
3. Repeat for the hues that look wrong. Changes save as you go.

The *Try a color* sliders show what the profile sends for any color, and *Show on LEDs* puts it on the
strip.

### Advanced settings

| Setting | Default | What it does |
| --- | --- | --- |
| **Saturation floor** (`min_out_sat`) | 0.55 | A color is never sent whiter than this. Hue and brightness are kept and saturation is raised to the floor, so colors can't come out washed out. Capped by the input's own saturation, so greys stay grey. Raise it if colors look pale, lower it if they look too strong, 0 turns it off. |
| **Saturation curve** (`sat_exponent`) | 0.5 | How quickly pastel colors fade toward white. Lower is paler sooner. |
| **Blue to sky blue** (`blue_nudge`) | 0.3 | Pushes pale blues toward sky blue instead of violet. |
| **Grey sharpness** (`grey_sharpness`) | 8 | How close to no color a color must be before the grey takes over. |

Profiles are plain JSON files in `~/.config/iridia/calibration/`, so you can edit them by hand or share
them.

## Where correction happens

For each frame, the pattern is built first (one color per LED), then corrected, then brightness is
applied, then the strip's power limit and color order. See [How it works](How-It-Works.md#the-color-pipeline).
