"""anpr-train-ocr: fine-tunes the pretrained fast-plate-ocr model on the plate crops (Keras 3, torch backend).

Run it from a terminal. The same command builds the config's crop dataset if it is missing and does nothing
for a finished run. A config whose `train` is null is a baseline: the pretrained model is exported unchanged.
Either way the run ends with model.onnx, the file the edge node runs, followed by an evaluation on the val
crops and, with W&B enabled, a report.

Training reuses fast-plate-ocr's model builder, data pipeline, default augmentation, loss and metrics with the
optimizer setup of its own CLI (AdamW with EMA, cosine decay with warmup). What differs is the run layout
(runs/ocr/<run>/), the checkpoint selection and the W&B logging. A run takes minutes and is not resumable:
an interrupted run directory is reported and has to be checked and removed by hand.
"""
import argparse
import shutil
from pathlib import Path

import yaml

from .. import tracking
from ..paths import CONFIGS_DIR
from .backend import keras_torch
from .config import (
    BEST,
    LAST,
    MODEL_CONFIG,
    ONNX,
    PLATE_CONFIG,
    TRAINING_LOG,
    dataset_dir,
    load_config,
    pretrained_files,
    run_config,
    run_dir,
    run_state,
)
from .dataset import ensure_dataset
from .evaluate import evaluate_run, print_summary
from .export import export_onnx
from .report import report

WEIGHT_DECAY_EXCLUDED = ["bias", "layer_norm"]  # fast-plate-ocr's default


def _optimizer(keras, t: dict, steps_per_epoch: int):
    """AdamW on a cosine schedule with linear warmup, as in fast-plate-ocr's CLI."""
    total = t["epochs"] * steps_per_epoch
    warmup = int(t["warmup_fraction"] * total)
    schedule = keras.optimizers.schedules.CosineDecay(
        initial_learning_rate=0.0, decay_steps=total - warmup, alpha=t["final_lr_factor"],
        warmup_steps=warmup, warmup_target=t["lr"])
    optimizer = keras.optimizers.AdamW(schedule, weight_decay=t["weight_decay"], clipnorm=t["clipnorm"],
                                       use_ema=t["ema"])
    optimizer.exclude_from_weight_decay(var_names=WEIGHT_DECAY_EXCLUDED)
    return optimizer


def _compile(keras, model, optimizer, t: dict, plate_config) -> None:
    from fast_plate_ocr.train.model.loss import cce_loss
    from fast_plate_ocr.train.model.metric import (
        cat_acc_metric,
        plate_acc_metric,
        plate_len_acc_metric,
        top_3_k_metric,
    )

    slots, vocab = plate_config.max_plate_slots, plate_config.vocabulary_size
    model.compile(
        optimizer=optimizer,
        loss={"plate": cce_loss(vocabulary_size=vocab, label_smoothing=t["label_smoothing"]),
              "region": keras.losses.CategoricalCrossentropy()},
        loss_weights={"plate": t["plate_loss_weight"], "region": 1 - t["plate_loss_weight"]},
        metrics={"plate": [
            cat_acc_metric(max_plate_slots=slots, vocabulary_size=vocab),
            plate_acc_metric(max_plate_slots=slots, vocabulary_size=vocab),
            top_3_k_metric(vocabulary_size=vocab),
            plate_len_acc_metric(max_plate_slots=slots, vocabulary_size=vocab,
                                 pad_token_index=plate_config.pad_idx),
        ]},
        jit_compile=False,
    )


def _callbacks(keras, cfg: dict, run: Path) -> list:
    t = cfg["train"]
    # Val accuracy moves in steps of single plates near the top (the pretrained model already reads 137 of
    # 145 val crops), so checkpoints are selected on the val loss, which still ranks models reading the same
    # plates. EMA weights are swapped in before the checkpoints, so both checkpoints hold the EMA weights.
    callbacks = [
        keras.callbacks.EarlyStopping(monitor=t["monitor"], mode="min", patience=t["patience"], verbose=1),
        *([keras.callbacks.SwapEMAWeights(swap_on_epoch=True)] if t["ema"] else []),
        keras.callbacks.ModelCheckpoint(run / LAST, save_best_only=False),
        keras.callbacks.ModelCheckpoint(run / BEST, monitor=t["monitor"], mode="min", save_best_only=True,
                                        verbose=1),
        keras.callbacks.TerminateOnNaN(),
        keras.callbacks.CSVLogger(str(run / TRAINING_LOG)),
    ]
    if cfg["wandb"]["enabled"]:
        callbacks.append(tracking.keras_callback(keras, cfg, run, run_config(cfg)))
    return callbacks


def fine_tune(cfg: dict, files: dict[str, Path], run: Path) -> None:
    """Trains the pretrained model on the dataset's train crops; best.keras is the selected checkpoint."""
    keras = keras_torch()
    import albumentations as A
    from fast_plate_ocr.train.data.augmentation import default_train_augmentation
    from fast_plate_ocr.train.data.dataset import PlateRecognitionPyDataset
    from fast_plate_ocr.train.model.config import load_plate_config_from_yaml
    from fast_plate_ocr.train.model.model_builders import build_model
    from fast_plate_ocr.train.model.model_schema import load_model_config_from_yaml

    t = cfg["train"]
    keras.utils.set_random_seed(t["seed"])
    plate_config = load_plate_config_from_yaml(files["plate_config"])
    augmentation = default_train_augmentation(img_color_mode=plate_config.image_color_mode)
    A.save(augmentation, run / "train_augmentation.yaml", "yaml")

    data = dataset_dir(cfg)
    train_data = PlateRecognitionPyDataset(annotations_file=data / "train" / "annotations.csv",
                                           transform=augmentation, plate_config=plate_config,
                                           batch_size=t["batch"], shuffle=True)
    val_data = PlateRecognitionPyDataset(annotations_file=data / "val" / "annotations.csv",
                                         plate_config=plate_config, batch_size=t["batch"], shuffle=False)

    model = build_model(load_model_config_from_yaml(files["model_config"]), plate_config,
                        enable_region_head=True)
    model.load_weights(files["keras"])  # same architecture and outputs: every weight must load
    _compile(keras, model, _optimizer(keras, t, len(train_data)), t, plate_config)
    model.fit(train_data, validation_data=val_data, epochs=t["epochs"], callbacks=_callbacks(keras, cfg, run))


def train(cfg: dict) -> Path:
    """Fine-tunes (or, for a baseline, copies) the pretrained model into a new run directory; exports it."""
    run = run_dir(cfg)
    if run.exists():
        raise FileExistsError(f"{run} already exists")
    files = pretrained_files(cfg)
    run.mkdir(parents=True)
    (run / "config.yaml").write_text(yaml.safe_dump(run_config(cfg), sort_keys=False))
    shutil.copy(files["model_config"], run / MODEL_CONFIG)
    shutil.copy(files["plate_config"], run / PLATE_CONFIG)
    if cfg["train"] is None:
        shutil.copy(files["keras"], run / BEST)
    else:
        fine_tune(cfg, files, run)
    export_onnx(run / BEST, run / PLATE_CONFIG, run / ONNX)
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=CONFIGS_DIR / "ocr_v0.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ensure_dataset(cfg)
    run = run_dir(cfg)
    state = run_state(run)
    if state == "finished":
        print(f"{run} is already finished; change run_name in {args.config.name} for a new run, "
              f"or re-evaluate it with `uv run anpr-eval-ocr --config {args.config}`")
        return
    if state == "interrupted":
        raise SystemExit(f"{run} was interrupted before its export (OCR runs are not resumable); "
                         "check it, delete it and run this command again")
    print(f"{'exporting the pretrained model' if cfg['train'] is None else 'training'} into {run}")
    train(cfg)
    print(f"done: {run / ONNX}")

    evaluation = evaluate_run(cfg)
    print_summary(evaluation)
    report(cfg, evaluation)


if __name__ == "__main__":
    main()
