#!/bin/sh
# The caches postinstall made aren't the package's files: take them away with it. Not on an upgrade
# ($1 is "upgrade" for a .deb, "1" for an .rpm), where the new version's caches are already there.
case "${1:-}" in upgrade|1) exit 0 ;; esac
find /usr/lib/iridia -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
exit 0
