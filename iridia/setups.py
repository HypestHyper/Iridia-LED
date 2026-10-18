"""Setups: named snapshots of everything Iridia knows, which double as backups.

A setup is one JSON file in ~/.config/iridia/setups/ holding copies of:
config.json (devices, zones, patterns, brightness, night mode, sleep, ...),
layout.json, wallpaper_colors.json (your picks per wallpaper), custom_colors.json,
palette.json, gui.json (window font and motion) and every calibration profile.

Loading a setup first saves the current state as an automatic backup
(setups/.backups/, the newest few are kept), so a wrong load can be undone.

A setup saved by this version is marked "complete": loading it puts the folder back exactly as it
was, so files and calibration profiles that didn't exist then are removed. Older setup files only
write what they hold.
"""

import json
import os
import tempfile
import time
from typing import List, Optional, Tuple

from iridia.calibration import valid_name

CONFIG_DIR = os.path.expanduser("~/.config/iridia")
FILES = ("config.json", "layout.json", "wallpaper_colors.json", "custom_colors.json", "palette.json", "gui.json")
KEEP_BACKUPS = 5


def _atomic_write(path: str, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _remove(path: str):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Setups:
    def __init__(self, config_dir: str = CONFIG_DIR, version: str = ""):
        self.config_dir = config_dir
        self.folder = os.path.join(config_dir, "setups")
        self.backups = os.path.join(self.folder, ".backups")
        self.version = version

    # ------------------------------------------------------------ capture
    def capture(self, name: str) -> dict:
        files = {}
        for fn in FILES:
            data = _read_json(os.path.join(self.config_dir, fn))
            if data is not None:
                files[fn] = data
        cal = {}
        cal_dir = os.path.join(self.config_dir, "calibration")
        try:
            for fn in sorted(os.listdir(cal_dir)):
                if fn.endswith(".json"):
                    data = _read_json(os.path.join(cal_dir, fn))
                    if data is not None:
                        cal[fn[:-5]] = data
        except OSError:
            pass
        return {"iridia_setup": 1, "name": name, "saved": time.strftime("%Y-%m-%d %H:%M"),
                "app_version": self.version, "complete": True, "files": files, "calibration": cal}

    def restore(self, data: dict) -> Optional[str]:
        """Write a captured setup back to the config folder."""
        if not isinstance(data, dict) or data.get("iridia_setup") != 1 or not isinstance(data.get("files"), dict):
            return "That isn't an Iridia setup file."
        files = data["files"]
        if "config.json" in files and not isinstance(files["config.json"], dict):
            return "The setup's config is damaged."
        exact = data.get("complete") is True and "config.json" in files
        for fn in FILES:
            path = os.path.join(self.config_dir, fn)
            if fn in files:
                _atomic_write(path, files[fn])
            elif exact:
                _remove(path)               # didn't exist when the setup was saved
        cal = {n: p for n, p in (data.get("calibration") or {}).items() if valid_name(n) and isinstance(p, dict)}
        cal_dir = os.path.join(self.config_dir, "calibration")
        for name, prof in cal.items():
            _atomic_write(os.path.join(cal_dir, f"{name}.json"), prof)
        if exact:
            try:
                extra = [f for f in os.listdir(cal_dir) if f.endswith(".json") and f[:-5] not in cal
                         and valid_name(f[:-5])]
            except OSError:
                extra = []
            for f in extra:
                _remove(os.path.join(cal_dir, f))
        return None

    # ------------------------------------------------------------ named setups
    def path(self, name: str) -> str:
        return os.path.join(self.folder, f"{name}.json")

    def list(self) -> List[dict]:
        out = []
        try:
            names = sorted(f[:-5] for f in os.listdir(self.folder) if f.endswith(".json"))
        except OSError:
            names = []
        for n in names:
            if not valid_name(n):
                continue
            d = _read_json(self.path(n)) or {}
            out.append({"name": n, "saved": d.get("saved", "")})
        return out

    def list_backups(self) -> List[dict]:
        try:
            names = sorted((f[:-5] for f in os.listdir(self.backups) if f.endswith(".json")), reverse=True)
        except OSError:
            names = []
        out = []
        for n in names:
            d = _read_json(os.path.join(self.backups, f"{n}.json")) or {}
            out.append({"id": n, "saved": d.get("saved", ""), "reason": d.get("reason", "")})
        return out

    def save(self, name: str, overwrite: bool = True) -> Optional[str]:
        if not valid_name(name):
            return "Use letters, numbers, spaces, dashes, underscores and brackets (up to 40 characters)."
        if not overwrite and os.path.exists(self.path(name)):
            return f"A setup called '{name}' already exists."
        _atomic_write(self.path(name), self.capture(name))
        return None

    def backup(self, reason: str) -> str:
        bid = base = time.strftime("auto-%Y%m%d-%H%M%S")
        n = 2
        while os.path.exists(os.path.join(self.backups, f"{bid}.json")):
            bid = f"{base}-{n}"             # two in the same second must not overwrite each other
            n += 1
        data = self.capture(bid)
        data["reason"] = reason
        _atomic_write(os.path.join(self.backups, f"{bid}.json"), data)
        for old in self.list_backups()[KEEP_BACKUPS:]:
            try:
                os.remove(os.path.join(self.backups, f"{old['id']}.json"))
            except OSError:
                pass
        return bid

    def load(self, name: str) -> Optional[str]:
        data = _read_json(self.path(name))
        if data is None:
            return f"Setup '{name}' couldn't be read."
        self.backup(f"before loading '{name}'")
        return self.restore(data)

    def load_backup(self, bid: str) -> Optional[str]:
        if not bid.startswith("auto-") or "/" in bid:
            return "Unknown backup."
        data = _read_json(os.path.join(self.backups, f"{bid}.json"))
        if data is None:
            return "That backup couldn't be read."
        self.backup(f"before restoring {bid}")
        return self.restore(data)

    def delete(self, name: str) -> Optional[str]:
        try:
            os.remove(self.path(name))
        except FileNotFoundError:
            return None
        except OSError as e:
            return str(e)
        return None

    def rename(self, old: str, new: str) -> Optional[str]:
        if not valid_name(new):
            return "Use letters, numbers, spaces, dashes, underscores and brackets (up to 40 characters)."
        if os.path.exists(self.path(new)):
            return f"A setup called '{new}' already exists."
        data = _read_json(self.path(old))
        if data is None:
            return f"Setup '{old}' couldn't be read."
        data["name"] = new
        _atomic_write(self.path(new), data)
        os.remove(self.path(old))
        return None

    def export_to(self, name: str, dest: str) -> Optional[str]:
        data = self.capture(name) if name == "" else _read_json(self.path(name))
        if data is None:
            return f"Setup '{name}' couldn't be read."
        try:
            _atomic_write(os.path.abspath(os.path.expanduser(dest)), data)
        except OSError as e:
            return str(e)
        return None

    def import_from(self, src: str) -> Tuple[Optional[str], Optional[str]]:
        data = _read_json(os.path.expanduser(src))
        if not isinstance(data, dict) or data.get("iridia_setup") != 1:
            return None, "That isn't an Iridia setup file."
        base = data.get("name") if valid_name(str(data.get("name", ""))) else "Imported"
        if str(base).startswith("auto-"):
            base = "Imported"
        name, n = base, 2
        existing = {s["name"] for s in self.list()}
        while name in existing:
            name = f"{base} ({n})"
            n += 1
        data["name"] = name
        _atomic_write(self.path(name), data)
        return name, None
