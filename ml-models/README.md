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
kernel or an IDE.

## Recipes

Ready-to-paste PowerShell for the usual tasks. Only the variables in the first line of each block change.

### Every new terminal

```powershell
cd ml-models                          # from the repository root
$env:UV_CACHE_DIR = "G:\uv-cache"     # skip if UV_CACHE_DIR is set as a user environment variable
```

### What exists already

```powershell
Import-Csv labeling\selected.csv | Group-Object batch | Select-Object Name, Count   # frames per batch
Get-ChildItem labeling\exports                 # <batch>.zip from CVAT, <batch>.jsonl once validated
Get-ChildItem configs\detector_*.yaml          # detector versions
Get-ChildItem runs\detector                    # their training runs
```

### New recordings

After the new `session_*` folders are copied into `data/`:

```powershell
$test = 1; $val = 1                            # how many of the NEW sessions go to test and to val (~1 in 7 each)
uv run anpr-index                              # hashes only the new frames
uv run anpr-splits --add --test $test --val $val
```

### New labeling batch

Batches are named `<split>_<NNN>`, numbered per split. A test batch is always labeled from scratch, never with
model suggestions.

```powershell
$split = "train"; $batch = "train_003"; $count = 300     # val: "val", "val_002", 150; test: "test", "test_001", 150
uv run anpr-select --split $split --sweep                # optional: frames left per dedupe threshold
uv run anpr-select --split $split --batch $batch --count $count
.\labeling\cvat.ps1 up                                   # Docker Desktop must be running
```

In CVAT (http://localhost:8080): *Tasks -> Create*, project `plates`, tab *Connected file share*, folder `<batch>`,
image quality 100 ([details](labeling/README.md#creating-the-project-and-tasks-in-cvat)). After labeling:
*Actions -> Export task dataset*, format **CVAT for images 1.1**, "Save images" off, saved as
`labeling\exports\<batch>.zip`. Then, with the same `$batch`:

```powershell
uv run anpr-validate "labeling\exports\$batch.zip" --out "labeling\exports\$batch.jsonl"
.\labeling\cvat.ps1 down                                 # keeps every annotation (never add -v)
```

The `.jsonl` is written only when there are no errors; fix the reported frames in CVAT, export again and rerun.

### New detector version

Copy the previous config and edit the copy:

```powershell
$prev = "v1"; $new = "v2"
Copy-Item "configs\detector_$prev.yaml" "configs\detector_$new.yaml"
```

In `configs\detector_<new>.yaml` change:

- the header comment: what this version changes and why;
- `run_name: v2`;
- when the data changes: `dataset.name: pose_1280x960_v2` (a new name, datasets are never overwritten) and
  `dataset.exports: [train_001, train_002, train_003, val_001]`;
- any training setting under test.

Then train. The dataset is built automatically; the same command resumes an interrupted run, and evaluates and
reports the run to W&B when it finishes:

```powershell
uv run anpr-train-detector --config "configs\detector_$new.yaml"
uv run anpr-eval-detector --config "configs\detector_$new.yaml"   # only to re-evaluate a finished run
```

Adding a val batch changes the val set: the notebook then flags the comparison with older versions as not
directly comparable.

### Analysis of a version

```powershell
uv run jupyter lab                    # open notebooks/01_detector.py with Open With -> Notebook
```

Set `VERSION = "v2"` and `BASELINE = "v1"` in the first code cell and run all cells. For PyCharm, create or
refresh the paired `.ipynb` first (with its tab closed):

```powershell
uv run jupytext --sync notebooks/01_detector.py
```

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
├── notebooks/                      jupytext .py notebooks; reports/ executed reports, conclusions/ per version
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

`notebooks/01_detector.py` analyses any finished detector run: `VERSION` and `BASELINE` in its first code cell
select the run (`configs/detector_<version>.yaml`) and the run it is compared against. The written conclusions of
each version are kept in `notebooks/conclusions/detector_<version>.md` and shown at the end of the notebook.

Frames show license plates, which are personal data. Cells that draw frames run only when `ANPR_SHOW_IMAGES` is
not `0`, and reports in `notebooks/reports/` are executed with `ANPR_SHOW_IMAGES=0`. The version environment
variables override the first cell, so a report needs no edit of the notebook:

```powershell
$env:ANPR_SHOW_IMAGES = "0"; $env:ANPR_DETECTOR_VERSION = "v1"; $env:ANPR_DETECTOR_BASELINE = "v0"
uv run jupytext --to ipynb --output notebooks/reports/01_detector_v1.ipynb notebooks/01_detector.py
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/reports/01_detector_v1.ipynb
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
