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
