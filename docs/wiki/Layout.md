# Layout

The **Layout** tab draws every enabled zone as a strip, one dot per LED, in the colors it shows right
now. Draw your strips where they really are (behind the desk, around the monitor, along the shelf) and
you get a live picture of your room you can paint on.

<img alt="The Layout tab" src="../screenshots/layout.png" width="420">

LED 1, where the data wire enters, is marked with a small **1**; the last LED shows its number too.

## The toolbar

The floating toolbar at the bottom holds the tools (hover for their names), the two paint colors, zoom,
*Fit* (show everything) and the layout lock.

| Tool | What it does |
| --- | --- |
| **Arrange** | Move strips and turn their sections |
| **Find LEDs** | Light a single LED on your real strip |
| **Paint** | Color LEDs by clicking or dragging |
| **Erase** | Give LEDs back the zone's own color |
| **Fill** | Color a whole strip |
| **Gradient** | Click the first LED, then the last |

Mouse wheel zooms, dragging the empty background pans.

## Moving, bending and turning

- **Move:** with Arrange, drag a strip.
- **Bends** split a strip into sections that run in different directions, for corners. Right-click a
  LED and choose *Add a bend here*, or use *Add a bend at LED* in the side panel. Every bend is ringed
  on the canvas, whatever tool you use.
- **Turning:** select a strip with Arrange and each section gets a round knob: behind LED 1 for the
  whole strip, and on the outside of each corner for a bend (labelled B1, B2...). Turn a knob to turn
  that section and everything after it around the corner. It snaps to 15 degrees; hold **Shift** for
  any angle.
- **The side panel** has 90 degree turn buttons, the start direction, and for each bend the LED it's at
  and its exact direction, with a button to remove it. *Straighten* (right-click) removes every bend.
- **Flip LED order** is for a strip whose data enters at the other end: the drawing flips, nothing
  changes on the hardware.

## Real lengths

Set **LEDs per metre** in the side panel (it's printed on the strip or in its listing: 30, 60, 96 and
144 are common). The strip is then drawn at its real length, so strips of different densities line up
like they do in your room. For 12V strips where one chip drives a group of LEDs, set *LEDs per pixel* on
the Devices tab (see [Strip types](Strip-Types.md)) and each dot is drawn as one group.

## Finding LEDs on the real strip

The **Find LEDs** tool (the target icon) lights exactly one LED on your real strip and turns the rest
dark. Click a LED, or drag along a strip, and watch where the light is in your room. It's the easiest
way to see where a corner really is: find the LED at the corner, then right-click to add a bend there.
Picking another tool brings your colors back.

## Painting on the layout

Paint, Erase, Fill and Gradient work like on the Devices tab, but on the drawing. The first stroke on a
zone switches it to the **Painted** pattern, starting from the colors it was showing, so nothing jumps.
Erase gives LEDs back the zone's own color, not black.

While a paint tool is active, the side panel shows **Paint colors**: your saved colors and the colors you
used recently. Click one for the first paint color, right-click for the second (only Gradient uses the
second), and **+** saves the first paint color.

## Color stops

Select a strip with a Gradient, Segments, Center out or Edges in pattern and drag the diamonds along it
to move where colors change. It's the same as *Edit layout* on the Devices tab.

## Clones, hiding and locking

- **Clone** (right-click) is for two strips on one wire that show the same thing. The clone shows the
  zone's colors and can be placed, bent and flipped on its own; nothing extra is sent to the hardware.
- **Hide** a strip (right-click, or the panel) to get it out of the way; it keeps its place and colors.
  With nothing selected, the side panel lists every strip with an eye button to show or hide it.
- **Lock this strip** (panel or right-click) or the **layout lock** in the toolbar stop strips from
  moving, so painting and dragging stops can't nudge them.

## Names

Rename a strip with the pencil in the side panel; the name is shared with the Devices and Keybinds tabs.
When two zones have the same name (two controllers with a "Channel 1"), the device name is added in
brackets.

The layout is saved in `~/.config/iridia/layout.json` and included in setups.
