"""OCR run configuration, the pretrained model and the locations of a run's files.

A config (configs/ocr_<name>.yaml) describes one OCR run completely:

    run_name    the run directory, runs/ocr/<run_name>/
    dataset     name (datasets/<name>/), exports, margin, jitter_copies, jitter_sigma, seed and optionally
                reject (sources, min_px: crops the OCR learns to answer with no text, see anpr_ml.ocr.dataset)
    model       the pretrained fast-plate-ocr model to start from (see PRETRAINED)
    train       fine-tuning settings; null for a baseline run, which evaluates the pretrained model unchanged
    wandb       enabled, project, entity, mode, log_images (see anpr_ml.tracking)

A new experiment gets a new config file; a finished run's config is never edited.
"""
import hashlib
import urllib.request
from pathlib import Path

import yaml

from ..paths import DATASETS_DIR, MODELS_DIR, RUNS_DIR

RELEASE_URL = "https://github.com/ankandrew/fast-plate-ocr/releases/download/arg-plates"
# Release files of each supported pretrained model with their SHA-256, so a changed upstream file is noticed
# instead of silently becoming the starting point of a run.
PRETRAINED = {
    "cct_s_v2_global": {
        "keras": ("cct_s_v2_global.keras",
                  "dc6db494714d88e1fb0a21b4e4e96089842dd5440418262abfc382454453c2c8"),
        "model_config": ("cct_s_v2_global_model_config.yaml",
                         "244c3c712205750e9747bca4707cd553a84005f41959745bff676b0fca8faba3"),
        "plate_config": ("cct_s_v2_global_plate_config.yaml",
                         "0335c74a305173bb6f393efed0fde03cadeaa0b649ed8e19f431016d8232d0a6"),
    },
}

# Files of a run directory
BEST = "best.keras"  # the checkpoint the run selected; the pretrained weights for a baseline run
LAST = "last.keras"
MODEL_CONFIG = "model_config.yaml"
PLATE_CONFIG = "plate_config.yaml"  # input size, alphabet, slots: needed next to model.onnx at inference
ONNX = "model.onnx"  # what the edge node runs; its presence marks a finished run
TRAINING_LOG = "training_log.csv"
EVAL = "eval_val.json"


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["dataset"]["size"] = tuple(cfg["dataset"]["size"])
    return cfg


def run_config(cfg: dict) -> dict:
    """The config as plain YAML / JSON values: written into the run directory and to its W&B run."""
    return {**cfg, "dataset": {**cfg["dataset"], "size": list(cfg["dataset"]["size"])}}


def dataset_dir(cfg: dict) -> Path:
    return DATASETS_DIR / cfg["dataset"]["name"]


def run_dir(cfg: dict) -> Path:
    return RUNS_DIR / "ocr" / cfg["run_name"]


def run_state(run: Path) -> str:
    """'missing', 'interrupted' or 'finished'; a run is finished once it has exported model.onnx."""
    if (run / ONNX).exists():
        return "finished"
    return "interrupted" if run.exists() else "missing"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pretrained_files(cfg: dict) -> dict[str, Path]:
    """Local copies of the pretrained model's files under models/pretrained/ocr/, downloaded once."""
    name = cfg["model"]["name"]
    if name not in PRETRAINED:
        raise ValueError(f"unknown pretrained OCR model {name!r}; known: {sorted(PRETRAINED)}")
    out_dir = MODELS_DIR / "pretrained" / "ocr"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for kind, (file, sha) in PRETRAINED[name].items():
        path = out_dir / file
        if not path.exists():
            partial = path.with_name(path.name + ".partial")
            urllib.request.urlretrieve(f"{RELEASE_URL}/{file}", partial)
            partial.rename(path)
        if sha256_file(path) != sha:
            raise ValueError(f"{path} does not match the pinned checksum; check it, delete it and run again")
        files[kind] = path
    return files
