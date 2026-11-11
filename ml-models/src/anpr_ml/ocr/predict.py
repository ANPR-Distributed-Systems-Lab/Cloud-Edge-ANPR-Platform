"""Running an exported OCR model (model.onnx) with ONNX Runtime on the CPU, as the edge node will."""
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import ONNX, PLATE_CONFIG
from .readability import READABLE_THRESHOLD, is_readability, readable_prob


@dataclass
class Reading:
    """The text read from one crop.

    slot_probs: the probability of the chosen character in each of the model's fixed slots, padding slots
    included: the model has to be sure where the plate ends, too. conf is the weakest slot, since a plate is
    only as right as its least certain character.
    readable: P(readable) from a model with the readability head (anpr_ml.ocr.readability), else None.
    """
    text: str
    slot_probs: np.ndarray
    readable: float | None = None

    @property
    def conf(self) -> float:
        return float(np.min(self.slot_probs))

    @property
    def weakest_slot(self) -> int:
        return int(np.argmin(self.slot_probs))

    @property
    def declined(self) -> bool:
        """The OCR declines to read the crop: no text (an OCR trained on rejects as empty texts), or the
        readability head finds it more likely unreadable. A declined reading is never sent."""
        return not self.text or (self.readable is not None and self.readable < READABLE_THRESHOLD)


class Reader:
    """The OCR of one finished run. Crops are BGR at the OCR input size, as rectify_plate() returns them."""

    def __init__(self, run: Path):
        from fast_plate_ocr import LicensePlateRecognizer

        self.model = LicensePlateRecognizer(onnx_model_path=run / ONNX, plate_config_path=run / PLATE_CONFIG,
                                            device="cpu")
        self.readability = is_readability(self.model.config.plate_regions)

    def read(self, crop_bgr: np.ndarray) -> Reading:
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        pred = self.model.run(rgb[None], return_confidence=True)[0]  # the export has batch size 1
        readable = readable_prob(pred.region, pred.region_prob) if self.readability else None
        return Reading(pred.plate, np.asarray(pred.char_probs, dtype=float), readable)

    def read_all(self, crops: list[np.ndarray]) -> list[Reading]:
        return [self.read(c) for c in crops]
