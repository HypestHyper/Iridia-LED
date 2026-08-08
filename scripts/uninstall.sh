#!/bin/bash

VENV_DIR="$HOME/.local/share/iridia-venv"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="iridia-daemon.service"
APPS_DIR="$HOME/.local/share/applications"

echo "============================================"
echo "  Iridia — Uninstaller"
echo "============================================"
echo ""

# Stop and disable service
echo "Stopping service..."
systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true

# Remove service file
if [ -f "$SERVICE_DIR/$SERVICE_NAME" ]; then
    echo "Removing systemd service file..."
    rm "$SERVICE_DIR/$SERVICE_NAME"
fi

systemctl --user daemon-reload 2>/dev/null || true

# Remove desktop entry
if [ -f "$APPS_DIR/iridia.desktop" ]; then
    echo "Removing desktop entry..."
    rm "$APPS_DIR/iridia.desktop"
fi

if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

# Remove venv
if [ -d "$VENV_DIR" ]; then
    echo "Removing virtual environment..."
    rm -rf "$VENV_DIR"
fi

echo ""
read -p "Remove config files at ~/.config/iridia/? [y/N] " answer
if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
    rm -rf "$HOME/.config/iridia"
    echo "Config removed."
else
    echo "Config preserved at ~/.config/iridia/"
fi

echo ""
echo "============================================"
echo "  Uninstall complete."
echo "============================================"
