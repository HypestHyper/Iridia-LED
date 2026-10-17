"""System sensors for the LEDs: CPU and GPU temperature and load, memory use, disk temperature.

Everything is read from files the kernel already keeps up to date, so a reading costs a few small
reads and no process:
    CPU load      /proc/stat (busy share since the last reading)
    memory        /proc/meminfo (MemTotal minus MemAvailable)
    temperatures  /sys/class/hwmon: k10temp/zenpower (AMD), coretemp (Intel), cpu_thermal (ARM),
                  amdgpu, nouveau and radeon (GPUs), nvme, drivetemp; and any other hwmon
                  temperature as "hwmon:<chip>:<label>"
    AMD GPU load  /sys/class/drm/card*/device/gpu_busy_percent
    NVIDIA        nvidia-smi, one long-running process (-lms) and only while a strip shows an NVIDIA
                  reading: starting it wakes a sleeping laptop GPU, so it's never run just to look

Only the sensors a strip shows are read, once a second, and smoothed over a few seconds so a bar
doesn't jump with every spike.
"""

import glob
import math
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

READ_SEC = 1.0
SMOOTH_SEC = 3.0            # exponential smoothing time constant
TEMP_RANGE = (30.0, 90.0)
PCT_RANGE = (0.0, 100.0)

CPU_CHIPS = ("k10temp", "zenpower", "coretemp", "cpu_thermal", "soc_thermal", "cpu-thermal")
CPU_LABELS = ("Tctl", "Tdie", "Package id 0", "Physical id 0")
GPU_CHIPS = ("amdgpu", "nouveau", "radeon")
GPU_LABELS = ("edge", "junction")
DISK_CHIPS = ("nvme", "drivetemp")

_ID_RE = re.compile(r"^[A-Za-z0-9_:.\- ]{1,80}$")


def valid_id(sid) -> bool:
    return isinstance(sid, str) and bool(_ID_RE.match(sid))


def default_range(sid: str) -> Tuple[float, float]:
    return TEMP_RANGE if sid.endswith("_temp") or sid.startswith("hwmon:") else PCT_RANGE


def unit_of(sid: str) -> str:
    return "°C" if sid.endswith("_temp") or sid.startswith("hwmon:") else "%"


def _read(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _read_milli(path: str) -> Optional[float]:
    txt = _read(path)
    try:
        return int(txt.strip()) / 1000.0 if txt is not None else None
    except ValueError:
        return None


class Source:
    """One reading: name for people, how to read it, and its default range."""

    def __init__(self, sid: str, name: str, read: Callable[[], Optional[float]], nvidia: bool = False):
        self.id, self.name, self.read, self.nvidia = sid, name, read, nvidia


class _NvidiaStream:
    """nvidia-smi printing temperature and load once a second, read line by line."""

    def __init__(self):
        self.temp: Optional[float] = None
        self.load: Optional[float] = None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        with self._lock:
            if self.running():
                return
            exe = shutil.which("nvidia-smi")
            if not exe:
                return
            try:
                self._proc = subprocess.Popen(
                    [exe, "--query-gpu=temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits",
                     "-lms", str(int(READ_SEC * 1000))],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True, bufsize=1)
            except OSError:
                self._proc = None
                return
            threading.Thread(target=self._loop, args=(self._proc,), daemon=True, name="nvidia-smi").start()

    def _loop(self, proc):
        for line in proc.stdout:
            parts = [p.strip() for p in line.split(",")]
            try:
                self.temp, self.load = float(parts[0]), float(parts[1])
            except (ValueError, IndexError):
                continue            # "[N/A]" or a second GPU's line: keep the last good one
        self.temp = self.load = None

    def stop(self):
        with self._lock:
            p, self._proc = self._proc, None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()
        self.temp = self.load = None


class SensorHub:
    """Finds the sensors, reads the ones in use and keeps a smoothed value for each."""

    def __init__(self, sys_root: str = "/sys", proc_root: str = "/proc"):
        self.sys, self.proc = sys_root, proc_root
        self._sources: Optional[Dict[str, Source]] = None
        self._found_at = 0.0
        self._wanted: set = set()
        self._raw: Dict[str, Optional[float]] = {}
        self._smooth: Dict[str, float] = {}
        self._last_read = 0.0
        self._last_smooth = 0.0
        self._cpu_prev: Optional[Tuple[int, int]] = None
        self._nvidia = _NvidiaStream()

    # ------------------------------------------------------------- finding sensors
    def _hwmon(self) -> List[Tuple[str, str, str]]:
        """(chip name, label, temp*_input path) for every hwmon temperature."""
        out = []
        for d in sorted(glob.glob(os.path.join(self.sys, "class", "hwmon", "hwmon*"))):
            chip = (_read(os.path.join(d, "name")) or "").strip()
            if not chip:
                continue
            for inp in sorted(glob.glob(os.path.join(d, "temp*_input")),
                              key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
                label = (_read(inp.replace("_input", "_label")) or "").strip() or \
                    os.path.basename(inp).replace("_input", "")
                out.append((chip, label, inp))
        return out

    def _pick(self, temps, chips, labels) -> Optional[str]:
        for chip in chips:
            mine = [(lbl, p) for c, lbl, p in temps if c == chip]
            for want in labels:
                for lbl, p in mine:
                    if lbl == want:
                        return p
            if mine:
                return mine[0][1]
        return None

    def discover(self) -> Dict[str, Source]:
        src: Dict[str, Source] = {}
        stat = os.path.join(self.proc, "stat")
        if _read(stat) is not None:
            src["cpu_load"] = Source("cpu_load", "CPU load", self._cpu_load)
        if _read(os.path.join(self.proc, "meminfo")) is not None:
            src["ram"] = Source("ram", "Memory use", self._ram)
        temps = self._hwmon()
        p = self._pick(temps, CPU_CHIPS, CPU_LABELS)
        if p is None:
            # no CPU chip driver: the ACPI thermal zone is the next best thing
            p = self._pick(temps, ("acpitz",), ())
        if p:
            src["cpu_temp"] = Source("cpu_temp", "CPU temperature", lambda p=p: _read_milli(p))
        nvidia = bool(shutil.which("nvidia-smi")) and os.path.isdir(os.path.join(self.proc, "driver", "nvidia"))
        busy = sorted(glob.glob(os.path.join(self.sys, "class", "drm", "card*", "device", "gpu_busy_percent")))
        gpu_t = self._pick(temps, GPU_CHIPS, GPU_LABELS)
        if nvidia:
            src["gpu_temp"] = Source("gpu_temp", "GPU temperature (NVIDIA)", lambda: self._nvidia.temp, nvidia=True)
            src["gpu_load"] = Source("gpu_load", "GPU load (NVIDIA)", lambda: self._nvidia.load, nvidia=True)
            if gpu_t:
                src["gpu2_temp"] = Source("gpu2_temp", "GPU temperature (second GPU)",
                                          lambda p=gpu_t: _read_milli(p))
            if busy:
                src["gpu2_load"] = Source("gpu2_load", "GPU load (second GPU)", lambda p=busy[0]: self._pct(p))
        else:
            if gpu_t:
                src["gpu_temp"] = Source("gpu_temp", "GPU temperature", lambda p=gpu_t: _read_milli(p))
            if busy:
                src["gpu_load"] = Source("gpu_load", "GPU load", lambda p=busy[0]: self._pct(p))
        p = self._pick(temps, DISK_CHIPS, ("Composite",))
        if p:
            src["disk_temp"] = Source("disk_temp", "Disk temperature", lambda p=p: _read_milli(p))
        seen = {}
        for chip, label, path in temps:
            sid = f"hwmon:{chip}:{label}"
            if sid in seen or not valid_id(sid):
                continue
            seen[sid] = True
            src[sid] = Source(sid, f"{chip} {label}", lambda p=path: _read_milli(p))
        return src

    def sources(self) -> Dict[str, Source]:
        now = time.monotonic()
        if self._sources is None or (now - self._found_at > 60 and any(w not in self._sources
                                                                         for w in self._wanted)):
            self._sources = self.discover()
            self._found_at = now
        return self._sources

    # ------------------------------------------------------------- readers
    def _cpu_load(self) -> Optional[float]:
        line = (_read(os.path.join(self.proc, "stat")) or "").split("\n", 1)[0].split()
        if not line or line[0] != "cpu":
            return None
        try:
            vals = [int(v) for v in line[1:]]
        except ValueError:
            return None
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals[:8])
        prev, self._cpu_prev = self._cpu_prev, (total, idle)
        if prev is None or total <= prev[0]:
            return None
        return max(0.0, min(100.0, 100.0 * (1 - (idle - prev[1]) / (total - prev[0]))))

    def _ram(self) -> Optional[float]:
        info = {}
        for line in (_read(os.path.join(self.proc, "meminfo")) or "").splitlines():
            k, _sep, v = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                try:
                    info[k] = int(v.split()[0])
                except (ValueError, IndexError):
                    pass
        if not info.get("MemTotal") or "MemAvailable" not in info:
            return None
        return 100.0 * (1 - info["MemAvailable"] / info["MemTotal"])

    @staticmethod
    def _pct(path) -> Optional[float]:
        txt = _read(path)
        try:
            return float(txt.strip()) if txt is not None else None
        except ValueError:
            return None

    # ------------------------------------------------------------- in use
    def set_wanted(self, ids) -> None:
        ids = {i for i in ids if valid_id(i)}
        if ids == self._wanted:
            return
        self._wanted = ids
        for k in list(self._smooth):
            if k not in ids:
                self._smooth.pop(k, None)
                self._raw.pop(k, None)
        srcs = self.sources() if ids else (self._sources or {})
        if any(srcs.get(i) is not None and srcs[i].nvidia for i in ids):
            self._nvidia.start()
        else:
            self._nvidia.stop()

    def update(self, now: Optional[float] = None) -> bool:
        """Read (once a second) and smooth; True when a value moved enough to redraw."""
        if not self._wanted:
            return False
        now = time.monotonic() if now is None else now
        if now - self._last_read >= READ_SEC:
            self._last_read = now
            srcs = self.sources()
            for sid in self._wanted:
                s = srcs.get(sid)
                v = s.read() if s is not None else None
                self._raw[sid] = None if v is None or v != v else float(v)
        dt = now - self._last_smooth if self._last_smooth else READ_SEC
        self._last_smooth = now
        k = 1 - math.exp(-max(0.0, dt) / SMOOTH_SEC)
        moved = False
        for sid in self._wanted:
            raw = self._raw.get(sid)
            if raw is None:
                if self._smooth.pop(sid, None) is not None:
                    moved = True
                continue
            old = self._smooth.get(sid)
            new = raw if old is None else old + (raw - old) * k
            if old is None or abs(new - old) >= 0.05:
                moved = True
            self._smooth[sid] = new
        return moved

    def value(self, sid: str) -> Optional[float]:
        return self._smooth.get(sid)

    def values(self) -> Dict[str, Optional[float]]:
        return {sid: (None if self._smooth.get(sid) is None else round(self._smooth[sid], 1))
                for sid in sorted(self._wanted)}

    def listing(self) -> List[dict]:
        """Every sensor with a fresh reading (NVIDIA only when it's already running)."""
        out = []
        for sid, s in self.sources().items():
            v = None
            if not s.nvidia:
                v = s.read() if sid != "cpu_load" else self.value(sid)
            elif self._nvidia.running():
                v = s.read()
            lo, hi = default_range(sid)
            out.append({"id": sid, "name": s.name, "unit": unit_of(sid), "value": None if v is None else round(v, 1),
                        "min": lo, "max": hi, "wakes_gpu": s.nvidia})
        return out

    def stop(self):
        self._nvidia.stop()
