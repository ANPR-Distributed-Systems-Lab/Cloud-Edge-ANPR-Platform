"""Experiment tracking in Weights & Biases.

Decision (2026-11-05): the W&B project is private and only its owner has access; it receives scalar metrics,
hyperparameters and, for visual review, validation frames with ground truth and predictions drawn on them.
Frames never go anywhere else (reports on GitHub stay without them). Ultralytics' built-in W&B integration
stays off: everything sent is chosen here.

One W&B run belongs to one training run: its id is kept in runs/detector/<run>/wandb_id.txt, so training,
resuming and evaluation all write to the same W&B run.
"""
import csv
import os
import secrets
from pathlib import Path

import cv2
import numpy as np

from .detector_eval import Prediction, match_image
from .geometry import plate_width_px, quad_box
from .paths import BATCHES_DIR, RUNS_DIR
from .preprocess import read_image, resize_for_detector

ID_FILE = "wandb_id.txt"
GT, PRED, IGNORED = (0, 200, 0), (0, 0, 255), (160, 160, 160)  # BGR


def _local_dirs() -> None:
    """W&B stages tables with images (as artifacts) and caches files under %LOCALAPPDATA% by default, on the
    nearly full C: drive. Keep all of it next to the runs on G: (gitignored)."""
    base = RUNS_DIR / "wandb-local"
    for var, sub in (("WANDB_DATA_DIR", "data"), ("WANDB_CACHE_DIR", "cache"), ("WANDB_ARTIFACT_DIR", "artifacts")):
        os.environ.setdefault(var, str(base / sub))


def start(cfg: dict, run: Path, config: dict | None = None):
    """Opens the W&B run tied to `run`, creating it on first use. Returns the wandb module."""
    _local_dirs()
    import wandb

    id_file = run / ID_FILE
    run_id = id_file.read_text().strip() if id_file.exists() else secrets.token_hex(4)  # W&B ids: [a-z0-9]
    w = cfg["wandb"]
    wandb.init(
        project=w["project"],
        entity=w.get("entity"),
        id=run_id,
        name=run.name,
        resume="allow",
        mode=w.get("mode", "online"),
        dir=str(RUNS_DIR),
        config=config,
    )
    id_file.write_text(run_id)
    return wandb


def is_tracked(run: Path) -> bool:
    return (run / ID_FILE).exists()


def _scalars(values: dict) -> dict:
    return {k: float(v) for k, v in values.items() if isinstance(v, (int, float, np.floating, np.integer))}


def training_callbacks(cfg: dict, manifest: dict) -> dict:
    """Ultralytics callbacks: hyperparameters at start, losses / metrics / learning rate every epoch."""
    state = {"wandb": None, "epoch": None}

    def on_train_start(trainer):
        args = {k: v for k, v in vars(trainer.args).items() if isinstance(v, (int, float, str, bool, type(None)))}
        state["wandb"] = start(cfg, Path(trainer.save_dir), {
            **args, "dataset": {**cfg["dataset"], "size": list(cfg["dataset"]["size"])},
            "dataset_counts": manifest.get("counts"),
        })

    def on_fit_epoch_end(trainer):
        # Ultralytics fires this once more after training for the final validation of best.pt; skip it.
        if state["wandb"] is None or trainer.epoch == state["epoch"]:
            return
        state["epoch"] = trainer.epoch
        values = {**trainer.label_loss_items(trainer.tloss, prefix="train"), **trainer.metrics, **trainer.lr}
        state["wandb"].log({**_scalars(values), "epoch": trainer.epoch + 1}, step=trainer.epoch + 1)

    def on_train_end(trainer):
        if state["wandb"] is not None:
            state["wandb"].finish()

    return {"on_train_start": on_train_start, "on_fit_epoch_end": on_fit_epoch_end, "on_train_end": on_train_end}


def log_history(wandb, run: Path) -> None:
    """Replays results.csv into W&B, for a run that was trained before tracking was on (detector v0)."""
    with open(run / "results.csv", newline="") as f:
        for row in csv.DictReader(f):
            row = {k.strip(): v for k, v in row.items()}
            epoch = int(float(row.pop("epoch")))
            wandb.log({**{k: float(v) for k, v in row.items() if v.strip()}, "epoch": epoch}, step=epoch)


def _draw(image: np.ndarray, record: dict, preds: list[Prediction], min_plate_px: float) -> np.ndarray:
    """Ground truth green, ignored regions and demoted small plates gray, predictions red; corner 0 (TL) larger."""
    out = image.copy()
    size = np.array([out.shape[1], out.shape[0]], dtype=float)
    orig = np.array([record["width"], record["height"]], dtype=float)

    def quad(corners, color, thickness=1):
        pts = np.round(np.asarray(corners) * size).astype(np.int32)
        cv2.polylines(out, [pts], True, color, thickness, cv2.LINE_AA)
        cv2.circle(out, tuple(int(v) for v in pts[0]), 3, color, -1, cv2.LINE_AA)

    for p in record["plates"]:
        small = plate_width_px(np.array(p["corners"]) * orig) < min_plate_px
        quad(p["corners"], IGNORED if small else GT, 2)
    for r in record["ignore"]:
        quad(r["corners"], IGNORED)
    for p in preds:
        quad(p.corners, PRED)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def _boxes(record: dict, preds: list[Prediction], min_plate_px: float) -> dict:
    """W&B box overlays (toggled in the UI); coordinates are fractions of the image."""
    orig = np.array([record["width"], record["height"]], dtype=float)

    def box(b, caption, scores=None):
        x1, y1, x2, y2 = (float(v) for v in b)
        item = {"position": {"minX": x1, "minY": y1, "maxX": x2, "maxY": y2}, "class_id": 0, "box_caption": caption}
        if scores:
            item["scores"] = scores
        return item

    gt = [box(quad_box(np.array(p["corners"])), f"{plate_width_px(np.array(p['corners']) * orig):.0f}px")
          for p in record["plates"] if plate_width_px(np.array(p["corners"]) * orig) >= min_plate_px]
    pr = [box(p.box, f"{p.conf:.2f}", {"conf": float(p.conf)}) for p in preds]
    labels = {0: "plate"}
    return {"ground_truth": {"box_data": gt, "class_labels": labels},
            "predictions": {"box_data": pr, "class_labels": labels}}


def frames_table(wandb, records: list[dict], predictions: dict[str, list[Prediction]], conf: float,
                 size: tuple[int, int], min_plate_px: float):
    """One row per validation frame at the given confidence; sort or filter the columns, click to see it."""
    columns = ["image", "frame", "session", "plates", "detected", "missed", "false_pos",
               "max_corner_err_px", "min_plate_width_px", "max_conf"]
    table = wandb.Table(columns=columns)
    for r in records:
        preds = [p for p in predictions.get(r["image"], []) if p.conf >= conf]
        m = match_image(r, preds, min_plate_px)
        hits = [x for x in m.matches if x.gt is not None]
        frame = resize_for_detector(read_image(BATCHES_DIR / r["image"]), size)
        image = wandb.Image(_draw(frame, r, preds, min_plate_px), boxes=_boxes(r, preds, min_plate_px),
                            file_type="jpg", caption=Path(r["image"]).name)
        table.add_data(
            image, Path(r["image"]).name, Path(r["image"]).name.split("__")[0], len(m.gt_widths), len(hits),
            len(m.gt_widths) - len(hits), sum(x.gt is None for x in m.matches),
            max((x.corner_error_px for x in hits), default=None),
            min(m.gt_widths, default=None), max((p.conf for p in preds), default=None),
        )
    return table


def log_evaluation(wandb, evaluation: dict, size: tuple[int, int], min_plate_px: float, images: bool) -> None:
    """Final metrics into the run summary, the P/R/F1 curve, recall by plate width and the frames table."""
    res, ultra = evaluation["result"], evaluation["ultralytics"]
    best, corner = res["best"], res["corner_error"]
    summary = {
        **{f"final/{k.replace(' ', '_')}": v for k, v in ultra.items()},
        **{f"final/{k}@best": best[k] for k in ("precision", "recall", "f1", "tp", "fp", "fn")},
        "final/best_conf": best["conf"],
        **{f"final/corner_{k}": v for k, v in corner.items()},
        **{f"final/recall_width_{b['width_px']}": b["recall"] for b in res["by_width"]},
    }
    wandb.run.summary.update(_scalars(summary))

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
        wandb.log({"eval/frames": frames_table(wandb, evaluation["records"], evaluation["predictions"],
                                               best["conf"], size, min_plate_px)})
