"""The plate OCR: fast-plate-ocr's cct-s-v2-global fine-tuned in ml-models (OCR v3), run with ONNX Runtime.

The model takes one 128x64 RGB uint8 crop (batch size 1) and has two outputs, both already probabilities:
  plate   10 slots x alphabet: the character in each slot, the pad character after the end of the text
  region  the readability head, classes listed in plate_config.yaml (`plate_regions`: readable, unreadable)
Decoding follows fast-plate-ocr (argmax per slot, trailing pad characters stripped) and ml-models'
anpr_ml.ocr.predict (confidence = the weakest slot, padding slots included).
"""
from dataclasses import dataclass

import cv2
import numpy as np
import yaml

from detection.vision import onnx

READABLE = "readable"


@dataclass(frozen=True)
class PlateConfig:
    alphabet: str
    pad_char: str
    slots: int
    size: tuple[int, int]  # (width, height) of the input crop
    regions: tuple[str, ...]

    @classmethod
    def load(cls, path: str) -> "PlateConfig":
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if raw.get("image_color_mode") != "rgb" or raw.get("keep_aspect_ratio"):
            raise ValueError("the OCR model must take RGB crops stretched to its input size")
        return cls(raw["alphabet"], raw["pad_char"], int(raw["max_plate_slots"]),
                   (int(raw["img_width"]), int(raw["img_height"])), tuple(raw.get("plate_regions") or ()))


@dataclass(frozen=True)
class Reading:
    text: str  # empty when the model reads no characters
    confidence: float  # probability of the weakest slot
    readable: float | None  # P(readable) of the readability head, None for a model without it


def decode(plate_probs: np.ndarray, region_probs: np.ndarray | None, config: PlateConfig) -> Reading:
    """One crop's outputs (slots x alphabet, and the region probabilities) -> Reading."""
    indices = plate_probs.argmax(axis=-1)
    text = "".join(config.alphabet[i] for i in indices).rstrip(config.pad_char)
    confidence = float(plate_probs.max(axis=-1).min())
    readable = None
    if region_probs is not None and READABLE in config.regions:
        readable = float(region_probs[config.regions.index(READABLE)])
    return Reading(text, confidence, readable)


class Reader:
    def __init__(self, model_path: str, plate_config_path: str) -> None:
        self.config = PlateConfig.load(plate_config_path)
        self.session = onnx.session(model_path)
        self.input_name = self.session.get_inputs()[0].name
        self.outputs = [o.name for o in self.session.get_outputs()]  # "plate", optionally "region"

    def read(self, crop_bgr: np.ndarray) -> Reading:
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        results = dict(zip(self.outputs, self.session.run(self.outputs, {self.input_name: rgb[None]}), strict=True))
        plate = results["plate"].reshape(self.config.slots, len(self.config.alphabet))
        region = results["region"][0] if "region" in results else None
        return decode(plate, region, self.config)
