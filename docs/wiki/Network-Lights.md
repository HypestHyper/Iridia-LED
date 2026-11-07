# Network lights (WiZ, Govee)

Iridia can drive **Philips WiZ** and **Govee** lights on your Wi-Fi as well as what OpenRGB drives.
It talks to them over your home network with their own local protocols: no account, no cloud,
nothing to pair or reset. They keep working in their own apps and in Google Home (Matter) as before.

## Switching it on

Devices tab, *Network lights*, *Look for WiZ and Govee lights* (or `iridia netlights on`). Lights
answer within a few seconds. Each one becomes a device with its own card, like a strip: wallpaper
colours, a pattern's colours, brightness, monitor brightness, scenes, night mode, lock and sleep all
work the same. Rename it on its card. *Look again* (`iridia netlights scan`) searches right away;
otherwise Iridia looks once a minute, and gives each light its colour again then (a light switched off
at the wall shows it again within a minute).

| | What it needs |
| --- | --- |
| Philips WiZ | Nothing: every WiZ light on the network answers |
| Govee | *LAN Control* switched on for each light: Govee app, the light, settings (the gear), *LAN Control*. Most Wi-Fi lights and strips from the last few years have it |

## What to expect

- **One colour per light.** A Govee strip shows one colour too (its segments use another protocol).
  A pattern with several colours shows their average.
- **Fades, not fast animations.** A light gets a new colour at most 10 times a second (Govee: 5), the
  newest one winning, and only when it changes. Breathing and colour cycle look right; comet and
  rainbow come out as a slow colour wash.
- **Lock and sleep turn them off too,** like your strips. A light that should stay on when the screen
  locks: its card, *Advanced*, the lock and idle setting.
- **Same network.** Iridia finds lights with a broadcast (WiZ, port 38899) and a multicast (Govee,
  239.255.255.250, answers on port 4002), so they have to be on the network your PC is on, and a
  firewall has to let those through. If another program already uses port 4002, Govee lights can't
  answer, and the card says so.

## Command line

```sh
iridia netlights          # on or off, and the lights found
iridia netlights on       # look for them (and keep them as devices)
iridia netlights scan     # look again now
iridia netlights off
```
