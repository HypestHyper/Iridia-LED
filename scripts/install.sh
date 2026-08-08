#!/bin/bash
set -e

VENV_DIR="$HOME/.local/share/iridia-venv"
CONFIG_DIR="$HOME/.config/iridia"
SERVICE_DIR="$HOME/.config/systemd/user"
APPS_DIR="$HOME/.local/share/applications"

echo "============================================"
echo "  Iridia — Installer"
echo "============================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Please install Python 3."
    exit 1
fi

# Create venv
echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

# Upgrade pip
echo "Upgrading pip..."
"$VENV_DIR/bin/pip" install --upgrade pip

# Install package
echo "Installing iridia..."
if [ -f "pyproject.toml" ]; then
    "$VENV_DIR/bin/pip" install .
else
    echo "WARNING: pyproject.toml not found in current directory."
    echo "Attempting to install from local directory anyway..."
    "$VENV_DIR/bin/pip" install -e .
fi

# Create config directory
echo "Creating config directory..."
mkdir -p "$CONFIG_DIR"

# Install desktop entry
echo "Installing desktop entry..."
mkdir -p "$APPS_DIR"
cp data/iridia.desktop "$APPS_DIR/iridia.desktop" 2>/dev/null || true
# If data/ not available (pip install from PyPI), create it inline
if [ ! -f "$APPS_DIR/iridia.desktop" ]; then
    cat > "$APPS_DIR/iridia.desktop" << 'EOF'
[Desktop Entry]
Name=Iridia
Comment=Sync LED colors with wallpaper via OpenRGB
Exec=iridia-gui
Type=Application
Terminal=false
Categories=System;Settings;HardwareSettings;
Keywords=led;rgb;openrgb;wallpaper;light;strip;
Icon=preferences-desktop-display-color
StartupNotify=false
StartupWMClass=iridia-gui
EOF
fi
chmod +x "$APPS_DIR/iridia.desktop"

# Update desktop database (best effort)
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

# Install systemd service
echo "Installing systemd user service..."
mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_DIR/iridia-daemon.service" << EOF
[Unit]
Description=Iridia Daemon
After=graphical-session.target network.target
Wants=graphical-session.target

[Service]
Type=simple
ExecStart=$VENV_DIR/bin/python3 -m iridia.daemon
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
Environment="PYTHONUNBUFFERED=1"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

echo ""
echo "============================================"
echo "  Installation complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit your config:"
echo "     $ iridia config edit"
echo ""
echo "  2. Add your OpenRGB devices to:"
echo "     ~/.config/iridia/config.json"
echo ""
echo "  3. Start the daemon:"
echo "     $ iridia-daemon        (foreground)"
echo "     $ iridia service start  (background via systemd)"
echo ""
echo "  4. Launch the tray app from your app launcher"
echo "     (search for 'Iridia' in wofi/rofi/GNOME/KDE)"
echo ""
echo "  5. Enable autostart:"
echo "     $ iridia service install"
echo ""
echo "  6. Check status:"
echo "     $ iridia status"
echo "     $ journalctl --user -u iridia-daemon -f"
echo ""
echo "  7. View log file (when enabled):"
echo "     ~/.local/share/iridia/iridia.log"
echo ""
