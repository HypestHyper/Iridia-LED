"""Which app is in front, and whether it's fullscreen, for scenes.

Each desktop says so in its own way, and most of them say it as it happens (nothing is asked on a
timer):
  Hyprland   its event socket (.socket2.sock); the window is then asked on its request socket
  Sway       `swaymsg -t subscribe` window events
  KDE Plasma a small KWin script (loaded at runtime, nothing installed) that calls Iridia on the
             session bus when the active window or its fullscreen state changes; KWin 6.8 no longer
             passes the second to scripts, so KWin is also asked about the window in front once a
             second (getWindowInfo, one call on the bus)
  X11        `xprop -spy` on the active window, and its state asked every few seconds
Anywhere else (GNOME on Wayland, other compositors) no app may see other apps' windows, so the
running programs are listed every few seconds instead: an app's own look then shows while it runs,
and the "anything fullscreen" look can't be told.
"""
import json
import logging
import os
import re
import select
import shutil
import socket
import subprocess
import threading
import time
from typing import Callable, Optional, Set, Tuple

logger = logging.getLogger("iridia")

BUS_NAME = "io.github.HypestHyper.Iridia.Focus"
BUS_PATH = "/io/github/HypestHyper/Iridia/Focus"
KWIN_PLUGIN = "iridia-focus"
KWIN_ASK_MS = 1000              # KDE: how often KWin is asked whether the window in front is fullscreen

KWIN_SCRIPT = """// Iridia: tells Iridia which window is in front and whether it's fullscreen (for scenes).
var N = "%s", P = "%s", DEBUG = %s;
function log(t) { if (DEBUG) callDBus(N, P, N, "Log", String(t)); }
function active() { return workspace.activeWindow !== undefined ? workspace.activeWindow : workspace.activeClient; }
var last = null;
function send(w) {
    var fs = !!(w && w.fullScreen), app = w ? String(w.resourceClass || "") : "", id = w ? key(w) : "";
    if (last !== null && last[0] === fs && last[1] === app && last[2] === id) return;   // only changes
    last = [fs, app, id];
    log("send " + app + " fullscreen=" + fs);
    callDBus(N, P, N, "Window", fs, app, id);
}
// Windows are told apart by their id: KWin may hand out a new JavaScript object for the same window
// (6.8 does). Each one watched is kept here too, so its signal connections live as long as it does.
var hooked = {};
function key(w) { return String(w.internalId); }
function changed() { send(active()); }      // whichever window changed, what counts is the one in front
function hook(w) {
    if (!w || hooked[key(w)]) return;
    hooked[key(w)] = w;
    w.fullScreenChanged.connect(function () { log("fullScreenChanged"); changed(); });
    // going fullscreen always changes the size too: a second way to hear it
    if (w.frameGeometryChanged) w.frameGeometryChanged.connect(changed);
}
function onActive(w) { log("activated " + (w ? w.resourceClass : "none")); hook(w); send(w); }
function onRemoved(w) { if (w) delete hooked[key(w)]; changed(); }
if (workspace.windowActivated) workspace.windowActivated.connect(onActive);
else workspace.clientActivated.connect(onActive);
if (workspace.windowRemoved) workspace.windowRemoved.connect(onRemoved);
else if (workspace.clientRemoved) workspace.clientRemoved.connect(onRemoved);
onActive(active());
"""


def kwin_script(debug: bool = False) -> str:
    """The KWin script; debug: it also tells Iridia what it sees (FocusWatch.script_log)."""
    return KWIN_SCRIPT % (BUS_NAME, BUS_PATH, "true" if debug else "false")

BUS_XML = f"""<node><interface name="{BUS_NAME}">
<method name="Window"><arg type="b" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
<method name="Log"><arg type="s" direction="in"/></method>
</interface></node>"""


# ----------------------------------------------------------------- parsing (pure)
def hypr_state(data) -> Tuple[str, bool]:
    """`j/activewindow`: (class, fullscreen). Hyprland 0.42+ gives fullscreen as a number (2 and 3 are
    fullscreen, 1 is maximised); older versions a bool with fullscreenMode 0 for real fullscreen."""
    if not isinstance(data, dict) or not data:
        return "", False
    v = data.get("fullscreen")
    if isinstance(v, bool):
        fs = v and data.get("fullscreenMode", 0) == 0
    else:
        try:
            fs = bool(int(v or 0) & 2)
        except (TypeError, ValueError):
            fs = False
    return str(data.get("class") or data.get("initialClass") or ""), fs


def sway_app(con: dict) -> str:
    props = con.get("window_properties") or {}
    return str(con.get("app_id") or props.get("class") or props.get("instance") or "")


def sway_event(ev, cur: Tuple[str, bool, int]) -> Optional[Tuple[str, bool, int]]:
    """A `swaymsg -t subscribe '["window"]'` event -> the new (app, fullscreen, window id), or None
    when what's in front didn't change."""
    if not isinstance(ev, dict):
        return None
    con = ev.get("container") or {}
    change, cid = ev.get("change"), con.get("id", -1)
    if change == "focus" or (change in ("fullscreen_mode", "title") and (con.get("focused") or cid == cur[2])):
        return sway_app(con), bool(con.get("fullscreen_mode")), cid
    if change == "close" and cid == cur[2]:
        return "", False, -1
    return None


def xprop_active(line: str) -> Optional[str]:
    """`_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a00007` -> "0x3a00007" (None for no window)."""
    m = re.search(r"#\s*(0x[0-9a-fA-F]+)", line or "")
    return m.group(1) if m and int(m.group(1), 16) else None


def xprop_window(out: str) -> Tuple[str, bool]:
    """`xprop -id W _NET_WM_STATE WM_CLASS` -> (class, fullscreen)."""
    m = re.search(r'WM_CLASS\(\w+\) = "([^"]*)"(?:, "([^"]*)")?', out or "")
    app = (m.group(2) or m.group(1)) if m else ""
    return app, "_NET_WM_STATE_FULLSCREEN" in (out or "")


def running_apps(proc: str = "/proc") -> Set[str]:
    """Names of this user's running programs: each one's file name (a Windows game's too, without
    .exe), and steam_app_N for a running Steam game (Steam starts each through `reaper ... AppId=N`)."""
    out: Set[str] = set()
    uid = os.getuid()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        d = os.path.join(proc, pid)
        try:
            if os.stat(d).st_uid != uid:
                continue
            with open(os.path.join(d, "cmdline"), "rb") as f:
                args = f.read(4096).split(b"\0")
        except OSError:
            continue
        if not args or not args[0]:
            continue
        exe = args[0].decode("utf-8", "replace").replace("\\", "/").rsplit("/", 1)[-1]
        if exe.lower().endswith(".exe"):
            exe = exe[:-4]
        if exe:
            out.add(exe)
        if exe == "reaper":
            for a in args[1:8]:
                m = re.match(rb"AppId=(\d+)$", a)
                if m:
                    out.add("steam_app_" + m.group(1).decode())
    return out


def _proc_running(name: str) -> bool:
    return name in running_apps()


# ----------------------------------------------------------------- the watcher
class FocusWatch:
    """Keeps front (the app in front), fullscreen and running (fallback only) up to date while
    needed; on_change() is called from the watcher thread when they change."""

    def __init__(self, on_change: Callable[[], None]):
        self._on_change = on_change
        self._lock = threading.Lock()
        self._gen = 0
        self._proc: Optional[subprocess.Popen] = None
        self._stop_hooks = []
        self.running_flag = False
        self.method: Optional[str] = None       # hyprland | sway | kde | x11 | processes
        self.front = ""
        self.fullscreen = False
        self.running: Set[str] = set()
        self.interval = 3.0
        self.wanted: Set[str] = set()           # apps worth looking for in the fallback
        self.script_log = []                    # what the KWin script says it saw (IRIDIA_KWIN_DEBUG)
        self._kde_window = ""                   # KDE: the id of the window in front

    # -- state
    def _set(self, front: str, fullscreen: bool, running: Optional[Set[str]] = None):
        changed = (front, fullscreen) != (self.front, self.fullscreen)
        self.front, self.fullscreen = front, fullscreen
        if running is not None and running != self.running:
            self.running = running
            changed = True
        if changed:
            try:
                self._on_change()
            except Exception as e:              # noqa: BLE001
                logger.debug(f"Focus handler failed: {e}")

    def state(self):
        return self.front, self.fullscreen, set(self.running)

    # -- start / stop
    def set_needed(self, on: bool, interval: float = 3.0, wanted=()):
        self.interval = float(interval)
        self.wanted = {str(a).lower() for a in wanted}
        with self._lock:
            if on and not self.running_flag:
                self.running_flag = True
                self._gen += 1
                self.method = self.pick_method()
                threading.Thread(target=self._run, args=(self.method, self._gen), daemon=True,
                                 name="focuswatch").start()
                logger.info(f"Watching for fullscreen apps ({self.method})")
            elif not on and self.running_flag:
                self.running_flag = False
                self._gen += 1
                self._teardown()
                self.front, self.fullscreen, self.running = "", False, set()

    def stop(self):
        self.set_needed(False)

    def _teardown(self):
        p, self._proc = self._proc, None
        if p is not None and p.poll() is None:
            p.terminate()
        hooks, self._stop_hooks = self._stop_hooks, []
        for h in hooks:
            try:
                h()
            except Exception:                   # noqa: BLE001
                pass

    @staticmethod
    def pick_method() -> str:
        from iridia.wallpaper import fill_session_env
        fill_session_env()
        if hypr_sockets():
            return "hyprland"
        sock = os.environ.get("SWAYSOCK")
        if sock and os.path.exists(sock) and shutil.which("swaymsg"):
            return "sway"
        desk = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if ("kde" in desk or _proc_running("plasmashell")) and _gio() is not None and shutil.which("gdbus"):
            return "kde"
        if os.environ.get("XDG_SESSION_TYPE") == "x11" or (os.environ.get("DISPLAY") and
                                                          not os.environ.get("WAYLAND_DISPLAY")):
            if shutil.which("xprop"):
                return "x11"
        return "processes"

    def _run(self, method, gen):
        backoff = 2.0
        while gen == self._gen:
            start = time.monotonic()
            try:
                getattr(self, "_loop_" + method)(gen)
            except Exception as e:              # noqa: BLE001
                logger.debug(f"Focus watcher ({method}) stopped: {type(e).__name__}: {e}")
            with self._lock:
                if gen == self._gen:
                    self._teardown()            # what the failed try left (a bus name, a process)
            if gen != self._gen:
                return
            backoff = 2.0 if time.monotonic() - start > 30 else min(60.0, backoff * 2)
            time.sleep(backoff)

    # -- Hyprland
    def _loop_hyprland(self, gen):
        req, events = hypr_sockets() or (None, None)
        if not events:
            raise OSError("Hyprland's sockets are gone")

        def ask():
            self._set(*hypr_state(hypr_request(req, "j/activewindow")))
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(events)
        self._stop_hooks.append(s.close)
        ask()
        buf = b""
        triggers = (b"activewindow", b"activewindowv2", b"fullscreen", b"closewindow", b"workspace",
                    b"workspacev2", b"focusedmon", b"movewindow", b"windowtitle")
        while gen == self._gen:
            chunk = s.recv(4096)
            if not chunk:
                raise OSError("Hyprland closed its event socket")
            buf += chunk
            lines = buf.split(b"\n")
            buf = lines.pop()
            if any(ln.split(b">>", 1)[0] in triggers for ln in lines):
                ask()

    # -- Sway
    def _loop_sway(self, gen):
        p = subprocess.Popen(["swaymsg", "-r", "-m", "-t", "subscribe", '["window"]'], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True)
        self._proc = p
        cur = ("", False, -1)
        dec = json.JSONDecoder()
        buf = ""
        for line in p.stdout:
            if gen != self._gen:
                break
            buf += line
            while buf.strip():
                try:
                    ev, end = dec.raw_decode(buf.lstrip())
                except ValueError:
                    break                       # not a whole event yet
                buf = buf.lstrip()[end:]
                new = sway_event(ev, cur)
                if new is not None:
                    cur = new
                    self._set(new[0], new[1])

    # -- KDE Plasma
    def _loop_kde(self, gen):
        Gio, GLib = _gio()
        ctx = GLib.MainContext.new()
        ctx.push_thread_default()
        try:
            conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(BUS_XML)

            def call(_c, _sender, _path, _iface, method, params, inv):
                if method == "Window":
                    fs, app, wid = params.unpack()
                    self._kde_window = str(wid)
                    self._set(str(app), bool(fs))
                elif method == "Log":               # the script's own lines, with IRIDIA_KWIN_DEBUG
                    self.script_log.append(str(params.unpack()[0]))
                    del self.script_log[:-50]
                    logger.debug(f"KWin script: {self.script_log[-1]}")
                inv.return_value(None)
            reg = conn.register_object(BUS_PATH, node.interfaces[0], call, None, None)
            own = Gio.bus_own_name_on_connection(conn, BUS_NAME, Gio.BusNameOwnerFlags.REPLACE, None, None)
            loop = GLib.MainLoop.new(ctx, False)

            def ask():
                """KWin 6.8 doesn't pass a window's fullscreen changes to scripts: ask KWin about the
                window in front (one call on the bus, no process) once a second."""
                wid = self._kde_window
                if wid and gen == self._gen:
                    try:
                        r = conn.call_sync("org.kde.KWin", "/KWin", "org.kde.KWin", "getWindowInfo",
                                           GLib.Variant("(s)", (wid,)), GLib.VariantType("(a{sv})"),
                                           Gio.DBusCallFlags.NONE, 1000, None)
                        info = r.unpack()[0]
                        if info:
                            self._set(str(info.get("resourceClass") or self.front), bool(info.get("fullscreen")))
                    except GLib.Error:
                        pass                        # gone meanwhile, or a KWin without getWindowInfo
                return gen == self._gen
            tick = GLib.timeout_source_new(KWIN_ASK_MS)
            tick.set_callback(lambda *_a: ask())
            tick.attach(ctx)

            def stop():
                _kwin_unload()
                Gio.bus_unown_name(own)
                conn.unregister_object(reg)
                GLib.idle_add(loop.quit)        # wakes the loop from the thread that stops it
            self._stop_hooks.append(stop)       # before loading: a script that fails to load is cleaned up too
            _kwin_load(_kwin_script_file())     # the script calls in at once: the name is ours by now
            if gen == self._gen:
                loop.run()
        finally:
            ctx.pop_thread_default()
        if gen == self._gen:
            raise OSError("KWin script stopped")

    # -- X11
    def _loop_x11(self, gen):
        p = subprocess.Popen(["xprop", "-root", "-spy", "_NET_ACTIVE_WINDOW"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True)
        self._proc = p
        win = None

        def ask():
            if win is None:
                self._set("", False)
                return
            out = _out(["xprop", "-id", win, "_NET_WM_STATE", "WM_CLASS"])
            self._set(*xprop_window(out))
        while gen == self._gen:
            ready, _, _ = select.select([p.stdout], [], [], self.interval)
            if ready:
                line = p.stdout.readline()
                if not line:
                    raise OSError("xprop stopped")
                win = xprop_active(line)
            ask()                                # and every few seconds: fullscreen toggles in place

    # -- anywhere else
    def _loop_processes(self, gen):
        while gen == self._gen:
            have = running_apps()
            want = self.wanted
            self._set("", False, {a for a in have if a.lower() in want})
            time.sleep(self.interval)


# ----------------------------------------------------------------- helpers
def hypr_sockets() -> Optional[Tuple[str, str]]:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    for base in (os.path.join(run, "hypr", sig), os.path.join("/tmp", "hypr", sig)):
        ev = os.path.join(base, ".socket2.sock")
        if os.path.exists(ev):
            return os.path.join(base, ".socket.sock"), ev
    return None


def hypr_request(path: str, cmd: str):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect(path)
        s.sendall(cmd.encode())
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    try:
        return json.loads(data.decode("utf-8", "replace") or "{}")
    except ValueError:
        return {}


def _out(cmd) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


_GIO = []


def _gio():
    """Gio and GLib (PyGObject), or None where it's missing."""
    if not _GIO:
        try:
            import gi
            from gi.repository import Gio, GLib
            _GIO.append((Gio, GLib))
            del gi
        except Exception:                       # noqa: BLE001
            _GIO.append(None)
    return _GIO[0]


def _kwin_script_file() -> str:
    folder = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "iridia")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "kwin-focus.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(kwin_script(bool(os.environ.get("IRIDIA_KWIN_DEBUG"))))
    return path


def _gdbus_kwin(path: str, method: str, *args) -> str:
    return _out(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", path,
                 "--method", method, *args])


def _kwin_load(path: str):
    _kwin_unload()
    out = _gdbus_kwin("/Scripting", "org.kde.kwin.Scripting.loadScript", path, KWIN_PLUGIN)
    m = re.search(r"(-?\d+)", out)
    if not m or int(m.group(1)) < 0:
        raise OSError(f"KWin didn't load the script ({out.strip() or 'no answer'})")
    sid = m.group(1)
    # Plasma 6 puts the script at /Scripting/ScriptN, Plasma 5 at /N
    for obj in (f"/Scripting/Script{sid}", f"/{sid}"):
        if _gdbus_kwin(obj, "org.kde.kwin.Script.run").strip() == "()":
            return
    _gdbus_kwin("/Scripting", "org.kde.kwin.Scripting.start")


def _kwin_unload():
    _gdbus_kwin("/Scripting", "org.kde.kwin.Scripting.unloadScript", KWIN_PLUGIN)
