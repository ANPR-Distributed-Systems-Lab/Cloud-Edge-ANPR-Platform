# ml-models

License plate models for the ANPR edge node (Raspberry Pi 5): dataset preparation, labeling tools, the plate
detector (YOLO-pose with the 4 plate corners as keypoints) and, next, the OCR.

- [ML_ASSUMPTIONS.md](ML_ASSUMPTIONS.md): the decisions (models, resolutions, metrics, deployment) and what is
  still open.
- [labeling/README.md](labeling/README.md): the labeling guide (rules for corners, `plate_ignore`, attributes)
  and the CVAT workflow.

## Pipeline

```
data/session_*/                        recordings from the data-collection app (rpi-edge), 4056x3040 JPEG
  │ anpr-index                         perceptual hash of every frame        -> labeling/frame_index.csv
  │ anpr-splits                        whole sessions -> train / val / test  -> labeling/splits.json
  │ anpr-select                        new batch without near-duplicates     -> labeling/batches/<batch>/
  ▼                                                                             labeling/selected.csv
CVAT (labeling/cvat.ps1)               4 corners per plate, attributes       -> labeling/exports/<batch>.zip
  │ anpr-validate                      checks the export                     -> labeling/exports/<batch>.jsonl
  ▼
  │ anpr-yolo-dataset                  YOLO-pose dataset at detector size    -> datasets/<name>/
  │ anpr-train-detector                training run from configs/<name>.yaml -> runs/detector/<run>/
  │ anpr-eval-detector                 metrics on the val split              -> eval_val.json, W&B
  ▼
notebooks/                             analysis of finished runs
```

## Setup

Python environment managed by [uv](https://docs.astral.sh/uv/), separate from `rpi-edge`. Torch is installed
with CUDA 12.6 from the PyTorch index pinned in `pyproject.toml`.

```powershell
uv sync                      # all dependency groups: dev, train, notebook
uv run wandb login           # once per machine, for experiment tracking
```

The uv cache defaults to the system drive; with little space there, set `UV_CACHE_DIR` to another drive first.

## Commands

All commands run from `ml-models/` with `uv run <command>`; each has `--help`.

| Command | What it does |
|---|---|
| `anpr-index` | Hashes the frames not indexed yet (incremental, safe to interrupt). |
| `anpr-splits [--add --test N --val N]` | Assigns sessions to splits once; `--add` assigns only new sessions. |
| `anpr-select --split S --batch NAME --count N` | Creates a labeling batch; `--sweep` shows how many frames each dedupe threshold keeps. |
| `anpr-validate EXPORT.zip --out EXPORT.jsonl` | Validates a CVAT export and writes the normalized labels. |
| `anpr-yolo-dataset --name NAME --exports B1 B2` | Builds a YOLO-pose dataset from validated labels. |
| `anpr-train-detector --config CONFIG` | Trains a detector run; resumes it if interrupted; evaluates and reports it when finished. |
| `anpr-eval-detector --config CONFIG` | Re-evaluates a finished run and reports it to W&B. |

Training always runs from a terminal, not from a notebook: a run takes an hour or more and must not depend on a
kernel or an IDE. Before a long run, stop CVAT and Docker Desktop; on a 16 GB machine they leave too little
memory for the dataloader workers.

A new experiment gets a new config: copy `configs/detector_v0.yaml`, change `run_name` and, when the data
changes, `dataset.name` and `dataset.exports`. Existing runs and datasets are never overwritten.

## Layout

```
ml-models/
├── README.md, ML_ASSUMPTIONS.md, CLAUDE.md
├── pyproject.toml, uv.lock
├── src/anpr_ml/
│   ├── paths.py                    every location the tooling reads or writes
│   ├── tracking.py                 Weights & Biases: one W&B run per training run
│   ├── common/
│   │   ├── geometry.py             plate width, boxes from corners, IoU
│   │   ├── preprocess.py           resize_for_detector(): must give the same pixels on the Pi
│   │   └── labels.py               splits.json, the validated .jsonl labels, batch file names
│   ├── labeling/
│   │   ├── frames.py               sessions on disk, perceptual hash (dHash)
│   │   ├── frame_index.py          anpr-index
│   │   ├── splits.py               anpr-splits
│   │   ├── selection.py            anpr-select
│   │   └── validation.py           anpr-validate
│   └── detector/
│       ├── config.py               run config, run directory and state
│       ├── dataset.py              anpr-yolo-dataset
│       ├── train.py                anpr-train-detector
│       ├── predict.py              inference on original frames, as on the Pi
│       ├── metrics.py              P / R / F1, recall by plate width, corner error
│       ├── evaluate.py             anpr-eval-detector
│       └── report.py               evaluation report in W&B (metrics, validation frames table)
├── tests/                          pytest; no GPU, network or real data needed
├── configs/                        one YAML per training run
├── notebooks/                      jupytext .py notebooks; reports/ holds executed reports
├── labeling/
│   ├── README.md                   labeling guide
│   ├── cvat.ps1, compose.share.yml the only supported way to run CVAT
│   ├── cvat_labels.json            label definition for the CVAT project
│   ├── splits.json, selected.csv   the dataset definition (committed)
│   └── frame_index.csv, batches/, exports/, cvat/        local only
├── data/, datasets/, runs/, models/                       local only
```

Everything marked local only is gitignored. Recordings, frames and weights never go into git; model weights
are distributed through S3.

## Notebooks

Notebooks are [jupytext](https://jupytext.readthedocs.io/) percent-format `.py` files paired with a gitignored
`.ipynb` that holds the outputs. Open them with `uv run jupyter lab` (*Open With -> Notebook*), or open the
`.ipynb` in PyCharm and sync afterwards with `uv run jupytext --sync notebooks/<name>.py` (with the notebook
closed in the IDE, which otherwise saves over the sync).

Frames show license plates, which are personal data. Cells that draw frames run only when `ANPR_SHOW_IMAGES` is
not `0`, and reports in `notebooks/reports/` are executed with `ANPR_SHOW_IMAGES=0`:

```powershell
$env:ANPR_SHOW_IMAGES = "0"
uv run jupytext --to ipynb --output notebooks/reports/01_detector_v0.ipynb notebooks/01_detector_v0.py
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/reports/01_detector_v0.ipynb
```

## Experiment tracking

Runs are tracked in a private Weights & Biases project (`wandb` section of the config): hyperparameters, epoch
metrics, the final evaluation and a table of the validation frames with labels and predictions drawn, for
reviewing errors. Validation frames are the only images that leave the machine.

## Quality checks

```powershell
uv run pytest
uv run ruff check src tests notebooks
```
