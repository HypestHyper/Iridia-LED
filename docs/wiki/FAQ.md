# FAQ

**Does it work on my desktop?**
Iridia doesn't depend on a desktop. It finds the wallpaper on Hyprland, Sway, niri (with swww/awww or
swaybg), GNOME, KDE, XFCE, Cinnamon, MATE and X11 window managers with feh, nitrogen or xwallpaper, plus
Caelestia, Noctalia and waypaper. Anything else works through the watch folder or a fixed image.

**Which LEDs does it support?**
Whatever OpenRGB supports: ARGB headers, RGB controllers, RAM, keyboards, mice, GPUs, and more. See
[Strip types](Strip-Types.md) for the kinds of strips.

**Do I need to keep the window open?**
No. The daemon does the work; the window only changes settings.

**Does it animate?**
Yes, since 1.2.0: breathing, comet, fill, embers, rainbow, rainbow vomit and color cycle, per zone, also
through the room following the layout. Static patterns are still the default. See
[Animations](Animations.md). Before 1.2.0 Iridia was static only: a static setup
costs next to nothing in CPU. Colors change when the wallpaper, brightness or your settings change.

**How much CPU does it use?**
Almost none. The daemon sleeps between checks and only sends to OpenRGB when the colors actually
change. Wallpaper colors are extracted once per image and cached.

**Can I use one color for everything and ignore the wallpaper?**
Yes. On the Status tab, pick *Custom color…*, or click a saved color. To stop following wallpaper changes
for a while, use **Freeze colors**.

**Can different strips show different things?**
Yes. Every zone has its own pattern, colors, brightness and correction. The Everything card is only a
shortcut to change them all.

**Can I switch strips from my keyboard?**
Yes, through your desktop's shortcuts. See [Keybinds](Keybinds.md).

**Does it work with OpenRGB as a Flatpak or AppImage?**
Yes. Iridia starts the Flatpak (`org.openrgb.OpenRGB`) by itself. For an AppImage, set
`openrgb.server_command` to the command that runs its server. Or start OpenRGB yourself and set
`openrgb.start_method` to `off`: Iridia only talks to its network port.

**Do I need systemd?**
No. By default the Iridia daemon starts OpenRGB's server itself, and the daemon can start from your
compositor's config or XDG autostart. See [Start at login](Start-at-Login.md).

**My LEDs show random colors after a reboot.**
Usually OpenRGB started before it could see the hardware, or two OpenRGB instances are running. See
[Troubleshooting](Troubleshooting.md#leds-show-random-colors-after-boot).

**Does it work on Fedora Atomic (Silverblue, Bazzite) or other immutable distributions?**
The installer needs GTK 4 and PyGObject on the host. Layer them (`rpm-ostree install gtk4
python3-gobject python3-cairo`) or run Iridia's window in a toolbox; the daemon and command line only
need Python.

**Can OpenRGB run on another machine?**
Yes. Set `openrgb.host` and `openrgb.port` in `config.json`. Iridia never starts or restarts anything
for a remote host; start OpenRGB there.

**Where are my settings?**
`~/.config/iridia/`. See [Configuration](Configuration.md). Save them all at once with a
[setup](Setups-and-Backups.md).

**Why is the `iridia` command not found?**
The installer links it into `~/.local/bin`, which some shells (fish, for one) don't have on their
`PATH` yet. See [Installation](Installation.md#running-it), or use the full path
`~/.local/share/iridia-venv/bin/iridia`.

**What is the window's class or app id, for window rules?**
`io.github.HypestHyper.Iridia`. For example, to make the window float on Hyprland:
`windowrule = float, class:^(io\.github\.HypestHyper\.Iridia)$`
