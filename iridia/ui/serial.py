"""One background worker for daemon calls, so changes reach the daemon in the order they were made
(separate threads could deliver "switch to Paint" after the first brush stroke and undo it)."""

import queue
import sys
import threading

_q: "queue.Queue" = queue.Queue()
_worker = None


def _run():
    while True:
        fn, args = _q.get()
        try:
            r = fn(*args)
            if isinstance(r, dict) and not r.get("ok", True):
                print(f"iridia-gui: daemon rejected request: {r.get('error')}", file=sys.stderr)
        except Exception as e:      # noqa: BLE001 - logged, the window keeps working
            print(f"iridia-gui: daemon call failed: {e}", file=sys.stderr)


def send(fn, *args):
    global _worker
    if _worker is None:
        _worker = threading.Thread(target=_run, daemon=True, name="iridia-daemon-calls")
        _worker.start()
    _q.put((fn, args))
