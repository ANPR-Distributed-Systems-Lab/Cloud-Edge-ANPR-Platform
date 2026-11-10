"""Image preprocessing that must give identical pixels in dataset preparation and on the edge node."""
from pathlib import Path

import cv2
import numpy as np

# (width, height). OPEN in ML_ASSUMPTIONS: 1280x960 is the v0 choice, final after the Pi benchmark.
DETECTOR_SIZE = (1280, 960)
# (width, height): the input of the pretrained fast-plate-ocr CCT models, which a fine-tuned model keeps.
OCR_SIZE = (128, 64)
# The quad is widened by this share of its size about its center: the pretrained OCR saw plates with some
# surroundings and reads tight crops worse (zero-shot on val_001: 0.918 tight, 0.986 with 8 %).
OCR_MARGIN = 0.08


def resize_for_detector(image: np.ndarray, size: tuple[int, int] = DETECTOR_SIZE) -> np.ndarray:
    """Full frame -> detector input with INTER_AREA, the reference filter the Pi has to reproduce.

    The 4056x3040 frame and the 4:3 detector sizes differ in aspect by under 0.1 %, so the frame is stretched
    to the exact size rather than letterboxed; normalized labels stay valid either way.
    """
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def rectify_plate(
    frame: np.ndarray, corners_px: np.ndarray, size: tuple[int, int] = OCR_SIZE, margin: float = OCR_MARGIN
) -> np.ndarray:
    """Perspective-corrected crop of one plate from the full-resolution frame: the OCR input.

    corners_px are TL, TR, BR, BL in pixels of `frame`. warpPerspective only interpolates bilinearly, which
    aliases when a large plate shrinks to 128 px, so the quad is first warped at about its own resolution
    and then downscaled with INTER_AREA. The Pi has to reproduce these exact steps.
    """
    c = np.asarray(corners_px, dtype=np.float32)
    center = c.mean(axis=0)
    c = center + (c - center) * (1 + margin)
    native_w = max(np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[2] - c[3]))
    native_h = max(np.linalg.norm(c[3] - c[0]), np.linalg.norm(c[2] - c[1]))
    w, h = max(size[0], int(np.ceil(native_w))), max(size[1], int(np.ceil(native_h)))
    target = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    warped = cv2.warpPerspective(frame, cv2.getPerspectiveTransform(c, target), (w, h),
                                 flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return warped if (w, h) == tuple(size) else cv2.resize(warped, size, interpolation=cv2.INTER_AREA)


def read_image(path: Path) -> np.ndarray:
    """BGR uint8 image. Decodes from bytes because cv2.imread fails on non-ASCII paths on Windows."""
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode {path}")
    return image
