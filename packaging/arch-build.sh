#!/bin/sh
# Builds the Arch package (iridia-VERSION-1-any.pkg.tar.zst) from this checkout with makepkg, in an
# Arch system or container: the release archive is made here (as the release does), so nothing is
# downloaded. makepkg won't run as root; as root, this builds as the user "builder" (made if needed).
# Usage: sh packaging/arch-build.sh [OUTDIR]
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mkdir -p "${1:-$ROOT/dist}" && cd "${1:-$ROOT/dist}" && pwd)
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/iridia/__init__.py")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp "$ROOT/packaging/arch/PKGBUILD" "$ROOT/packaging/arch/iridia.install" "$WORK/"
sed -i "s/^pkgver=.*/pkgver=$VERSION/" "$WORK/PKGBUILD"
# the archive the release publishes (the files git knows, without tests/, .github/ and scripts/),
# with iridia/ at its top
(cd "$ROOT" && git ls-files --cached --others --exclude-standard -z -- . ':!tests' ':!.github' ':!scripts' \
    | tar --null -T - --transform 's|^|iridia/|' -czf "$WORK/iridia-$VERSION.tar.gz")
if [ "$(id -u)" = 0 ]; then
    id builder >/dev/null 2>&1 || useradd -m builder
    chown -R builder "$WORK"
    su builder -c "cd '$WORK' && PKGDEST='$WORK/out' makepkg --nodeps --noconfirm -f"
else
    (cd "$WORK" && PKGDEST="$WORK/out" makepkg --nodeps --noconfirm -f)
fi
cp "$WORK"/out/*.pkg.tar.* "$OUT/"
ls -l "$OUT"
