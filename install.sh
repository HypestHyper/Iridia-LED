#!/bin/bash
# `sh install.sh` on Debian/Ubuntu runs dash, which can't read the rest: hand over to bash first.
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"
set -e
# Work from the project folder, wherever the script was started from.
cd "$(dirname "$(readlink -f "$0")")"
VENV_DIR="$HOME/.local/share/iridia-venv"
CONFIG_DIR="$HOME/.config/iridia"

echo "============================================"
echo " Iridia, Installer"
echo "============================================"

ASSUME_YES=0
SKIP_DEPS=0
UPDATE=0
OPENRGB_METHOD=""
AUTOSTART=""
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        --no-deps) SKIP_DEPS=1 ;;
        --update) UPDATE=1; ASSUME_YES=1; SKIP_DEPS=1 ;;
        --openrgb=*) OPENRGB_METHOD="${arg#*=}" ;;
        --autostart=*) AUTOSTART="${arg#*=}" ;;
        -h|--help)
            echo "Usage: bash install.sh [--yes] [--no-deps] [--openrgb=METHOD] [--autostart=METHOD]"
            echo "  --yes                 don't ask: install missing system packages, use the defaults below"
            echo "  --no-deps             never touch system packages"
            echo "  --update              update an installed Iridia: no questions, no system packages (so no"
            echo "                        password), keep how OpenRGB and the daemon start (the Updates tab uses this)"
            echo "  --openrgb=daemon      the Iridia daemon starts OpenRGB's server (default)"
            echo "  --openrgb=systemd     a systemd user service starts it with your graphical session"
            echo "  --openrgb=off         you start OpenRGB yourself"
            echo "  --autostart=systemd   the daemon starts at login through a systemd user service"
            echo "  --autostart=xdg       ... through ~/.config/autostart (GNOME, KDE, XFCE, ...)"
            echo "  --autostart=compositor  ... through a line in your compositor's config (printed for you)"
            echo "  --autostart=none      nothing starts it at login"
            echo "  Default for --autostart: systemd when your session reaches graphical-session.target,"
            echo "  else your compositor's line when one is detected, else xdg."
            exit 0 ;;
        *) echo "Unknown option: $arg (see --help)"; exit 1 ;;
    esac
done
case "$OPENRGB_METHOD" in ""|daemon|systemd|off) ;; *) echo "--openrgb must be daemon, systemd or off"; exit 1 ;; esac
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
    echo "Run this as your normal user, without sudo: bash install.sh"
    echo "(Iridia installs into your home folder, and the installer asks for sudo itself when it needs it.)"
    exit 1
fi
OS_ID=""; OS_LIKE=""
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    OS_ID=$(. /etc/os-release && echo "${ID:-}")
    # shellcheck disable=SC1091
    OS_LIKE=$(. /etc/os-release && echo "${ID_LIKE:-}")
fi
if [ -e /etc/NIXOS ] || [ "$OS_ID" = nixos ]; then
    cat <<'NIX'
NixOS: install.sh can't install system packages here, and a Python venv doesn't see Nix's GTK.
Set up the system parts in configuration.nix:
    hardware.i2c.enable = true;                  # monitor brightness (ddcutil)
    services.hardware.openrgb.enable = true;     # OpenRGB's server as a system service
    environment.systemPackages = with pkgs; [ ddcutil ];
then run the installer from a shell with GTK 4 for Python, keeping OpenRGB's start to the service:
    nix-shell -p gtk4 gobject-introspection 'python3.withPackages (p: [ p.pygobject3 p.pycairo ])' \
      --run 'bash install.sh --no-deps --openrgb=off'
The daemon works without GTK; the window needs that shell (or a Nix package of Iridia).
NIX
    if [ -z "${IN_NIX_SHELL:-}" ]; then exit 1; fi
fi
# Python 3.8 or newer (openSUSE Leap's python3 is 3.6; its newer Python is python3.11)
PY3=""
for c in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
        PY3="$c"; break
    fi
done
case "$AUTOSTART" in ""|systemd|xdg|compositor|none|keep) ;; *) echo "--autostart must be systemd, xdg, compositor or none"; exit 1 ;; esac
if [ "$UPDATE" -eq 1 ]; then
    [ -z "$AUTOSTART" ] && AUTOSTART=keep
    if [ ! -x "$HOME/.local/share/iridia-venv/bin/python" ]; then
        echo "--update needs an existing install; run bash install.sh first."; exit 1
    fi
fi

# --- work out what is missing -------------------------------------------
MISSING=()   # generic names: python openrgb ddcutil gtk venv gdbus
GTK_CHECK="import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; import cairo; gi.require_foreign('cairo')"
[ -n "$PY3" ] || MISSING+=(python)
if [ -n "$PY3" ]; then
    "$PY3" -c "$GTK_CHECK" >/dev/null 2>&1 || MISSING+=(gtk)
    "$PY3" -c "import venv, ensurepip" >/dev/null 2>&1 || MISSING+=(venv)
fi
# OpenRGB as a command, or from Flathub (Iridia starts either)
have_openrgb() {
    command -v openrgb >/dev/null 2>&1 \
        || { command -v flatpak >/dev/null 2>&1 && flatpak info org.openrgb.OpenRGB >/dev/null 2>&1; }
}
have_openrgb || MISSING+=(openrgb)
command -v ddcutil >/dev/null 2>&1 || MISSING+=(ddcutil)
command -v gdbus >/dev/null 2>&1 || MISSING+=(gdbus)    # sleep and lock detection

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
        zypper:python) if [ "$OS_ID" = opensuse-leap ]; then echo python311; else echo python3; fi ;;
        zypper:venv) ;;
        zypper:gtk)    if [ "$OS_ID" = opensuse-leap ]; then
                           echo typelib-1_0-Gtk-4_0 python311-gobject python311-gobject-cairo python311-pycairo
                       else
                           echo typelib-1_0-Gtk-4_0 python3-gobject python3-gobject-cairo python3-cairo
                       fi ;;
        emerge:python) echo dev-lang/python ;; emerge:venv) ;;
        emerge:gtk)    echo gui-libs/gtk dev-python/pygobject dev-python/pycairo ;;
        emerge:openrgb) echo app-misc/openrgb ;; emerge:ddcutil) echo app-misc/ddcutil ;;
        apt:gdbus) echo libglib2.0-bin ;;  zypper:gdbus) echo glib2-tools ;;
        *:gdbus) ;;
        xbps:python)   echo python3 ;;     xbps:venv) ;;
        xbps:gtk)      echo gtk4 python3-gobject python3-cairo ;;
        apk:python)    echo python3 ;;     apk:venv) ;;
        apk:gtk)       echo gtk4.0 py3-gobject3 py3-cairo ;;
        zypper:openrgb) echo OpenRGB ;;
        # Ubuntu before 25.10 and Debian before 14 don't have it: openrgb.org's .deb or Flathub then
        apt:openrgb) apt-cache show openrgb >/dev/null 2>&1 && echo openrgb ;;
        *:openrgb) echo openrgb ;;         *:ddcutil) echo ddcutil ;;
    esac
}
# The distribution says which package manager is its own (a 'pacman' game on Debian is not Arch's).
case " $OS_ID $OS_LIKE " in
    *" arch "*)                PM=pacman ;;
    *" debian "*|*" ubuntu "*) PM=apt ;;
    *" fedora "*|*" rhel "*)   PM=dnf ;;
    *suse*)                    PM=zypper ;;
    *" void "*)                PM=xbps ;;
    *" alpine "*)              PM=apk ;;
    *" gentoo "*)              PM=emerge ;;
esac
if [ -z "$PM" ]; then
    if   command -v pacman >/dev/null 2>&1 && pacman -V 2>/dev/null | grep -q 'Pacman v'; then PM=pacman
    elif command -v apt-get >/dev/null 2>&1; then PM=apt
    elif command -v dnf >/dev/null 2>&1;     then PM=dnf
    elif command -v zypper >/dev/null 2>&1;  then PM=zypper
    elif command -v xbps-install >/dev/null 2>&1; then PM=xbps
    elif command -v apk >/dev/null 2>&1;     then PM=apk
    elif command -v emerge >/dev/null 2>&1;  then PM=emerge
    fi
fi
SUDO_CMD=sudo
if ! command -v sudo >/dev/null 2>&1 && command -v doas >/dev/null 2>&1; then SUDO_CMD=doas; fi
case "$PM" in
    pacman) INSTALL_CMD=("$SUDO_CMD" pacman -S --needed --noconfirm) ;;
    apt)    INSTALL_CMD=("$SUDO_CMD" apt-get install -y) ;;
    dnf)    INSTALL_CMD=("$SUDO_CMD" dnf install -y) ;;
    zypper) INSTALL_CMD=("$SUDO_CMD" zypper install -y) ;;
    xbps)   INSTALL_CMD=("$SUDO_CMD" xbps-install -Sy) ;;
    apk)    INSTALL_CMD=("$SUDO_CMD" apk add) ;;
    emerge) INSTALL_CMD=("$SUDO_CMD" emerge --noreplace) ;;
esac
# Image-based systems: packages go into the next boot's image, so say what to run instead
if [ -e /run/ostree-booted ]; then
    PM=""
    ATOMIC="Fedora Atomic (Silverblue, Kinoite, Bazzite): install the system parts with
    sudo rpm-ostree install --idempotent gtk4 python3-gobject python3-cairo ddcutil
  (OpenRGB: flatpak install flathub org.openrgb.OpenRGB), reboot, then run: bash install.sh --no-deps"
elif command -v transactional-update >/dev/null 2>&1; then
    PM=""
    ATOMIC="openSUSE Aeon/Kalpa/MicroOS: install the system parts with
    sudo transactional-update -n pkg install typelib-1_0-Gtk-4_0 python3-gobject python3-gobject-cairo python3-cairo ddcutil
  (OpenRGB: flatpak install flathub org.openrgb.OpenRGB), reboot, then run: bash install.sh --no-deps"
fi

if [ ${#MISSING[@]} -gt 0 ] && [ "$SKIP_DEPS" -eq 0 ]; then
    for m in "${MISSING[@]}"; do
        for p in $(pkgname "$m"); do PKGS+=("$p"); done
    done
    [ "$(id -u)" -eq 0 ] && INSTALL_CMD=("${INSTALL_CMD[@]:1}")   # already root: no sudo
    echo "Missing on this system: ${MISSING[*]}"
    if [ -n "${ATOMIC:-}" ]; then
        echo "$ATOMIC"
    elif [ -z "$PM" ]; then
        echo "Couldn't detect your package manager. Please install these yourself:"
        echo "  python 3.8+ (with venv), GTK 4 with PyGObject and pycairo, openrgb, ddcutil, gdbus (glib)"
    elif [ "$(id -u)" -ne 0 ] && [ "${INSTALL_CMD[0]}" = sudo ] && ! sudo -v; then
        echo "sudo isn't set up for $USER. As root, run:"
        echo "  ${INSTALL_CMD[*]:1} ${PKGS[*]}"
        echo "(for example: su -c '...'), then: bash install.sh --no-deps"
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
                    read -r -a group <<< "$(pkgname "$m")"
                    [ ${#group[@]} -eq 0 ] && continue
                    if "${INSTALL_CMD[@]}" "${group[@]}"; then
                        [ "$m" = openrgb ] && OPENRGB_NEW=1
                    else
                        echo "WARNING: couldn't install ${group[*]} (see above), continuing."
                    fi
                done
                if [ "${OPENRGB_NEW:-0}" = 1 ] && command -v udevadm >/dev/null 2>&1; then
                    # OpenRGB's udev rules only reach devices plugged in after the package: apply them
                    # to what's there now, or its server can't open USB controllers (many motherboards,
                    # Razer, Corsair...) until the next reboot.
                    ELEV=(); case "${INSTALL_CMD[0]}" in sudo|doas) ELEV=("${INSTALL_CMD[0]}") ;; esac
                    "${ELEV[@]}" udevadm control --reload-rules 2>/dev/null || true
                    "${ELEV[@]}" udevadm trigger --subsystem-match=hidraw --subsystem-match=usb \
                        --subsystem-match=i2c-dev 2>/dev/null || true
                fi
                ;;
        esac
    fi
fi

# the Python just installed (Leap: python3.11)
if [ -z "$PY3" ]; then
    for c in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
            PY3="$c"; break
        fi
    done
fi
if [ -z "$PY3" ]; then
    echo "ERROR: Iridia needs Python 3.8 or newer, and none was found$(command -v python3 >/dev/null 2>&1 && echo " (python3 is $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null))")."
    exit 1
fi
if ! "$PY3" -c "$GTK_CHECK" >/dev/null 2>&1; then
    echo "NOTE: GTK 4 for Python (PyGObject + pycairo) is missing for $(command -v "$PY3"),"
    echo "      so the Iridia window won't open until you install it. The daemon works without it."
fi
if ! have_openrgb; then
    echo "NOTE: OpenRGB is not installed (Iridia can't drive LEDs without it)."
    echo "      If your distribution doesn't package it: the .deb or AppImage from https://openrgb.org, or"
    echo "      flatpak install flathub org.openrgb.OpenRGB. Iridia starts its server by itself once it's there."
fi
if ! command -v gdbus >/dev/null 2>&1; then
    echo "NOTE: 'gdbus' (part of GLib's tools) is missing: the LEDs won't turn off on suspend, and the lock"
    echo "      screen isn't seen. Debian/Ubuntu: libglib2.0-bin; openSUSE: glib2-tools."
fi
if ! command -v ddcutil &> /dev/null; then
    echo "NOTE: 'ddcutil' is not installed (optional: monitor-brightness-synced LEDs)."
fi

# --- monitor brightness: ddcutil needs read/write access to /dev/i2c-* -----
# That means: the i2c-dev module loaded, the i2c devices owned by an 'i2c' group, and you in it.
# Distributions differ in which of these they already do, so only what's missing is done.
I2C_USER="$USER"
[ "$(id -u)" -eq 0 ] && I2C_USER="${SUDO_USER:-}"
if command -v ddcutil >/dev/null 2>&1 && [ -n "$I2C_USER" ] && [ "$SKIP_DEPS" -eq 0 ]; then
    SUDO=(sudo); [ "$(id -u)" -eq 0 ] && SUDO=()
    I2C_TODO=()
    # ddcutil's own rules (60-ddcutil*.rules) often give the logged-in user the bus already (uaccess)
    HAVE_I2C=0
    for d in /dev/i2c-*; do
        if [ -r "$d" ] && [ -w "$d" ]; then HAVE_I2C=1; break; fi
    done
    if grep -qsE 'i2c.*TAG\+="uaccess"' /etc/udev/rules.d/*.rules /usr/lib/udev/rules.d/*.rules \
            /lib/udev/rules.d/*.rules; then
        HAVE_I2C=1
    fi
    if [ "$HAVE_I2C" -eq 0 ]; then
        getent group i2c >/dev/null 2>&1 || I2C_TODO+=("create the 'i2c' group")
        id -nG "$I2C_USER" 2>/dev/null | tr ' ' '\n' | grep -qx i2c || I2C_TODO+=("add $I2C_USER to it")
        # a udev rule giving the group the i2c devices (ddcutil's own package often ships one)
        if ! grep -qsE 'i2c.*GROUP="?i2c' /etc/udev/rules.d/*.rules /usr/lib/udev/rules.d/*.rules \
                /lib/udev/rules.d/*.rules; then
            I2C_TODO+=("give it the i2c devices (a udev rule)")
            I2C_RULE=1
        fi
    fi
    # the i2c-dev module at boot (ddcutil's package sometimes does this already)
    if ! grep -qsxE 'i2c[-_]dev' /etc/modules-load.d/*.conf /usr/lib/modules-load.d/*.conf \
            /run/modules-load.d/*.conf; then
        I2C_TODO+=("load the i2c-dev module now and at every boot")
        I2C_MOD=1
    fi
    if [ ${#I2C_TODO[@]} -gt 0 ]; then
        echo ""
        echo "Monitor brightness (ddcutil) needs access to the I2C bus. To set that up, this will:"
        for t in "${I2C_TODO[@]}"; do echo "  - $t"; done
        reply="y"
        if [ "$ASSUME_YES" -eq 0 ]; then
            read -r -p "Do that now (uses sudo)? [Y/n] " reply || reply="n"
        fi
        case "${reply:-y}" in
            n|N|no|NO)
                echo "Skipped. Monitor brightness may not work; see docs/wiki/Installation.md (Monitor brightness)." ;;
            *)
                if [ "$HAVE_I2C" -eq 0 ]; then
                    getent group i2c >/dev/null 2>&1 || "${SUDO[@]}" groupadd --system i2c \
                        || echo "WARNING: couldn't create the i2c group."
                fi
                if [ "$HAVE_I2C" -eq 0 ] && ! id -nG "$I2C_USER" | tr ' ' '\n' | grep -qx i2c; then
                    if "${SUDO[@]}" usermod -aG i2c "$I2C_USER"; then
                        I2C_RELOGIN=1
                    else
                        echo "WARNING: couldn't add $I2C_USER to the i2c group."
                    fi
                fi
                if [ "${I2C_RULE:-0}" = 1 ]; then
                    if echo 'KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"' \
                            | "${SUDO[@]}" tee /etc/udev/rules.d/45-iridia-i2c.rules >/dev/null; then
                        "${SUDO[@]}" udevadm control --reload-rules 2>/dev/null || true
                        "${SUDO[@]}" udevadm trigger --subsystem-match=i2c-dev 2>/dev/null || true
                    else
                        echo "WARNING: couldn't write the udev rule for the i2c group."
                    fi
                fi
                if [ "${I2C_MOD:-0}" = 1 ]; then
                    echo i2c-dev | "${SUDO[@]}" tee /etc/modules-load.d/i2c-dev.conf >/dev/null || true
                    "${SUDO[@]}" modprobe i2c-dev 2>/dev/null || true
                fi
                ;;
        esac
    fi
fi

# An older daemon left running would keep the old code alive (and block the
# new one through the single-instance lock), so stop it before upgrading.
if [ -x "$VENV_DIR/bin/iridia" ]; then
    "$VENV_DIR/bin/iridia" daemon stop >/dev/null 2>&1 || true
fi

rm -rf build ./*.egg-info
# Upgrade in place whenever the installed environment still works: quicker, and a failed pip run
# leaves the old Iridia working. Start fresh when there is none, or when Python changed underneath
# it (a distribution upgrade from 3.12 to 3.13 leaves it unable to import anything).
if [ "$UPDATE" -eq 0 ] && [ -x "$VENV_DIR/bin/python" ] \
        && "$VENV_DIR/bin/python" -c 'import iridia, PIL' >/dev/null 2>&1 \
        && [ "$("$VENV_DIR/bin/python" -c 'import sys; print(sys.version_info[:2])')" = "$("$PY3" -c 'import sys; print(sys.version_info[:2])')" ]; then
    UPDATE=1
elif [ "$UPDATE" -eq 1 ] && ! "$VENV_DIR/bin/python" -c 'import iridia, PIL' >/dev/null 2>&1; then
    echo "Python changed since Iridia was installed: building its environment again."
    UPDATE=0
fi
# if anything below fails, the daemon stopped above comes back
trap '"$VENV_DIR/bin/iridia" daemon start >/dev/null 2>&1 || true' ERR
if [ "$UPDATE" -eq 1 ]; then
    # In place: the installed libraries stay (quicker, works offline when nothing new is needed),
    # and pip replaces Iridia's own files cleanly.
    echo "Updating iridia..."
    "$VENV_DIR/bin/pip" install --upgrade --upgrade-strategy only-if-needed .
else
    echo "Creating virtual environment..."
    # --system-site-packages: the window uses your distro's GTK 4 bindings (PyGObject),
    # which can't be built with pip without a full compiler toolchain.
    # --clear: start fresh, so files from older versions can't linger.
    "$PY3" -m venv --system-site-packages --clear "$VENV_DIR"
    echo "Upgrading pip..."
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet
    echo "Installing iridia..."
    "$VENV_DIR/bin/pip" install .
fi
trap - ERR

echo "Creating config directory..."
mkdir -p "$CONFIG_DIR"

# --- how OpenRGB's server and the daemon start ----------------------------
PY="$VENV_DIR/bin/python"
# choose VAR DEFAULT NAME DESCRIPTION [NAME DESCRIPTION ...]: a numbered menu. Enter takes the default;
# a number or the name picks one. Sets VAR to the name.
choose() {
    local var=$1 def=$2 i=0 defn=1 reply n
    local names=()
    shift 2
    while [ $# -ge 2 ]; do
        i=$((i + 1))
        names+=("$1")
        if [ "$1" = "$def" ]; then
            defn=$i
            printf '  %d) %-11s %s  (default)\n' "$i" "$1" "$2"
        else
            printf '  %d) %-11s %s\n' "$i" "$1" "$2"
        fi
        shift 2
    done
    while true; do
        reply=""
        read -r -p "Choose 1-$i [$defn]: " reply || true      # end of input: what was typed, or the default
        reply="${reply:-$defn}"
        if [[ "$reply" =~ ^[0-9]+$ ]] && [ "$reply" -ge 1 ] && [ "$reply" -le "$i" ]; then
            printf -v "$var" '%s' "${names[$((reply - 1))]}"
            return
        fi
        for n in "${names[@]}"; do
            if [ "$n" = "$reply" ]; then printf -v "$var" '%s' "$n"; return; fi
        done
        echo "  Type a number from 1 to $i, or press Enter for $defn."
    done
}
if [ -z "$OPENRGB_METHOD" ] && [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; then
    CUR=$("$PY" -c "from iridia import openrgb_server as o; print(o.start_method())" 2>/dev/null || echo daemon)
    OTHERS=$("$PY" -c "from iridia import openrgb_server as o; print(', '.join(o.others()))" 2>/dev/null || true)
    OPTS=(daemon "the Iridia daemon starts it, inside your session (recommended; works with or without systemd)")
    "$PY" -c "from iridia import openrgb_server as o; raise SystemExit(0 if o.has_systemd() else 1)" 2>/dev/null &&
        OPTS+=(systemd "a systemd user service starts it with your graphical session")
    OPTS+=(off "you start OpenRGB yourself (its window with the SDK server on, a root service, ...)")
    echo ""
    echo "How should OpenRGB's server be started?"
    if [ -n "$OTHERS" ]; then
        echo "Something else already starts OpenRGB: $OTHERS"
        echo "Two OpenRGB instances fight over the hardware. Pick 'off' to keep that, or keep 'daemon' and turn"
        echo "that off (for an autostart entry: iridia openrgb hide-autostart)."
    fi
    choose OPENRGB_METHOD "$CUR" "${OPTS[@]}"
fi
if [ -z "$AUTOSTART" ]; then
    DEF=$("$PY" -c "from iridia.cli import default_autostart; print(default_autostart())" 2>/dev/null || echo xdg)
    if [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; then
        echo ""
        echo "How should the Iridia daemon start when you log in?"
        choose AUTOSTART "$DEF" \
            systemd "a systemd user service (needs a session that reaches graphical-session.target)" \
            xdg "an entry in ~/.config/autostart (GNOME, KDE, XFCE, Cinnamon, ...)" \
            compositor "a line in your compositor's config (Hyprland, Sway, niri, ...); printed below" \
            none "nothing; you start it yourself"
    else
        AUTOSTART="$DEF"
    fi
fi

# The desktop entry, icon, and services are all written by `iridia service install` itself (see
# iridia/cli.py) rather than duplicated here: it resolves the venv's own binary paths, so the
# generated files are always correct regardless of where this venv ends up living.
echo "Installing desktop entry, icon, and login autostart..."
SVC_ARGS=(--autostart "$AUTOSTART")
[ -n "$OPENRGB_METHOD" ] && SVC_ARGS+=(--openrgb "$OPENRGB_METHOD")
"$VENV_DIR/bin/iridia" service install "${SVC_ARGS[@]}"

# `iridia` and `iridia-gui` on the PATH: links in ~/.local/bin (never over a file that isn't ours)
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
for cmd in iridia iridia-gui; do
    target="$BIN_DIR/$cmd"
    if [ ! -e "$target" ] || { [ -L "$target" ] && readlink "$target" | grep -q "iridia-venv"; }; then
        ln -sfn "$VENV_DIR/bin/$cmd" "$target"
    fi
done
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo ""
       echo "NOTE: $BIN_DIR isn't on your PATH, so the 'iridia' command won't be found. Add it:"
       echo "  fish:      fish_add_path ~/.local/bin"
       echo "  bash/zsh:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc   (or ~/.zshrc)"
       echo "" ;;
esac

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
echo "  2. Check everything: iridia doctor"
echo "  3. Open the GUI from your launcher, or run:"
echo "                       $VENV_DIR/bin/iridia-gui"
echo ""
if [ "${I2C_RELOGIN:-0}" = 1 ]; then
    echo "You were added to the 'i2c' group: log out and back in once, so monitor brightness can work."
    echo ""
fi
echo "To uninstall: bash uninstall.sh (in this folder), or: iridia uninstall"
echo ""
