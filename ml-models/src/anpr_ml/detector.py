"""anpr-train-detector: trains the plate detector with Ultralytics from a configs/*.yaml file.

Run it from a terminal: a training run takes an hour or more, and a terminal process does not depend on a
notebook kernel or an IDE. The same command builds the dataset if it is missing, resumes an interrupted run
from last.pt, and does nothing for a finished run. When a run finishes it is evaluated on the val split
(anpr_ml.evaluate_detector) and, with W&B enabled, reported there. Notebooks only analyse finished runs.

Ultralytics is imported lazily so the labeling tools and unit tests run without torch.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import yaml

from .detector_eval import Prediction
from .paths import BATCHES_DIR, CONFIGS_DIR, DATASETS_DIR, EXPORTS_DIR, MODELS_DIR, RUNS_DIR
from .preprocess import read_image, resize_for_detector


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["dataset"]["size"] = tuple(cfg["dataset"]["size"])
    return cfg


def dataset_dir(cfg: dict) -> Path:
    return DATASETS_DIR / cfg["dataset"]["name"]


def run_dir(cfg: dict) -> Path:
    return RUNS_DIR / "detector" / cfg["run_name"]


def ensure_dataset(cfg: dict) -> dict:
    """Builds datasets/<name>/ if missing and returns its manifest. Refuses a dataset built from other label
    files or parameters, so a relabeled batch never trains silently on stale data."""
    from .yolo_dataset import build_dataset, sha256_file

    d = cfg["dataset"]
    exports = [EXPORTS_DIR / f"{b}.jsonl" for b in d["exports"]]
    out = dataset_dir(cfg)
    if not (out / "manifest.json").exists():
        build_dataset(exports, out, d["size"], d["min_plate_px"], d["ignore_margin_px"])
    manifest = json.loads((out / "manifest.json").read_text())
    expected = {
        "sources": {p.name: sha256_file(p) for p in exports},
        "size": list(d["size"]),
        "min_plate_px": d["min_plate_px"],
        "ignore_margin_px": d["ignore_margin_px"],
    }
    stale = {k: {"dataset": manifest[k], "config": v} for k, v in expected.items() if manifest[k] != v}
    if stale:
        raise ValueError(f"{out} does not match the config, give the dataset a new name: {stale}")
    return manifest


def run_state(run: Path) -> str:
    """'missing', 'interrupted' or 'finished'. best.pt is saved every epoch, so it does not mean finished;
    Ultralytics marks a completed run by stripping the optimizer and setting epoch to -1 in last.pt."""
    import torch

    last = run / "weights" / "last.pt"
    if not last.exists():
        return "interrupted" if run.exists() else "missing"
    ckpt = torch.load(last, map_location="cpu", weights_only=False)
    return "finished" if ckpt.get("epoch") == -1 else "interrupted"


def pretrained_weights(cfg: dict) -> Path:
    path = MODELS_DIR / "pretrained" / cfg["model"]["weights"]
    path.parent.mkdir(parents=True, exist_ok=True)
    return path  # Ultralytics downloads its released weights to this path if missing


def check_integrations() -> None:
    """Ultralytics' own W&B integration would log in parallel with ours (anpr_ml.tracking); keep it off."""
    from ultralytics.utils import SETTINGS

    if SETTINGS.get("wandb"):
        raise RuntimeError(
            "Ultralytics' built-in W&B integration is on; turn it off with `uv run yolo settings wandb=False`. "
            "Tracking goes through anpr_ml.tracking, which decides what is sent."
        )


def _add_wandb(model, cfg: dict, manifest: dict) -> None:
    if cfg["wandb"]["enabled"]:
        from .tracking import training_callbacks

        for event, fn in training_callbacks(cfg, manifest).items():
            model.add_callback(event, fn)


def train(cfg: dict, manifest: dict, overrides: dict | None = None) -> Path:
    """Trains from the pretrained weights; returns the run directory. Refuses to overwrite a run."""
    from ultralytics import YOLO

    check_integrations()
    name = (overrides or {}).get("name", cfg["run_name"])
    if (RUNS_DIR / "detector" / name).exists():
        raise FileExistsError(f"{RUNS_DIR / 'detector' / name} already exists")
    model = YOLO(str(pretrained_weights(cfg)))
    _add_wandb(model, cfg, manifest)
    args = {**cfg["train"], "name": name, **(overrides or {})}
    model.train(data=str(dataset_dir(cfg) / "data.yaml"), project=str(RUNS_DIR / "detector"), exist_ok=False, **args)
    return Path(model.trainer.save_dir)


def resume(cfg: dict, manifest: dict) -> Path:
    """Continues an interrupted run from last.pt with its optimizer state and schedule.

    Only memory-related settings (batch, workers) are taken from the current config; Ultralytics keeps the
    rest of the original arguments.
    """
    from ultralytics import YOLO

    check_integrations()
    run = run_dir(cfg)
    last = run / "weights" / "last.pt"
    if not last.exists():
        raise FileNotFoundError(f"{last} is missing: the run stopped before its first epoch; remove {run} and retrain")
    model = YOLO(str(last))
    _add_wandb(model, cfg, manifest)
    model.train(resume=True, batch=cfg["train"]["batch"], workers=cfg["train"]["workers"])
    return Path(model.trainer.save_dir)


def predict_records(
    weights: Path, records: list[dict], size: tuple[int, int], conf: float = 0.05, device=0
) -> dict[str, list[Prediction]]:
    """Runs the detector the way the edge node will: original frame -> resize_for_detector -> model.

    The frames are not painted, so the model also sees the ignored plates; the evaluation drops
    detections there instead of counting them as false positives.
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


def corners_to_px(corners: np.ndarray, width: int, height: int) -> np.ndarray:
    return np.asarray(corners, dtype=float) * np.array([width, height])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=CONFIGS_DIR / "detector_v0.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    manifest = ensure_dataset(cfg)
    run = run_dir(cfg)
    state = run_state(run)
    if state == "finished":
        print(f"{run} is already finished; change run_name in {args.config.name} for a new run, "
              f"or re-evaluate it with `uv run anpr-eval-detector --config {args.config}`")
        return
    print(f"{'resuming' if state == 'interrupted' else 'starting'} {run}")
    run = train(cfg, manifest) if state == "missing" else resume(cfg, manifest)
    print(f"done: {run / 'weights' / 'best.pt'}")

    from .evaluate_detector import evaluate_run, print_summary, report

    evaluation = evaluate_run(cfg)
    print_summary(evaluation)
    report(cfg, evaluation)


if __name__ == "__main__":
    main()
