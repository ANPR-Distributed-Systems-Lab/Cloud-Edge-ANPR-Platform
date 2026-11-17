"""Reporting an OCR evaluation to the run's W&B run (see anpr_ml.tracking).

Logged: the final metrics in the run summary, the coverage curve, exact match by plate width and, with
wandb.log_images, a table with one row per val crop (crop, kind, true text, read text, declined,
confidence, P(readable), width), which can be sorted and filtered in the W&B UI. Only val crops are sent;
the val frames are already in the detector's project, so the crops show nothing new.
"""
from typing import TYPE_CHECKING

import cv2

from .. import tracking
from ..common.preprocess import read_image
from .config import run_config
from .metrics import SUMMARY_KEYS

if TYPE_CHECKING:
    from .evaluate import Evaluation

VIEW_SCALE = 3  # crops are 128x64; enlarged without smoothing so the pixels the model saw stay visible


def crops_table(wandb, evaluation: "Evaluation"):
    columns = ["crop", "kind", "true", "read", "correct", "declined", "conf", "readable", "weakest_slot",
               "width_px", "frame", "session"]
    table = wandb.Table(columns=columns)
    for crop, reading in zip(evaluation.crops, evaluation.readings):
        image = cv2.cvtColor(read_image(crop["path"]), cv2.COLOR_BGR2RGB)
        image = cv2.resize(image, None, fx=VIEW_SCALE, fy=VIEW_SCALE, interpolation=cv2.INTER_NEAREST)
        table.add_data(wandb.Image(image, file_type="png"), crop["kind"], crop["text"], reading.text,
                       reading.text == crop["text"], reading.declined, reading.conf, reading.readable,
                       reading.weakest_slot + 1, crop["width_px"], crop["frame"], crop["session"])
    return table


def log_evaluation(wandb, evaluation: "Evaluation", images: bool) -> None:
    res = evaluation.result
    summary = {
        **{f"final/{k}": res[k] for k in SUMMARY_KEYS},
        **{f"final/exact_width_{b['width_px']}": b["exact"] for b in res["by_width"]},
    }
    wandb.run.summary.update(tracking.scalars(summary))
    coverage = [c for c in res["coverage"] if c["n_kept"]]
    series = {"share kept": [c["kept"] for c in coverage], "exact among kept": [c["exact"] for c in coverage]}
    if res["reject_crops"]:
        series["share of rejects sent"] = [c["rejects_sent"] / res["reject_crops"] for c in coverage]
    width_table = wandb.Table(data=[[b["width_px"], b["exact"]] for b in res["by_width"]],
                              columns=["width_px", "exact"])
    wandb.log({
        "eval/coverage": wandb.plot.line_series(
            xs=[c["conf"] for c in coverage], ys=list(series.values()), keys=list(series),
            title="val: reads kept vs confidence threshold", xname="confidence threshold"),
        "eval/exact_by_width": wandb.plot.bar(
            width_table, "width_px", "exact", title="val: exact match by plate width on the original (px)"),
    })
    if images:
        wandb.log({"eval/crops": crops_table(wandb, evaluation)})


def report(cfg: dict, evaluation: "Evaluation") -> None:
    """Sends an evaluation to the run's W&B run when tracking is enabled. A baseline run, which has no
    training, gets its W&B run here; the config is only passed when the W&B run is created."""
    if not cfg["wandb"]["enabled"]:
        return
    config = None if tracking.is_tracked(evaluation.run) else run_config(cfg)
    wandb = tracking.start(cfg, evaluation.run, config)
    try:
        log_evaluation(wandb, evaluation, images=cfg["wandb"].get("log_images", False))
    finally:
        wandb.finish()
