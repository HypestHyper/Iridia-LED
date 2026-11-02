"""Iridia's window against a running daemon (with the fake OpenRGB): every tab at every window size.
Fails on any Python exception (GTK callbacks only print them, so they're caught here); run.sh also
fails on GTK criticals in the output."""
import sys
import traceback

from iridia.ui import fonts

fonts.register()
from gi.repository import GLib  # noqa: E402

from iridia.ui.app import IridiaApp  # noqa: E402

errors = []


def hook(t, v, tb):
    errors.append("".join(traceback.format_exception(t, v, tb)))
    sys.__excepthook__(t, v, tb)


sys.excepthook = hook
app = IridiaApp()
plan = []


def start():
    w = app.win
    if not w.client.status().get("ok"):
        errors.append("the window can't reach the daemon")
        app.quit()
        return False
    for size in ("compact", "default", "large"):
        plan.append(("size", size))
        for tab in w._tabs:
            plan.append(("tab", tab))
    GLib.timeout_add(400, step)
    return False


def step():
    w = app.win
    if not plan:
        print(f"window: every tab at every size, {len(errors)} error(s)")
        app.quit()
        return False
    kind, what = plan.pop(0)
    try:
        if kind == "size":
            w._apply_ui_size(what)
        else:
            w._tabs[what].set_active(True)
    except Exception:                   # noqa: BLE001
        errors.append(traceback.format_exc())
    return True


GLib.timeout_add(3000, start)
GLib.timeout_add(120000, lambda: (errors.append("timed out"), app.quit()))
app.run([])
if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
