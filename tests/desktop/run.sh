#!/bin/sh
# Desktop checks on a real KWin (headless): scenes' focus watcher, then the window with the daemon.
# Needs kwin_wayland, dbus-run-session, gdbus and a Python with GTK 4 (PyGObject) and Iridia.
# Usage: sh tests/desktop/run.sh [PYTHON]   (run from the checkout; CI: .github/workflows/tests.yml)
set -u
PY=${1:-python3}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] || [ -z "${IRIDIA_DESKTOP_INNER:-}" ]; then
    IRIDIA_DESKTOP_INNER=1 exec dbus-run-session -- sh "$0" "$PY"
fi
WORK=$(mktemp -d)
# stop KWin and the daemon and let them finish writing before the folder goes; never changes the result
trap 'kill $KWIN $DAEMON 2>/dev/null; wait 2>/dev/null; rm -rf "$WORK" 2>/dev/null || true' EXIT
export HOME="$WORK/home" XDG_RUNTIME_DIR="$WORK/run" XDG_CONFIG_HOME="" XDG_CACHE_HOME="" XDG_STATE_HOME=""
unset XDG_CONFIG_HOME XDG_CACHE_HOME XDG_STATE_HOME DISPLAY WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE SWAYSOCK
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
export IRIDIA_KWIN_DEBUG=1          # the KWin script tells what it sees (printed when the check fails)
export XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true GTK_A11Y=none NO_AT_BRIDGE=1 PYTHONPATH="$ROOT"

# kwin_wayland carries a file capability (CAP_SYS_NICE) that containers refuse: a plain copy hasn't it
KW=$(command -v kwin_wayland) || { echo "kwin_wayland is missing"; exit 1; }
cp "$KW" "$WORK/kwin_wayland"
QT_QPA_PLATFORM=offscreen "$WORK/kwin_wayland" --virtual --socket wayland-iridia --width 1280 --height 800 \
    > "$WORK/kwin.log" 2>&1 &
KWIN=$!
DAEMON=""
i=0
until gdbus call --session --dest org.kde.KWin --object-path /Scripting \
        --method org.kde.kwin.Scripting.isScriptLoaded x >/dev/null 2>&1; do
    i=$((i + 1))
    if [ $i -gt 100 ] || ! kill -0 $KWIN 2>/dev/null; then
        echo "KWin didn't start:"; cat "$WORK/kwin.log"; exit 1
    fi
    sleep 0.2
done
echo "KWin $("$WORK/kwin_wayland" --version 2>/dev/null | tail -1) is up"
export WAYLAND_DISPLAY=wayland-iridia GDK_BACKEND=wayland
fail=0

if ! "$PY" "$HERE/focus_check.py" > "$WORK/focus.log" 2>&1; then
    fail=1
    echo "KWin's log:"
    grep -v "MESA\|EGL\|aurorae\|^ *\^\|^ *$" "$WORK/kwin.log" | tail -40
fi
cat "$WORK/focus.log"

# the daemon, with the fake OpenRGB first on PATH (it starts it by itself)
mkdir -p "$WORK/bin"
ln -s "$ROOT/tests/fakes/openrgb" "$WORK/bin/openrgb"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$(command -v "$PY")" > "$WORK/bin/python3"
chmod +x "$WORK/bin/python3"
export FAKE_OPENRGB_MODE=devices
PATH="$WORK/bin:$PATH" "$PY" -m iridia.daemon > "$WORK/daemon.log" 2>&1 &
DAEMON=$!
sleep 4
PATH="$WORK/bin:$PATH" "$PY" "$HERE/window_check.py" > "$WORK/window.log" 2>&1 || fail=1
cat "$WORK/window.log"
if grep -E "CRITICAL|Traceback" "$WORK/window.log" "$WORK/daemon.log" >/dev/null; then
    echo "GTK criticals or Python errors above (or in the daemon's log):"
    grep -E -A3 "CRITICAL|Traceback" "$WORK/daemon.log" | head -40
    fail=1
fi
[ $fail -eq 0 ] && echo "desktop checks passed"
exit $fail
