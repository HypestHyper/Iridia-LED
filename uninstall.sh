#!/bin/bash
# Removes Iridia. Thin wrapper around `iridia uninstall`, with a manual
# fallback for when the virtualenv is already gone or broken.
VENV_DIR="$HOME/.local/share/iridia-venv"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="iridia-daemon.service"
APPS_DIR="$HOME/.local/share/applications"

if [ "$1" = "--keep-settings" ]; then KEEP=1
elif [ "$1" = "--purge" ]; then KEEP=0
else
    read -r -p "Also delete your settings in ~/.config/iridia/? [y/N] " answer
    case "$answer" in y|Y) KEEP=0 ;; *) KEEP=1 ;; esac
fi

if [ -x "$VENV_DIR/bin/iridia" ]; then
    if [ "$KEEP" = 1 ]; then "$VENV_DIR/bin/iridia" uninstall --yes --keep-settings
    else "$VENV_DIR/bin/iridia" uninstall --yes; fi
    exit $?
fi

echo "Iridia's virtualenv wasn't found; removing the known files directly..."
systemctl --user disable --now "$SERVICE_NAME" iridia-openrgb.service 2>/dev/null || true
# the OpenRGB server the daemon started, if any (its PID file says which one)
if [ -n "$XDG_RUNTIME_DIR" ]; then PIDF="$XDG_RUNTIME_DIR/iridia-openrgb.pid"; else PIDF="/tmp/iridia-openrgb-$(id -u).pid"; fi
if [ -f "$PIDF" ]; then
    # only if that PID is still an OpenRGB (a stale file could name a reused PID)
    read -r OPID _ < "$PIDF" && [ -n "$OPID" ] && tr '\0' ' ' < "/proc/$OPID/cmdline" 2>/dev/null \
        | grep -qi openrgb && kill "$OPID" 2>/dev/null
    rm -f "$PIDF"
fi
rm -f "$SERVICE_DIR/$SERVICE_NAME" "$SERVICE_DIR/iridia-openrgb.service" "$APPS_DIR/iridia.desktop" "$APPS_DIR/io.github.iridia.Iridia.desktop" "$APPS_DIR/io.github.HypestHyper.Iridia.desktop" "$HOME/.config/autostart/iridia-daemon.desktop"
find "$HOME/.local/share/icons/hicolor" -name 'iridia*' -delete 2>/dev/null
systemctl --user daemon-reload 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null
if [ "$KEEP" = 0 ]; then
    rm -rf "$HOME/.config/iridia" "$HOME/.cache/iridia" "$HOME/.local/share/iridia"
    echo "Settings removed."
fi
echo "Iridia is uninstalled."
