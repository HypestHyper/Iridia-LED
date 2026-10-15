#!/usr/bin/env python3
"""Rebuild the window's translations (maintainers only; the results are committed).

    pip install babel
    python3 scripts/build_locales.py            # extract po/iridia.pot, check and compile po/*.po
    python3 scripts/build_locales.py --update   # also merge new strings into every po/*.po

Each po/<code>.po is compiled to iridia/data/locale/<code>/LC_MESSAGES/iridia.mo. A
translation that uses a {placeholder} the English text doesn't have would crash the
window, so those are reported and left out of the compiled file.
"""

import os
import string
import sys

from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO_DIR = os.path.join(ROOT, "po")
OUT = os.path.join(ROOT, "iridia", "data", "locale")
KEYWORDS = {"_": None, "ngettext": (1, 2), "N_": None, "pgettext": ((1, "c"), 2)}


def extract() -> Catalog:
    cat = Catalog(project="Iridia", copyright_holder="Iridia Contributors")
    for sub in ("iridia/ui", "iridia"):
        base = os.path.join(ROOT, sub)
        method = [("**.py", "python")] if sub == "iridia/ui" else [("calibration.py", "python"), ("**", "ignore")]
        for fn, lineno, msg, comments, ctx in extract_from_dir(base, method_map=method, keywords=KEYWORDS):
            cat.add(msg, None, [(os.path.join(sub, fn), lineno)], auto_comments=comments, context=ctx)
    return cat


def fields(text: str) -> set:
    try:
        return {f for _lit, f, _spec, _conv in string.Formatter().parse(text) if f is not None}
    except ValueError:
        return {"<broken braces>"}


def check(msg) -> list:
    """Problems with one translated message."""
    ids = msg.id if isinstance(msg.id, (list, tuple)) else [msg.id]
    strs = msg.string if isinstance(msg.string, (list, tuple)) else [msg.string]
    allowed = set().union(*(fields(i) for i in ids))
    bad = []
    for s in strs:
        if not s:
            continue
        extra = fields(s) - allowed
        if extra:
            bad.append(f"{ids[0]!r}: unknown placeholder(s) {sorted(extra)}")
    return bad


def main():
    pot = extract()
    with open(os.path.join(PO_DIR, "iridia.pot"), "wb") as f:
        write_po(f, pot, width=100)
    print(f"po/iridia.pot: {len(pot)} strings")
    for fn in sorted(os.listdir(PO_DIR)):
        if not fn.endswith(".po"):
            continue
        code = fn[:-3]
        path = os.path.join(PO_DIR, fn)
        with open(path, "rb") as f:
            cat = read_po(f, locale=None)
        if "--update" in sys.argv:
            cat.update(pot)
            with open(path, "wb") as f:
                write_po(f, cat, width=100)
        problems, missing = [], 0
        for msg in list(cat):
            if not msg.id:
                continue
            p = check(msg)
            if p:
                problems += p
                msg.string = "" if not isinstance(msg.id, (list, tuple)) else ("",) * len(msg.string)
            if not msg.string or (isinstance(msg.string, (list, tuple)) and not all(msg.string)):
                missing += 1
        os.makedirs(os.path.join(OUT, code, "LC_MESSAGES"), exist_ok=True)
        with open(os.path.join(OUT, code, "LC_MESSAGES", "iridia.mo"), "wb") as f:
            write_mo(f, cat, use_fuzzy=False)
        print(f"{code}: {len(cat) - missing} of {len(cat)} translated" + (f", {len(problems)} rejected" if problems else ""))
        for p in problems:
            print("   ", p)


if __name__ == "__main__":
    main()
