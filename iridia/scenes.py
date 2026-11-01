"""Scenes: a different look for the lights while something is fullscreen, or while a chosen app is in
front (a game, a film). Nothing in the settings changes: the look sits on top of every strip the way
a keybind does, and goes away again when the app does.

Settings (config "scenes"):
  enabled       on or off
  look          what any fullscreen app gets (None: nothing, only the apps below)
  apps          [{"app": "mpv", "look": {...}}]: an app's own look, while it's in front
  ignore        apps that never get the fullscreen look (a browser playing a video, say)
  on_delay      seconds something has to stay before the look comes on
  off_delay     and after it's gone, before the lights go back
  interval      seconds between checks, where the desktop can't say what's in front by itself

A look: {"kind": "off" | "dim" | "color" | "effect", "bright": 0-100, "hex": "rrggbb", "effect": name}.
"""
import re
from typing import Optional

from iridia import animations

KINDS = ("off", "dim", "color", "effect")
SEEN_MAX = 40
APPS_MAX = 40

DEFAULTS = {
    "enabled": False,
    "look": {"kind": "dim", "bright": 20},
    "apps": [],
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


def clean(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    out["enabled"] = bool(raw.get("enabled", False))
    out["look"] = clean_look(raw["look"]) if "look" in raw else dict(DEFAULTS["look"])
    apps, seen_keys = [], set()
    for r in raw.get("apps") or []:
        if not isinstance(r, dict):
            continue
        name, look = str(r.get("app") or "").strip(), clean_look(r.get("look"))
        if name and look and app_key(name) not in seen_keys and len(apps) < APPS_MAX:
            seen_keys.add(app_key(name))
            apps.append({"app": name, "look": look})
    out["apps"] = apps
    ign = []
    for a in raw.get("ignore") or []:
        a = str(a or "").strip()
        if a and app_key(a) not in {app_key(x) for x in ign} and len(ign) < APPS_MAX:
            ign.append(a)
    out["ignore"] = ign
    out["on_delay"] = round(_num(raw.get("on_delay"), DEFAULTS["on_delay"], 0.0, 10.0), 1)
    out["off_delay"] = round(_num(raw.get("off_delay"), DEFAULTS["off_delay"], 0.0, 10.0), 1)
    out["interval"] = _num(raw.get("interval"), DEFAULTS["interval"], 1, 30, int)
    out["seen"] = [str(a) for a in raw.get("seen") or [] if isinstance(a, str) and a][:SEEN_MAX]
    return out


def pick(st: dict, front: str, fullscreen: bool, running=()) -> Optional[dict]:
    """The look that should show: the app in front's own look, else the fullscreen look (unless the
    app is ignored), else None. running: apps known to be running, where the desktop can't say
    which one is in front (they count as in front)."""
    if not st.get("enabled"):
        return None
    here = {app_key(front)} | {app_key(a) for a in running}
    here.discard("")
    for r in st.get("apps") or []:
        if app_key(r["app"]) in here:
            return r["look"]
    if fullscreen and st.get("look") and app_key(front) not in {app_key(a) for a in st.get("ignore") or []}:
        return st["look"]
    return None


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
        self.shown = None
        self._want = None
        self._since = 0.0

    def update(self, want, now: float, on_delay: float, off_delay: float):
        if want != self._want:
            self._want, self._since = want, now
        if want != self.shown:
            wait = off_delay if want is None else on_delay
            if now - self._since >= wait:
                self.shown = want
        return self.shown

    def force(self, look):
        self.shown = self._want = look
