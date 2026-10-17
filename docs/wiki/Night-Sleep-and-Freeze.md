# Night mode, sleep and freeze

## Night mode

In **Settings, Night mode and sleep**, switch on *Night mode*, set a time window and a brightness cap.
During the window no zone goes brighter than the cap; outside it nothing changes. The window can cross
midnight (23:00 to 07:00). Times are 24 hour.

```bash
iridia night on --start 23:00 --end 07:00 --cap 20
iridia night off
iridia night toggle
iridia night show
```

## LEDs off while the PC sleeps

*Turn the LEDs off while the PC sleeps* switches every LED off right before the PC suspends and back on
after it wakes. It listens to systemd-logind (with `gdbus`), so it works on any desktop, and it briefly
holds the suspend until the LEDs are really dark. After waking it re-sends the colors twice, a few
seconds apart, because USB controllers sometimes come back late.

On systems without logind the option has no effect; if Iridia can't watch for suspend, its log says so
(`iridia log`).

## Lock and idle

Settings, *Lock and idle*: what the LEDs do **when the screen locks** and **after N minutes without
input**: *Keep*, *Dim* (to the *Dim to* percentage) or *Off*. Both are *Keep* until you change them.
The LEDs fade out over 2 seconds and come back in half a second. When both apply, the darker one
wins; lights off and sleep still come first, and night mode's cap still applies. *Try it* shows the
lock setting (or off, if that's *Keep*) for 5 seconds. A strip can ignore all this: *Stay lit when the
screen locks or you're away*, under Brightness on its card.

How Iridia sees it, without any setup:

| | Seen through |
| --- | --- |
| Locking | logind's LockedHint (GNOME, KDE, ...), ScreenSaver signals, and screen lockers that tell nobody (hyprlock, swaylock, gtklock, waylock, i3lock, ...) for as long as they run |
| Idle time | GNOME (Mutter), KDE and others (ScreenSaver), X11 (`xprintidle`), or logind's IdleHint |

The window shows what it found. On compositors with no idle time to read (Hyprland, Sway, ...) let
your idle daemon tell Iridia; *Lines for hypridle or swayidle* in the same section (or
`iridia session hooks`) has them ready to copy:

```ini
# hypridle (~/.config/hypr/hypridle.conf)
listener {
    timeout = 300
    on-timeout = iridia idle on
    on-resume = iridia idle off
}
```

```bash
# swayidle (Sway config)
exec swayidle -w timeout 300 'iridia idle on' resume 'iridia idle off'
```

Iridia then uses that daemon's timeout. `iridia lock on|off` does the same for a screen locker Iridia
doesn't know.

## Lights off by hand

```bash
iridia lights off
iridia lights on
iridia lights toggle
```

## Freeze

**Freeze colors** (the button in the header, or the command) keeps the current colors and ignores
wallpaper changes until you unfreeze. Useful while you try wallpapers, or when a slideshow changes the
wallpaper all the time.

```bash
iridia freeze
iridia unfreeze
iridia freeze toggle
```

While frozen, everything else keeps working: brightness, night mode, keybinds and your changes in the
window.
