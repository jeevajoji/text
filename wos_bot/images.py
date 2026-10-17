"""PNG read/write that works with non-ASCII Windows paths.

cv2.imread/imwrite go through the C runtime's narrow-char API on Windows and fail
silently for paths like C:\\Users\\Jösé\\...; encoding in memory and using numpy's file
I/O avoids that.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def write_png(path: str | Path, image: np.ndarray) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"could not encode image for {path}")
    buf.tofile(str(path))
    return path


def read_image(path: str | Path) -> np.ndarray:
    """Read an image as BGR (alpha dropped)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"could not read image: {path}")
    return image
