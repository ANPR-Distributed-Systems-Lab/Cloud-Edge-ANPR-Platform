"""Experiment tracking in Weights & Biases.

The W&B project is private and only its owner has access (decided 2026-11-05). It receives hyperparameters,
scalar metrics and, for visual review, validation frames with labels and predictions drawn on them (see
anpr_ml.detector.report). Frames go nowhere else; reports committed to git stay without them. Ultralytics'
built-in W&B integration stays off, so everything sent is chosen in this package.

One W&B run belongs to one training run: its id is kept in <run dir>/wandb_id.txt, so training, resuming and
evaluation all write to the same W&B run.
"""
import csv
import os
import secrets
from pathlib import Path

import numpy as np

from .paths import RUNS_DIR

ID_FILE = "wandb_id.txt"


def _local_dirs() -> None:
    """W&B stages logged tables and their images as artifacts and keeps a cache, by default under
    %LOCALAPPDATA% on the nearly full C: drive. Keep all of it next to the runs instead (gitignored)."""
    base = RUNS_DIR / "wandb-local"
    for var, sub in (("WANDB_DATA_DIR", "data"), ("WANDB_CACHE_DIR", "cache"), ("WANDB_ARTIFACT_DIR", "artifacts")):
        os.environ.setdefault(var, str(base / sub))


def start(cfg: dict, run: Path, config: dict | None = None):
    """Opens the W&B run tied to the run directory `run`, creating it on first use. Returns the wandb module."""
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


def scalars(values: dict) -> dict:
    """The numeric entries of `values` as floats; W&B rejects numpy scalars in some places."""
    return {k: float(v) for k, v in values.items() if isinstance(v, (int, float, np.floating, np.integer))}


def training_callbacks(cfg: dict, manifest: dict) -> dict:
    """Ultralytics callbacks: hyperparameters at the start, losses / metrics / learning rate every epoch."""
    state = {"wandb": None, "epoch": None}

    def on_train_start(trainer):
        args = {k: v for k, v in vars(trainer.args).items() if isinstance(v, (int, float, str, bool, type(None)))}
        state["wandb"] = start(cfg, Path(trainer.save_dir), {
            **args, "dataset": {**cfg["dataset"], "size": list(cfg["dataset"]["size"])},
            "dataset_counts": manifest.get("counts"),
        })

    def on_fit_epoch_end(trainer):
        # After the last epoch Ultralytics validates best.pt and fires this event once more, with the epoch
        # counter unchanged or (after a resume) one past the end. That is not an epoch: skip it.
        if state["wandb"] is None or trainer.epoch == state["epoch"] or trainer.epoch + 1 > trainer.epochs:
            return
        state["epoch"] = trainer.epoch
        values = {**trainer.label_loss_items(trainer.tloss, prefix="train"), **trainer.metrics, **trainer.lr}
        state["wandb"].log({**scalars(values), "epoch": trainer.epoch + 1}, step=trainer.epoch + 1)

    def on_train_end(trainer):
        if state["wandb"] is not None:
            state["wandb"].finish()

    return {"on_train_start": on_train_start, "on_fit_epoch_end": on_fit_epoch_end, "on_train_end": on_train_end}


def log_history(wandb, run: Path) -> None:
    """Replays results.csv into W&B, for a run trained before tracking was enabled (detector v0)."""
    with open(run / "results.csv", newline="") as f:
        for row in csv.DictReader(f):
            row = {k.strip(): v for k, v in row.items()}
            epoch = int(float(row.pop("epoch")))
            wandb.log({**{k: float(v) for k, v in row.items() if v.strip()}, "epoch": epoch}, step=epoch)
