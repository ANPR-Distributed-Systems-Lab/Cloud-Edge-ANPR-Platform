"""Image preprocessing that must give identical pixels in dataset preparation and on the edge node."""
from pathlib import Path

import cv2
import numpy as np

# (width, height). OPEN in ML_ASSUMPTIONS: 1280x960 is the v0 choice, final after the Pi benchmark.
DETECTOR_SIZE = (1280, 960)


def resize_for_detector(image: np.ndarray, size: tuple[int, int] = DETECTOR_SIZE) -> np.ndarray:
    """Full frame -> detector input with INTER_AREA, the reference filter the Pi has to reproduce.

    The 4056x3040 frame and the 4:3 detector sizes differ in aspect by under 0.1 %, so the frame is stretched
    to the exact size rather than letterboxed; normalized labels stay valid either way.
    """
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def read_image(path: Path) -> np.ndarray:
    """BGR uint8 image. Decodes from bytes because cv2.imread fails on non-ASCII paths on Windows."""
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode {path}")
    return image
