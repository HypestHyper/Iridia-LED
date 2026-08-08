"""Universal wallpaper detection for Linux DEs/WMs."""

import glob
import os
import re
import subprocess


class WallpaperDetector:
    """Detect the current wallpaper path across different Linux environments."""

    def __init__(self, manual_path: str = None, watch_folder: str = None):
        self.manual_path = os.path.expanduser(manual_path) if manual_path else None
        self.watch_folder = os.path.expanduser(watch_folder) if watch_folder else None
        self._last_path = None
        self._de = self._detect_de()

    def _detect_de(self) -> str:
        """Detect desktop environment or compositor."""
        env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if env:
            return env
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return "hyprland"
        if os.environ.get("SWAYSOCK"):
            return "sway"
        if os.environ.get("I3SOCK"):
            return "i3"
        return "unknown"

    def detect(self) -> str:
        """Return the absolute path to the current wallpaper, or None."""
        # 1. Manual override
        if self.manual_path and os.path.exists(self.manual_path):
            return os.path.abspath(self.manual_path)

        # 2. Try DE-specific methods
        methods = [
            self._caelestia,
            self._hyprland,
            self._sway,
            self._gnome,
            self._kde,
            self._xfce,
            self._cinnamon,
            self._mate,
            self._feh,
            self._nitrogen,
            self._xwallpaper,
        ]

        for method in methods:
            path = method()
            if path and os.path.exists(path):
                resolved = os.path.abspath(os.path.realpath(path))
                self._last_path = resolved
                return resolved

        # 3. Watch folder fallback — most recently modified image
        if self.watch_folder and os.path.isdir(self.watch_folder):
            images = []
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp"):
                images.extend(glob.glob(os.path.join(self.watch_folder, ext)))
                images.extend(glob.glob(os.path.join(self.watch_folder, "**", ext), recursive=True))
            if images:
                latest = max(images, key=os.path.getmtime)
                return os.path.abspath(latest)

        # 4. Return last known
        return self._last_path

    def _run(self, cmd: list, timeout: int = 3) -> str:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return ""

    def _caelestia(self) -> str:
        """Caelestia shell stores wallpaper at ~/.local/state/caelestia/wallpaper/path.txt"""
        path_file = os.path.expanduser("~/.local/state/caelestia/wallpaper/path.txt")
        if os.path.exists(path_file):
            try:
                with open(path_file, "r") as f:
                    path = f.read().strip()
                if path and os.path.exists(path):
                    return path
            except OSError:
                pass
        return None

    def _hyprland(self) -> str:
        # Try swww first
        out = self._run(["swww", "query"])
        if out:
            m = re.search(r"currently displaying:\s*(.+)", out)
            if m:
                return m.group(1).strip()
        # Try hyprpaper config
        hypaper_conf = os.path.expanduser("~/.config/hypr/hyprpaper.conf")
        if os.path.exists(hypaper_conf):
            try:
                with open(hypaper_conf) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("wallpaper"):
                            parts = line.split("=")
                            if len(parts) == 2:
                                return parts[1].strip().split(",")[-1].strip()
                        elif line.startswith("preload"):
                            parts = line.split("=")
                            if len(parts) == 2:
                                return parts[1].strip()
            except OSError:
                pass
        # Try swaybg process
        out = self._run(["ps", "aux"])
        m = re.search(r"swaybg.*-i\s+(\S+)", out)
        if m:
            return m.group(1)
        return None

    def _sway(self) -> str:
        out = self._run(["swww", "query"])
        if out:
            m = re.search(r"currently displaying:\s*(.+)", out)
            if m:
                return m.group(1).strip()
        out = self._run(["ps", "aux"])
        m = re.search(r"swaybg.*-i\s+(\S+)", out)
        if m:
            return m.group(1)
        return None

    def _gnome(self) -> str:
        out = self._run(["gsettings", "get", "org.gnome.desktop.background", "picture-uri"])
        if out:
            path = out.strip().strip("'")
            if path.startswith("file://"):
                return path[7:]
        return None

    def _kde(self) -> str:
        kfile = os.path.expanduser("~/.config/plasma-org.kde.desktop.appletsrc")
        if not os.path.exists(kfile):
            return None
        try:
            with open(kfile) as f:
                content = f.read()
            m = re.search(r"Image=(.+)", content)
            if m:
                path = m.group(1).strip()
                if path.startswith("file://"):
                    path = path[7:]
                return path
        except OSError:
            pass
        return None

    def _xfce(self) -> str:
        out = self._run([
            "xfconf-query", "-c", "xfce4-desktop",
            "-p", "/backdrop/screen0/monitor0/workspace0/last-image"
        ])
        if out and not out.startswith("/"):
            # Sometimes returns a property value, not a path
            pass
        if out and os.path.exists(out):
            return out
        return None

    def _cinnamon(self) -> str:
        out = self._run(["gsettings", "get", "org.cinnamon.desktop.background", "picture-uri"])
        if out:
            path = out.strip().strip("'")
            if path.startswith("file://"):
                return path[7:]
        return None

    def _mate(self) -> str:
        out = self._run(["gsettings", "get", "org.mate.desktop.background", "picture-filename"])
        if out:
            return out.strip().strip("'")
        return None

    def _feh(self) -> str:
        fehbg = os.path.expanduser("~/.fehbg")
        if os.path.exists(fehbg):
            try:
                with open(fehbg) as f:
                    content = f.read()
                m = re.search(r"'(.+?)'", content)
                if m:
                    return m.group(1)
            except OSError:
                pass
        out = self._run(["ps", "aux"])
        m = re.search(r"feh.*--bg-(?:scale|fill|center|max|tile).*\s(\S+\.(?:jpg|jpeg|png|webp))", out)
        if m:
            return m.group(1)
        return None

    def _nitrogen(self) -> str:
        cfg = os.path.expanduser("~/.config/nitrogen/bg-saved.cfg")
        if not os.path.exists(cfg):
            return None
        try:
            with open(cfg) as f:
                for line in f:
                    if line.startswith("file="):
                        return line[5:].strip()
        except OSError:
            pass
        return None

    def _xwallpaper(self) -> str:
        out = self._run(["ps", "aux"])
        m = re.search(r"xwallpaper.*--(zoom|maximize|center|tile|stretch)\s+(\S+)", out)
        if m:
            return m.group(2)
        return None
