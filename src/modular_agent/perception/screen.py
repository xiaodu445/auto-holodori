from __future__ import annotations

from pathlib import Path
import cv2
import mss
import numpy as np
from .models import CapturedFrame


def load_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None: raise ValueError(f"Cannot read image: {path}")
    return image


def capture_monitor(monitor: int = 1) -> tuple[np.ndarray, CapturedFrame]:
    """Read-only capture; monitor 0 is the combined virtual display."""
    with mss.mss() as session:
        if monitor < 0 or monitor >= len(session.monitors): raise ValueError(f"monitor must be 0..{len(session.monitors) - 1}")
        bounds = session.monitors[monitor]
        shot = session.grab(bounds)
    image = np.asarray(shot)[:, :, :3]
    return image, CapturedFrame(image.shape[1], image.shape[0], monitor, bounds["left"], bounds["top"])
