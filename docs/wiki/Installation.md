# Installation

## Requirements

| What | Needed for | Notes |
| --- | --- | --- |
| Linux | everything | Any desktop or compositor, Wayland or X11 |
| Python 3.8 or newer, with `venv` | everything | The installer creates its own virtual environment |
| [OpenRGB](https://openrgb.org/) with its SDK server running | talking to the LEDs | 0.9 or newer; 1.0 recommended for animations |
| GTK 4.6 or newer, PyGObject, pycairo | the window | From your distribution; the daemon and the command line work without them |
| [ddcutil](https://www.ddcutil.com/) | following monitor brightness | Optional |
| `gdbus` (part of GLib) | LEDs off while the PC sleeps | Installed almost everywhere |

The Python libraries Iridia uses (`openrgb-python`, `Pillow`, `watchdog`) are installed into the virtual
environment by the installer. `material-color-utilities` is optional: it adds the *Material* color
engine (see [How it works](How-It-Works.md#color-engines)).

## Quick install

```bash
git clone https://github.com/HypestHyper/Iridia-LED.git
cd Iridia-LED
bash install.sh
```

Or download a release archive, unpack it and run `bash install.sh` inside it.

The installer:

1. Checks for Python with venv, GTK 4 with PyGObject and pycairo, OpenRGB and ddcutil, and offers to
   install whatever is missing with your package manager (pacman, apt, dnf, zypper, xbps or apk). It
   installs each group on its own, so a package your distribution lacks doesn't block the rest.
2. Stops an older Iridia daemon if one is running.
3. Creates a virtual environment in `~/.local/share/iridia-venv` (with access to your distribution's
   GTK bindings) and installs Iridia into it.
4. Asks how OpenRGB's server should be started, and how the daemon should start at login (see below
   and [Start at login](Start-at-Login.md)). With `--yes` or without a terminal it uses the defaults.
5. Installs the app launcher entry and icons, and sets up what you picked.
6. Starts the daemon.

| Flag | Effect |
| --- | --- |
| `--yes` | Don't ask: install missing system packages, use the defaults below |
| `--no-deps` | Never touch system packages |
| `--openrgb=daemon` | The Iridia daemon starts OpenRGB's server (default) |
| `--openrgb=systemd` | A systemd user service starts it with your graphical session |
| `--openrgb=off` | You start OpenRGB yourself |
| `--autostart=systemd` | The daemon starts at login through a systemd user service |
| `--autostart=xdg` | ... through `~/.config/autostart` (GNOME, KDE, XFCE, ...) |
| `--autostart=compositor` | ... through a line in your compositor's config; the installer prints it |
| `--autostart=none` | Nothing starts the daemon at login |

The default for `--autostart` is `systemd` when your session reaches `graphical-session.target`, else
`compositor` when a compositor is detected (Hyprland, Sway, niri, ...), else `xdg`.

Nothing is installed system-wide except the packages you agree to. Iridia itself lives in your home
folder.

## Installing the dependencies yourself

If you'd rather install the system packages by hand, these are the names per distribution:

**Arch, CachyOS, EndeavourOS, Manjaro**
```bash
sudo pacman -S --needed python gtk4 python-gobject python-cairo openrgb ddcutil
```

**Debian, Ubuntu, Linux Mint, Pop!_OS**
```bash
sudo apt install python3 python3-venv gir1.2-gtk-4.0 python3-gi python3-gi-cairo openrgb ddcutil
```
If your release has no `openrgb` package, install the `.deb` from [openrgb.org](https://openrgb.org/).

**Fedora**
```bash
sudo dnf install python3 gtk4 python3-gobject python3-cairo openrgb ddcutil
```

**openSUSE**
```bash
sudo zypper install python3 typelib-1_0-Gtk-4_0 python3-gobject python3-gobject-cairo python3-cairo OpenRGB ddcutil
```

**Void**
```bash
sudo xbps-install python3 gtk4 python3-gobject python3-cairo openrgb ddcutil
```

**Alpine**
```bash
sudo apk add python3 gtk4.0 py3-gobject3 py3-cairo ddcutil
```
OpenRGB isn't packaged for every Alpine release; check your repositories or build it from source.

Then run the installer with `--no-deps`.

The GTK bindings must belong to the same `python3` the installer runs. A Python from pyenv, uv or
conda won't see your distribution's PyGObject, so run the installer with the system `python3` first in
your `PATH`.

## Setting up OpenRGB

Iridia talks to OpenRGB's SDK server. You pick what starts that server with `openrgb.start_method`:
in the installer, in the window (**Service, OpenRGB connection, Start OpenRGB**), or with
`iridia openrgb start-method`.

| Method | What happens |
| --- | --- |
| `daemon` (default, *With Iridia*) | The Iridia daemon starts `openrgb --server` and starts it again if it exits (after 5 s, 15 s and 60 s, then it gives up and says so). Works with or without systemd, however the daemon itself is started. |
| `systemd` (*systemd service*) | A user service, `iridia-openrgb.service`, starts it with your graphical session. Only offered when there's a systemd user session. |
| `off` (*I start it myself*) | Iridia never starts, stops or restarts OpenRGB. For the OpenRGB window with its SDK server on, a root system service, or your own setup. |

**Why `daemon` is the default.** At boot, the session gets access to the USB and I2C devices only once
it's up. An OpenRGB started earlier (for example by a service that starts with the user manager) finds
no devices and never looks again. The daemon runs inside your session, so the OpenRGB it starts can see
the hardware. It waits 10 seconds after the daemon starts, so OpenRGB's own autostart can go first.

**Only one OpenRGB.** Two instances fight over the same hardware: one takes the controller and the
other leaves it showing random colors. So Iridia never starts OpenRGB while another OpenRGB process
runs, or while something else is set up to start it (another systemd unit, an entry in
`~/.config/autostart`, a line in your compositor's config). `iridia doctor` and the *Service* tab name
what they found. To turn off OpenRGB's own autostart entry, use the *Turn off OpenRGB's own autostart*
button or `iridia openrgb hide-autostart`: it adds `Hidden=true` to the file and never deletes it.

**Which OpenRGB is Iridia's.** The daemon remembers the server it started (in
`$XDG_RUNTIME_DIR/iridia-openrgb.pid`), keeps it running across daemon restarts, and writes its output
to `~/.local/share/iridia/openrgb.log`. Iridia only restarts an OpenRGB it started itself, or its own
`iridia-openrgb.service`. *Restart OpenRGB server* in the window can also replace a headless
`openrgb --server` that something else started; it never touches the OpenRGB window.

**No devices.** If OpenRGB answers but reports no devices for 30 seconds, Iridia restarts the OpenRGB
it started, then once more after 2 minutes if needed (at most twice per daemon run). If it didn't start
it, it says so in the log and in `iridia doctor` instead.

**Upgrading from 1.1.0.** 1.1.0 set up `iridia-openrgb.service` to start with the user manager, which
is too early (see above). Iridia removes that service when you update, but only if Iridia wrote it, and
switches to `daemon`.

`iridia openrgb status` shows the method, the command, whether Iridia started the running OpenRGB, and
what else starts it. Iridia finds OpenRGB as the `openrgb` command or as the Flatpak
(`org.openrgb.OpenRGB`). For an AppImage, set `openrgb.server_command` to the command that runs its
server, for example `"/home/you/Apps/OpenRGB.AppImage --server"`.

To use the OpenRGB window while the server runs, connect the window to it (its *Client* tab,
`localhost`, port 6742) instead of letting it scan the hardware a second time. If you'd rather run the
window with its own server, pick `off` and turn on *Start Server* in OpenRGB's *SDK Server* tab.

Iridia finds the server on ports 6742 to 6744 by itself. For another port, set `openrgb.port`: the
OpenRGB that Iridia starts then listens on it (`--server-port`). For OpenRGB on another machine, set
`openrgb.host`; Iridia never starts anything for a remote host (see [Configuration](Configuration.md)).

OpenRGB needs permission to reach your hardware. Its package normally installs the udev rules
(`60-openrgb.rules`). Motherboard and RAM lighting also needs the `i2c-dev` kernel module (and
`i2c-piix4` on many AMD boards):

```bash
sudo modprobe i2c-dev
echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf   # load it at every boot
```

If a device doesn't show up in OpenRGB itself, Iridia can't see it either; see the
[OpenRGB documentation](https://openrgb.org/) for your hardware.

## Setting up monitor brightness (optional)

ddcutil reads your monitor's brightness over DDC/CI. It usually needs access to the I2C devices:

```bash
sudo usermod -aG i2c $USER     # then log out and back in
ddcutil detect                 # should list your monitor
```

DDC/CI must also be enabled in your monitor's own menu on some models. If no monitor answers, Iridia
just uses the brightness you set by hand.

## The Material color engine (optional)

```bash
~/.local/share/iridia-venv/bin/pip install material-color-utilities
```

Then restart the daemon (`iridia daemon stop`, `iridia daemon start`) and pick the engine in
*Settings, Color extraction*.

## Running it

Open **Iridia** from your app launcher, or run:

```bash
~/.local/share/iridia-venv/bin/iridia-gui
```

The installer links `iridia` and `iridia-gui` into `~/.local/bin` (it never replaces a file there that
isn't Iridia's). If your shell says `iridia` isn't found, that folder isn't on your `PATH` yet; the
installer says so too. Add it once:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc    # or ~/.zshrc
```

or for fish: `fish_add_path ~/.local/bin`.

## Updating

Get the new version (`git pull`, or unpack the new release) and run the installer again:

```bash
bash install.sh --yes
```

Your settings in `~/.config/iridia/` are kept, and so is your OpenRGB start method (add
`--openrgb=...` or `--autostart=...` to change them). Updating from 1.1.0 removes its
`iridia-openrgb.service` unless you pick `--openrgb=systemd`. Check with `iridia --version` and
`iridia doctor`.

## Uninstalling

From the window: **Service, Uninstall Iridia**. From a terminal:

```bash
iridia uninstall                  # asks first, removes your settings too
iridia uninstall --keep-settings  # keeps ~/.config/iridia (and your setups)
```

Or run `bash uninstall.sh` from the Iridia folder, which also works if the virtual environment
is already broken. If you added an Iridia line to your compositor's config (for autostart or
keybinds), remove it by hand.
