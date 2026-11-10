#!/bin/sh
# Installs a built package on this system (a fresh container: Arch, Debian/Ubuntu, Fedora) with its
# dependencies from the distribution, checks that Iridia works from /usr, then removes it and checks
# nothing is left. Run as root. Usage: sh packaging/test-install.sh PACKAGE_FILE
set -eu
PKG=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
say() { printf '\n== %s\n' "$*"; }

say "installing $(basename "$PKG")"
case "$PKG" in
    *.deb) export DEBIAN_FRONTEND=noninteractive
           apt-get update -qq && apt-get install -y -qq --no-install-recommends "$PKG" >/dev/null ;;
    *.rpm) dnf install -y -q "$PKG" >/dev/null ;;
    *.pkg.tar.*) pacman -Syu --noconfirm >/dev/null
                 pacman -U --noconfirm "$PKG" >/dev/null ;;
    *) echo "unknown package type: $PKG"; exit 2 ;;
esac

say "a virtual display for the window check"
case "$PKG" in
    *.deb) apt-get install -y -qq --no-install-recommends xvfb xauth >/dev/null ;;
    *.rpm) dnf install -y -q xorg-x11-server-Xvfb xauth which >/dev/null; command -v xvfb-run >/dev/null || dnf install -y -q /usr/bin/xvfb-run >/dev/null ;;
    *) pacman -S --noconfirm --needed xorg-server-xvfb xorg-xauth >/dev/null ;;
esac

say "version"
iridia --version
want=$(basename "$PKG" | sed -E 's/^iridia[-_]([0-9][0-9.]*[0-9]).*/\1/')
iridia --version | grep -qx "iridia $want"

say "files"
for f in /usr/bin/iridia /usr/bin/iridia-gui /usr/bin/iridia-daemon /usr/lib/iridia/iridia/__init__.py \
         /usr/lib/systemd/user/iridia-daemon.service /usr/share/applications/io.github.HypestHyper.Iridia.desktop \
         /usr/share/metainfo/io.github.HypestHyper.Iridia.metainfo.xml /usr/share/icons/hicolor/scalable/apps/iridia.svg; do
    test -e "$f" || { echo "missing: $f"; exit 1; }
done
find /usr/lib/iridia -name '*.pyc' | grep -q . || { echo "not byte-compiled"; exit 1; }
echo ok

say "a system package, as far as Iridia can tell"
python3 - <<'PY'
import sys
sys.path.insert(0, "/usr/lib/iridia")
from iridia import updater
assert updater.install_kind() == "package", updater.install_kind()
print("install kind:", updater.install_kind())
PY

say "the window's modules load (GTK 4, PyGObject, pycairo, Pillow)"
python3 - <<'PY'
import sys
sys.path.insert(0, "/usr/lib/iridia")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: F401
import cairo  # noqa: F401
import PIL  # noqa: F401
import watchdog  # noqa: F401
import iridia.ui.app  # noqa: F401
print("ok, GTK", Gtk.get_major_version(), Gtk.get_minor_version())
PY

say "the daemon runs and answers"
useradd -m iridiatest 2>/dev/null || true
# shellcheck disable=SC2016  # expanded by the test user's shell, on purpose
su iridiatest -s /bin/sh -c '
    set -e
    export HOME=/home/iridiatest XDG_RUNTIME_DIR=$(mktemp -d)
    chmod 700 "$XDG_RUNTIME_DIR"
    python3 -c "import json,os; os.makedirs(os.path.expanduser(\"~/.config/iridia\"), exist_ok=True); json.dump({\"openrgb\": {\"start_method\": \"off\"}}, open(os.path.expanduser(\"~/.config/iridia/config.json\"), \"w\"))"
    iridia-daemon >"$HOME/daemon.log" 2>&1 &
    pid=$!
    i=0
    until iridia status >/dev/null 2>&1; do
        i=$((i + 1)); [ $i -gt 40 ] && { cat "$HOME/daemon.log"; exit 1; }; sleep 0.5
    done
    iridia status | head -5
    echo "-- the window, on a virtual display, for 8 seconds"
    rc=0
    xvfb-run -a timeout 8 iridia-gui >"$HOME/gui.log" 2>&1 || rc=$?
    if [ $rc != 124 ] || grep -E "Traceback|Error:|CRITICAL" "$HOME/gui.log"; then
        echo "the window failed (exit $rc):"; cat "$HOME/gui.log"; exit 1
    fi
    echo "the window opened and ran"
    iridia daemon stop >/dev/null 2>&1 || kill $pid
    wait $pid 2>/dev/null || true
'

say "installing it again over itself (as an upgrade does)"
case "$PKG" in
    *.deb) apt-get install -y -qq --reinstall "$PKG" >/dev/null ;;
    *.rpm) dnf reinstall -y -q "$PKG" >/dev/null ;;
    *) pacman -U --noconfirm "$PKG" >/dev/null ;;
esac
iridia --version
find /usr/lib/iridia -name '*.pyc' | grep -q . || { echo "caches gone after the upgrade"; exit 1; }
echo ok

say "removing"
case "$PKG" in
    *.deb) apt-get remove -y -qq iridia >/dev/null ;;
    *.rpm) dnf remove -y -q iridia >/dev/null ;;
    *) pacman -R --noconfirm iridia >/dev/null ;;
esac
for f in /usr/lib/iridia /usr/bin/iridia /usr/lib/systemd/user/iridia-daemon.service; do
    test ! -e "$f" || { echo "left behind: $f"; find "$f" | head; exit 1; }
done
echo "nothing left behind"
say "all good"
