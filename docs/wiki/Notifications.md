# Notifications

The *Notifications* tab (the lightning bolt): flash some LEDs when a desktop notification comes in. Only the LEDs you
pick flash; the rest of the strip keeps showing what it was showing, animations included. Iridia
only sees which app sent a notification and whether it's urgent, never its title or text, and keeps
nothing but the app's name (so you can pick apps).

## Which LEDs

Pick a strip (switched-off ones aren't listed), then which part of it, and press *Add* (or *Remove*, to take those LEDs out again: say,
LEDs 5 to 6 out of 3 to 7):

| | |
| --- | --- |
| *All of it* | The whole strip |
| *Part N* | One of the parts you split the strip into (the *Advanced* part of its card). If you split it differently later, part N is whatever part N is then |
| *Some LEDs* | A range, like LEDs 3 to 12 (numbers start at 1). Next to it: how many that is, how many the strip has, and its middle LED (two LEDs, like 10–11, when the count is even) |

Add as many as you like, on as many strips and devices as you like: they all flash together. On the
Devices tab, a thin line under a strip's preview marks the LEDs that flash, and *Notifications: LEDs …*
under it opens this tab.

Or pick them on the map: *Edit on the map* opens the **Layout tab's Notifications tool** (the
lightning bolt in its toolbar). Click or drag over LEDs to choose them; start on a ringed one to take
LEDs out. Chosen LEDs show the colour they'll flash in, and *Play* shows the flash on the map and on
your real strips. *All settings* goes back to the Notifications tab. *Try it*, at the bottom right of
the Notifications tab, flashes them from there.

## Through the room, from A to B

On the same tool, two points **A** and **B** (drag them anywhere, or *Put A and B at the ends*). With
*Run through the room from A to B* on, a moving flash goes over your LEDs by where they really are,
across every strip at once, and only between A and B: LEDs outside that stretch stay out of it. The
Ripple spreads out from A, as far as B. Pulse and Flash light every chosen LED either way. Off, a
moving flash runs along each strip's own LEDs instead.

## How they flash

| | |
| --- | --- |
| *Effect* | *Pulse* (two soft swells), *Flash* (three blinks), *Sweep* (a band running along), *Comet* (a bright head with a tail), *Fill* (fills up, then fades) or *Ripple* (a ring spreading out) |
| *Direction* | For the moving ones: *A to B*, *B to A*, *A to B and back*, or *From the middle out* |
| *Band* | How many LEDs light at once (1 to 30): the band, the comet's tail or the ripple's ring, with about one LED of soft edge, however long the stretch |
| *Plays*, *Length* | How many times it plays (1 to 5), each 0.5 to 5 seconds |
| *Brightness* | 10 to 100% of the strip's brightness |
| *Colour* | *Wallpaper* (the colour your LEDs follow), *One per app* (each app gets its own colour, the same every time) or *Custom* (picked with the colour wheel) |
| *Urgent notifications flash red* | Whatever the colour setting |
| *Urgent ones use* | The same effect, or one of their own |
| *Apps with their own look* | An app's own effect and colour (pick the app, the effect, the colour, *Add*); every other app uses the settings above |

The flash follows the strip's brightness (never dimmer than 35%, so you can see it), and a strip that
is dark (switched off, the screen locked with *Off*) stays dark. Notifications that come in a burst
make one flash.

## Which apps

*Every app*, *Only these* or *All but these*. Apps show up as buttons once they've sent a notification;
pick the ones you mean. *Not while Do Not Disturb is on* and *Not during night mode* keep it quiet.

Do Not Disturb is read from GNOME, KDE Plasma (and other desktops whose notification server says
when it's inhibited), mako, dunst and SwayNC.

## How Iridia hears them

Every desktop shows notifications the same way: apps send them on the session bus to whoever shows
them (GNOME Shell, Plasma, XFCE, Cinnamon, mako, dunst, SwayNC, ...). GNOME's own apps use GNOME's
own channel, which is watched too. Iridia listens with `dbus-monitor` (the dbus tools package), or
`busctl` (part of systemd) where that's missing. Nothing listens while this is off or no LEDs are
chosen. The window says when neither tool is there.

Iridia's own notifications (a new version) don't flash.

## Command line

```sh
iridia notify                           # settings, and what it's listening with
iridia notify add Desk part 2           # a strip's name, Device/Zone, a device or all
iridia notify add Case leds 1-10
iridia notify on --effect sweep --color app --duration 2
iridia notify --effect comet --direction abba --band 4 --plays 2 --brightness 80
iridia notify --layout on                # run from A to B (set them on the Layout tab)
iridia notify test                      # flash now (--urgent: as an urgent one)
iridia notify clear                     # no LEDs
iridia notify off
```
