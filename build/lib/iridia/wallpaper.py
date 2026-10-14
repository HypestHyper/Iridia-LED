"""Universal wallpaper detection for Linux DEs/WMs."""
import json, logging, os, re, subprocess, time
from urllib.parse import unquote

logger = logging.getLogger("iridia")


def fill_session_env():
    """Find the desktop session when we weren't started from inside it.

    A systemd user service doesn't always get WAYLAND_DISPLAY or
    HYPRLAND_INSTANCE_SIGNATURE (only if the compositor exports them, as UWSM
    does), and without them `swww query` and `hyprctl` can't find the session.
    Their sockets are in XDG_RUNTIME_DIR, so look there. Values that point at a
    session that's gone (Hyprland restarted) are replaced."""
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not os.path.isdir(run):
        return
    os.environ.setdefault("XDG_RUNTIME_DIR", run)

    def newest(paths):
        best, bt = None, -1.0
        for p in paths:
            try:
                t = os.path.getmtime(p)
            except OSError:
                continue
            if t > bt:
                best, bt = p, t
        return best

    try:
        names = os.listdir(run)
    except OSError:
        return
    wl = os.environ.get("WAYLAND_DISPLAY")
    if not wl or not os.path.exists(os.path.join(run, wl)):
        cand = newest(os.path.join(run, n) for n in names if n.startswith("wayland-") and not n.endswith(".lock"))
        if cand:
            os.environ["WAYLAND_DISPLAY"] = os.path.basename(cand)
            logger.debug(f"Session: using WAYLAND_DISPLAY={os.environ['WAYLAND_DISPLAY']}")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    hypr = os.path.join(run, "hypr")
    if os.path.isdir(hypr) and (not sig or not os.path.isdir(os.path.join(hypr, sig))):
        try:
            cand = newest(os.path.join(hypr, d) for d in os.listdir(hypr)
                          if os.path.exists(os.path.join(hypr, d, ".socket.sock")))
        except OSError:
            cand = None
        if cand:
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = os.path.basename(cand)
            logger.debug(f"Session: using HYPRLAND_INSTANCE_SIGNATURE={os.path.basename(cand)}")
    sock = os.environ.get("SWAYSOCK")
    if not sock or not os.path.exists(sock):
        cand = newest(os.path.join(run, n) for n in names if n.startswith("sway-ipc.") and n.endswith(".sock"))
        if cand:
            os.environ["SWAYSOCK"] = cand


class WallpaperDetector:
    def __init__(self, manual_path=None, watch_folder=None, cache_path=None):
        self.manual_path = os.path.expanduser(manual_path) if manual_path else None
        self.watch_folder = os.path.expanduser(watch_folder) if watch_folder else None
        self._last_path = None
        fill_session_env()
        self._de = self._detect_de()
        self._last_successful_method = None
        self.last_error = None
        # Backends that spawn a process (swww, gsettings, ps, ...) are only
        # re-run every `slow_interval` seconds; state-file backends are read
        # on every call because that costs next to nothing.
        self.slow_interval = 3.0
        self._slow_ts = 0.0
        self._slow_hit = None      # (backend name, path) from the last slow cycle
        self.cache_path = os.path.expanduser(cache_path) if cache_path else None
        self._sticky = None        # remembered working backend
        self._misses = 0
        if self.cache_path:
            self._load_cache()

    def invalidate(self):
        """Force the next detect() to re-run the slow backends (called when
        a file watcher says something wallpaper-related changed)."""
        self._slow_ts = 0.0

    SLOW = {"hyprland", "sway", "gnome", "kde", "xfce", "cinnamon", "mate", "feh", "xwallpaper", "watch_folder"}

    def _detect_de(self):
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

    @property
    def last_backend(self):
        return self._last_successful_method

    # ------------------------------------------------------------- caching
    # The backend that identified the wallpaper is remembered (in memory and
    # in detection_cache.json) so later ticks - and the next daemon start -
    # ask only that one instead of probing every backend. If it stops
    # answering for several checks in a row, everything is probed again.
    MISS_LIMIT = 3

    def _load_cache(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                name = json.load(f).get("backend")
            if isinstance(name, str) and name in self._table():
                self._sticky = name
                logger.info(f"Using cached wallpaper backend '{name}' (Settings > reset to re-detect)")
        except (OSError, ValueError):
            pass

    def _save_cache(self):
        if not self.cache_path:
            return
        try:
            if self._sticky is None:
                if os.path.exists(self.cache_path):
                    os.remove(self.cache_path)
                return
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump({"backend": self._sticky}, f)
        except OSError as e:
            logger.debug(f"Couldn't update {self.cache_path}: {e}")

    def reset_cache(self):
        """Forget the remembered backend; the next detect() probes everything."""
        self._sticky = None
        self._misses = 0
        self._last_successful_method = None
        self._save_cache()
        self.invalidate()
        logger.info("Wallpaper detection cache cleared; scanning all backends")

    @property
    def cached_backend(self):
        return self._sticky

    def _table(self):
        # waypaper last: its config keeps the old choice after you stop using it.
        names = ["caelestia", "noctalia", "hyprland", "sway", "gnome", "kde", "xfce", "cinnamon",
                 "mate", "feh", "nitrogen", "xwallpaper", "waypaper"]
        t = {n: getattr(self, "_" + n) for n in names}
        t["watch_folder"] = self._watch_folder_latest
        return t

    def _watch_folder_latest(self):
        if not (self.watch_folder and os.path.isdir(self.watch_folder)):
            return None
        # Newest image in the folder and up to two levels of subfolders; capped so pointing
        # this at a huge folder (your whole home) can't make every check slow.
        exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
        best, best_t, seen = None, -1.0, 0
        root = self.watch_folder.rstrip(os.sep)
        for folder, dirs, files in os.walk(root):
            if folder[len(root):].count(os.sep) >= 2:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if not name.lower().endswith(exts):
                    continue
                seen += 1
                try:
                    t = os.path.getmtime(os.path.join(folder, name))
                except OSError:
                    continue                # removed while we looked, or a broken link
                if t > best_t:
                    best, best_t = os.path.join(folder, name), t
            if seen > 20000:
                break
        return best

    def _full_order(self):
        order = list(self._table())
        # A removed shell leaves its state file behind (stale path.txt etc.),
        # so between the two shells that keep state files, trust the one
        # that was updated most recently.
        def _mtime(f):
            try:
                return os.path.getmtime(f)
            except OSError:
                return 0
        state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        if _mtime(os.path.join(state, "noctalia", "settings.toml")) > \
                _mtime(os.path.join(state, "caelestia", "wallpaper", "path.txt")):
            order.remove("noctalia")
            order.insert(0, "noctalia")
        return order

    def _query(self, name, slow_due):
        """Ask one backend. Returns (path_or_None, actually_queried, note)."""
        if name in self.SLOW and not slow_due:
            # Between slow cycles only replay what the last cycle found.
            if self._slow_hit and self._slow_hit[0] == name:
                return self._slow_hit[1], False, name
            return None, False, name
        try:
            path = self._table()[name]()
        except Exception as e:
            logger.debug(f"Wallpaper backend '{name}' raised {type(e).__name__}: {e}")
            return None, True, f"{name} (error: {e})"
        found = bool(path) and os.path.exists(path)
        if found and name in self.SLOW:
            self._slow_hit = (name, path)
        if found:
            return path, True, name
        return None, True, f"{name} (found '{path}', but it doesn't exist)" if path else f"{name} (no match)"

    def _accept(self, name, path):
        resolved = os.path.abspath(os.path.realpath(path))
        self._last_path = resolved
        if self._last_successful_method != name:
            logger.info(f"Wallpaper detected via '{name}' backend")
            self._last_successful_method = name
        if self._sticky != name:
            self._sticky = name
            self._save_cache()
        self._misses = 0
        self.last_error = None
        return resolved

    def detect(self):
        if self.manual_path and os.path.exists(self.manual_path):
            return os.path.abspath(self.manual_path)
        now = time.monotonic()
        slow_due = now - self._slow_ts >= self.slow_interval
        if slow_due:
            self._slow_ts = now
            self._slow_hit = None

        if self._sticky:
            path, queried, _ = self._query(self._sticky, slow_due)
            if path:
                return self._accept(self._sticky, path)
            if not queried:
                return self._last_path          # nothing new to learn this tick
            self._misses += 1
            if self._misses == 1:
                fill_session_env()          # a restarted compositor has a new socket
            if self._misses < self.MISS_LIMIT:
                return self._last_path
            logger.info(f"Cached wallpaper backend '{self._sticky}' stopped answering; "
                        "scanning all backends again")
            self._sticky = None
            self._misses = 0
            self._save_cache()
            slow_due = True
            self._slow_ts = now
            self._slow_hit = None

        tried = []
        for name in self._full_order():
            path, queried, note = self._query(name, slow_due)
            if queried or path:
                tried.append(note)
            if path:
                return self._accept(name, path)

        if slow_due:
            fill_session_env()              # the compositor may have restarted since
            # Nothing answered: don't spawn every backend's tools every few seconds forever.
            # A watched file changing (invalidate()) still triggers a check right away.
            self._slow_ts = now + 27.0
        if self._last_path is None:
            # Never found anything at all - this is the case worth
            # explaining, since it means nothing will ever be extracted.
            msg = (f"No wallpaper backend matched (desktop='{self._de}'). Tried: {tried}. "
                   "Set wallpaper.watch_folder or wallpaper.manual_path in the config.")
            if self.last_error is None:   # warn once, not on every slow cycle
                logger.warning(msg)
            self.last_error = msg
        return self._last_path

    def _run(self, cmd, timeout=3):
        if cmd[:2] == ["ps", "-eo"]:
            # Several backends look for a wallpaper process: list processes once per check.
            hit = getattr(self, "_ps_cache", None)
            if hit and time.monotonic() - hit[0] < 1.0:
                return hit[1]
            out = self._run_now(cmd, timeout)
            self._ps_cache = (time.monotonic(), out)
            return out
        return self._run_now(cmd, timeout)

    def _run_now(self, cmd, timeout=3):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0 and result.stderr.strip():
                logger.debug(f"{cmd[0]} exited {result.returncode}: {result.stderr.strip()}")
            return result.stdout.strip()
        except FileNotFoundError:
            logger.debug(f"'{cmd[0]}' not found on PATH")
            return ""
        except subprocess.TimeoutExpired:
            logger.debug(f"'{cmd[0]}' timed out after {timeout}s")
            return ""
        except Exception as e:
            logger.debug(f"'{cmd[0]}' failed: {type(e).__name__}: {e}")
            return ""

    def _caelestia(self):
        path_file = os.path.expanduser("~/.local/state/caelestia/wallpaper/path.txt")
        if os.path.exists(path_file):
            try:
                with open(path_file, "r") as f:
                    path = f.read().strip()
                if path and os.path.exists(path):
                    return path
            except OSError as e:
                logger.debug(f"Couldn't read {path_file}: {e}")
        return None

    def _noctalia(self):
        """Noctalia keeps the current wallpaper in
        $XDG_STATE_HOME/noctalia/settings.toml under
        [wallpaper.monitors.<output>] / [wallpaper.last] / [wallpaper.default]
        (key: path). Parsed by hand so it works on Python < 3.11 too."""
        state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        f = os.path.join(state, "noctalia", "settings.toml")
        if not os.path.exists(f):
            return None
        found = {}
        section = ""
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("["):
                        section = line.strip("[] ").strip()
                        continue
                    m = re.match(r'path\s*=\s*"((?:[^"\\]|\\.)*)"', line)
                    if m and section.startswith("wallpaper."):
                        found[section] = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
        except OSError as e:
            logger.debug(f"Couldn't read {f}: {e}")
            return None
        order = [k for k in found if k.startswith("wallpaper.monitors.")]
        order += ["wallpaper.last", "wallpaper.default"]
        for key in order:
            path = os.path.expanduser(found.get(key, ""))
            if path and os.path.exists(path):
                return path
        return None

    def _swww(self):
        """swww (renamed awww in 2025): 'currently displaying: image: /path'."""
        for tool in ("swww", "awww"):
            out = self._run([tool, "query"])
            m = re.search(r"currently displaying:\s*(?:image:\s*)?(/.+)", out or "")
            if m:
                return m.group(1).strip()
        return None

    def _waypaper(self):
        """waypaper (a front end for swww, hyprpaper, swaybg, feh ...) saves its choice."""
        f = os.path.expanduser("~/.config/waypaper/config.ini")
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r"\s*wallpaper\s*=\s*(.+)", line)
                    if m:
                        first = m.group(1).strip().split(",")[0].strip()
                        return os.path.expanduser(first) if first else None
        except OSError:
            pass
        return None

    def _hyprland(self):
        found = self._swww()
        if found:
            return found
        out = self._run(["hyprctl", "hyprpaper", "listactive"])
        for line in out.splitlines():           # "DP-1 = /path/to/img.png"
            if "=" in line:
                cand = line.split("=", 1)[1].strip()
                if cand.startswith("/") and os.path.exists(cand):
                    return cand
        hypaper_conf = os.path.expanduser("~/.config/hypr/hyprpaper.conf")
        if os.path.exists(hypaper_conf):
            try:
                with open(hypaper_conf) as f:
                    for line in f:
                        line = line.strip()
                        if re.match(r"path\s*=", line):      # hyprpaper >= 0.8 block syntax
                            cand = os.path.expanduser(line.split("=", 1)[1].strip())
                            if os.path.exists(cand):
                                return cand
                        elif line.startswith("wallpaper"):
                            parts = line.split("=")
                            if len(parts) == 2:
                                return parts[1].strip().split(",")[-1].strip()
                        elif line.startswith("preload"):
                            parts = line.split("=")
                            if len(parts) == 2:
                                return parts[1].strip()
            except OSError as e:
                logger.debug(f"Couldn't read {hypaper_conf}: {e}")
        out = self._run(["ps", "-eo", "args"])
        m = re.search(r"swaybg.*-i\s+(\S+)", out)
        if m:
            return m.group(1)
        return None

    def _sway(self):
        found = self._swww()
        if found:
            return found
        out = self._run(["ps", "-eo", "args"])
        m = re.search(r"swaybg.*-i\s+(\S+)", out)
        if m:
            return m.group(1)
        return None

    def _gnome(self):
        key = "picture-uri"
        scheme = self._run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"])
        if "dark" in scheme:
            key = "picture-uri-dark"   # GNOME 42+ shows this one in dark mode
        out = self._run(["gsettings", "get", "org.gnome.desktop.background", key])
        if out:
            path = out.strip().strip("'")
            if path.startswith("file://"):
                return unquote(path[7:])
        return None

    def _kde(self):
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
                    path = unquote(path[7:])
                return path
        except OSError as e:
            logger.debug(f"Couldn't read {kfile}: {e}")
        return None

    def _xfce(self):
        out = self._run(["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop/screen0/monitor0/workspace0/last-image"])
        if out and os.path.exists(out):
            return out
        return None

    def _cinnamon(self):
        out = self._run(["gsettings", "get", "org.cinnamon.desktop.background", "picture-uri"])
        if out:
            path = out.strip().strip("'")
            if path.startswith("file://"):
                return unquote(path[7:])
        return None

    def _mate(self):
        out = self._run(["gsettings", "get", "org.mate.desktop.background", "picture-filename"])
        if out:
            return out.strip().strip("'")
        return None

    def _feh(self):
        fehbg = os.path.expanduser("~/.fehbg")
        if os.path.exists(fehbg):
            try:
                with open(fehbg) as f:
                    content = f.read()
                m = re.search(r"'(.*?)'", content)
                if m:
                    return m.group(1)
            except OSError as e:
                logger.debug(f"Couldn't read {fehbg}: {e}")
        out = self._run(["ps", "-eo", "args"])
        m = re.search(r"feh.*--bg-(?:scale|fill|center|max|tile).*\s(\S+\.(?:jpg|jpeg|png|webp))", out)
        if m:
            return m.group(1)
        return None

    def _nitrogen(self):
        cfg = os.path.expanduser("~/.config/nitrogen/bg-saved.cfg")
        if not os.path.exists(cfg):
            return None
        try:
            with open(cfg) as f:
                for line in f:
                    if line.startswith("file="):
                        return line[5:].strip()
        except OSError as e:
            logger.debug(f"Couldn't read {cfg}: {e}")
        return None

    def _xwallpaper(self):
        out = self._run(["ps", "-eo", "args"])
        m = re.search(r"xwallpaper.*--(zoom|maximize|center|tile|stretch)\s+(\S+)", out)
        if m:
            return m.group(2)
        return None
