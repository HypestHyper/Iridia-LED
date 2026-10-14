#!/bin/bash
# Publish docs/wiki/ as the project's GitHub wiki.
#
#   bash scripts/publish_wiki.sh https://github.com/OWNER/iridia.wiki.git
#
# GitHub creates the wiki repository only after the first page is saved on the website, so create
# any page there once first. Links between pages are written as "Page.md" so they work when browsing
# the repository; the wiki wants "Page", so they are rewritten on the way.
set -euo pipefail

WIKI_URL="${1:-}"
if [ -z "$WIKI_URL" ]; then
    echo "Usage: bash scripts/publish_wiki.sh https://github.com/OWNER/iridia.wiki.git"
    exit 1
fi
SRC="$(cd "$(dirname "$(readlink -f "$0")")/../docs/wiki" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --quiet "$WIKI_URL" "$WORK/wiki"
find "$WORK/wiki" -maxdepth 1 -name '*.md' -delete
for f in "$SRC"/*.md; do
    sed -E 's/\]\(([A-Za-z0-9_-]+)\.md(#[^)]*)?\)/](\1\2)/g' "$f" > "$WORK/wiki/$(basename "$f")"
done
cd "$WORK/wiki"
git add -A
if git diff --cached --quiet; then
    echo "The wiki is already up to date."
    exit 0
fi
git commit --quiet -m "Update wiki from docs/wiki"
git push --quiet
echo "Wiki published."
