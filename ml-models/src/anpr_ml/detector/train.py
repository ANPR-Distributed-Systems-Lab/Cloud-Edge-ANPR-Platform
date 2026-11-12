"""anpr-train-detector: trains the plate detector with Ultralytics from a config (see config.py).

Run it from a terminal: a training run takes an hour or more and must not depend on a notebook kernel or an IDE.
The same command builds the config's dataset if it is missing, resumes an interrupted run from last.pt, and does
nothing for a finished run. When a run finishes it is evaluated on the val split and, with W&B enabled,
reported there.

Ultralytics is imported lazily so that the labeling tools and the unit tests run without torch.
"""
import argparse
from pathlib import Path

from ..paths import CONFIGS_DIR, RUNS_DIR
from .config import dataset_dir, load_config, pretrained_weights, run_dir, run_state
from .dataset import ensure_dataset
from .evaluate import evaluate_run, print_summary
from .report import report


def check_integrations() -> None:
    """Ultralytics' built-in W&B integration would log in parallel with anpr_ml.tracking; it must stay off."""
    from ultralytics.utils import SETTINGS

    if SETTINGS.get("wandb"):
        raise RuntimeError(
            "Ultralytics' built-in W&B integration is on; turn it off with `uv run yolo settings wandb=False`. "
            "Tracking goes through anpr_ml.tracking, which decides what is sent."
        )


def _add_tracking(model, cfg: dict, manifest: dict) -> None:
    if cfg["wandb"]["enabled"]:
        from ..tracking import training_callbacks

        for event, fn in training_callbacks(cfg, manifest).items():
            model.add_callback(event, fn)


def train(cfg: dict, manifest: dict, overrides: dict | None = None) -> Path:
    """Trains from the pretrained weights and returns the run directory; never overwrites an existing run."""
    from ultralytics import YOLO

    check_integrations()
    name = (overrides or {}).get("name", cfg["run_name"])
    if (RUNS_DIR / "detector" / name).exists():
        raise FileExistsError(f"{RUNS_DIR / 'detector' / name} already exists")
    model = YOLO(str(pretrained_weights(cfg)))
    _add_tracking(model, cfg, manifest)
    args = {**cfg["train"], "name": name, **(overrides or {})}
    model.train(data=str(dataset_dir(cfg) / "data.yaml"), project=str(RUNS_DIR / "detector"), exist_ok=False, **args)
    return Path(model.trainer.save_dir)


def resume(cfg: dict, manifest: dict) -> Path:
    """Continues an interrupted run from last.pt, with its optimizer state and learning-rate schedule.

    Ultralytics keeps the original arguments; only memory-related ones (batch, workers) are taken from the
    current config, so a run that ran out of memory can be resumed with lighter settings.
    """
    from ultralytics import YOLO

    check_integrations()
    run = run_dir(cfg)
    last = run / "weights" / "last.pt"
    if not last.exists():
        raise FileNotFoundError(f"{last} is missing: the run stopped before its first epoch; remove {run} and retrain")
    model = YOLO(str(last))
    _add_tracking(model, cfg, manifest)
    model.train(resume=True, batch=cfg["train"]["batch"], workers=cfg["train"]["workers"])
    return Path(model.trainer.save_dir)


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

    evaluation = evaluate_run(cfg)
    print_summary(evaluation)
    report(cfg, evaluation)


if __name__ == "__main__":
    main()
