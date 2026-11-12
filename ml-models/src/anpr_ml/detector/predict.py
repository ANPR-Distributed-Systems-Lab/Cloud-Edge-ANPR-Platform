"""Running a trained detector the way the edge node will: original frame -> resize_for_detector() -> model."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..common.geometry import quad_box
from ..common.preprocess import read_image, resize_for_detector
from ..paths import BATCHES_DIR


@dataclass
class Prediction:
    """One detected plate, in fractions of the frame.

    corners: the 4 keypoints (TL, TR, BR, BL) from the pose head; they drive the perspective crop for OCR.
    box: the axis-aligned box (x1, y1, x2, y2) from the detection head; it decides what counts as a detection
    (NMS, matching to labels). Derived from the corners when not given.
    """
    conf: float
    corners: np.ndarray
    box: np.ndarray | None = None

    def __post_init__(self):
        self.corners = np.asarray(self.corners, dtype=float)
        self.box = quad_box(self.corners) if self.box is None else np.asarray(self.box, dtype=float)


def predict_records(
    weights: Path, records: list[dict], size: tuple[int, int], conf: float = 0.05, device=0
) -> dict[str, list[Prediction]]:
    """Predictions per labeled frame (keyed by its "image").

    The frames are not painted, so the model also sees the ignored plates; the evaluation drops detections
    there instead of counting them as false positives. A low `conf` keeps enough detections for the
    precision / recall curve; the operating threshold is chosen afterwards.
    """
    from ultralytics import YOLO

    model = YOLO(str(weights))
    out: dict[str, list[Prediction]] = {}
    for r in records:
        image = resize_for_detector(read_image(BATCHES_DIR / r["image"]), size)
        res = model.predict(image, imgsz=max(size), conf=conf, device=device, verbose=False)[0]
        if res.keypoints is None or len(res.boxes) == 0:
            out[r["image"]] = []
            continue
        kpts = res.keypoints.xyn.cpu().numpy()
        boxes = res.boxes.xyxyn.cpu().numpy()
        confs = res.boxes.conf.cpu().numpy()
        out[r["image"]] = [Prediction(float(c), k, b) for c, k, b in zip(confs, kpts, boxes)]
    return out
