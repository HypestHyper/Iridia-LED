#!/bin/sh
# Lays Iridia out as a system package would install it, under DESTDIR:
#   /usr/lib/iridia/iridia/            the program (pure Python, for any Python 3.10+)
#   /usr/bin/iridia, iridia-gui, iridia-daemon
#   /usr/lib/systemd/user/iridia-daemon.service
#   the launcher, metainfo, icons, licence
# Used by build.sh (.deb, .rpm, Arch) and by arch/PKGBUILD. Usage: sh packaging/stage.sh DESTDIR
set -eu
DEST=${1:?usage: stage.sh DESTDIR}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP=io.github.HypestHyper.Iridia

install -d "$DEST/usr/lib/iridia" "$DEST/usr/bin"
# the program, without caches (they're made after installing, for the Python that's there)
tar -C "$ROOT" --exclude='__pycache__' --exclude='*.pyc' -cf - iridia | tar -C "$DEST/usr/lib/iridia" -xf -

for pair in "iridia:iridia.cli" "iridia-gui:iridia.gui" "iridia-daemon:iridia.daemon"; do
    name=${pair%%:*}
    mod=${pair#*:}
    cat > "$DEST/usr/bin/$name" <<PY
#!/usr/bin/python3
# $name: Iridia, installed as a system package (/usr/lib/iridia).
import os
import sys

LIB = "/usr/lib/iridia"
sys.path.insert(0, LIB)
# what Iridia starts with the same Python (python3 -m iridia.cli ...) finds it too
os.environ["PYTHONPATH"] = LIB + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
from $mod import main  # noqa: E402

sys.exit(main())
PY
    chmod 755 "$DEST/usr/bin/$name"
done

install -Dm644 /dev/stdin "$DEST/usr/lib/systemd/user/iridia-daemon.service" <<'UNIT'
[Unit]
Description=Iridia Daemon
After=graphical-session.target
PartOf=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart=/usr/bin/iridia-daemon
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=graphical-session.target
UNIT

sed "s|^Exec=.*|Exec=/usr/bin/iridia-gui|" "$ROOT/data/$APP.desktop" \
    | install -Dm644 /dev/stdin "$DEST/usr/share/applications/$APP.desktop"
install -Dm644 "$ROOT/data/$APP.metainfo.xml" "$DEST/usr/share/metainfo/$APP.metainfo.xml"
install -Dm644 "$ROOT/iridia/data/iridia.svg" "$DEST/usr/share/icons/hicolor/scalable/apps/iridia.svg"
install -Dm644 "$ROOT/iridia/data/iridia-symbolic.svg" "$DEST/usr/share/icons/hicolor/symbolic/apps/iridia-symbolic.svg"
for n in 48 64 128 256; do
    install -Dm644 "$ROOT/iridia/data/iridia-$n.png" "$DEST/usr/share/icons/hicolor/${n}x$n/apps/iridia.png"
done
install -Dm644 "$ROOT/LICENSE" "$DEST/usr/share/licenses/iridia/LICENSE"
install -Dm644 "$ROOT/LICENSE" "$DEST/usr/share/doc/iridia/copyright"
