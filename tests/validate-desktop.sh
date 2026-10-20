#!/bin/sh
# Checks the desktop entry, AppStream metadata and icons, and that every place holding the version
# agrees. Needs desktop-file-utils and appstream (appstreamcli).
set -eu
cd "$(dirname "$0")/.."
ID=io.github.HypestHyper.Iridia
fail=0

desktop-file-validate "data/$ID.desktop" || fail=1
appstreamcli validate --no-net "data/$ID.metainfo.xml" || fail=1

for svg in data/icons/hicolor/scalable/apps/*.svg data/icons/hicolor/symbolic/apps/*.svg; do
    w=$(sed -n 's/.*<svg[^>]* width="\([0-9.]*\)[a-z]*".*/\1/p' "$svg" | head -n 1)
    h=$(sed -n 's/.*<svg[^>]* height="\([0-9.]*\)[a-z]*".*/\1/p' "$svg" | head -n 1)
    if [ -z "$w" ]; then        # the attributes can be on the lines after <svg
        w=$(sed -n 's/^ *width="\([0-9.]*\)[a-z]*".*/\1/p' "$svg" | head -n 1)
        h=$(sed -n 's/.*height="\([0-9.]*\)[a-z]*".*/\1/p' "$svg" | head -n 1)
    fi
    if [ -z "$w" ] || [ "$w" != "$h" ]; then
        echo "$svg isn't square (${w:-?} x ${h:-?})"; fail=1
    fi
done

v=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' iridia/__init__.py)
[ -n "$v" ] || { echo "No VERSION in iridia/__init__.py"; exit 1; }
grep -q "^version = \"$v\"" pyproject.toml || { echo "pyproject.toml doesn't say version $v"; fail=1; }
grep -q "^## $v " CHANGELOG.md || { echo "CHANGELOG.md has no '## $v ' section"; fail=1; }
grep -q "<release version=\"$v\"" "data/$ID.metainfo.xml" || { echo "The metainfo has no release $v"; fail=1; }
grep -q "^pkgver=$v\$" packaging/arch/PKGBUILD || { echo "PKGBUILD doesn't say pkgver=$v"; fail=1; }
grep -q "badge/version-$v-" README.md || { echo "The README's version badge doesn't say $v"; fail=1; }

[ "$fail" = 0 ] && echo "All checks passed (version $v)."
exit "$fail"
