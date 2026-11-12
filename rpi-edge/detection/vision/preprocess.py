"""Image preprocessing that must give the same pixels as the training data.

A copy of resize_for_detector() and rectify_plate() from ml-models (src/anpr_ml/common/preprocess.py).
tests/vision/test_preprocess.py holds the same golden checksums as ml-models/tests/test_common.py, so a change on
either side that alters the pixels fails a test. opencv is pinned to the version the checksums were made with.
"""
import cv2
import numpy as np

OCR_SIZE = (128, 64)  # (width, height): the input of the fast-plate-ocr CCT models
OCR_MARGIN = 0.08  # the quad is widened by this share about its center, as in the OCR training crops


def resize_for_detector(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Full frame -> detector input (width, height). Stretched, not letterboxed, as in training."""
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def rectify_plate(
    frame: np.ndarray, corners_px: np.ndarray, size: tuple[int, int] = OCR_SIZE, margin: float = OCR_MARGIN
) -> np.ndarray:
    """Perspective-corrected crop of one plate from the full-resolution frame: the OCR input.

    corners_px are TL, TR, BR, BL in pixels of `frame`. The quad is warped at about its own resolution and
    then downscaled with INTER_AREA, because warpPerspective alone aliases when a large plate shrinks.
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
