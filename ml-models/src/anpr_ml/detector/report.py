"""Reporting a detector evaluation to the run's W&B run (see anpr_ml.tracking).

Logged: the final metrics in the run summary, the precision / recall / F1 curve, recall by plate width and,
with wandb.log_images, a table with one row per validation frame. The table columns (missed, false_pos,
max_corner_err_px, ...) can be sorted and filtered in the W&B UI; each row shows the frame at detector
resolution with labels and predictions drawn, plus toggleable box overlays.
"""
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .. import tracking
from ..common.geometry import quad_box
from ..common.labels import plate_width_px, session_of
from ..common.preprocess import read_image, resize_for_detector
from ..paths import BATCHES_DIR
from .metrics import frame_results
from .predict import Prediction

if TYPE_CHECKING:
    from .evaluate import Evaluation

GT, PRED, IGNORED = (0, 200, 0), (0, 0, 255), (160, 160, 160)  # BGR


def draw_frame(image: np.ndarray, record: dict, preds: list[Prediction], min_plate_px: float) -> np.ndarray:
    """RGB copy with labels green, ignore regions and demoted small plates gray, predictions red;
    corner 0 (TL) is marked with a dot."""
    out = image.copy()
    size = np.array([out.shape[1], out.shape[0]], dtype=float)

    def quad(corners, color, thickness=1):
        pts = np.round(np.asarray(corners) * size).astype(np.int32)
        cv2.polylines(out, [pts], True, color, thickness, cv2.LINE_AA)
        cv2.circle(out, tuple(int(v) for v in pts[0]), 3, color, -1, cv2.LINE_AA)

    for p in record["plates"]:
        quad(p["corners"], IGNORED if plate_width_px(p["corners"], record) < min_plate_px else GT, 2)
    for r in record["ignore"]:
        quad(r["corners"], IGNORED)
    for p in preds:
        quad(p.corners, PRED)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def box_overlays(record: dict, preds: list[Prediction], min_plate_px: float) -> dict:
    """W&B box overlays, toggled separately in the UI; coordinates are fractions of the image."""
    def box(b, caption, scores=None):
        x1, y1, x2, y2 = (float(v) for v in b)
        item = {"position": {"minX": x1, "minY": y1, "maxX": x2, "maxY": y2}, "class_id": 0, "box_caption": caption}
        if scores:
            item["scores"] = scores
        return item

    gt = []
    for p in record["plates"]:
        width = plate_width_px(p["corners"], record)
        if width >= min_plate_px:
            gt.append(box(quad_box(np.array(p["corners"])), f"{width:.0f}px"))
    pr = [box(p.box, f"{p.conf:.2f}", {"conf": float(p.conf)}) for p in preds]
    labels = {0: "plate"}
    return {"ground_truth": {"box_data": gt, "class_labels": labels},
            "predictions": {"box_data": pr, "class_labels": labels}}


def frames_table(wandb, records: list[dict], predictions: dict[str, list[Prediction]], conf: float,
                 size: tuple[int, int], min_plate_px: float):
    """One row per frame, at the operating threshold `conf`."""
    columns = ["image", "frame", "session", "plates", "detected", "missed", "false_pos",
               "max_corner_err_px", "min_plate_width_px", "max_conf"]
    table = wandb.Table(columns=columns)
    for r, res in zip(records, frame_results(records, predictions, min_plate_px, conf)):
        preds = [p for p in predictions.get(r["image"], []) if p.conf >= conf]
        frame = resize_for_detector(read_image(BATCHES_DIR / r["image"]), size)
        image = wandb.Image(draw_frame(frame, r, preds, min_plate_px), boxes=box_overlays(r, preds, min_plate_px),
                            file_type="jpg", caption=Path(r["image"]).name)
        table.add_data(
            image, Path(r["image"]).name, session_of(r["image"]), len(res.plates), len(res.hits),
            len(res.missed), len(res.false_positives),
            max((m.corner_error_px for m in res.hits), default=None),
            min(res.gt_widths, default=None), max((p.conf for p in preds), default=None),
        )
    return table


def log_evaluation(wandb, evaluation: "Evaluation", size: tuple[int, int], min_plate_px: float,
                   images: bool) -> None:
    res, ultra = evaluation.result, evaluation.ultralytics
    best, corner = res["best"], res["corner_error"]
    summary = {
        **{f"final/{k.replace(' ', '_')}": v for k, v in ultra.items()},
        **{f"final/{k}@best": best[k] for k in ("precision", "recall", "f1", "tp", "fp", "fn")},
        "final/best_conf": best["conf"],
        **{f"final/corner_{k}": v for k, v in corner.items()},
        **{f"final/recall_width_{b['width_px']}": b["recall"] for b in res["by_width"]},
    }
    wandb.run.summary.update(tracking.scalars(summary))

    curve = res["curve"]
    wandb.log({
        "eval/pr_curve": wandb.plot.line_series(
            xs=[c["conf"] for c in curve],
            ys=[[c[k] for c in curve] for k in ("precision", "recall", "f1")],
            keys=["precision", "recall", "f1"], title="val: P / R / F1 vs confidence", xname="confidence"),
        "eval/recall_by_width": wandb.plot.bar(
            wandb.Table(data=[[b["width_px"], b["recall"]] for b in res["by_width"]], columns=["width_px", "recall"]),
            "width_px", "recall", title="val: recall by plate width on the original (px)"),
    })
    if images:
        wandb.log({"eval/frames": frames_table(wandb, evaluation.records, evaluation.predictions,
                                               best["conf"], size, min_plate_px)})


def report(cfg: dict, evaluation: "Evaluation") -> None:
    """Sends an evaluation to the run's W&B run when tracking is enabled in the config. A run trained before
    tracking was on gets a new W&B run with its epoch history replayed from results.csv."""
    if not cfg["wandb"]["enabled"]:
        return
    run = evaluation.run
    new = not tracking.is_tracked(run)
    wandb = tracking.start(cfg, run)
    try:
        if new:
            tracking.log_history(wandb, run)
        log_evaluation(wandb, evaluation, cfg["dataset"]["size"], cfg["dataset"]["min_plate_px"],
                       images=cfg["wandb"].get("log_images", False))
    finally:
        wandb.finish()
