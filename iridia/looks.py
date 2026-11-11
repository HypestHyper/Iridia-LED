"""Looks and favourites.

A look is a one-tap change you name yourself ("Movie": everything at 15%; "Gaming": the desk red, the
room off): a look (off, dimmer, one colour, an effect; see scenes.py) for some strips or all of them.
Turning it on puts that look on top of those strips the way a keybind does, so the settings don't
change; turning it off (or `iridia zone ... normal`) puts them back.

Favourites are the tiles on the Favourites tab, in order: cards you make (a title, some strips or all of
them, and the controls to show for them: on/off, brightness, colours, follow the monitor, stay lit,
effect, look chips, switch chips), a single look, a saved setup, or a switch (lights, freeze, night
mode, animations, scenes, notifications, network lights). Each has a size: small, wide, tall or large.

Config:
  looks      [{"id": "a1b2", "name": "Movie", "targets": ["*"] or ["Device|Zone", ...], "look": {...}}]
  favorites  [{"type": "card", "id": "c3d4", "title": "Desk", "targets": ["Device|Zone", ...] or ["*"],
               "controls": ["power", "brightness", "colors", ...], "looks": [ids], "scenes": [scene ids],
              "switches": [...],
               "size": "s"|"w"|"t"|"l"},
              {"type": "look", "id": "a1b2", "size": "s"}, {"type": "setup", "name": "Evening"},
              {"type": "switch", "what": "lights"}]
"""
import re
import secrets

from iridia import scenes

SWITCHES = ("lights", "freeze", "night", "animations", "scenes", "notify", "netlights")
TILE_TYPES = ("card", "look", "setup", "switch")
# what a card can show, for its strips
CONTROLS = ("power", "brightness", "colors", "follow", "stay_lit", "effect", "looks", "scenes", "switches")
SIZES = ("s", "w", "t", "l")        # small 1x1, wide 2x1, tall 1x2, large 2x2
SPAN = {"s": (1, 1), "w": (2, 1), "t": (1, 2), "l": (2, 2)}
LOOKS_MAX = 60
FAVORITES_MAX = 80


def new_id() -> str:
    return secrets.token_hex(3)


def clean_look(raw) -> dict | None:
    """A look with a name, targets and what it does; None if it can't be one."""
    if not isinstance(raw, dict):
        return None
    name = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()[:40]
    look = scenes.clean_look(raw.get("look"))
    if not name or look is None:
        return None
    t = raw.get("targets")
    targets = ["*"] if t in (None, "*", "all") or t == ["*"] else \
        [str(k) for k in t if isinstance(k, str) and "|" in k] if isinstance(t, list) else []
    if not targets:
        return None
    lid = str(raw.get("id") or "")
    return {"id": lid if re.fullmatch(r"[0-9a-f]{4,12}", lid) else new_id(), "name": name,
            "targets": list(dict.fromkeys(targets)), "look": look}


def clean_looks(raw) -> list[dict]:
    out, ids, names = [], set(), set()
    for x in raw if isinstance(raw, list) else []:
        lk = clean_look(x)
        if lk is None or lk["name"].lower() in names or len(out) >= LOOKS_MAX:
            continue
        while lk["id"] in ids:
            lk["id"] = new_id()
        ids.add(lk["id"])
        names.add(lk["name"].lower())
        out.append(lk)
    return out


def clean_card(raw) -> dict | None:
    """A card: a title, its strips (zone keys, or ["*"]), the controls it shows (in that order), the
    looks and switches its chips are for, and its size."""
    t = raw.get("targets")
    targets = ["*"] if t == ["*"] or t == "*" else \
        list(dict.fromkeys(k for k in t if isinstance(k, str) and "|" in k)) if isinstance(t, list) else []
    controls = [c for c in dict.fromkeys(raw.get("controls") or []) if c in CONTROLS]
    if not controls:
        return None
    lid = str(raw.get("id") or "")
    return {"type": "card", "id": lid if re.fullmatch(r"[0-9a-f]{4,12}", lid) else new_id(),
            "title": re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()[:40], "targets": targets,
            "controls": controls,
            "looks": [x for x in dict.fromkeys(raw.get("looks") or []) if isinstance(x, str)][:12],
            "scenes": [x for x in dict.fromkeys(raw.get("scenes") or []) if isinstance(x, str)][:12],
            "switches": [x for x in dict.fromkeys(raw.get("switches") or []) if x in SWITCHES],
            "size": raw.get("size") if raw.get("size") in SIZES else "w"}


def clean_tile(raw) -> dict | None:
    if isinstance(raw, dict) and raw.get("type") == "device" and isinstance(raw.get("key"), str) and "|" in raw["key"]:
        # a one-strip tile from before cards: a card for that strip
        raw = {"type": "card", "targets": [raw["key"]], "controls": ["power", "brightness", "colors"],
               "size": "w"}
    if not isinstance(raw, dict) or raw.get("type") not in TILE_TYPES:
        return None
    t = raw["type"]
    if t == "card":
        return clean_card(raw)
    size = raw.get("size") if raw.get("size") in SIZES else "s"
    if t == "look" and isinstance(raw.get("id"), str) and raw["id"]:
        return {"type": t, "id": raw["id"], "size": size}
    if t == "setup" and isinstance(raw.get("name"), str) and raw["name"].strip():
        return {"type": t, "name": raw["name"].strip(), "size": size}
    if t == "switch" and raw.get("what") in SWITCHES:
        return {"type": t, "what": raw["what"], "size": size}
    return None


def tile_id(tile: dict) -> str:
    """What a tile points at: a look, setup or switch is on the tab once; each card is its own."""
    return f"{tile['type']}:{tile.get('id') or tile.get('name') or tile.get('what')}"


def clean_favorites(raw) -> list[dict]:
    out, seen = [], set()
    for x in raw if isinstance(raw, list) else []:
        t = clean_tile(x)
        if t is None or tile_id(t) in seen or len(out) >= FAVORITES_MAX:
            continue
        seen.add(tile_id(t))
        out.append(t)
    return out


def find(looks: list[dict], what: str) -> dict | None:
    """A look by its id or its name (any case)."""
    w = str(what or "").strip().lower()
    return next((lk for lk in looks if lk["id"] == w or lk["name"].lower() == w), None)


def describe(look: dict) -> str:
    k = look["kind"]
    if k == "off":
        return "off"
    if k == "dim":
        return f"dim to {look['bright']}%"
    if k == "color":
        return f"#{look['hex']} at {look['bright']}%"
    return f"{look['effect']} at {look['bright']}%"
