"""Translations for the window (gettext).

The language is the one picked in Settings, Appearance (saved as "language" in
~/.config/iridia/gui.json), or Proper English (British spelling) when none is
picked. Translations live in iridia/data/locale/<code>/
LC_MESSAGES/iridia.mo; their sources are po/<code>.po. The daemon's log and the
command line stay in English.
"""

import gettext
import json
import os

DOMAIN = "iridia"
LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "locale")
PREFS_PATH = os.path.expanduser("~/.config/iridia/gui.json")

# code -> name shown in the Language menu (never translated, so you can always find your way back).
# The joke codes don't match any real locale, so they are only used when picked.
LANGUAGES = {
    "en_GB": "Proper English",
    "en": "English (American)",
    "en_posh": "Posh English",
    "en_pirate": "Pirate",
    "fr_omelette": "Français",
}

DEFAULT = "en_GB"

_tr = None


def _pref() -> str:
    try:
        with open(PREFS_PATH, encoding="utf-8") as f:
            v = json.load(f).get("language", "")
        return v if isinstance(v, str) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def setup(lang=None):
    """Load the translation. lang: a code like "en_GB" or "en"; None or "" for the saved choice."""
    global _tr
    code = (_pref() if lang is None else lang) or DEFAULT
    if code == "en":
        _tr = gettext.NullTranslations()
    else:
        # an unknown code (or a missing .mo) falls back to the untranslated American English
        _tr = gettext.translation(DOMAIN, LOCALE_DIR, languages=[code], fallback=True)
    return current()


def current() -> str:
    """Code of the language in use ("en" when nothing is translated)."""
    if _tr is None:
        setup()
    info = _tr.info() if hasattr(_tr, "info") else {}
    lang = info.get("language", "") if isinstance(info, dict) else ""
    return lang or "en"


def available():
    """Languages with a translation installed, plus American English."""
    out = {"en": LANGUAGES["en"]}
    order = list(LANGUAGES)
    try:
        for code in sorted(os.listdir(LOCALE_DIR)):
            if os.path.exists(os.path.join(LOCALE_DIR, code, "LC_MESSAGES", DOMAIN + ".mo")):
                out[code] = LANGUAGES.get(code, code)
    except OSError:
        pass
    return dict(sorted(out.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99))


def _(text: str) -> str:
    if _tr is None:
        setup()
    return _tr.gettext(text)


def ngettext(singular: str, plural: str, n: int) -> str:
    if _tr is None:
        setup()
    return _tr.ngettext(singular, plural, n)


def pgettext(context: str, text: str) -> str:
    """Like _() but for a word that means different things in different places."""
    if _tr is None:
        setup()
    return _tr.pgettext(context, text)
