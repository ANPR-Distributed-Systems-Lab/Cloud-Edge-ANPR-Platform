"""The plate detector: YOLO11n-pose exported to ONNX with NMS inside, run with ONNX Runtime.

The model takes the frame resized to its input size (RGB, 0..1, NCHW) and returns up to max_det rows of
[x1, y1, x2, y2, confidence, class, then x, y, visibility for each corner TL, TR, BR, BL], in pixels of the
model input. A model trained on a band of the frame (a fixed camera mount, detector v3 on) declares it in its
metadata, key `crop` = "top,bottom" as shares of the frame height: only those rows go in, at full width, and the
corners are mapped back to the whole frame. A model without the key sees the whole frame.
"""
from dataclasses import dataclass

import cv2
import numpy as np

from detection.vision import onnx
from detection.vision.preprocess import crop_rows, detector_input


@dataclass(frozen=True)
class Detection:
    confidence: float
    corners: np.ndarray  # 4 x 2, TL TR BR BL, in pixels of the original frame


def parse_crop(value: str | None) -> tuple[float, float] | None:
    """The `crop` metadata of a model, "top,bottom", as shares of the frame height; None for the whole frame."""
    if not value:
        return None
    try:
        top, bottom = (float(part) for part in value.split(","))
    except ValueError:
        raise ValueError(f"the model's crop is not 'top,bottom': {value!r}") from None
    if not 0.0 <= top < bottom <= 1.0:
        raise ValueError(f"the model's crop is not a band inside the frame: {value!r}")
    return top, bottom


def parse_output(rows: np.ndarray, input_size: tuple[int, int], frame_size: tuple[int, int],
                 min_confidence: float, crop: tuple[float, float] | None = None) -> list[Detection]:
    """Rows of the model output -> detections at or above min_confidence, corners mapped to the frame.

    input_size and frame_size are (width, height); crop is the band the model saw. The NMS of the export already
    drops rows below 0.1 (CONF_FLOOR in ml-models), so a lower min_confidence changes nothing. Corners outside the
    input (a plate cut off by the edge) are not clipped: the send rule drops plates near the edge.
    """
    y0, y1 = crop_rows(frame_size[1], crop)
    scale = np.array([frame_size[0] / input_size[0], (y1 - y0) / input_size[1]])
    offset = np.array([0.0, y0])
    detections = []
    for row in rows:
        confidence = float(row[4])
        if confidence < min_confidence:
            continue
        corners = row[6:18].reshape(4, 3)[:, :2] * scale + offset
        detections.append(Detection(confidence, corners))
    return detections


class Detector:
    def __init__(self, model_path: str) -> None:
        self.session = onnx.session(model_path)
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        _, _, height, width = model_input.shape  # fixed at export
        self.input_size = (width, height)
        self.crop = parse_crop(self.session.get_modelmeta().custom_metadata_map.get("crop"))

    def detect(self, frame_bgr: np.ndarray, min_confidence: float) -> list[Detection]:
        small = detector_input(frame_bgr, self.input_size, self.crop)
        blob = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        rows = self.session.run(None, {self.input_name: blob})[0][0]
        frame_size = (frame_bgr.shape[1], frame_bgr.shape[0])
        return parse_output(rows, self.input_size, frame_size, min_confidence, self.crop)
