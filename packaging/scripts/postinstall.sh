#!/bin/sh
# Byte-compile for the Python that's installed (it can't write caches into /usr by itself), and let
# the menus and icon caches see the new files. None of this is needed for Iridia to work.
python3 -m compileall -q /usr/lib/iridia >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
exit 0
