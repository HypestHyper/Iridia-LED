#!/bin/bash
set -e
# Work from the project folder, wherever the script was started from.
cd "$(dirname "$(readlink -f "$0")")/.."
VENV_DIR="$HOME/.local/share/iridia-venv"
CONFIG_DIR="$HOME/.config/iridia"

echo "============================================"
echo " Iridia, Installer"
echo "============================================"

ASSUME_YES=0
SKIP_DEPS=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        --no-deps) SKIP_DEPS=1 ;;
        -h|--help)
            echo "Usage: bash scripts/install.sh [--yes] [--no-deps]"
            echo "  --yes      install missing system packages without asking"
            echo "  --no-deps  never touch system packages"
            exit 0 ;;
    esac
done

# --- work out what is missing -------------------------------------------
MISSING=()   # generic names: python openrgb ddcutil gtk venv
GTK_CHECK="import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; import cairo; gi.require_foreign('cairo')"
command -v python3 >/dev/null 2>&1 || MISSING+=(python)
if command -v python3 >/dev/null 2>&1; then
    python3 -c "$GTK_CHECK" >/dev/null 2>&1 || MISSING+=(gtk)
    python3 -c "import venv, ensurepip" >/dev/null 2>&1 || MISSING+=(venv)
fi
command -v openrgb >/dev/null 2>&1 || MISSING+=(openrgb)
command -v ddcutil >/dev/null 2>&1 || MISSING+=(ddcutil)

# --- map generic names to this distro's package manager -----------------
PM=""; PKGS=(); INSTALL_CMD=()
pkgname() {
    case "$PM:$1" in
        pacman:python) echo python ;;      pacman:venv) ;;
        pacman:gtk)    echo gtk4 python-gobject python-cairo ;;
        apt:python)    echo python3 ;;     apt:venv) echo python3-venv ;;
        apt:gtk)       echo gir1.2-gtk-4.0 python3-gi python3-gi-cairo ;;
        dnf:python)    echo python3 ;;     dnf:venv) ;;
        dnf:gtk)       echo gtk4 python3-gobject python3-cairo ;;
        zypper:python) echo python3 ;;     zypper:venv) ;;
        zypper:gtk)    echo typelib-1_0-Gtk-4_0 python3-gobject python3-gobject-cairo python3-cairo ;;
        xbps:python)   echo python3 ;;     xbps:venv) ;;
        xbps:gtk)      echo gtk4 python3-gobject python3-cairo ;;
        apk:python)    echo python3 ;;     apk:venv) ;;
        apk:gtk)       echo gtk4.0 py3-gobject3 py3-cairo ;;
        zypper:openrgb) echo OpenRGB ;;
        *:openrgb) echo openrgb ;;         *:ddcutil) echo ddcutil ;;
    esac
}
if   command -v pacman >/dev/null 2>&1; then PM=pacman; INSTALL_CMD=(sudo pacman -S --needed --noconfirm)
elif command -v apt-get >/dev/null 2>&1; then PM=apt;    INSTALL_CMD=(sudo apt-get install -y)
elif command -v dnf >/dev/null 2>&1;     then PM=dnf;    INSTALL_CMD=(sudo dnf install -y)
elif command -v zypper >/dev/null 2>&1;  then PM=zypper; INSTALL_CMD=(sudo zypper install -y)
elif command -v xbps-install >/dev/null 2>&1; then PM=xbps; INSTALL_CMD=(sudo xbps-install -y)
elif command -v apk >/dev/null 2>&1;     then PM=apk;    INSTALL_CMD=(sudo apk add)
fi

if [ ${#MISSING[@]} -gt 0 ] && [ "$SKIP_DEPS" -eq 0 ]; then
    for m in "${MISSING[@]}"; do
        for p in $(pkgname "$m"); do PKGS+=("$p"); done
    done
    [ "$(id -u)" -eq 0 ] && INSTALL_CMD=("${INSTALL_CMD[@]:1}")   # already root: no sudo
    echo "Missing on this system: ${MISSING[*]}"
    if [ -z "$PM" ]; then
        echo "Couldn't detect your package manager. Please install these yourself:"
        echo "  python 3 (with venv), GTK 4 with PyGObject and pycairo, openrgb, ddcutil"
    elif [ ${#PKGS[@]} -gt 0 ]; then
        echo "Will run: ${INSTALL_CMD[*]} ${PKGS[*]}"
        reply="y"
        if [ "$ASSUME_YES" -eq 0 ]; then
            read -r -p "Install these now? [Y/n] " reply || reply="n"
        fi
        case "${reply:-y}" in
            n|N|no|NO) echo "Skipping system packages." ;;
            *)
                if [ "$PM" = apt ]; then
                    if [ "$(id -u)" -eq 0 ]; then apt-get update || true; else sudo apt-get update || true; fi
                fi
                # One group at a time: a package your distro doesn't have (OpenRGB isn't in
                # every repository) must not stop GTK or Python from being installed.
                for m in "${MISSING[@]}"; do
                    group=($(pkgname "$m"))
                    [ ${#group[@]} -eq 0 ] && continue
                    "${INSTALL_CMD[@]}" "${group[@]}" || echo "WARNING: couldn't install ${group[*]} (see above), continuing."
                done
                ;;
        esac
    fi
fi

if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found."
    exit 1
fi
if ! python3 -c "$GTK_CHECK" >/dev/null 2>&1; then
    echo "NOTE: GTK 4 for Python (PyGObject + pycairo) is missing for $(command -v python3),"
    echo "      so the Iridia window won't open until you install it. The daemon works without it."
fi
if ! command -v openrgb &> /dev/null; then
    echo "NOTE: 'openrgb' is not installed (Iridia can't drive LEDs without it)."
    echo "      If your distribution doesn't package it, get the AppImage or package from https://openrgb.org"
    echo "      and run it with its SDK server on (openrgb --server)."
fi
if ! command -v ddcutil &> /dev/null; then
    echo "NOTE: 'ddcutil' is not installed (optional: monitor-brightness-synced LEDs)."
fi
if command -v ddcutil >/dev/null 2>&1 && ! id -nG | grep -qw i2c; then
    echo "NOTE: ddcutil usually needs you in the 'i2c' group:  sudo usermod -aG i2c \$USER  (then log out and in)"
fi

# An older daemon left running would keep the old code alive (and block the
# new one through the single-instance lock), so stop it before upgrading.
if [ -x "$VENV_DIR/bin/iridia" ]; then
    "$VENV_DIR/bin/iridia" daemon stop >/dev/null 2>&1 || true
fi

echo "Creating virtual environment..."
# --system-site-packages: the window uses your distro's GTK 4 bindings (PyGObject),
# which can't be built with pip without a full compiler toolchain.
# --clear: start fresh, so files from older versions can't linger.
python3 -m venv --system-site-packages --clear "$VENV_DIR"
echo "Upgrading pip..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
rm -rf build ./*.egg-info
echo "Installing iridia..."
"$VENV_DIR/bin/pip" install .

echo "Creating config directory..."
mkdir -p "$CONFIG_DIR"

# The desktop entry, icon, and systemd service are all written by
# `iridia service install` itself (see iridia/cli.py) rather than
# duplicated here, it resolves the venv's own binary paths, so the
# generated files are always correct regardless of where this venv
# ends up living. This also means the GUI's own Service > Install
# button produces an identical result to running this script.
echo "Installing desktop entry, icon, and systemd service..."
"$VENV_DIR/bin/iridia" service install

echo "Starting the daemon..."
"$VENV_DIR/bin/iridia" daemon start || true

echo ""
echo "============================================"
echo " Installation complete!"
echo "============================================"
echo ""
echo "Iridia should now appear in your application launcher."
echo ""
echo "Next steps:"
echo "  1. Edit config:      iridia config edit"
echo "                       (or: $VENV_DIR/bin/iridia config edit)"
echo "  2. Check the daemon: systemctl --user status iridia-daemon.service"
echo "  3. Open the GUI from your launcher, or run:"
echo "                       $VENV_DIR/bin/iridia-gui"
echo ""
echo "To uninstall: bash scripts/uninstall.sh"
echo ""
