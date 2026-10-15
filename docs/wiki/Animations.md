# Animations

Besides the static patterns, a zone can run an animated effect. Effects use the zone's own colors (the
wallpaper colors, saved colors or exact colors you picked), and everything else still applies to every
frame: brightness, night mode, color correction, color order, RGBW and the power limit. Static patterns
stay the default.

## Picking an effect

On the **Devices** tab, open a zone and switch **Pattern** from *Static* to *Animated*, then pick the
effect. Its settings show under it, each with its value, and changes apply right away. The strip preview
animates like the LEDs do.

The **Everything** card does the same for every zone at once. Its **Keep zones with this effect in step**
switch (on by default) runs every zone with the same effect on one clock, so a breathing fades in and
out everywhere together. Turn it off for zones that should drift apart.

From the command line (see [Command line](Command-Line.md)):

```bash
iridia zone "Desk back" effect breathing --speed 3 --min 10 --max 100 --save
iridia zone all effect rainbow --param width=60 --save
iridia zone "Desk back" effect static --save        # back to its static pattern
```

Without `--save` the effect is a [keybind](Keybinds.md) change: temporary, and running the same command
again puts the strip back.

## The effects

| Effect | What it does | Settings |
| --- | --- | --- |
| **Breathing** | Fades between a minimum and a maximum brightness | Seconds per breath; brightness range (default 10% to 100%); easing (sine, smooth, sharp); next color at each breath |
| **Comet** | Bright heads with a fading tail run along the strip | Speed (LEDs per second); tail length; heads; spacing (0 spreads them evenly); bounce back and forth; reverse; background (off, dim, the second color) |
| **Fill** | The strip fills up with its pattern, then empties | Speed; pause when full and empty; fill from the start, the end or the center; empty back, the same way, or reset |
| **Embers** | Points glow up and die down like embers, each drifting slowly through the zone's colors | Speed; density; softness (blend with neighbours); flicker; colors (the picked colors, or fire colors: deep red to amber, yellower when hotter) |
| **Rainbow** | A moving rainbow wave (ignores the zone's colors) | Speed; width (LEDs per rainbow); saturation; reverse |
| **Rainbow vomit** | The loud one: a fast, uneven rainbow with random sparkles | Speed; chaos (sparkles); width |
| **Color cycle** | The whole zone fades from one color to the next | Fade time; hold each color |

Colors fade into each other as light does (red to green passes through yellow, not a dull brown), and
Breathing moves through its range evenly for the eye rather than lingering near the top. Comet heads
glide between LEDs instead of hopping.

Breathing with *next color at each breath* off breathes the zone's static pattern, so a gradient zone
breathes as a gradient. Fill fills with the static pattern too. Every effect runs on a clock, not a frame
count, so a busy moment never slows it down.

The minimum and maximum of Breathing are relative to the zone's brightness: at 40% monitor brightness,
10% to 100% goes from 4% to 40%.

## Follow the layout

Comet, Fill, Rainbow, Rainbow vomit and Embers have **Follow the layout**. Instead of running along each
strip from LED 1, the effect runs through the room, using where each LED is on the [Layout](Layout.md)
tab: a comet or a rainbow travels across several strips in step. The **Direction** dial sets the way it
goes (0° is left to right, 90° top to bottom). Bends, turns and flipped strips are taken into account.
Every strip with the same effect and direction shares one run, so give them all *Follow the layout*.

The Layout tab shows the animation live while it's open.

## Settings

In **Settings, Animations**:

- **Run animations**: off makes every animated zone show its first color, still.
- **Frame rate**: 15, 30 (default) or 60 frames per second.
- **Pause animations during night mode** and **Slow animations during night mode** (half speed).

`iridia animations pause`, `resume` and `toggle` pause every animation until you resume it (or the daemon
restarts); there's a keybind for that too.

Animations pause on a zone while something else shows on it: lights off, the PC asleep, Identify, Count
LEDs, Test colors, a color preview, or a keybind that turns the strip off or gives it a color. A keybind
that only changes brightness keeps the animation running at that brightness.

When the monitor's brightness changes, LEDs glide to the new brightness over about 0.3 seconds instead
of jumping, for static patterns too.

## Performance

Animations run on their own thread, which only exists while a zone animates. With only static patterns
the daemon is exactly as idle as before.

- Each device is paced on its own. If sending a frame takes longer than the frame interval, the next frame
  simply comes later (frames are never queued), and a device that keeps being slow gets a lower rate (60,
  30, then 15 fps). The log says so once.
- Every frame goes to OpenRGB as one update for the whole device, with the zones that don't animate
  showing their static colors. OpenRGB 1.0 writes colour updates one by one at the controller's pace,
  so Iridia (speaking SDK protocol 6) waits until OpenRGB says each one is applied before sending the
  next: a controller slower than the frame rate gets fewer frames instead of a queue, and a change,
  like going back to a static pattern, shows at once. With OpenRGB before 1.0 (no protocol 6) Iridia
  uses openrgb-python; those versions merge whole-device updates. Frames that didn't change aren't
  sent.
- Color correction uses lookup tables, rebuilt only when the colors or settings change.
- The log (`iridia log`) shows when an effect starts, stops or changes on a zone. `iridia animations
  status` shows the frames per second each device actually gets and how long a frame takes, and warns
  when the daemon still runs older code than what's installed.

To measure the cost on your PC: `python3 scripts/bench_animations.py` (in the Iridia folder) runs 6 zones
of 80 LEDs at 30 fps for 10 seconds and prints the CPU it used. Options: `--fps`, `--effect`, `--mode`
(color correction), `--zones`, `--leds`.

## Steppy fades on cheap strips

Some LED chips can't fade smoothly at low brightness: near the dark end, breathing and fades move in
visible steps, whatever the frame rate or length. That's the chips, not Iridia. Keep the Breathing
minimum at 10% or more (the default) to stay above the steppy range, or pick an effect that doesn't go
dark, like Color cycle or Comet with a dim background.
