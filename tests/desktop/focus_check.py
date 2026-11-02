"""Scenes on a real KWin: a GTK window opens, goes fullscreen, comes back and closes, and Iridia's
focus watcher (the KWin script, iridia/focuswatch.py) has to see each step. Run by run.sh inside a
headless kwin_wayland; exits 1 with what it saw when something's missing."""
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from iridia import focuswatch as F  # noqa: E402

APP_ID = "org.iridia.DesktopCheck"
seen = []
w = F.FocusWatch(lambda: seen.append((w.front, w.fullscreen)))
if w.pick_method() != "kde":
    sys.exit(f"expected the KDE watcher, got {w.pick_method()}")
w.set_needed(True)


def wait(pred, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


steps = []
runner = []


def on_gtk(fn):
    """fn() run on GTK's thread (GTK isn't thread-safe), its result here."""
    box, done = [], threading.Event()
    GLib.idle_add(lambda: (box.append(fn()), done.set(), False)[2])
    done.wait(5)
    return box[0] if box else None


def script(win, app):
    """Runs off the GTK thread: each step waits for the watcher before the next one."""
    for name, act, want in (("open", None, (APP_ID, False)),
                            ("fullscreen", win.fullscreen, (APP_ID, True)),
                            ("unfullscreen", win.unfullscreen, (APP_ID, False)),
                            ("close", win.close, ("", False))):
        if act is not None:
            GLib.idle_add(lambda a=act: (a(), False)[1])
        ok = wait(lambda w=want: bool(seen) and seen[-1] == w)
        steps.append((name, ok))
        if name in ("fullscreen", "unfullscreen"):
            # what the compositor told GTK: tells "KWin didn't do it" from "Iridia didn't hear it"
            steps.append(("gtk says fullscreen", on_gtk(win.is_fullscreen)))
        if not ok:
            GLib.idle_add(lambda: (app.quit(), False)[1])
            return


def activate(app):
    win = Gtk.ApplicationWindow(application=app, title="Desktop check")
    win.set_default_size(320, 200)
    win.present()
    t = threading.Thread(target=script, args=(win, app), daemon=True)
    runner.append(t)
    t.start()


app = Gtk.Application(application_id=APP_ID)
app.connect("activate", activate)
app.run([])
for t in runner:
    t.join(20)                          # the last step (the window gone) is checked after the app quits
if len(steps) == 6 and all(ok == (n != "gtk says fullscreen" or i == 2) for i, (n, ok) in enumerate(steps)):
    # after the window has gone, the watcher has to say so too (checked in the loop above);
    # switching scenes off has to unload the script from KWin
    w.stop()
    time.sleep(1.0)
    out = F._gdbus_kwin("/Scripting", "org.kde.kwin.Scripting.isScriptLoaded", F.KWIN_PLUGIN)
    if "false" not in out:
        sys.exit(f"the KWin script is still loaded after stopping: {out.strip()}")
    print("focus: open, fullscreen, unfullscreen, close all seen; script unloaded"
          f" ({len(w.script_log)} lines from the script)")
    sys.exit(0)
print("focus: steps", steps, "seen", seen, file=sys.stderr)
print("focus: the KWin script said:", *w.script_log, sep="\n  ", file=sys.stderr)
sys.exit(1)
