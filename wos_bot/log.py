"""Console + rotating file logging, and failure screenshots for debugging."""
from __future__ import annotations

import logging
import logging.handlers
import re
import time
from pathlib import Path

import numpy as np

from config import resolve_path
from images import write_png

_log_dir = resolve_path("logs")


def setup_logging(level: str = "INFO", log_dir: str | Path = "logs") -> Path:
    """Send INFO+ (or `level`) to the console and everything to <log_dir>/bot.log."""
    global _log_dir
    _log_dir = resolve_path(log_dir)
    _log_dir.mkdir(parents=True, exist_ok=True)
    log_file = _log_dir / "bot.log"

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler()
    console.setLevel(level.upper())
    console.setFormatter(fmt)
    file = logging.handlers.RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file.setLevel(logging.DEBUG)
    file.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file)
    # adbutils logs every socket at DEBUG, which would drown our own debug lines.
    logging.getLogger("adbutils").setLevel(logging.WARNING)
    return log_file


def save_failure(image: np.ndarray | None, reason: str) -> Path | None:
    """Save a screenshot to <log_dir>/failures/<timestamp>_<reason>.png and log the path."""
    if image is None:
        return None
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", reason).strip("_")[:60] or "failure"
    path = _log_dir / "failures" / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe}.png"
    try:
        write_png(path, image)
    except (OSError, ValueError) as e:
        logging.getLogger(__name__).error("Could not save failure screenshot %s: %s", path, e)
        return None
    logging.getLogger(__name__).warning("Saved failure screenshot: %s", path)
    return path
