# Notifications

Settings, *Notifications*: flash some LEDs when a desktop notification comes in. Only the LEDs you
pick flash; the rest of the strip keeps showing what it was showing, animations included. Iridia
only sees which app sent a notification and whether it's urgent, never its title or text, and keeps
nothing but the app's name (so you can pick apps).

## Which LEDs

Pick a strip, then which part of it, and press *Add*:

| | |
| --- | --- |
| *All of it* | The whole strip |
| *Part N* | One of the parts you split the strip into (the *Advanced* part of its card). If you split it differently later, part N is whatever part N is then |
| *Some LEDs* | A range, like LEDs 3 to 12 (numbers start at 1) |

Add as many as you like, on as many strips and devices as you like: they all flash together.

## How they flash

| | |
| --- | --- |
| *Effect* | *Pulse* (two soft swells), *Flash* (three blinks) or *Sweep* (a band running along the LEDs) |
| *for* | How long, 0.5 to 5 seconds |
| *Color* | *Wallpaper* (the colour your LEDs follow), *One per app* (each app gets its own colour, the same every time) or *Custom* |
| *Urgent notifications flash red* | Whatever the colour setting |

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
iridia notify test                      # flash now (--urgent: as an urgent one)
iridia notify clear                     # no LEDs
iridia notify off
```
