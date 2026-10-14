"""Turn the LEDs off when the PC suspends, and back on when it wakes.

systemd-logind announces suspend with the PrepareForSleep(true) signal on the
system bus and resume with PrepareForSleep(false). We listen with whichever of
`gdbus` or `dbus-monitor` is installed, so there is no extra Python dependency.

To get the LEDs dark *before* the machine sleeps, we hold a "delay" sleep
inhibitor (`systemd-inhibit --mode=delay`). logind then waits (a few seconds at
most) until we release it, which we do right after the LEDs went dark.
"""

import logging
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("iridia")


class SleepWatcher:
    def __init__(self, on_sleep: Callable[[], None], on_wake: Callable[[], None]):
        self._on_sleep = on_sleep
        self._on_wake = on_wake
        self._proc: Optional[subprocess.Popen] = None
        self._inhibit: Optional[subprocess.Popen] = None
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self.available = False
        self.method = None

    # ------------------------------------------------------------ inhibitor
    def _take_inhibitor(self):
        if self._inhibit and self._inhibit.poll() is None:
            return
        exe = shutil.which("systemd-inhibit")
        if not exe:
            return
        try:
            self._inhibit = subprocess.Popen(
                [exe, "--what=sleep", "--mode=delay", "--who=Iridia",
                 "--why=Turn the LEDs off before sleeping", "sleep", "infinity"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            logger.debug(f"Sleep inhibitor unavailable: {e}")
            self._inhibit = None

    def _release_inhibitor(self):
        p, self._inhibit = self._inhibit, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(1)
            except subprocess.TimeoutExpired:
                p.kill()

    # --------------------------------------------------------------- monitor
    def _command(self):
        if shutil.which("gdbus"):
            return "gdbus", ["gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
                             "--object-path", "/org/freedesktop/login1"]
        if shutil.which("dbus-monitor"):
            return "dbus-monitor", ["dbus-monitor", "--system",
                                    "type='signal',interface='org.freedesktop.login1.Manager',"
                                    "member='PrepareForSleep'"]
        return None, None

    def start(self) -> bool:
        self.method, cmd = self._command()
        if not cmd:
            logger.info("Sleep detection off: neither gdbus nor dbus-monitor is installed")
            return False
        self.available = True
        self._thread = threading.Thread(target=self._run, args=(cmd,), daemon=True, name="sleepwatch")
        self._thread.start()
        return True

    def _run(self, cmd):
        backoff = 2
        fails = 0
        while not self._stop:
            started = time.monotonic()
            self._take_inhibitor()
            try:
                self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                              stdin=subprocess.DEVNULL, text=True, bufsize=1)
            except OSError as e:
                logger.warning(f"Sleep detection failed to start ({e})")
                return
            logger.debug(f"Watching for suspend/resume via {self.method}")
            pending_bool = False          # dbus-monitor prints the argument on the next line
            for line in self._proc.stdout:
                if self._stop:
                    break
                if not self.available and fails:
                    self.available, fails = True, 0
                if "PrepareForSleep" in line:
                    if "true" in line:
                        self._sleeping()
                    elif "false" in line:
                        self._waking()
                    else:
                        pending_bool = True
                    continue
                if pending_bool and "boolean" in line:
                    pending_bool = False
                    (self._sleeping if "true" in line else self._waking)()
            if self._stop:
                break
            quick = time.monotonic() - started < 5
            fails = fails + 1 if quick else 0
            if fails == 3:
                # The system bus can't be watched (no logind, a sandbox, dbus-monitor without
                # rights): say so once and keep trying slowly in the background.
                self.available = False
                logger.warning(f"Sleep detection isn't working ({self.method} keeps exiting); the LEDs won't "
                               "turn off on suspend. Installing gdbus (part of glib2) usually fixes this.")
            logger.debug("Sleep monitor exited, restarting")
            time.sleep(backoff)
            backoff = min(60, backoff * 2)

    def _sleeping(self):
        logger.info("PC is going to sleep: turning the LEDs off")
        try:
            self._on_sleep()
        finally:
            self._release_inhibitor()

    def _waking(self):
        logger.info("PC woke up: turning the LEDs back on")
        self._take_inhibitor()
        try:
            self._on_wake()
        except Exception:
            logger.exception("Wake handler failed")

    def stop(self):
        self._stop = True
        for p in (self._proc,):
            if p and p.poll() is None:
                p.terminate()
        self._release_inhibitor()
