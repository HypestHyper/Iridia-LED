#!/bin/sh
# Builds the .deb and .rpm into dist/: iridia_VERSION_all.deb and iridia-VERSION-1.noarch.rpm (the Arch
# package: makepkg in packaging/arch, see arch-build.sh). Needs nfpm (https://nfpm.goreleaser.com):
#   go install github.com/goreleaser/nfpm/v2/cmd/nfpm@v2.46.3
# Usage: sh packaging/build.sh [OUTDIR]
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-$ROOT/dist}
NFPM=${NFPM:-nfpm}
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/iridia/__init__.py")
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
sh "$ROOT/packaging/stage.sh" "$STAGE"
mkdir -p "$OUT"
cd "$ROOT"
sed -e "s|@VERSION@|$VERSION|" -e "s|@STAGE@|$STAGE|" packaging/nfpm.yaml > "$STAGE.yaml"
trap 'rm -rf "$STAGE" "$STAGE.yaml"' EXIT
for fmt in deb rpm; do
    "$NFPM" package --config "$STAGE.yaml" --packager "$fmt" --target "$OUT/"
done
ls -l "$OUT"
