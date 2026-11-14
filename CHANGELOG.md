# Changelog

## 1.4.0 — 2026-11-14

A new look for the window: quieter, so your lights' own colours are what stands out.

- **Home** brings Status and Favourites together. At the top: your wallpaper, its colours (click one
  to use it on all your lights) and brightness, Freeze and the lights' power, glowing from below in the
  colours your strips show right now. Saved colours and the colour-correction preview fold away under it;
  the daemon's details moved to Service.
- **A side rail** instead of ten tabs in a row: Home, Devices, Layout and Scenes, then the pages you set
  up once under *Setup*, Settings at the bottom. In a narrow window it shows just the icons.
- **Devices is a compact list:** a row per strip with a line of the colours it shows, its brightness and
  power; its menu (⋮) has Favourites, Hide and Rename, and a click opens the rest. A network light is one
  row with its own name. Range, invert, gamma and colour correction fold under *More*.
- **Layout:** the strips glow on the wall in their colours, the strip list is plain text, and the how-to
  is one line with the rest behind **?**.
- **No bar at the bottom any more:** Restart daemon and the folders are on Service, Refresh is gone (the
  window updates itself), and Ctrl+Q closes the window like its close button.
- **Calmer colours:** grey surfaces instead of tinted ones, the accent only where there's light, power
  buttons lit in it when on (no pastel green and red), and a blue window until there are colours.
- **Material 3 Expressive touches:** a device's strips are one grouped list (2px apart, rounded at the
  group's ends, an open row fully rounded); the selected page in the rail sits on a pill; power buttons
  are round and outlined when off and a filled square when on; sliders have a 16px track with a gap
  round a thin handle; headings are heavier; Freeze and the lights' power on Home are the bigger size.
- **Smooth:** the page you pick fades in on its own instead of crossfading with the old one (which drew
  two whole pages every frame), only colours and corners animate so nothing jumps, and a row's arrow turns
  as it opens; every frame measured well within 60 fps. Reduce motion turns all of it off.
- The new texts are in every language: British, Pirate, Posh and Omelette.
- Set-up pages use plain sections instead of boxes, shorter texts, and the status chip only shows when
  something needs you. The wallpaper picture stays sharp on HiDPI screens.

## 1.3.15 — 2026-11-13

- **Text in the window can be selected and copied** (drag over it, then Ctrl+C or right-click, Copy):
  help text, names, values, paths, error messages. Text on buttons, menus and clickable headers stays
  as it was, so clicks still work. The selection takes the theme's colours.
- **Strips hidden on the Devices tab stay out of the Layout tab too** (the room and its strip list).
  Their place in the room is kept for when you show them again, and room effects still reach them.

## 1.3.14 — 2026-11-13

- **One-click updates for the system packages (Arch, `.deb`, `.rpm`):** *Update now* on the Updates tab
  downloads the new release's package for your system, checks it against its SHA-256, and installs it
  with pacman, apt, dnf or zypper through your system's password prompt, then restarts the daemon and the
  window. Before, it only opened the download page.
- **Update from the notification:** the "new version" notification has an *Update now* button (for the
  install.sh install and the packages alike); a second notification says when it's done.

- **The window uses less CPU while it sits open:** the Favourites tab checked the window's width on every
  screen frame (60 times a second, on any tab); it now only reacts when the width changes. Status
  updates no longer rebuild the notification chip on every device card each poll, which laid the whole
  window out again every 2 seconds. Loading animations draw at 30 frames a second instead of the
  screen's rate (the "daemon isn't running" page used about 8% of a core, now about half that).

## 1.3.13 — 2026-11-11

- **The window shrinks again with Favourites open:** the card grid made the window as wide as its
  columns, so it couldn't get narrower than it was and the grid never dropped columns (since 1.3.10). It
  now follows the window, wide cards included, and never needs more room than there is.
- **A card's brightness** shows what the strips really show: the monitor's level for strips that follow
  it, their own for the rest (it showed 0% when only some followed the monitor).
- **Window buttons** (minimize, maximize, close) are off by default on Hyprland, Sway, niri, i3 and river,
  where the compositor handles windows; Settings, Appearance turns them on.

## 1.3.12 — 2026-11-11

- **Favourites cards:** a wide or large card puts its switch rows two per line only when there are four
  or more; with fewer, each row spans the card, so a card with one or two switches isn't squeezed into
  half its width ("Contr…"). Short names always show in full.

## 1.3.11 — 2026-11-11

- **Favourites cards, clearer:** every on/off setting on a card is a row with its name and a real switch,
  so what's on is plain to see (no more wide buttons that look the same either way); one per line on
  small and tall cards, two on wide and large ones. The brightness slider has its icon and value, shows
  the monitor's level while the strips follow it, and moving it sets their own brightness (before, it
  seemed to do nothing while they followed the monitor). Effect and speed have their icons too. New: an
  *Iridia controls it* switch. Looks, Scenes and Switches never come out empty: with none picked, a
  card shows all looks and scenes, and the common switches. A pencil on every card, small ones too.

## 1.3.10 — 2026-11-11

- **Favourites cards, simpler:** the card editor is chips you tap (strips, what's on the card, and then
  which looks, scenes and switches) instead of rows of checkboxes; on a card, *Follow the monitor* and
  *Stay lit* are small chips, not a row each. New on cards: a *Speed* slider under the effect (slow to
  fast, whatever the effect), and *Scenes*: a chip per scene to switch it on or off. Cards are sized to
  what's on them.
- **Each strip's card:** the switch on the left now means *Let Iridia control it* (off: Iridia sends it
  nothing and it keeps whatever it shows), and a new round ⏻ button in the header turns it on or off
  (pastel green on, red off). For a network light set to *Only when I change it*, ⏻ sends one on or off
  command when pressed, and colour changes wait while it's off; before, its switch was ignored. *Not at
  all* is gone from *How Iridia uses it*: that's the switch now.
- **Favourites cards:** changes from a card now reach network lights set to *Only when I change it*;
  every control you tick shows, whatever the size (a card grows taller to fit); a pencil on each card
  changes it (right-click a small one); and on/off is the same ⏻ button. A brightness change on an *Only
  when I change it* light is sent at the brightness asked for, not the first step of a fade.
- **System packages:** each release now has a package for Arch (and CachyOS, Manjaro, EndeavourOS),
  Debian and Ubuntu, and Fedora and openSUSE, with a `SHA256SUMS` file. The package manager brings in
  what Iridia needs and removes it all again; Iridia lives in `/usr/lib/iridia`, with a systemd user
  unit, the launcher and icons in `/usr`. Installed that way, the Updates tab says when there's a new
  version and opens its download page, *Uninstall* says how to remove the package, and `iridia doctor`
  notices an older install.sh copy left in your home folder. Every push builds the packages and installs
  each one on a fresh Arch, Debian, Ubuntu and Fedora (the command line, the daemon, the window, an
  upgrade and removing it).

## 1.3.9 — 2026-11-09

- **Favourites:** a tab (right after Status) with the controls you use most, on a grid you arrange
  yourself. *Cards* you make: a title, some strips or all of them, and just the controls you want (on/off,
  one brightness, colours with a popup for saved colours and the colour wheel, follow the monitor,
  stay lit, effect, look chips, switch chips); presets for a colour, brightness, looks or switches
  card. Looks, setups and switches can go there on their own too. Tiles are small, wide, tall or large;
  *Arrange* drags them into place. The ★ on a strip's card makes a card for it.
- **Scenes, as many as you like:** each one "when this happens, these strips look like this", made in
  an editor on the Scenes tab: a name, when (anything fullscreen, or some apps in front), which strips
  (or everything) and the look. Switch each on or off, try it, and move it up or down: the higher one
  wins on a strip two scenes share. Your scenes from before carry over.
- **Safer without XDG_RUNTIME_DIR:** where it isn't set (cron, `sudo -u`, some SSH sessions), the
  daemon's socket, lock and pid files now go in `/run/user/UID` or `~/.cache/iridia/run` instead of the
  shared `/tmp`, where another user could have put a file of their own under the same name first.
- **Ready for newer Python and GTK:** the code uses today's Python forms throughout (checked by ruff
  in CI, now on a fixed ruff version), the tests fail on anything Python deprecates in Iridia's code,
  the window asks for GTK 4's own Gdk and Pango up front, and the tab bar's scroll arrows no longer
  make GTK lay the window out with no room for them (a warning on every start).
- **OpenRGB on another PC is no longer an option:** Iridia always talks to the OpenRGB on this PC
  (`openrgb.host` is gone from `config.json`; it's removed by itself).
- **Docs:** the window rule to float Iridia on Hyprland for the Lua config and the newer
  `hyprland.conf` syntax; the tab tour, configuration and command line brought up to date.
- **Hide strips:** the eye on a strip's card hides one you don't use (a channel with nothing plugged in);
  it waits under *Hidden* at the bottom of the Devices tab and stays out of the lists elsewhere.
- **Looks:** one-tap changes you name yourself ("Movie": everything at 15%), for some strips or all:
  off, dimmer, one colour or an effect. On and back off like a keybind, so settings don't change. From
  a key too: the Keybinds tab, or `iridia look NAME`.

## 1.3.8 — 2026-11-07

- **Philips WiZ and Govee lights on your Wi-Fi:** Devices tab, *Network lights* (or `iridia netlights
  on`). Iridia finds them over the network with their own local protocols, with nothing to pair, and
  each becomes a device like a strip: wallpaper colours, brightness, scenes, night mode, lock and sleep.
  They keep working in their own apps and in Google Home. Govee lights need *LAN Control* on in the
  Govee app. Lights on another VLAN or subnet (an IoT network) are asked directly: give their address
  or network under *Other networks* (`iridia netlights add 192.168.20.0/24`). *Test* asks one address
  and says what came back and what may block it (this PC's firewall, the router); a light whose
  answers don't get back can be added by address and driven anyway (`iridia netlights add-light`).
- **Network lights next to their own app and automations:** *How Iridia uses it* at the top of a light's
  card: *With the rest*, *Only when I change it* (colour and brightness only when changed on its card,
  never on or off, so a Google Home routine that switches it with the TV stays in charge) or *Not at
  all*. A light added by address opens its card right away.
- **Use a device only when you want, per device** (its card, Brightness): *Let Iridia control it* (off:
  Iridia sends it nothing, so its own app can set it), *On its own* (ignores the monitor's brightness,
  night mode, lock and sleep) and, for network lights, *Keep its own colour* (only brightness and
  on/off).

## 1.3.7 — 2026-11-02

- **Iridia needs Python 3.10 or newer now** (3.8 and 3.9 are no longer supported by Python itself).
  Updating an install made with an older Python builds its environment again with a newer one, by
  itself; if there's none, the update stops and says so, and the installed version keeps working.
- **Scenes:** a different look for the lights while a game or a film is fullscreen, or while an app you
  pick is in front: off, dimmer, one colour or an effect, at a brightness. The lights go back when it's
  gone (after a short wait, so switching away for a moment doesn't make them flicker), and your
  settings never change. Hyprland, Sway, KDE Plasma (a KWin script loaded while it's on) and X11 say
  what's in front as it happens; anywhere else, apps get their look while they run. A *Scenes* tab and
  `iridia scenes`.

## 1.3.6 — 2026-10-29

- **KDE Plasma (or GNOME, ...) installed next to Hyprland:** the wallpaper is now the desktop's own.
  Before, Caelestia's or hyprpaper's files from the Hyprland session were asked first and kept naming
  the old wallpaper.
- **Notification flashes, more of them:**
  - **On the Layout tab:** a Notifications tool (the lightning bolt) shows which LEDs flash. Click or
    drag over LEDs to add them, or start on a ringed one to take them out. *Play* shows the flash on
    the map and on the strips.
  - **From A to B:** two points on the map. A moving flash then runs through the room by where your
    LEDs really are, across every strip at once, and only between A and B. It can go A to B, B to A,
    A to B and back, or from the middle out.
  - **Three more effects:** *Comet*, *Fill* and *Ripple*, which spreads from A as far as B.
  - **More settings:** the band (how many LEDs light at once, 1 to 30, with crisp edges, so a sweep
    reads as a sweep even on a short stretch), the length (a slider), how many times it plays, a
    brightness cap, and an effect of their own for urgent notifications.
  - **Apps with their own look:** an effect and a colour for each app you pick.
  - **Their own tab:** the settings moved from Settings to a *Notifications* tab, with *Edit on the
    map* to go to the Layout tab's tool, *All settings* there to come back, and *Try it* floating at
    the bottom right, in view wherever the page is scrolled to.
  - **A custom colour is picked with the colour wheel and sliders,** as everywhere else, for the main
    colour and for each app.
  - **Remove** next to *Add* takes LEDs out again (some LEDs, a part or the whole strip), keeping the
    rest of that strip's chosen LEDs. Next to the range: how many LEDs it covers, the strip's count and
    its middle LED (the two middle ones, like 10–11, on an even count). The range goes up to the strip's
    size as OpenRGB reports it when the strip's own size isn't saved. Switched-off strips aren't listed.
  - **On the Devices tab,** a thin line under a strip's preview marks the LEDs that flash for
    notifications, with a shortcut to the Notifications tab under it.
- Some labels of the Notifications settings had stayed in plain English in the joke languages; they're
  translated now.
- **The LEDs light back up fully after unlocking.** Coming back from *Off* (or *Dim*) on lock, static
  strips could stay almost dark: the half-second fade back was over before the daemon looked again, so
  its last step, at a few percent, was what stayed on the strips. The final brightness is now always
  sent, and fades run at 20 steps a second instead of one.
- **The LEDs come back after unlocking even when the unlock signal is missed.** While the desktop says
  the screen is locked, Iridia now asks it again every 10 seconds (and at once when something asks to
  unlock), so a missed "unlocked" signal can't keep the strips dark. Only screen savers' signals count
  as locking now: another app's signal of the same name could lock the LEDs for good.
- **Text in buttons no longer stays at the old size after changing the window size.** Switching
  between Compact, Default and Large left the text in buttons on the other tabs at the old size
  (GTK 4.24 doesn't recompute it for hidden widgets) until you hovered each one, so buttons seemed
  to shrink or grow on hover. Every widget now takes the new size straight away.
- The launcher has a clearer description and more search words, and launchers that check it now know
  Iridia sends notifications. The themed (symbolic) icon is square, so panels no longer squash it.
- For packagers: a desktop entry, AppStream metadata and icons in `data/`, and an Arch PKGBUILD in
  `packaging/arch/`.

## 1.3.5 — 2026-10-20

- **LEDs can flash for desktop notifications** (Settings, *Notifications*, or `iridia notify`). Pick
  which LEDs: whole strips, one of their parts, or a range like LEDs 3 to 12, on any devices. Only
  those flash (*Pulse*, *Flash* or *Sweep*), in the wallpaper colour, a colour per app or one you
  pick, red when urgent; the rest of the strip, animations included, carries on. Every app, only
  some, or all but some; quiet during Do Not Disturb (GNOME, KDE, mako, dunst, SwayNC) and,
  if you like, night mode. Works on any desktop: Iridia listens on the session bus with
  `dbus-monitor` or systemd's `busctl`, and only sees which app sent a notification, never what it says.
- **Sensor bars can fill from the middle**, growing both ways at once (*Fills from: The start, The
  middle, The other end*). With an even number of LEDs the two middle ones light together, so both
  sides always match; the tip on each side is partly lit, as at the ends.
- Tidier screenshots in the README and wiki.

## 1.3.4 — 2026-10-19

- **Text no longer cut off at the Default window size.** Default scales the window to 90%, which gave
  fractional sizes (13.2px text, 5.4px padding), and GTK 4.24 cuts off the tops of letters then.
  Every scaled size is now a whole pixel. (1.3.3's switch to GTK's GL renderer wasn't the fix.)
- No "Use GtkSettings:gtk-interface-color-scheme instead" warning on GTK 4.20 and newer.
- **Buttons and options no longer grow on hover.** A desktop GTK theme or `~/.config/gtk-4.0/gtk.css`
  could make the text in buttons bolder or bigger on hover (or scale the buttons); the text in a button
  now keeps the button's own size and weight, and nothing scales.
- **Sensor bars work with color correction.** Palette correction snaps each color by its hue, so it
  turned the bar's partly lit tip and its dimmed rest into full colors: "the rest of the bar dim" lit
  the whole strip, and the bar jumped a whole LED at a time instead of gliding. Correction now works on
  the full color and each LED's level (the tip, the dimmed rest, the blink) is applied after it, with
  gamma correction and in Calibrated mode too. The dimmed rest is a little brighter (12%).
- **A sensor's reading no longer jiggles the part's settings popup:** readings show as whole degrees and
  percentages with equal-width digits (it showed every digit of the smoothed value, so the text, and
  the popup pinned next to it, changed width every second).
- **The connected button groups light up on hover** (Off / Palette / Calibrated and the like): their own
  background hid the hover color.

## 1.3.3 — 2026-10-19

- **The installer's questions are numbered menus.** How OpenRGB's server starts and how the daemon
  starts at login: type a number (or press Enter for the default) instead of a name. Names still work,
  and so do `--openrgb=` and `--autostart=`.
- **Colors show up on the strips without nudging them.** Static colors are only sent when they change,
  and nothing forgot what had been sent when OpenRGB reconnected (after a restart) or its device list
  changed, so a fresh OpenRGB kept showing its own colors until you changed one. Now everything is
  sent again then, and once more three seconds later for controllers that miss the first update after
  being switched to Direct mode.
- **Install ddcutil from the window:** *Settings, Monitor brightness* has an *Install ddcutil* button
  when it's missing. It asks for your password (the desktop's own dialog), installs it with your
  distribution's package manager and gives your session the I2C bus, so monitor brightness works
  without a terminal, also after updating (updates don't install system packages). The installer's
  list of missing packages now says what each optional one is for.
- **No more cut-off text** (the tops of letters in labels and buttons) with fractional scaling, on
  Hyprland for one: GTK's Vulkan renderer clips Iridia's font there, so the window uses GTK's GL
  renderer. To pick another: `GSK_RENDERER=vulkan iridia-gui` (or `ngl`, `cairo`).
- **Pick the monitor on the Everything card too:** a *Monitor* dropdown under Follow monitor brightness,
  the same choice as in *Settings, Monitor brightness* (changing one changes the other).

## 1.3.2 — 2026-10-19

- **OpenRGB's server no longer dies over and over** (exit code -13). OpenRGB before 1.0 (Fedora's
  0.9+git, for one) doesn't ignore SIGPIPE, so a client hanging up just before OpenRGB wrote to it
  killed the whole server. That happened easily at start: OpenRGB, still scanning, reported no
  devices; Iridia hung up to reconnect, and OpenRGB then announced the first device it found to the
  closed connection. Iridia now stays connected while the list is empty, and the server it starts
  ignores SIGPIPE (as a systemd service does).
- **Devices show up sooner after OpenRGB starts:** for the first minute after connecting, and while
  the list is empty, Iridia looks every second instead of every 10.
- The window's status no longer waits for a slow OpenRGB (it timed out, and the daemon logged
  "Broken pipe" errors). OpenRGB going away logs one line about animations instead of one per zone,
  and no warning per device while it has none.
- "OpenRGB not reachable, is its SDK server actually running?" is no longer a warning while Iridia (or
  its systemd unit) is starting that server anyway.

## 1.3.1 — 2026-10-18

- **Pick the monitor whose brightness the LEDs follow.** *Settings, Monitor brightness* lists the
  monitors ddcutil finds (also `iridia monitor`). *Automatic* follows the first one that answers, as
  before; a monitor you pick is the only one followed, never swapped for another when it doesn't answer.
  The section says what's wrong when nothing can be followed, and *Look again* finds a monitor (or
  ddcutil) added since.
- **Follow monitor brightness has a fallback.** Without a monitor to follow (no ddcutil, DDC/CI off in
  the monitor's menu, the chosen monitor switched off), strips use their *Manual* brightness instead of
  a fixed 100%, and the strip's Brightness section says so.
- **Follow monitor brightness is off for new strips.** Strips you already have keep their setting. ddcutil
  is only asked while some strip follows the monitor.
- The brightness in the window's header is the LEDs' own (the brightest strip), not the monitor's.
- **The installer applies OpenRGB's udev rules right away.** When it installs OpenRGB, the rules only
  reached devices plugged in afterwards, so OpenRGB's server couldn't open USB controllers (many
  motherboards, Razer and others) until the next reboot.
- **Devices OpenRGB finds after Iridia connected are picked up.** OpenRGB answers while it's still
  finding devices (the RAM first, USB controllers and graphics cards later). With OpenRGB before 1.0,
  Iridia kept the first, partial list until the next restart; with 1.0 it relied on OpenRGB saying
  so. It now checks the list every few seconds either way.
- **KDE Plasma's default wallpaper is found.** Plasma writes no wallpaper line until you pick one, so a
  fresh desktop (a live USB, a new user) had none to find. The global theme's default is used then.
- **The launcher shows up in Plasma right away**, with its icon on the window: Plasma's menu cache is
  rebuilt after installing.
- *Diagnostics* names the devices it sees, so one OpenRGB doesn't report at all stands out.
- **No more GTK warnings in the terminal** with the Breeze theme (KDE Plasma's default for GTK apps):
  Breeze pulls scrollbars out with a negative margin that Iridia's style didn't undo, and GTK warned
  on every redraw. Dragging a slider warned too.
- The README is shorter.

## 1.3.0 — 2026-10-18

- **Updates.** A new *Updates* tab (and `iridia update`): Iridia looks for a new release when it
  starts (at most every few hours), shows one desktop notification per new version, and installs
  it on a click: the download is checked against GitHub's SHA-256, your settings are backed up,
  the current version is kept, and no password is needed. If the install fails, the previous
  version is put back by itself; *Go back* (or `iridia update --rollback`) returns to it any time.
  `install.sh --update` is the quiet, no-questions mode it uses.
- **Wallpaper detection fixed on KDE Plasma** (it read a file name Plasma doesn't use), **XFCE**
  (real monitor names), **MATE** (the right settings schema), and for **GNOME, Cinnamon and MATE
  slideshows** (the default backgrounds on Ubuntu and Fedora). New: **COSMIC** and **LXQt**.
  Desktops that keep the wallpaper in a settings file are watched instead of asked every 3 seconds.
- **Lighter in the background.** Nothing watches the lock screen or idle time while both are *Keep*;
  the daemon wakes once a second instead of twice when nothing is going on; sensor readings only
  redraw the strips that show them; the window polls less while it's in the background and pauses
  its previews while minimized. At rest the daemon now uses about a third of the CPU it did.
- **Quicker start:** the daemon starts OpenRGB after 2 seconds instead of 10 when nothing else is set
  up to start it.
- **Backups restore exactly:** loading a setup or backup removes files and calibration profiles that
  didn't exist when it was saved; two backups in the same second no longer overwrite each other.
- Screen lockers whose process name is longer than 15 characters are recognised.
- **Installer, on more distributions:** picks a Python 3.8 or newer (openSUSE Leap's python3 is 3.6:
  it uses Python 3.11 there), reads the distribution from `/etc/os-release` (a `pacman` game on Debian
  is no longer taken for Arch), knows Gentoo, explains Fedora Atomic, openSUSE Aeon/Kalpa and NixOS
  instead of failing, accepts OpenRGB from Flathub, only asks apt for OpenRGB where it's packaged,
  installs `gdbus` where it's separate (Debian, Ubuntu, openSUSE), skips the I2C group and rule when
  ddcutil's own rules already give you the bus, works with `doas`, and says what to run as root when
  sudo isn't set up. Running it again upgrades in place (quicker; a failed download leaves the old
  version working, and the daemon comes back), and rebuilds the environment when a distribution
  upgrade changed Python. `sh install.sh` hands over to bash; `sudo bash install.sh` is refused
  (it would install for root). Pillow 9.1 or newer is required: with Ubuntu 22.04's 9.0 every
  wallpaper gave the same color.
- **Monitor brightness on Ubuntu and Debian:** ddcutil 1.x (Ubuntu 22.04 and 24.04, Debian 12) refused
  an option Iridia passed, so brightness never followed the monitor there. Laptops without a DDC/CI
  monitor now follow the built-in screen's backlight.
- **Sensors on more machines:** with an integrated and a dedicated AMD GPU, the dedicated one is shown;
  two drives of the same kind each get their own sensor; with several NVIDIA GPUs the first is read;
  Intel Arc (xe) temperatures are found.
- **Start at login, on more desktops:** the river line no longer uses `riverctl` (river 0.4 refuses
  to start when its init file contains it); Wayfire gets its own line; i3 gets its own (with
  `--no-startup-id`); river, bspwm and dwm started from a TTY or startx are recognised by their
  process. Choosing systemd on a session that never reaches `graphical-session.target` (XFCE,
  Cinnamon, MATE, i3, Hyprland without UWSM, ...) now sets up what does start there, and
  `iridia daemon start` only goes through systemd when that's how it starts at login. A daemon a
  compositor started stops when you log out, so it can't block the next login's. Paths with spaces
  work in the autostart entry and the service; the service's restart limit is in the right section.
  `iridia doctor` shows the fix when nothing starts the daemon at login, and no longer says
  "started by systemd" for programs a UWSM- or niri-session-started compositor launched.

- **Sensors.** A part of a strip (or the whole strip) can show CPU or GPU temperature and load,
  memory use, disk temperature or any other temperature sensor: as a level bar, as a color, or as a
  bar in the reading's color, cool to hot or in your colors, with an optional flash above a reading.
  Several sensors fit on one strip as separate parts. Only sensors a strip shows are read, once a
  second, straight from the kernel, and smoothed; NVIDIA readings use one `nvidia-smi` process only
  while shown. `iridia sensors` lists them; `iridia split NAME part 2 sensor cpu_temp` sets one.

- **Lock and idle.** Settings, *Lock and idle*: keep, dim or turn off the LEDs when the screen locks,
  and after a number of minutes without input. They fade out over 2 seconds and back in half a second;
  *Try it* shows it for 5 seconds, and a strip can stay lit (*Stay lit when the screen locks or you're
  away*, under its Brightness). Iridia sees locking through logind, ScreenSaver signals and screen
  lockers such as hyprlock and swaylock, and idle time on GNOME, KDE and X11, with nothing to set up.
  For Hyprland, Sway and the like, `iridia idle on|off` from hypridle or swayidle (the window and
  `iridia session hooks` have the lines). `iridia session` shows and changes it all.

- **Window size.** Settings, Appearance, Size: Compact, Default, Large or Automatic. Default is about
  10% smaller than before and Large is the old size; Automatic is Compact in a window narrower than
  900 pixels. Ctrl+minus and Ctrl+plus change it, Ctrl+0 goes back to Automatic. Text shrinks less
  than the rest and never below 10 pixels.
- **Window buttons** in the same Material icons as the rest of the window: a round highlight under the
  pointer, close turns red, maximize turns into restore. They follow your desktop's button layout
  (side and order), and Settings, Appearance, *Window buttons* hides them.
- **Narrow windows.** Only the tab on show sets how narrow the window can be, long help text wraps,
  and rows of buttons wrap onto a second line. Below 760 pixels the tabs and the bottom buttons show
  only their icons (the words become tooltips), and if the tabs still don't fit they scroll sideways
  with arrows. The window now goes down to about 600 pixels wide.
  Below 960 pixels the Layout tab's side panel moves under the canvas.
- **LED numbers** under every strip preview (1, every few LEDs, and the last LED, which is the strip's
  real count), so you can see which LED is which.
- Popups no longer show a black frame on X11 without a compositor.
- **Split a strip into parts.** *Advanced: split this strip, set single LEDs* on a zone card: add
  dividers (drag them, they snap to whole LEDs) and let each part show the strip's own look, a static
  pattern of its own, an animated effect of its own, or nothing. A static strip can have one animated
  part, and an animated strip can keep static parts. **Space evenly** splits the parts in whole LEDs
  with the same notes and warnings as below. Changing the LED count moves the dividers along.
- **Single LEDs.** Set any LED to a color or off, over everything else (a fixed LED between two bars):
  click or drag over the strip in the same panel.
- `iridia split NAME ...` does both from the command line (`even 3`, `at 28 55`, `part 2 effect comet`,
  `led 27 ffffff`, `join`, ...).
- **Space evenly** for the Segments pattern: the layout editor shows how many LEDs each color gets,
  splits them evenly in whole LEDs, says when the count doesn't divide evenly, and warns when parts are
  only 1 or 2 LEDs apart.

## 1.2.1 — 2026-10-16

**Iridia's own OpenRGB client.** With OpenRGB 1.0, Iridia now talks to OpenRGB entirely with SDK
protocol 6, through its own client, instead of openrgb-python plus a second connection for animation
frames.

- Every update waits until OpenRGB has applied it: static colors, mode changes and zone resizes too,
  not only animation frames. Nothing can pile up, and when OpenRGB refuses an update the log says so.
- One connection to OpenRGB instead of two.
- OpenRGB announces changes, and Iridia follows them at once: a new device list (a device plugged in
  or a rescan), and a device another program changed. If something switches a device out of Direct
  mode, Iridia puts it back on its next update.
- Zones whose size OpenRGB only uses for the controller's own effects count as one LED, as in OpenRGB.
- `iridia status` and `iridia doctor` say whether Iridia talks protocol 6 or, with OpenRGB before 1.0,
  uses openrgb-python as before.

## 1.2.0 — 2026-10-16

**Animations.** Iridia is no longer static only. Static patterns stay as they were, and stay the default.

- Seven effects per zone: Breathing, Comet, Fill, Embers, Rainbow, Rainbow vomit and Color cycle. They use
  the zone's colors (wallpaper, saved or exact colors; the rainbows ignore them), and brightness, night
  mode, color correction, color order, RGBW and the power limit apply to every frame. Embers drift
  through the picked colors, or glow in fire colors. Colors blend as light does.
- On the Devices tab, Pattern switches between Static and Animated; each effect shows its settings with
  their values, changes apply live, and the strip preview animates. The Everything card sets an effect on
  every zone and keeps zones with the same effect in step (Sync). Picking a static pattern anywhere
  (the Layout tab, painting, the Everything card, the command line) stops the effect.
- Follow the layout: an effect runs through the room across every strip that follows it, using where the
  LEDs are on the Layout tab, in the direction set with a dial. The Layout tab animates live while open.
- Settings, Animations: run animations (off shows each animated zone's first color), frame rate (15, 30,
  60), pause or slow animations during night mode.
- Breathing's minimum and maximum are relative to the zone's brightness. When the monitor's brightness
  changes, LEDs glide to it over about 0.3 s, for static patterns too.
- Lights off, sleep, Identify, Count LEDs, Test colors, color previews and keybind colors pause the
  animation on that zone, and it resumes afterwards.
- `iridia zone TARGET effect NAME [--speed N --min N --max N --param KEY=VALUE] [--save]`,
  `iridia zone TARGET effect static`, `iridia animations pause|resume|toggle|status`; `iridia status`
  shows each zone's effect. The Keybinds tab has "Effect" for strips and "Pause / resume animations".

**Keeping up with the hardware.** OpenRGB 1.0 writes every colour update in turn at the controller's
pace and only tells SDK protocol 6 clients when one is done. Iridia sends animation frames over a second,
protocol 6 connection, one whole-device update at a time, each once the one before is written: a slow
controller gets fewer frames (the rate drops by itself, and the log says so) instead of a queue, so a
change shows at once. With OpenRGB before 1.0, frames go over the main connection.

- One animation thread, only while something animates (static setups stay as idle as before). Each
  device is paced on its own; unchanged frames aren't sent; frames are packed straight into SDK packets.
- `iridia animations status` shows each device's frames per second and frame time, and warns when the
  daemon still runs older code than what's installed. The log notes every effect change.
  `scripts/bench_animations.py` measures the CPU cost.
- Changes reach the LEDs right away instead of at the daemon's next half-second tick.
- Iridia puts each device in Direct mode once per connection even when OpenRGB already reports it,
  since another client or the controller's own effect can change it without OpenRGB noticing.

**Layout**

- Cuts for a strip that was cut and joined again with a wire: the wire is drawn dashed, the piece after
  a cut can be dragged anywhere (or its wire length set), and Join again removes the cut.
- Parts of a strip can be left out of the drawing. Clones can have their own names. A toolbar button
  hides strip names and LED numbers, and the bend knobs no longer carry B1, B2... tags.

**Window and install**

- Sliders and number boxes don't react to the mouse wheel (it scrolls the page), so scrolling past
  them never changes a setting.
- The installer links `iridia` and `iridia-gui` into `~/.local/bin` and says how to add that folder to
  the `PATH` when it's missing (fish included).
- When ddcutil is installed, the installer sets up I2C access for monitor brightness, doing only what's
  missing: the `i2c` group (created if needed) with you in it, a udev rule giving that group the I2C
  devices, and the `i2c-dev` module now and at every boot. It asks first (`--yes` doesn't, `--no-deps`
  leaves it alone) and reminds you to log out and in once.

## 1.1.1 — 2026-10-15

**OpenRGB at boot.** On some machines the LEDs showed random colors after a reboot: 1.1.0's
`iridia-openrgb.service` started OpenRGB with the user manager, before the session could reach the
hardware, so it found no devices and never looked again, and a second OpenRGB from an autostart entry
then fought it over the controller.

- New setting `openrgb.start_method`, picked in the installer, in the window (*Service, Start OpenRGB*)
  or with `iridia openrgb start-method`: `daemon` (default: the Iridia daemon starts OpenRGB inside your
  session), `systemd` (`iridia-openrgb.service`, now started with the graphical session) or `off`.
  It replaces `openrgb.start_server`; `false` there becomes `off`. `iridia openrgb enable` and `disable`
  still work.
- Updating removes 1.1.0's `iridia-openrgb.service` (only if Iridia wrote it) unless you pick `systemd`.
- The daemon remembers the OpenRGB it started (`$XDG_RUNTIME_DIR/iridia-openrgb.pid`), reuses it after a
  daemon restart, starts it again if it exits (after 5 s, 15 s, 60 s, then it stops and says so), passes
  `openrgb.port` on as `--server-port`, and writes its output to `~/.local/share/iridia/openrgb.log`.
- When OpenRGB answers but reports no devices for 30 seconds, Iridia restarts it, then once more after
  2 minutes, if Iridia started it. It never restarts an OpenRGB it didn't start on its own, including
  for a missing device; *Restart OpenRGB server* can still replace a headless one when you click it.
- Iridia never starts OpenRGB while another one runs or is set to start. `iridia doctor` and the window
  name the other starter; *Turn off OpenRGB's own autostart* (`iridia openrgb hide-autostart`) adds
  `Hidden=true` to its autostart entry. Doctor also says when the OpenRGB window is open with its SDK
  server off.
- The port is probed once instead of on every retry (each probe left an error in OpenRGB's log).

**Without systemd, or started from your compositor.**

- The installer asks how the daemon starts at login: `--autostart=systemd|xdg|compositor|none`. The
  default is systemd only when your session reaches `graphical-session.target`, else your compositor's
  line (printed for you), else XDG autostart.
- `iridia doctor` shows how the daemon was started ("started by Hyprland", "systemd", ...), no longer
  shows an enabled but inactive `iridia-daemon.service` as a problem while the daemon runs, warns when
  that service can never start because the session doesn't reach `graphical-session.target`, and notes
  when the daemon is set to start from more than one place.
- A daemon started outside systemd turns on file logging, since there is no journal (unless you set
  `logging.enabled` yourself).
- `iridia openrgb status` shows the start method, whether Iridia started the running OpenRGB, and what
  else starts it.

**Other**

- A command naming a zone a device doesn't have (a keybind typo, a zone OpenRGB renamed) gets a plain
  "zone not found" reply instead of being logged as a failed command.
- The daemon's socket is created with mode 600 from the start, instead of being tightened right after
  it appears.
- Unit tests (`tests/`), including the daemon's commands and rendering, and OpenRGB's start and restart
  rules against a fake `openrgb` and `systemctl`. A GitHub Actions workflow runs them on Python 3.8 to
  3.13, with ruff and shellcheck. `pip install -e ".[dev]"` installs the tools.

## 1.1.0 — 2026-10-15

- Iridia starts OpenRGB's server: with systemd through a user service, `iridia-openrgb.service`, set up by
  the installer; without systemd the daemon runs `openrgb --server` itself when it can't reach it. It
  leaves OpenRGB alone when something else already starts it, and never runs a second instance.
  `iridia openrgb enable`, `disable` and `status`, and a switch in the Service tab. Works with the
  Flatpak; `openrgb.server_command` for an AppImage.
- `iridia doctor` says what starts OpenRGB at login; it no longer shows a unit that doesn't exist as
  "inactive".
- The window uses British spelling by default. American English can be picked in Settings,
  Appearance, Language; switching restarts the window.
- The command line, the log and `iridia doctor` keep American spelling.
- `install.sh` and `uninstall.sh` moved from `scripts/` to the top folder: `bash install.sh`.
- The app id is now `io.github.HypestHyper.Iridia` (the window class for window rules). The old
  launcher is removed when the service is installed again.

## 1.0.0 — 2026-10-15

The first public release.

- Wallpaper colors on your RGB devices through OpenRGB, with wallpaper detection for Hyprland, Sway,
  niri, GNOME, KDE, XFCE, Cinnamon, MATE, X11 window managers, Caelestia, Noctalia and waypaper.
- Monitor brightness sync over DDC/CI, night mode, LEDs off during sleep, freeze.
- Static patterns (solid, gradient, segments, center out, edges in, alternating, painted) with color
  stops, reverse and mirror; color picks remembered per wallpaper.
- GTK 4 window in the Material 3 Expressive style: Status, Devices, Layout, Keybinds, Settings and
  Service tabs.
- Layout tab: strips drawn at their real length with bends, clones, painting and Find LEDs.
- Strip types (addressable 5V, 12V grouped, one color, RGBW), color order, power limit.
- Color correction: palette, calibration profiles with an editor, exact colors.
- Keybind commands that combine actions and switch back on a second press.
- Setups with automatic backups, a full command line, `iridia doctor`.
