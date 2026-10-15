"""Sends animation frames: one thread, running only while some zone animates.

The daemon describes the work as jobs (one per animated zone, grouped by device) and hands them
over with set_jobs(); the thread renders each due device's zones, sends only what changed, and
paces each device on its own:

- Frames are never queued. If a device takes longer to accept a frame than the frame interval,
  its next frame is simply later (the clock keeps running, so effects don't slow down).
- If that keeps happening, the device gets a lower rate (60 -> 30 -> 15 fps), logged once.
- When every zone of a device animates, one packet updates the whole device; otherwise only the
  zones that changed are sent.

With no jobs the thread isn't running at all, so a setup with only static patterns costs nothing.
"""

import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("iridia.animator")

RGB = Tuple[int, int, int]
RATES = (15, 30, 60)


class Job:
    """One animated zone. frame(clock) returns the finished colours to send, or None while the
    zone is paused (identify, a keybind, lights off...), when the daemon's normal path owns it."""

    def __init__(self, key: str, device: str, zone: str, real_n: int,
                 frame: Callable[[float], Optional[List[RGB]]], describe: Optional[str] = ""):
        self.key, self.device, self.zone, self.real_n = key, device, zone, real_n
        self.frame = frame
        self.describe = describe


class _Dev:
    def __init__(self, fps: int):
        self.fps = fps
        self.next_due = 0.0
        self.last: Dict[str, List[RGB]] = {}     # zone -> last frame sent
        self.last_whole: Optional[List[RGB]] = None
        self.slow_since: Optional[float] = None  # frames have taken longer than the interval since then
        self.frames = 0                          # frames sent since the last fps report
        self.reported = time.monotonic()
        self.win_start = time.monotonic()        # the 5 second window for timing
        self.win_frames = 0
        self.win_took = 0.0
        self.win_max = 0.0


class Animator:
    SLOW_SEC = 1.0               # a device slower than its frame rate for this long gets a lower rate

    def __init__(self, send: Callable[[str, Dict[str, Sequence[RGB]]], Optional[bool]]):
        self._send = send
        self._lock = threading.Lock()
        self._jobs: Dict[str, Tuple[bool, List[Job]]] = {}
        self._devs: Dict[str, _Dev] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.fps = 30
        self.rate = 1.0                          # clock speed (0.5 = slowed for night mode)
        self._clock = 0.0
        self._last_tick: Optional[float] = None
        self.measured: Dict[str, float] = {}     # device -> frames per second over the last minute
        self.timing: Dict[str, dict] = {}        # device -> {fps, ms per frame, slowest ms} over the last 5 s

    # ------------------------------------------------------------ state
    @property
    def clock(self) -> float:
        """Seconds of animation time (shared by every zone; the window uses it for its preview)."""
        return self._clock

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def keys(self) -> set:
        with self._lock:
            return {j.key for _w, jobs in self._jobs.values() for j in jobs if j.describe is not None}

    def set_jobs(self, jobs: Dict[str, Tuple[bool, List[Job]]], fps: int, rate: float = 1.0):
        """Replace the work. jobs: device -> (send the whole device in one packet, its zones)."""
        fps = fps if fps in RATES else 30
        with self._lock:
            old = {j.key: j.describe for _w, js in self._jobs.values() for j in js if j.describe is not None}
            new = {j.key: j.describe for _w, js in jobs.values() for j in js if j.describe is not None}
            self._jobs = jobs
            if fps != self.fps:
                self._devs = {}
            self.fps, self.rate = fps, rate
            for d in list(self._devs):
                if d not in jobs:
                    del self._devs[d]
            for d in list(self.timing):
                if d not in jobs:
                    del self.timing[d]
        for k in sorted(set(old) | set(new)):
            if old.get(k) != new.get(k):
                if k not in new:
                    logger.info(f"Animation stopped on {k}")
                else:
                    logger.info(f"Animation on {k}: {new[k]}")
        if jobs and not self.running():
            self._stop.clear()
            self._last_tick = None
            self._thread = threading.Thread(target=self._run, daemon=True, name="iridia-animation")
            self._thread.start()
            logger.debug(f"Animation thread started ({fps} fps)")
        self._wake.set()

    def forget(self, key: str):
        """The zone was changed by something else: send its next frame even if it looks the same."""
        with self._lock:
            for d in self._devs.values():
                d.last = {}
                d.last_whole = None

    def stop(self):
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2)
        self._thread = None

    # ------------------------------------------------------------ the loop
    def _run(self):
        try:
            while not self._stop.is_set():
                with self._lock:
                    jobs = dict(self._jobs)
                if not jobs:
                    break
                now = time.monotonic()
                if self._last_tick is not None:
                    self._clock += (now - self._last_tick) * self.rate
                self._last_tick = now
                for dev, (whole, zjobs) in jobs.items():
                    st = self._devs.get(dev)
                    if st is None:
                        st = self._devs[dev] = _Dev(self.fps)
                    if now >= st.next_due:
                        self._frame(dev, whole, zjobs, st)
                due = min((d.next_due for d in self._devs.values()), default=now + 1 / self.fps)
                self._wake.wait(max(0.001, due - time.monotonic()))
                self._wake.clear()
        except Exception:                   # noqa: BLE001  (never take the daemon down)
            logger.exception("Animation thread failed; animations stop until settings change")
        finally:
            logger.debug("Animation thread stopped")

    def _frame(self, dev: str, whole: bool, zjobs: List[Job], st: _Dev):
        start = time.monotonic()
        interval = 1.0 / st.fps
        frames: Dict[str, List[RGB]] = {}
        paused = False
        for job in zjobs:
            f = job.frame(self._clock)
            if f is None:
                paused = True
                st.last.pop(job.zone, None)
                continue
            frames[job.zone] = f
        if paused:
            st.last_whole = None
        sent = None
        if whole and not paused and frames:
            flat = [c for job in zjobs for c in _fit(frames[job.zone], job.real_n)]
            if flat != st.last_whole:
                sent = self._send(dev, {"": flat})
                if sent:
                    st.last_whole = flat
        else:
            changed = {z: f for z, f in frames.items() if f != st.last.get(z)}
            if changed:
                sent = self._send(dev, changed)
                if sent:
                    st.last.update(changed)
        took = time.monotonic() - start
        if sent:
            st.frames += 1
            st.win_frames += 1
            st.win_took += took
            st.win_max = max(st.win_max, took)
        if start - st.win_start >= 5:
            span = start - st.win_start
            self.timing[dev] = {"fps": round(st.win_frames / span, 1), "target": st.fps,
                                "ms": round(1000 * st.win_took / max(1, st.win_frames), 1),
                                "max_ms": round(1000 * st.win_max, 1)}
            st.win_start, st.win_frames, st.win_took, st.win_max = start, 0, 0.0, 0.0
        if sent is False:
            st.last, st.last_whole = {}, None     # the connection dropped: resend everything later
        # pacing: the next frame is due one interval after this one started, or right after a slow
        # send; never earlier, never queued
        st.next_due = max(start + interval, time.monotonic())
        if took <= interval:
            st.slow_since = None
        elif st.slow_since is None:
            st.slow_since = start
        elif start - st.slow_since >= self.SLOW_SEC and st.fps > RATES[0]:
            lower = max(r for r in RATES if r < st.fps)
            logger.info(f"'{dev}' can't keep up with {st.fps} fps (a frame takes {took * 1000:.0f} ms), "
                        f"using {lower}")
            st.fps, st.slow_since = lower, None
        if start - st.reported >= 60:
            fps = st.frames / (start - st.reported)
            self.measured[dev] = round(fps, 1)
            logger.debug(f"Animation on '{dev}': {fps:.1f} frames sent per second (target {st.fps})")
            st.frames, st.reported = 0, start


def _fit(colors: Sequence[RGB], n: int) -> List[RGB]:
    out = list(colors[:n])
    while len(out) < n:
        out.append(out[-1] if out else (0, 0, 0))
    return out
