"""anpr-eval-ocr: evaluates a finished OCR run on the val crops (labeled corners, no jitter).

This measures the OCR alone: reading the readable plates and, when the dataset has rejects, declining the
rest (see anpr_ml.ocr.metrics). The OCR behind the real detector, on its corners and its false positives, is
measured by anpr-eval-pipeline.

Writes runs/ocr/<run>/eval_val.json and, with W&B enabled in the config, reports to the run's W&B run.
anpr-train-ocr runs the same code when a run finishes; the notebooks call evaluate_run().
"""
import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from ..common.preprocess import read_image
from ..paths import CONFIGS_DIR
from .config import EVAL, load_config, run_dir, run_state
from .dataset import ensure_dataset, read_crops
from .metrics import evaluate
from .predict import Reader, Reading
from .report import report


@dataclass
class Evaluation:
    run: Path
    crops: list[dict]  # dataset.read_crops() rows of the val split
    readings: list[Reading]
    result: dict  # metrics.evaluate()


def evaluate_run(cfg: dict) -> Evaluation:
    """Reads every val crop with the run's model.onnx and saves eval_val.json."""
    run = run_dir(cfg)
    state = run_state(run)
    if state != "finished":
        raise RuntimeError(f"{run} is {state}: run `uv run anpr-train-ocr` first")
    ensure_dataset(cfg)
    crops = read_crops(cfg, "val")
    reader = Reader(run)
    readings = [reader.read(read_image(c["path"])) for c in crops]
    res = evaluate([c["text"] for c in crops], readings, [c["width_px"] for c in crops])
    (run / EVAL).write_text(json.dumps(res, indent=2))
    return Evaluation(run, crops, readings, res)


def print_summary(evaluation: Evaluation) -> None:
    res = evaluation.result
    print(f"{evaluation.run.name}: {res['crops']} readable val crops; exact {res['exact']:.3f}, "
          f"CER {res['cer']:.4f}, wrong length {res['wrong_length']}, read as no text {res['false_rejects']}, "
          f"mean confidence {res['mean_conf']:.3f}")
    if res["reject_crops"]:
        print(f"{res['reject_crops']} val rejects; read as no text {res['reject_rate']:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=CONFIGS_DIR / "ocr_v0.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    evaluation = evaluate_run(cfg)
    print_summary(evaluation)
    report(cfg, evaluation)


if __name__ == "__main__":
    main()
