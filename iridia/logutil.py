"""Ring-buffer file logging — single file, overwrite from front when full."""

import logging
import os
import threading


class RingBufferHandler(logging.Handler):
    """Logging handler that writes to a single file, trimming oldest lines when size limit is hit."""

    def __init__(self, filepath: str, max_size_kb: int = 1024):
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
                # Trim oldest ~25% of lines
                with open(self.filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                trim_count = max(1, len(lines) // 4)
                with open(self.filepath, "w", encoding="utf-8") as f:
                    f.writelines(lines[trim_count:])

            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(msg)


def setup_logging(config) -> logging.Logger:
    """Configure logger with optional ring-buffer file handler."""
    logger = logging.getLogger("iridia")
    logger.setLevel(logging.DEBUG)

    # Clear existing handlers
    logger.handlers = []

    log_cfg = config.logging if hasattr(config, "logging") else config
    level_str = log_cfg.get("level", "info") if isinstance(log_cfg, dict) else log_cfg.get("level", "info")
    level = getattr(logging, level_str.upper(), logging.INFO)
    logger.setLevel(level)

    # Console handler (stderr) — always on
    console = logging.StreamHandler()
    console.setLevel(level)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    console.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(console)

    # File handler — only if enabled
    enabled = log_cfg.get("enabled", False) if isinstance(log_cfg, dict) else log_cfg.get("enabled", False)
    if enabled:
        filepath = log_cfg.get("file_path", "~/.local/share/iridia/iridia.log")
        max_kb = log_cfg.get("max_size_kb", 1024)
        fh = RingBufferHandler(filepath, max_kb)
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)

    return logger
