"""Ring-buffer file logging."""
import collections, logging, os, threading

class RingBufferHandler(logging.Handler):
    def __init__(self, filepath, max_size_kb=1024):
        super().__init__()
        self.filepath = os.path.expanduser(filepath)
        self.max_size = max_size_kb * 1024
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)

    def emit(self, record):
        msg = self.format(record) + "\n"
        encoded = msg.encode("utf-8")
        with self._lock:
            current_size = os.path.getsize(self.filepath) if os.path.exists(self.filepath) else 0
            if current_size + len(encoded) > self.max_size and current_size > 0:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                trim_count = max(1, len(lines) // 4)
                with open(self.filepath, "w", encoding="utf-8") as f:
                    f.writelines(lines[trim_count:])
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(msg)

class MemoryHandler(logging.Handler):
    """Keeps the last few hundred formatted lines so the GUI/CLI can show
    recent activity even when file logging is off."""

    def __init__(self, capacity: int = 300):
        super().__init__()
        self._lines = collections.deque(maxlen=capacity)
        self._lock2 = threading.Lock()

    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:
            return
        with self._lock2:
            self._lines.append(line)

    def tail(self, n: int):
        with self._lock2:
            return list(self._lines)[-max(1, n):]


MEMORY = MemoryHandler()


def setup_logging(config):
    logger = logging.getLogger("iridia")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    log_cfg = config.logging if hasattr(config, "logging") else config
    level_str = log_cfg.get("level", "info") if isinstance(log_cfg, dict) else log_cfg.get("level", "info")
    level = getattr(logging, level_str.upper(), logging.INFO)
    logger.setLevel(level)
    console = logging.StreamHandler()
    console.setLevel(level)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    console.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(console)
    MEMORY.setLevel(logging.INFO if level > logging.INFO else level)
    MEMORY.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(MEMORY)
    enabled = log_cfg.get("enabled", False) if isinstance(log_cfg, dict) else log_cfg.get("enabled", False)
    if enabled:
        filepath = log_cfg.get("file_path", "~/.local/share/iridia/iridia.log")
        max_kb = log_cfg.get("max_size_kb", 1024)
        fh = RingBufferHandler(filepath, max_kb)
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)
    return logger
