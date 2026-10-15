# Installation

## Requirements

| What | Needed for | Notes |
| --- | --- | --- |
| Linux | everything | Any desktop or compositor, Wayland or X11 |
| Python 3.8 or newer, with `venv` | everything | The installer creates its own virtual environment |
| [OpenRGB](https://openrgb.org/) with its SDK server running | talking to the LEDs | 0.9 or newer recommended |
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
4. Installs the app launcher entry and icons, and sets up the systemd user service. Without a systemd
   user session (Void, Alpine, Artix, Gentoo with OpenRC) it writes an XDG autostart entry instead and
   prints the line for your compositor.
5. Starts the daemon.

| Flag | Effect |
| --- | --- |
| `--yes` | Install missing system packages without asking |
| `--no-deps` | Never touch system packages |

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

Iridia talks to OpenRGB's SDK server, and starts that server itself, so usually there's nothing to do:

- **With systemd** (most distributions), the installer adds a user service, `iridia-openrgb.service`,
  that runs `openrgb --server` at every login and restarts it if it crashes. The *Service* tab's
  *Start OpenRGB's server with Iridia* switch (or `iridia openrgb enable` / `disable`) turns it on and off.
- **Without systemd**, the daemon runs `openrgb --server` itself when it can't reach a server.
- **If something else already starts OpenRGB** (its own *start at login* setting, another systemd unit, a
  line in your compositor's config), Iridia leaves it alone. It also never starts a second OpenRGB while
  one is running, because two instances fight over the same hardware.

`iridia openrgb status` shows what starts OpenRGB on your machine. Iridia finds OpenRGB as the `openrgb`
command or as the Flatpak (`org.openrgb.OpenRGB`). For an AppImage, set `openrgb.server_command` to the
command that runs its server, for example `"~/Apps/OpenRGB.AppImage --server"` with the full path.

To use the OpenRGB window while the server runs, connect the window to it (its *Client* tab,
`localhost`, port 6742) instead of letting it scan the hardware a second time, or stop the server first
(`systemctl --user stop iridia-openrgb.service`). If you'd rather manage OpenRGB yourself, run
`iridia openrgb disable` and turn on *Start Server* in OpenRGB's *SDK Server* tab.

Iridia finds the server on ports 6742 to 6744 by itself. For another host or port, set `openrgb.host` and
`openrgb.port` (see [Configuration](Configuration.md)).

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

To use the `iridia` command from anywhere, add the folder to your `PATH`, for example in
`~/.bashrc` or `~/.zshrc`:

```bash
export PATH="$HOME/.local/share/iridia-venv/bin:$PATH"
```

or for fish: `fish_add_path ~/.local/share/iridia-venv/bin`.

## Updating

Get the new version (`git pull`, or unpack the new release) and run the installer again:

```bash
bash install.sh --yes
```

Your settings in `~/.config/iridia/` are kept.

## Uninstalling

From the window: **Service, Uninstall Iridia**. From a terminal:

```bash
iridia uninstall                  # asks first, removes your settings too
iridia uninstall --keep-settings  # keeps ~/.config/iridia (and your setups)
```

Or run `bash uninstall.sh` from the Iridia folder, which also works if the virtual environment
is already broken. If you added an Iridia line to your compositor's config (for autostart or
keybinds), remove it by hand.
