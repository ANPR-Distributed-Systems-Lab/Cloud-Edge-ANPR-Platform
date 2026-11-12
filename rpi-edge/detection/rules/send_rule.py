"""Which detections become events (DETECTION.md, "Send rule"). Thresholds come from settings.ml.

  1. Geometry, before the OCR: the plate is wide enough and fully inside the frame. Narrower plates are not
     read reliably, and a plate cut by the frame edge gives a wrong crop.
  2. Per frame, after the OCR: some text, the Polish format, the OCR confidence and P(readable).
  3. Per plate: the same text is not sent again within plate_cooldown_seconds, so one passing car is one event.
"""
import numpy as np

from detection.contract.configuration import MlConfiguration
from detection.rules.plates import is_polish_plate
from detection.vision.ocr import Reading

DEGENERATE_TURN_PX2 = 1.0  # a turn with a smaller cross product is a straight line or a fold


def plate_width(corners: np.ndarray) -> float:
    """Mean length of the top and bottom edges, as in ml-models (anpr_ml.common.geometry)."""
    return float((np.linalg.norm(corners[1] - corners[0]) + np.linalg.norm(corners[2] - corners[3])) / 2)


def is_clockwise_convex(corners: np.ndarray) -> bool:
    """The rule of the ingest Lambda: with image y growing downwards, every turn TL->TR->BR->BL has a positive
    cross product. Checked here because one invalid detection makes the cloud reject the whole batch."""
    for i in range(4):
        a, b, c = corners[i], corners[(i + 1) % 4], corners[(i + 2) % 4]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) <= DEGENERATE_TURN_PX2:
            return False
    return True


def geometry_rejection(corners: np.ndarray, frame_size: tuple[int, int], ml: MlConfiguration) -> str | None:
    """Why the plate is not worth reading, or None. frame_size is (width, height)."""
    if not is_clockwise_convex(corners):
        return "bad_corners"
    if plate_width(corners) < ml.min_plate_width_px:
        return "too_small"
    margin = ml.min_edge_margin_px
    width, height = frame_size
    xs, ys = corners[:, 0], corners[:, 1]
    if xs.min() < margin or ys.min() < margin or xs.max() > width - 1 - margin or ys.max() > height - 1 - margin:
        return "near_edge"
    return None


def reading_rejection(reading: Reading, ml: MlConfiguration) -> str | None:
    """Why the reading is not worth sending, or None."""
    if not reading.text:
        return "no_text"
    if reading.readable is not None and reading.readable < ml.readable_min_probability:
        return "unreadable"
    if not is_polish_plate(reading.text):
        return "bad_format"
    if reading.confidence < ml.ocr_min_confidence:
        return "low_confidence"
    return None


class Cooldown:
    """Remembers when each plate was last accepted. Plate texts are kept in memory only."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def accept(self, plate: str, now: float, seconds: float) -> bool:
        """True (and remembered) when the plate was not accepted within the last `seconds`."""
        self._last = {p: t for p, t in self._last.items() if now - t < seconds}
        if plate in self._last:
            return False
        self._last[plate] = now
        return True
