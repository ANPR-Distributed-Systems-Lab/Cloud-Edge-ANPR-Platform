"""Image preprocessing that must be identical in dataset preparation and on the edge node."""
from pathlib import Path

import cv2
import numpy as np

# (width, height). OPEN in ML_ASSUMPTIONS: 1280x960 is the v0 choice, final after the Pi benchmark.
DETECTOR_SIZE = (1280, 960)


def resize_for_detector(image: np.ndarray, size: tuple[int, int] = DETECTOR_SIZE) -> np.ndarray:
    """Full frame -> detector input. INTER_AREA is the reference filter; the Pi must reproduce these pixels.

    The 4056x3040 frame and 4:3 detector sizes differ in aspect by under 0.1 %, so the frame is stretched
    to the exact size instead of letterboxed. Normalized labels stay valid either way.
    """
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def read_image(path: Path) -> np.ndarray:
    """BGR uint8 image. imdecode instead of imread, which fails on non-ASCII paths on Windows."""
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode {path}")
    return image
