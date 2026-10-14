# Strip types

Iridia drives whatever OpenRGB can drive, but LED strips aren't all alike. Each zone card on the
Devices tab has a **Strip type and wiring** section. Iridia guesses the type from what OpenRGB reports
(a zone OpenRGB calls single-color, or a device with one LED, becomes *One color*); you can change it.

## The types

| Strip type | Examples | Wires | How Iridia handles it |
| --- | --- | --- | --- |
| **Addressable 5V** | WS2812B, SK6812, often sold as ARGB, RGBIC or "digital" | 3: 5V, data, GND | Every LED is its own color. Everything works per LED. |
| **Addressable 12V in groups** | WS2811, many COB strips | 3: 12V, data, GND | One chip drives a group of LEDs (often 3), so a group is one pixel and OpenRGB counts pixels. Set **LEDs per pixel** and the Layout tab draws the real length. |
| **One color** | Plain 5050 12V RGB strips, motherboard 12V RGB headers | 4: 12V, R, G, B | The whole strip is one color. Patterns, painting, color stops and Count LEDs are hidden, and the strip shows a solid color. |
| **RGBW addressable** (experimental) | SK6812 RGBW | 4 (with a white channel) | See below. |

WS2815 strips (12V with a backup data line) behave like 5V addressable strips on an ARGB header.

## Color order

Strips don't all expect their channels in the same order. A WS2812B wants green, red, blue; some
clones and many WS2811 strips want red, green, blue or another order. On the wrong strip, red shows up
as green, and so on.

1. Click **Test colors**. The strip lights red at the LED 1 end, green in the middle and blue at the far
   end. A one-color strip cycles red, green and blue instead.
2. If that's not what you see, change **Color order** until it is. The test updates live.
3. Click *Stop test* (it also ends by itself after a minute).

## Power limit

A long 5V strip at full white pulls a lot of current: about 60 mA per LED, so 6 A for 100 LEDs. Too much
for the power supply or the controller and the far end turns orange or pink, or the controller resets.

Enter your power supply's amps (a little under its rating) as **Power limit**. Iridia estimates the
current for the colors it's about to send and, only when they'd go over the limit, dims that zone just
enough. Normal colors look the same; only near-white, full-brightness scenes get dimmed. The card shows
the estimate (about now, and at full white) while OpenRGB is connected.

The estimate assumes 60 mA per LED at full white; strips differ, so set `ma_per_led` on the zone in
`config.json` if yours is known to draw more or less. One-color strips have no limit (Iridia can't know
how long they are).

## RGBW strips (experimental)

OpenRGB sends three bytes (R, G, B) per LED; RGBW strips like the SK6812 RGBW read four (G, R, B, W).
Sent normally, the colors shift more and more along the strip.

With the type set to *RGBW addressable*, Iridia takes the white out of every color itself, lays the bytes
out the way the strip reads them and packs them into the three-byte stream. The OpenRGB zone then has to
be a third longer than the strip (120 RGBW LEDs need 160); the card shows a button to resize it.

This assumes the header sends data like it would for a WS2812B (green, red, blue), which is the usual
case. If colors come out swapped, try *Color order*. Count LEDs doesn't work on these strips; set the LED
count by hand. It hasn't been tested on every controller, so reports are welcome.

## Calibrating other strips

Color correction profiles are made per strip type. Iridia ships **WS2812B** (tuned on a real strip) and
**Neutral** (pure colors, no correction). For any other strip, make a copy of Neutral in *Settings,
Color calibration* and tune it by eye; see [Color correction](Color-Correction.md#calibration-profiles).

## Strips Iridia can't drive

- **Single-color and tunable-white (CCT) strips** have no RGB to set.
- **Strips on Wi-Fi controllers** (WLED, Govee, Hue...) work only if OpenRGB supports that controller;
  Iridia then sees it like any other device.
