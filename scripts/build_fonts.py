#!/usr/bin/env python3
"""Rebuild the fonts in iridia/data/fonts (maintainers only; the results are committed).

Sources (from npm, any machine with npm):
    npm pack material-symbols @fontsource/google-sans-flex
    tar xzf material-symbols-*.tgz; tar xzf fontsource-google-sans-flex-*.tgz

Usage:
    pip install fonttools brotli
    python3 scripts/build_fonts.py path/to/material-symbols/package path/to/google-sans-flex/package

Writes:
    iridia/data/fonts/MaterialSymbolsRounded-Iridia.ttf   only the icons in iridia/ui/icon_names.py
    iridia/data/fonts/icons.json                           icon name -> codepoint
    iridia/data/fonts/GoogleSansFlex-*.ttf                 Latin + Latin Extended, 400/500/700
"""

import json
import os
import shutil
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "iridia", "data", "fonts")
sys.path.insert(0, ROOT)
from iridia.ui.icon_names import ICON_NAMES  # noqa: E402


def icons(src_pkg):
    full = TTFont(os.path.join(src_pkg, "material-symbols-rounded.woff2"))
    rev = {}
    for cp, name in sorted(full.getBestCmap().items()):
        rev.setdefault(name, cp)
    missing = [n for n in ICON_NAMES if n not in rev]
    if missing:
        sys.exit(f"not in the font: {missing}")
    cps = {n: rev[n] for n in ICON_NAMES}
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.hinting = False
    opts.flavor = None
    s = subset.Subsetter(opts)
    s.populate(unicodes=sorted(set(cps.values())))
    s.subset(full)
    full.flavor = None
    full.save(os.path.join(OUT, "MaterialSymbolsRounded-Iridia.ttf"))
    with open(os.path.join(OUT, "icons.json"), "w") as f:
        json.dump(cps, f, indent=0, sort_keys=True)
    shutil.copy(os.path.join(src_pkg, "LICENSE"), os.path.join(OUT, "LICENSE-MaterialSymbols.txt"))


def text(src_pkg):
    files = os.path.join(src_pkg, "files")
    for w in (400, 500, 700):
        for part in ("latin", "latin-ext"):
            f = TTFont(os.path.join(files, f"google-sans-flex-{part}-{w}-normal.woff2"))
            f.flavor = None
            f.save(os.path.join(OUT, f"GoogleSansFlex-{part}-{w}.ttf"))
    shutil.copy(os.path.join(src_pkg, "LICENSE"), os.path.join(OUT, "LICENSE-GoogleSansFlex.txt"))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    os.makedirs(OUT, exist_ok=True)
    icons(sys.argv[1])
    text(sys.argv[2])
    print("fonts written to", OUT)
