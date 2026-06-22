from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread_unicode(path: Path, flags: int) -> np.ndarray | None:
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)
