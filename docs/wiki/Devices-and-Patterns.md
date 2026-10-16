# Devices, patterns and colors

Everything here is on the **Devices** tab.

<img alt="The Devices tab" src="../screenshots/devices.png" width="420">

## Zones and the Everything card

OpenRGB splits devices into zones: a motherboard has one zone per header, a controller one per channel,
and simple devices (a mouse, a GPU) are one zone for the whole device. Iridia gives every zone its own
card with its own settings.

The **Everything** card at the top changes all zones at once. Where zones differ, it shows *Mixed*;
changing that setting on Everything sets it on every zone. You can still change single zones
afterwards.

Each card's header has a switch (zone on or off), the zone's name with a pencil to rename it, a short
summary, and an arrow to open the details. Names are shared with the Layout and Keybinds tabs.

## Patterns

| Pattern | What it does | Color stops |
| --- | --- | --- |
| **Solid** | One color on every LED | |
| **Gradient** | Blends smoothly from one color to the next along the strip | Where each color sits |
| **Segments** | Blocks of color, one after the other | Where each block ends |
| **Center out** | Rings of color from the middle of the strip to both ends | Where each ring ends |
| **Edges in** | The same, from both ends toward the middle | Where each ring ends |
| **Alternating** | LED by LED: color 1, color 2, color 1... | |
| **Painted** | Every LED its own color, painted by hand | |

Switch **Pattern** to *Animated* for an animated effect instead (Breathing, Comet, Fill, Embers,
Rainbow, Rainbow vomit, Color cycle); see [Animations](Animations.md). The strip preview under the
pattern shows exactly what your LEDs will show, animated or not.
Click **Edit layout** to drag the color stops along the preview (or drag the diamonds on the Layout
tab). **Reverse** flips the pattern end for end; **Mirror** draws it on the first half and mirrors it
onto the second, for a symmetric look.

While you edit a **Segments** layout, Iridia shows how many LEDs each color gets ("80 LEDs: 27 + 27 +
26"). **Space evenly** splits them as evenly as whole LEDs allow; when the LED count doesn't divide
evenly, the first parts get one LED more, and Iridia says so. When the parts are only 1 or 2 LEDs apart
(easy to miss on the strip), it points that out too.

## Choosing colors

- **Wallpaper colors** are the colors Iridia found in your current wallpaper, the most important first.
  Picking "wallpaper color 2" means "whatever is second in the current wallpaper", so it changes with
  the wallpaper.
- **Saved colors** are fixed colors you saved. Click **+** to pick a new one; right-click one to delete
  it.
- With *Solid* you pick one color. With the other patterns you pick several, and the numbers on the
  swatches show their order.

**Iridia remembers your picks per wallpaper.** Whatever you choose, for all zones or single zones, is
stored with the current wallpaper and comes back when you return to it. A wallpaper you never picked for
simply follows its own colors. *Status, Reset saved colors for this wallpaper* forgets the picks for the
current image; *Settings, Forget all saved wallpaper colors* forgets all of them.

On the **Status** tab, clicking a wallpaper color or *Custom color…* applies it to every zone at once.

## The color picker

The color picker has a square or a wheel, H S V and R G B sliders, and a hex field. While it's open, the
strip shows the color live; when it closes, the strip goes back to what it was until you click *Select*.

- **Your saved colors** and **Recently used** (your last 16 picks) are one click away.
- **Save color** adds the current color to your saved colors.
- **Exact color** sends the hex exactly as picked, skipping color correction (see
  [Color correction](Color-Correction.md#exact-colors)). Exact colors have a small dot on their swatch
  everywhere.
- On zones with color correction, a third swatch shows what is actually sent to the strip.

## Painting

The **Painted** pattern colors single LEDs. On a zone card, painting tools appear under the preview:

| Tool | What it does |
| --- | --- |
| **Paint** | Click or drag over LEDs to give them the first paint color |
| **Erase** | Gives LEDs back the zone's own color (the one set on the zone or on Everything), not black |
| **Gradient** | Click the first LED, then the last: a blend from the first to the second paint color |
| **Fill** | The whole strip in the first paint color |
| **Clear** | Erases every LED |

The two wells next to the tools are the paint colors; click one to change it. Under the tools, your saved
and recent colors work as quick picks: click for the first color, right-click for the second. The same
tools, with more room, are on the [Layout](Layout.md) tab.

## Brightness

| Setting | What it does |
| --- | --- |
| **Follow monitor brightness** | LED brightness follows your monitor over DDC/CI. Off: the *Manual* value is used. |
| **Range** | Maps the monitor's 0 to 100% onto this range, for example 20 to 80% so the LEDs never go fully dark or fully bright |
| **Invert** | Brighter LEDs when the monitor is darker (bias lighting) |
| **Gamma correction** | Makes dim levels look more even on strips with a harsh response. Not used in Calibrated mode. |

Night mode can cap the brightness on top of this; see [Night mode, sleep and freeze](Night-Sleep-and-Freeze.md).

## Splitting a strip into parts, and single LEDs

Open **Advanced: split this strip, set single LEDs** on a zone card (it stays closed until you need it).

- **Add divider** splits the biggest part in two. Drag the handle under a divider to move it; it snaps
  to whole LEDs. The numbers above the strip are the part numbers.
- **Space evenly** gives every part the same number of LEDs, as far as whole LEDs allow. "80 LEDs:
  27 + 27 + 26" shows the sizes; when the count doesn't divide evenly Iridia says which parts get one
  more, and when parts are only 1 or 2 LEDs apart (easy to miss on the strip) it warns you.
- Each part shows one of:
  - **Same as the strip**: whatever the strip shows there (its pattern or effect, wallpaper colors
    and all). A part in the middle can keep the strip's look while the parts around it do something else.
  - **Its own pattern**: any static pattern with its own colors, drawn over just that part.
  - **Its own effect**: any animated effect with its own colors and settings, over just that part.
    The rest of the strip stays as it is, static or animated.
  - **Off**.
  **Settings** next to a part opens its pattern or effect and colors; **✕** removes a part (it joins
  the one before it).
- **Single LEDs**: click **Set LEDs**, pick **Color** (and the color in the well next to it), **Off**
  or **Back to normal**, then click or drag over LEDs on the strip. A set LED shows its color over
  everything else, for example one white LED between two bars. A dot under the strip marks them;
  **Clear all** removes them.

Changing the LED count moves the dividers along with it; single LEDs keep their number. Brightness and
color correction apply to the whole strip, parts included. The same is possible from the command line
with `iridia split` (see [Command line](Command-Line.md)).

## Other tools on a zone card

- **Identify** lights only this zone white for a while, to see which strip it is.
- **Count LEDs** walks one lit LED along the strip to find its real length, and can resize the OpenRGB
  zone on addressable headers.
- **LEDs** sets how many LEDs Iridia sends to. Normally the count OpenRGB reports.
- **Color correction** chooses Off, Palette or Calibrated (see [Color correction](Color-Correction.md)).
- **Strip type and wiring** (see [Strip types](Strip-Types.md)).

## Devices that show one color

Some devices have no *Direct* mode in OpenRGB and can only show one color for the whole device. Iridia
picks the best mode they have and sends the first color of the pattern; the card says so.
