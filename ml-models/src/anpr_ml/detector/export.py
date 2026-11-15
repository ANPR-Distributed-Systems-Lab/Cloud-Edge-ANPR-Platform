"""anpr-export-detector: exports a finished detector run to ONNX for the edge node and checks the export.

    uv run anpr-export-detector --config configs/detector_v2.yaml

Writes runs/detector/<run>/model.onnx from best.pt: input `images` (1, 3, height, width), RGB scaled to 0..1, at
the run's dataset size; NMS inside the model, output (1, MAX_DET, 18) with rows [x1, y1, x2, y2, confidence, class,
then x, y, visibility of the corners TL, TR, BR, BL] in pixels of the model input. That is what
rpi-edge/detection/vision/detector.py reads.

A detector with a crop band carries it in the model's metadata, key `crop`, value "top,bottom" (shares of the frame
height, as in common.preprocess.crop_rows()): the device crops those rows before resizing and maps the output
back. A model without the key sees the whole frame. The check then runs a sample of val frames through both the export
(ONNX Runtime, as on the Pi) and the PyTorch weights (Ultralytics) and refuses an export whose detections differ.

A run's model.onnx is never overwritten; `anpr-publish-model detector <run>` uploads it.
"""
import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..common.preprocess import detector_input, read_image
from ..paths import BATCHES_DIR, CONFIGS_DIR
from .config import load_config, run_dir, run_state
from .evaluate import val_records

# NMS settings baked into the export. CONF_FLOOR is below any operating threshold: the device applies its own
# detectorMinConfidence from its configuration.
CONF_FLOOR = 0.1
IOU = 0.7
MAX_DET = 100
CHECK_CONF = 0.4  # the operating point of the detectors so far (best F1 on val)
MAX_CORNER_DIFF_PX = 1.0  # at detector scale; ONNX Runtime and PyTorch differ by float rounding only
CHECK_FRAMES = 20


@dataclass(frozen=True)
class FrameCheck:
    onnx_count: int
    torch_count: int
    max_corner_diff_px: float  # 0 when either side found nothing

    @property
    def matches(self) -> bool:
        return self.onnx_count == self.torch_count and self.max_corner_diff_px <= MAX_CORNER_DIFF_PX


def compare_frame(onnx_rows: np.ndarray, torch_corners: np.ndarray, torch_confs: np.ndarray, conf: float,
                  size: tuple[int, int] | None = None) -> FrameCheck:
    """onnx_rows: (MAX_DET, 18) export output; torch_corners: (n, 4, 2) and torch_confs: (n,) from Ultralytics.

    Each ONNX detection is matched to the nearest PyTorch one by its corners. Ultralytics clips corners to the
    input image (width, height) and the export does not, so with `size` the export's corners are clipped the same
    way: a plate cut off by the frame edge would otherwise differ by the part outside the image.
    """
    rows = onnx_rows[onnx_rows[:, 4] >= conf]
    torch_corners = torch_corners[torch_confs >= conf]
    corners = rows[:, 6:18].reshape(-1, 4, 3)[:, :, :2]
    if size is not None:
        corners = np.clip(corners, 0, np.array(size, dtype=float))
    diff = 0.0
    if len(corners) and len(torch_corners):
        distances = np.abs(corners[:, None] - torch_corners[None]).max(axis=(2, 3))  # (onnx, torch)
        diff = float(distances.min(axis=1).max())
    return FrameCheck(len(rows), len(torch_corners), diff)


CROP_KEY = "crop"


def export(weights: Path, size: tuple[int, int], out: Path, crop: tuple[float, float] | None = None) -> Path:
    """Ultralytics' ONNX export with NMS inside, plus the crop in the metadata; written to `out` only when
    complete."""
    import onnx
    from ultralytics import YOLO

    width, height = size
    exported = Path(YOLO(str(weights)).export(format="onnx", imgsz=[height, width], nms=True, conf=CONF_FLOOR,
                                              iou=IOU, max_det=MAX_DET, device="cpu"))
    if crop is not None:
        model = onnx.load(str(exported))
        onnx.helper.set_model_props(model, {**{p.key: p.value for p in model.metadata_props},
                                            CROP_KEY: f"{crop[0]},{crop[1]}"})
        onnx.save(model, str(exported))
    exported.replace(out)
    return out


def model_crop(session) -> tuple[float, float] | None:
    """The crop an exported model declares, read the way the device reads it."""
    value = session.get_modelmeta().custom_metadata_map.get(CROP_KEY)
    return tuple(float(v) for v in value.split(",")) if value else None


def check(model: Path, weights: Path, records: list[dict], size: tuple[int, int]) -> list[FrameCheck]:
    """The export and the weights on the same frames, preprocessed as on the Pi (detector_input() with the
    crop the export declares)."""
    import cv2
    import onnxruntime as ort
    from ultralytics import YOLO

    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    crop = model_crop(session)
    torch_model = YOLO(str(weights))
    checks = []
    for record in records:
        small = detector_input(read_image(BATCHES_DIR / record["image"]), size, crop)
        blob = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        rows = session.run(None, {name: blob})[0][0]
        result = torch_model.predict(small, imgsz=max(size), conf=CHECK_CONF, device="cpu", verbose=False)[0]
        corners = result.keypoints.xy.cpu().numpy() if result.keypoints is not None else np.zeros((0, 4, 2))
        checks.append(compare_frame(rows, corners, result.boxes.conf.cpu().numpy(), CHECK_CONF, size))
    return checks


def sample(records: list[dict], count: int) -> list[dict]:
    """Evenly spread frames, so the check sees several sessions; frames with plates first."""
    with_plates = [r for r in records if r["plates"]]
    step = max(1, len(with_plates) // count)
    return with_plates[::step][:count]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=CONFIGS_DIR / "detector_v2.yaml")
    parser.add_argument("--frames", type=int, default=CHECK_FRAMES, help="val frames to compare")
    args = parser.parse_args()

    cfg = load_config(args.config)
    run = run_dir(cfg)
    if run_state(run) != "finished":
        raise SystemExit(f"{run} is not a finished run")
    out = run / "model.onnx"
    if out.exists():
        raise SystemExit(f"{out} exists; a run's export is never overwritten")
    weights, size, crop = run / "weights" / "best.pt", cfg["dataset"]["size"], cfg["dataset"]["crop"]

    partial = export(weights, size, run / "model.onnx.partial", crop)
    checks = check(partial, weights, sample(val_records(cfg), args.frames), size)
    worst = max((c.max_corner_diff_px for c in checks), default=0.0)
    mismatched = sum(not c.matches for c in checks)
    print(f"{len(checks)} val frames: {sum(c.onnx_count for c in checks)} detections (ONNX), "
          f"{sum(c.torch_count for c in checks)} (PyTorch) at conf {CHECK_CONF}; "
          f"largest corner difference {worst:.3f} px at detector scale; {mismatched} frames differ")
    import onnxruntime as ort

    declared = model_crop(ort.InferenceSession(str(partial), providers=["CPUExecutionProvider"]))
    if mismatched or declared != crop:
        partial.unlink()
        raise SystemExit("the export does not match the weights or its crop; nothing was written")
    partial.replace(out)
    print(f"written {out}")


if __name__ == "__main__":
    main()
