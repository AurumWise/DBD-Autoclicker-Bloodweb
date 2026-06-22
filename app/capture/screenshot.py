from __future__ import annotations

from pathlib import Path

import cv2
import mss
import numpy as np

from app.vision.image_io import imread_unicode


class ScreenshotService:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def capture_primary_monitor(self) -> tuple[np.ndarray, str]:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = np.array(sct.grab(monitor))
        image = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
        return image, "screen:primary"

    def load_from_file(self, image_path: Path) -> tuple[np.ndarray, str]:
        image_path = self.resolve_image_path(image_path)
        image = imread_unicode(image_path, cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Unable to load image: {image_path}")
        return image, image_path.name

    def resolve_image_path(self, image_path: Path) -> Path:
        if image_path.exists():
            return image_path

        screenshots_dir = self.root_dir / "скриншоты"
        if screenshots_dir.exists():
            candidates = sorted(screenshots_dir.glob("*.png"))
            if candidates:
                return candidates[0]
        return image_path
