"""Scenes: a different look for the lights while something is fullscreen, or while a chosen app is in
front (a game, a film). Nothing in the settings changes: the look sits on top of its strips the way a
keybind does, and goes away again when the app does.

You make as many scenes as you like, each "when this happens, these strips look like this":

Settings (config "scenes"):
  enabled       on or off, for all of them
  scenes        [{"id": "a1b2", "name": "Games", "on": true, "when": "fullscreen" | "apps",
                  "apps": ["steam_app_1091500", ...], "targets": ["*"] or ["Device|Zone", ...],
                  "look": {...}}], in order: where two want the same strip, the one higher up wins
  ignore        apps that never count as fullscreen (a browser playing a video, say)
  on_delay      seconds something has to stay before the look comes on
  off_delay     and after it's gone, before the lights go back
  interval      seconds between checks, where the desktop can't say what's in front by itself

Older settings ("look" for anything fullscreen and "apps": [{"app", "look"}]) become scenes.

A look: {"kind": "off" | "dim" | "color" | "effect", "bright": 0-100, "hex": "rrggbb", "effect": name}.
"""
import hashlib
import re
import secrets
from typing import List, Optional

from iridia import animations

KINDS = ("off", "dim", "color", "effect")
SEEN_MAX = 40
APPS_MAX = 40
SCENES_MAX = 40
WHEN = ("fullscreen", "apps")

DEFAULTS = {
    "enabled": False,
    "scenes": None,             # None: one to start with (see default_scenes)
    "ignore": [],
    "on_delay": 1.0,
    "off_delay": 2.0,
    "interval": 3,
    "seen": [],
}


def _num(v, default, lo, hi, kind=float):
    try:
        x = kind(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, x))


def _hex(v, default="ff0000") -> str:
    s = str(v or "").strip().lstrip("#").lower()
    return s if re.fullmatch(r"[0-9a-f]{6}", s) else default


def app_key(app) -> str:
    """Apps are matched by name without case: "Steam_App_1091500" and "steam_app_1091500" are one."""
    return str(app or "").strip().lower()


def clean_look(raw) -> Optional[dict]:
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    kind = raw["kind"]
    out = {"kind": kind}
    if kind != "off":
        out["bright"] = _num(raw.get("bright"), 20 if kind == "dim" else 100, 0, 100, int)
    if kind == "color":
        out["hex"] = _hex(raw.get("hex"))
    if kind == "effect":
        out["effect"] = raw.get("effect") if raw.get("effect") in animations.EFFECTS else "breathing"
    return out


def default_scenes() -> List[dict]:
    """What there is before you make any: anything fullscreen dims everything to 20%."""
    return [{"id": "f5f5f5", "name": "Anything fullscreen", "on": True, "when": "fullscreen", "apps": [],
             "targets": ["*"], "look": {"kind": "dim", "bright": 20}}]


def _apps(raw) -> List[str]:
    out, keys = [], set()
    for a in raw if isinstance(raw, list) else []:
        a = str(a or "").strip()[:80]
        if a and app_key(a) not in keys and len(out) < APPS_MAX:
            keys.add(app_key(a))
            out.append(a)
    return out


def clean_scene(raw) -> Optional[dict]:
    """A scene: a name, when (anything fullscreen, or one of its apps in front), its strips and its
    look; None if it can't be one."""
    if not isinstance(raw, dict):
        return None
    look = clean_look(raw.get("look"))
    if look is None:
        return None
    when = raw.get("when") if raw.get("when") in WHEN else "fullscreen"
    apps = _apps(raw.get("apps"))
    t = raw.get("targets")
    targets = ["*"] if t in (None, "*", "all") or t == ["*"] else \
        list(dict.fromkeys(k for k in t if isinstance(k, str) and "|" in k)) if isinstance(t, list) else []
    if not targets:
        return None
    name = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()[:40] or \
        (", ".join(apps)[:40] if when == "apps" and apps else "Anything fullscreen")
    sid = str(raw.get("id") or "")
    return {"id": sid if re.fullmatch(r"[0-9a-f]{4,12}", sid) else secrets.token_hex(3), "name": name,
            "on": bool(raw.get("on", True)), "when": when, "apps": apps if when == "apps" else [],
            "targets": targets, "look": look}


def _migrate(raw: dict) -> List[dict]:
    """Settings from before scenes were a list: each app's own look, then anything fullscreen."""
    out, keys = [], set()
    for r in raw.get("apps") or []:
        if isinstance(r, dict) and str(r.get("app") or "").strip() and app_key(r["app"]) not in keys:
            keys.add(app_key(r["app"]))
            sid = hashlib.sha1(app_key(r["app"]).encode()).hexdigest()[:6]      # the same every time
            out.append({"id": sid, "name": str(r["app"]).strip(), "when": "apps", "apps": [r["app"]],
                        "look": r.get("look")})
    look = raw["look"] if "look" in raw else {"kind": "dim", "bright": 20}
    if look:
        out.append({"id": "f5f5f5", "name": "Anything fullscreen", "when": "fullscreen", "look": look})
    return out


def clean(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    out["enabled"] = bool(raw.get("enabled", False))
    if isinstance(raw.get("scenes"), list):
        src = raw["scenes"]
    elif "look" in raw or "apps" in raw:
        src = _migrate(raw)
    else:
        src = default_scenes()
    lst, ids = [], set()
    for x in src:
        sc = clean_scene(x)
        if sc is None or len(lst) >= SCENES_MAX:
            continue
        while sc["id"] in ids:
            sc["id"] = secrets.token_hex(3)
        ids.add(sc["id"])
        lst.append(sc)
    out["scenes"] = lst
    out["ignore"] = _apps(raw.get("ignore"))
    out["on_delay"] = round(_num(raw.get("on_delay"), DEFAULTS["on_delay"], 0.0, 10.0), 1)
    out["off_delay"] = round(_num(raw.get("off_delay"), DEFAULTS["off_delay"], 0.0, 10.0), 1)
    out["interval"] = _num(raw.get("interval"), DEFAULTS["interval"], 1, 30, int)
    out["seen"] = [str(a) for a in raw.get("seen") or [] if isinstance(a, str) and a][:SEEN_MAX]
    return out


def watched_apps(st: dict) -> List[str]:
    return [a for sc in st.get("scenes") or [] if sc["on"] and sc["when"] == "apps" for a in sc["apps"]]


def needs_watching(st: dict) -> bool:
    return bool(st.get("enabled")) and any(sc["on"] for sc in st.get("scenes") or [])


def pick(st: dict, front: str, fullscreen: bool, running=()) -> tuple:
    """The scenes that should show, in order (higher up wins on a strip they share): those with an
    app in front, and those for anything fullscreen (unless the app in front is ignored). running:
    apps known to be running, where the desktop can't say which one is in front (they count as in
    front). Ids, so a scene changed while it shows stays on."""
    if not st.get("enabled"):
        return ()
    here = {app_key(front)} | {app_key(a) for a in running}
    here.discard("")
    fs = fullscreen and app_key(front) not in {app_key(a) for a in st.get("ignore") or []}
    out = []
    for sc in st.get("scenes") or []:
        if not sc["on"]:
            continue
        if sc["when"] == "apps" and here & {app_key(a) for a in sc["apps"]}:
            out.append(sc["id"])
        elif sc["when"] == "fullscreen" and fs:
            out.append(sc["id"])
    return tuple(out)


def overlay(look: Optional[dict]) -> Optional[dict]:
    """A look as the overlay every strip gets (the same kind a keybind sets)."""
    if not look:
        return None
    kind = look["kind"]
    if kind == "off":
        return {"power": "off"}
    if kind == "dim":
        return {"bright": look["bright"]}
    if kind == "color":
        return {"hex": look["hex"], "bright": look["bright"]}
    return {"effect": animations.clean({"effect": look["effect"]}), "bright": look["bright"]}


class Delay:
    """What shows now, given what's wanted: a new look comes on once it's been wanted for on_delay
    seconds, and goes once it's been gone for off_delay (switching between two looks waits
    on_delay). Alt-tabbing out of a game for a moment doesn't make the room flicker."""

    def __init__(self):
        self.shown = ()
        self._want = ()
        self._since = 0.0

    def update(self, want, now: float, on_delay: float, off_delay: float):
        if want != self._want:
            self._want, self._since = want, now
        if want != self.shown:
            wait = off_delay if not want else on_delay
            if now - self._since >= wait:
                self.shown = want
        return self.shown

    def force(self, want=()):
        self.shown = self._want = want
