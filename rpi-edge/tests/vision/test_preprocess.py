"""The edge preprocessing must give the pixels of ml-models. The inputs and the golden SHA-256 prefixes are those of
ml-models/tests/test_common.py (opencv 5.0.0); if one changes there, it changes here, and the models are rechecked.

resize_for_detector() is bit-identical on x86 and on the Pi's ARM CPU. rectify_plate() is bit-identical on x86 only:
OpenCV's warpPerspective and resize take other SIMD paths on ARM, which moves a few values by 1 (measured on a Pi 5:
at most 0.05 % of a crop's values, never more than 1). So on ARM the crop is compared with the x86 reference crops
in tests/vision/golden/ (synthetic noise, the crops whose hashes are the golden ones) within that tolerance.
"""
import hashlib
import platform
from pathlib import Path

import cv2
import numpy as np
import pytest

from detection.vision.preprocess import OCR_SIZE, rectify_plate, resize_for_detector

GOLDEN_RESIZE = "2b2164cc869b5e20"
GOLDEN_RECTIFY = {"large": "5a6c6056a22f957c", "small": "c37da4690b8a6aa8"}
QUADS = {"large": [[200, 300], [560, 280], [570, 370], [205, 395]],  # downscaled to the OCR size
         "small": [[100, 100], [160, 104], [158, 118], [99, 115]]}  # upscaled to it
REFERENCE_DIR = Path(__file__).parent / "golden"
X86 = platform.machine().lower() in ("x86_64", "amd64")
ARM_MAX_DIFF = 1
ARM_MAX_SHARE = 0.001  # of a crop's values


def sha16(array: np.ndarray) -> str:
    return hashlib.sha256(array.tobytes()).hexdigest()[:16]


def test_resize_for_detector_reference_pixels():
    frame = np.random.default_rng(7).integers(0, 256, (3040, 4056, 3), dtype=np.uint8)
    out = resize_for_detector(frame, (1280, 960))
    assert out.shape == (960, 1280, 3) and out.dtype == np.uint8
    assert sha16(out) == GOLDEN_RESIZE  # on every CPU


@pytest.mark.parametrize("name", QUADS)
def test_rectify_plate_reference_pixels(name):
    frame = np.random.default_rng(11).integers(0, 256, (600, 800, 3), dtype=np.uint8)
    out = rectify_plate(frame, np.array(QUADS[name], float))
    assert out.shape == (OCR_SIZE[1], OCR_SIZE[0], 3) and out.dtype == np.uint8
    reference = np.load(REFERENCE_DIR / f"rectify_{name}.npy")
    assert sha16(reference) == GOLDEN_RECTIFY[name]  # the stored crop is the golden one of ml-models
    if X86:
        assert sha16(out) == GOLDEN_RECTIFY[name]
    else:
        diff = np.abs(out.astype(int) - reference.astype(int))
        assert diff.max() <= ARM_MAX_DIFF and (diff > 0).mean() <= ARM_MAX_SHARE


def test_rectify_plate_maps_the_quad_onto_the_crop():
    frame = np.zeros((300, 400, 3), np.uint8)
    quad = np.array([[100, 120], [300, 100], [310, 160], [105, 175]], float)
    cv2.fillPoly(frame, [quad.astype(np.int32)], (255, 255, 255))
    tight = rectify_plate(frame, quad, margin=0.0)
    assert tight[8:-8, 8:-8].min() > 200  # the plate fills the crop
