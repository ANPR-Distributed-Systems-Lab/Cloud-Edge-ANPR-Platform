"""anpr-eval-detector: evaluates a finished detector run on the val split and reports it.

Writes runs/detector/<run>/eval_val.json and, with W&B enabled in the config, logs the metrics, the curves and
the table of validation frames to the run's W&B run (created on first use, with the epoch history replayed
from results.csv for runs trained before tracking was on). anpr-train-detector calls the same code when a
run finishes; the notebook calls evaluate_run() for its analysis.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path

from .detector import load_config, predict_records, run_dir, run_state
from .detector_eval import evaluate
from .make_splits import load_splits
from .paths import CONFIGS_DIR, EXPORTS_DIR
from .yolo_dataset import load_records, split_records


def val_records(cfg: dict) -> list[dict]:
    exports = [EXPORTS_DIR / f"{b}.jsonl" for b in cfg["dataset"]["exports"]]
    return split_records(load_records(exports), load_splits())["val"]


def ultralytics_val(cfg: dict, weights: Path, data_yaml: Path) -> dict:
    """Ultralytics' own metrics on the (painted) val images: box and pose mAP."""
    from ultralytics import YOLO

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):  # progress bars
        val = YOLO(str(weights)).val(data=str(data_yaml), split="val", imgsz=cfg["train"]["imgsz"],
                                     batch=cfg["train"]["batch"], device=cfg["train"]["device"], plots=False,
                                     verbose=False)
    return {
        "box precision": float(val.box.mp), "box recall": float(val.box.mr),
        "box mAP50": float(val.box.map50), "box mAP50-95": float(val.box.map),
        "pose mAP50": float(val.pose.map50), "pose mAP50-95": float(val.pose.map),
    }


def evaluate_run(cfg: dict) -> dict:
    """Ultralytics val plus our metrics on the original, unpainted frames; saves eval_val.json."""
    from .detector import dataset_dir

    run = run_dir(cfg)
    state = run_state(run)
    if state != "finished":
        raise RuntimeError(f"{run} is {state}: run `uv run anpr-train-detector` first")
    best = run / "weights" / "best.pt"
    records = val_records(cfg)
    ultra = ultralytics_val(cfg, best, dataset_dir(cfg) / "data.yaml")
    preds = predict_records(best, records, cfg["dataset"]["size"], conf=0.05, device=cfg["train"]["device"])
    res = evaluate(records, preds, cfg["dataset"]["min_plate_px"])
    (run / "eval_val.json").write_text(json.dumps({"ultralytics": ultra, **res}, indent=2, default=lambda o: o.item()))
    return {"run": run, "weights": best, "records": records, "predictions": preds, "ultralytics": ultra, "result": res}


def report(cfg: dict, evaluation: dict) -> None:
    """Sends the evaluation to the run's W&B run when tracking is enabled in the config."""
    if not cfg["wandb"]["enabled"]:
        return
    from . import tracking

    run = evaluation["run"]
    new = not tracking.is_tracked(run)
    wandb = tracking.start(cfg, run)
    try:
        if new:
            tracking.log_history(wandb, run)
        tracking.log_evaluation(wandb, evaluation, cfg["dataset"]["size"], cfg["dataset"]["min_plate_px"],
                                images=cfg["wandb"].get("log_images", False))
    finally:
        wandb.finish()


def print_summary(evaluation: dict) -> None:
    res = evaluation["result"]
    b, c = res["best"], res["corner_error"]
    print(f"{evaluation['run'].name}: {res['plates']} val plates; at conf {b['conf']}: precision {b['precision']:.3f}, "
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
