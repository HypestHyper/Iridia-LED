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
  firewall has to let those through; for lights on another VLAN, see below. If another program
  already uses port 4002, Govee lights can't answer, and the card says so.

## Next to its own app and automations

At the top of a network light's card, *How Iridia uses it*:

| | |
| --- | --- |
| *With the rest* (the default) | Like a strip: wallpaper colours, monitor brightness, lock, sleep, night mode, scenes, keybinds, notifications |
| *Only when I change it* | Iridia sends its colour and brightness only at the moment you change them on its card (or on a Favourites card with it), and switches it on or off **only when you press its ⏻ button**: its own app and automations (a Google Home routine that switches it on with the TV, say) stay in charge. Wallpaper changes, the monitor, lock, sleep, night mode, scenes and notifications leave it alone. While its ⏻ is off, colour changes wait, since a light may switch itself on when it gets a colour. Your choice stays saved, but isn't sent again by itself (not after a restart either) |

To have Iridia send it nothing at all, turn off the switch on the left of its card.

## Using a light only now and then

The card's header and two switches (under Brightness) decide how much Iridia does with it. They work
for any device; the last is for network lights only.

| | |
| --- | --- |
| The switch on the left of the card | *Let Iridia control it*. Off: Iridia sends it nothing at all, so it keeps whatever it shows, and its own app (Govee, WiZ, Google Home) can set it. On again: Iridia's colours come back |
| The round ⏻ button in the header | On (pastel green) or off (pastel red): off, the device is dark. For a network light that's a "turn off" command |
| *On its own: ignore the monitor, night mode, lock and sleep* | Its own brightness (the Manual value), whatever the monitor's brightness, night mode, the lock screen or sleep say. Keybinds, scenes and notifications still reach it |
| *Keep its own colour* | Iridia sets only its brightness and switches it on and off; the colour stays what its own app set. With *On its own* as well, that's only when you ask (a keybind, a scene that turns it off) |

## Lights on another VLAN or subnet

The search (a broadcast for WiZ, a multicast for Govee) stays on your PC's own network: routers don't
pass it on. Lights on an IoT network or another VLAN don't hear it. Under *Other networks*, give their
address (`192.168.20.31`) or their whole network (`192.168.20.0/24`, up to 1024 addresses), and Iridia
asks each address directly at every search, which the router passes on like any other traffic.

The router's firewall has to allow, between the two networks:

| From | To | UDP port | What |
| --- | --- | --- | --- |
| this PC | the lights | 38899 | WiZ: the search, and colours (the light answers from the same port) |
| this PC | the lights | 4001 | Govee: the search |
| the lights | this PC | 4002 | Govee: its answer (to another port, so a firewall that only lets replies back doesn't let it through) |
| this PC | the lights | 4003 | Govee: colours |

Many routers let devices on the main network reach the IoT network and only block the other way: then
only the Govee row from the lights to this PC needs a rule. This PC's own firewall (ufw, firewalld)
has to let UDP 4002 in too: `sudo ufw allow 4002/udp`, or
`sudo firewall-cmd --permanent --add-port=4002/udp && sudo firewall-cmd --reload`.

**Still not found?** Type its address under *Other networks* and press *Test* (or `iridia netlights
test 192.168.20.31`): Iridia asks it as a WiZ and as a Govee light and says what came back, and whether
this PC's firewall is on. If nothing comes back but the address is right, *Add as a Govee light* (or
`iridia netlights add-light govee 192.168.20.31`) drives it without ever needing its answers: commands
from this PC to the light usually get through even when the answers don't. Such a light is listed as
*added by address*, with a ✕ to take it out again. A light that keeps the same address (a
DHCP reservation for it on the router) is the easiest to give: add that one address.

## Command line

```sh
iridia netlights          # on or off, and the lights found
iridia netlights on       # look for them (and keep them as devices)
iridia netlights scan     # look again now
iridia netlights off
iridia netlights add 192.168.20.0/24     # also ask these directly (another VLAN or subnet)
iridia netlights remove 192.168.20.0/24
iridia netlights test 192.168.20.31      # ask one address, say what came back and what may block it
iridia netlights add-light govee 192.168.20.31   # drive it without needing its answers
iridia netlights remove-light 192.168.20.31
```
