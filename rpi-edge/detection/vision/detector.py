"""The plate detector: YOLO11n-pose exported to ONNX with NMS inside, run with ONNX Runtime.

The model takes the frame resized to its input size (RGB, 0..1, NCHW) and returns up to max_det rows of
[x1, y1, x2, y2, confidence, class, then x, y, visibility for each corner TL, TR, BR, BL], in pixels of the
model input. YOLO26 end-to-end models return the same layout, so they can replace it without code changes.
"""
from dataclasses import dataclass

import cv2
import numpy as np

from detection.vision import onnx
from detection.vision.preprocess import resize_for_detector


@dataclass(frozen=True)
class Detection:
    confidence: float
    corners: np.ndarray  # 4 x 2, TL TR BR BL, in pixels of the original frame


def parse_output(rows: np.ndarray, input_size: tuple[int, int], frame_size: tuple[int, int],
                 min_confidence: float) -> list[Detection]:
    """Rows of the model output -> detections at or above min_confidence, corners scaled to the frame.

    input_size and frame_size are (width, height).
    """
    scale = np.array([frame_size[0] / input_size[0], frame_size[1] / input_size[1]])
    detections = []
    for row in rows:
        confidence = float(row[4])
        if confidence < min_confidence:
            continue
        corners = row[6:18].reshape(4, 3)[:, :2] * scale
        detections.append(Detection(confidence, corners))
    return detections


class Detector:
    def __init__(self, model_path: str) -> None:
        self.session = onnx.session(model_path)
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        _, _, height, width = model_input.shape  # fixed at export
        self.input_size = (width, height)

    def detect(self, frame_bgr: np.ndarray, min_confidence: float) -> list[Detection]:
        small = resize_for_detector(frame_bgr, self.input_size)
        blob = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        rows = self.session.run(None, {self.input_name: blob})[0][0]
        frame_size = (frame_bgr.shape[1], frame_bgr.shape[0])
        return parse_output(rows, self.input_size, frame_size, min_confidence)
