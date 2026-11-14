"""Detector run configuration and the locations of a run's files.

A config (configs/<name>.yaml) describes one training run completely:

    run_name    the run directory, runs/detector/<run_name>/
    dataset     name (datasets/<name>/), exports (label batches), size [w, h], min_plate_px, ignore_margin_px
    model       weights: the pretrained Ultralytics checkpoint to start from
    train       passed unchanged to Ultralytics model.train()
    wandb       enabled, project, entity, mode, log_images (see anpr_ml.tracking)

A new experiment gets a new config file; a finished run's config is never edited.
"""
from pathlib import Path

import yaml

from ..paths import DATASETS_DIR, MODELS_DIR, RUNS_DIR


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["dataset"]["size"] = tuple(cfg["dataset"]["size"])
    return cfg


def dataset_dir(cfg: dict) -> Path:
    return DATASETS_DIR / cfg["dataset"]["name"]


def run_dir(cfg: dict) -> Path:
    return RUNS_DIR / "detector" / cfg["run_name"]


def pretrained_weights(cfg: dict) -> Path:
    """Where the starting checkpoint lives; Ultralytics downloads its released weights there if missing."""
    path = MODELS_DIR / "pretrained" / cfg["model"]["weights"]
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def run_state(run: Path) -> str:
    """'missing', 'interrupted' or 'finished'.

    best.pt and last.pt are written after every epoch, so their presence does not mean the run is complete.
    Ultralytics marks a finished run by stripping the optimizer from last.pt and setting its epoch to -1.
    """
    import torch

    last = run / "weights" / "last.pt"
    if not last.exists():
        return "interrupted" if run.exists() else "missing"
    ckpt = torch.load(last, map_location="cpu", weights_only=False)
    return "finished" if ckpt.get("epoch") == -1 else "interrupted"
