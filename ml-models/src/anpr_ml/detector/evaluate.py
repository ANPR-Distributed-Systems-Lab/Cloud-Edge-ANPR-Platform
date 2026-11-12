"""anpr-eval-detector: evaluates a finished detector run on the val split.

Two views of the same model:
- Ultralytics' own validation on the dataset's val images (painted), for box and pose mAP;
- our metrics on the original, unpainted frames run as on the edge node (see metrics.py).

Writes runs/detector/<run>/eval_val.json and, with W&B enabled in the config, reports to the run's W&B run.
anpr-train-detector runs the same code when a run finishes; the notebook calls evaluate_run().
"""
import argparse
import contextlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

from ..common.labels import export_paths, load_records, load_splits, split_records
from ..paths import CONFIGS_DIR
from .config import dataset_dir, load_config, run_dir, run_state
from .metrics import evaluate
from .predict import Prediction, predict_records
from .report import report


@dataclass
class Evaluation:
    run: Path
    weights: Path
    records: list[dict]  # val frames
    predictions: dict[str, list[Prediction]]
    ultralytics: dict[str, float]
    result: dict  # metrics.evaluate()


def val_records(cfg: dict) -> list[dict]:
    return split_records(load_records(export_paths(cfg["dataset"]["exports"])), load_splits())["val"]


def ultralytics_val(cfg: dict, weights: Path) -> dict[str, float]:
    from ultralytics import YOLO

    # Ultralytics prints a progress bar per batch; the numbers are returned below.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        val = YOLO(str(weights)).val(data=str(dataset_dir(cfg) / "data.yaml"), split="val",
                                     imgsz=cfg["train"]["imgsz"], batch=cfg["train"]["batch"],
                                     device=cfg["train"]["device"], plots=False, verbose=False)
    return {
        "box precision": float(val.box.mp), "box recall": float(val.box.mr),
        "box mAP50": float(val.box.map50), "box mAP50-95": float(val.box.map),
        "pose mAP50": float(val.pose.map50), "pose mAP50-95": float(val.pose.map),
    }


def evaluate_run(cfg: dict) -> Evaluation:
    """Evaluates best.pt of the config's finished run and saves eval_val.json."""
    run = run_dir(cfg)
    state = run_state(run)
    if state != "finished":
        raise RuntimeError(f"{run} is {state}: run `uv run anpr-train-detector` first")
    weights = run / "weights" / "best.pt"
    records = val_records(cfg)
    ultra = ultralytics_val(cfg, weights)
    preds = predict_records(weights, records, cfg["dataset"]["size"], device=cfg["train"]["device"])
    res = evaluate(records, preds, cfg["dataset"]["min_plate_px"])
    (run / "eval_val.json").write_text(json.dumps({"ultralytics": ultra, **res}, indent=2, default=lambda o: o.item()))
    return Evaluation(run, weights, records, preds, ultra, res)


def print_summary(evaluation: Evaluation) -> None:
    res = evaluation.result
    b, c = res["best"], res["corner_error"]
    print(f"{evaluation.run.name}: {res['plates']} val plates; at conf {b['conf']}: precision {b['precision']:.3f}, "
          f"recall {b['recall']:.3f} (tp {b['tp']}, fp {b['fp']}, fn {b['fn']}); corner error median "
          f"{c['median_px']:.2f} px, p90 {c['p90_px']:.2f} px on the original")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=CONFIGS_DIR / "detector_v0.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    evaluation = evaluate_run(cfg)
    print_summary(evaluation)
    report(cfg, evaluation)


if __name__ == "__main__":
    main()
