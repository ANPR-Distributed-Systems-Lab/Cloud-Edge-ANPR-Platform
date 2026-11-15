"""Image preprocessing that must give identical pixels in dataset preparation and on the edge node."""
from pathlib import Path

import cv2
import numpy as np

# (width, height): the full-frame input of detectors v0 to v2 and the default of anpr-yolo-dataset. A detector
# config may crop a band of rows first (dataset.crop, from v3 on).
DETECTOR_SIZE = (1280, 960)
# (width, height): the input of the pretrained fast-plate-ocr CCT models, which a fine-tuned model keeps.
OCR_SIZE = (128, 64)
# The quad is widened by this share of its size about its center: the pretrained OCR saw plates with some
# surroundings and reads tight crops worse (zero-shot on val_001: 0.918 tight, 0.986 with 8 %).
OCR_MARGIN = 0.08


def resize_for_detector(image: np.ndarray, size: tuple[int, int] = DETECTOR_SIZE) -> np.ndarray:
    """Full frame -> detector input with INTER_AREA, the reference filter the Pi has to reproduce.

    The 4056x3040 frame (or its crop band) and the detector size differ in aspect by under 0.2 %, so the image
    is stretched to the exact size rather than letterboxed; normalized labels stay valid either way.
    """
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def crop_rows(frame_height: int, crop: tuple[float, float] | None) -> tuple[int, int]:
    """Rows [y0, y1) of the frame the detector sees. crop is (top, bottom) as shares of the frame height, the
    band where plates appear for a fixed camera mount; None is the whole frame."""
    if crop is None:
        return 0, frame_height
    return round(crop[0] * frame_height), round(crop[1] * frame_height)


def detector_input(image: np.ndarray, size: tuple[int, int], crop: tuple[float, float] | None = None) -> np.ndarray:
    """Full frame -> detector input: the crop's rows at full width, then resize_for_detector()."""
    y0, y1 = crop_rows(image.shape[0], crop)
    return resize_for_detector(image[y0:y1], size)


def to_crop(points: np.ndarray, frame_height: int, crop: tuple[float, float] | None) -> np.ndarray:
    """Points (..., 2) in fractions of the frame -> fractions of the detector input."""
    y0, y1 = crop_rows(frame_height, crop)
    out = np.array(points, dtype=float)
    out[..., 1] = (out[..., 1] * frame_height - y0) / (y1 - y0)
    return out


def from_crop(points: np.ndarray, frame_height: int, crop: tuple[float, float] | None) -> np.ndarray:
    """Points (..., 2) in fractions of the detector input -> fractions of the frame; the inverse of to_crop()."""
    y0, y1 = crop_rows(frame_height, crop)
    out = np.array(points, dtype=float)
    out[..., 1] = (y0 + out[..., 1] * (y1 - y0)) / frame_height
    return out


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
