# ml-models

License plate models for the ANPR edge node (Raspberry Pi 5): dataset preparation, labeling tools, the plate
detector (YOLO-pose with the 4 plate corners as keypoints) and the OCR (fast-plate-ocr, fine-tuned on rectified
plate crops).

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
  ├──────────────────────────────────────┐
  │ anpr-yolo-dataset                    │ anpr-ocr-dataset  rectified crops of readable plates
  │   YOLO-pose dataset at detector size │     and rejects (train: jittered) -> datasets/<name>/
  │ anpr-train-detector                  │ anpr-train-ocr    fine-tunes fast-plate-ocr, exports ONNX
  │   -> runs/detector/<run>/            │     -> runs/ocr/<run>/
  │ anpr-eval-detector  (val, W&B)       │ anpr-eval-ocr     (val crops, W&B)
  ├──────────────────────────────────────┘
  │ anpr-eval-pipeline                 detector + OCR on the val frames      -> runs/pipeline/<det>__<ocr>/
  ▼
notebooks/                             01 detector, 02 OCR, 03 both together

runs/detector/<run>/  │ anpr-export-detector   ONNX with NMS, checked     -> runs/detector/<run>/model.onnx
runs/<model>/<run>/   │ anpr-publish-model     to the models bucket       -> s3://<bucket>/models/<model>/<run>/
                      ▼                        the devices download the versions their configuration names
```

## Setup

Python environment managed by [uv](https://docs.astral.sh/uv/), separate from `rpi-edge`. Torch is installed
with CUDA 12.6 from the PyTorch index pinned in `pyproject.toml`. The OCR runs on Keras 3 with the torch backend;
TensorFlow is not installed, and the OCR code selects the backend itself before Keras is first imported.

```powershell
uv sync                      # all dependency groups: dev, train, ocr, publish, notebook
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
| `anpr-ocr-dataset --name NAME --exports B1 B2 [--reject unreadable ignore]` | Builds an OCR crop dataset from validated labels; `--reject` adds crops the OCR learns to answer with no text. |
| `anpr-train-ocr --config CONFIG` | Fine-tunes an OCR run (or exports the pretrained model for a baseline config), exports `model.onnx`, evaluates and reports it. |
| `anpr-eval-ocr --config CONFIG` | Re-evaluates a finished OCR run on the val crops and reports it to W&B. |
| `anpr-eval-pipeline --detector CONFIG --ocr CONFIG` | Runs detector and OCR together on the val frames and classifies every read. |
| `anpr-export-detector --config CONFIG` | Exports a finished detector run to `model.onnx` for the edge node (NMS inside) and checks it against the PyTorch weights on val frames. |
| `anpr-publish-model {detector,ocr} RUN --bucket BUCKET [--profile P]` | Uploads a run's edge files and `release.json` to the models bucket; a published version is never replaced. |

Training always runs from a terminal, not from a notebook: a run must not depend on a kernel or an IDE. Detector
runs can be resumed; OCR runs take minutes and are not resumable (an interrupted one is reported and has to be
removed by hand).

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

### New OCR version

The same way, from the OCR configs (`configs\ocr_v0.yaml` is the pretrained baseline, `ocr_v1.yaml` the first
fine-tuning, `ocr_v2.yaml` the first with rejects, read as no text, `ocr_v3.yaml` the first with
`model.readability_head`, a second head that declines the rejects instead of the country head):

```powershell
$prev = "v3"; $new = "v4"
Copy-Item "configs\ocr_$prev.yaml" "configs\ocr_$new.yaml"
```

In `configs\ocr_<new>.yaml` change the header comment, `run_name`, and when the data or the crops change
(new batches, margin, jitter, `reject`) `dataset.name` to a new name such as `ocr_128x64_v2`. Then:

```powershell
uv run anpr-train-ocr --config "configs\ocr_$new.yaml"
uv run anpr-eval-ocr --config "configs\ocr_$new.yaml"     # only to re-evaluate a finished run
```

A run takes about half an hour (with rejects, nearly twice as many crops: up to an hour). If one is
interrupted, delete its `runs\ocr\<run>` folder (after a look) and run the training command again.

### Detector and OCR together

```powershell
$det = "v2"; $ocr = "v3"
uv run anpr-eval-pipeline --detector "configs\detector_$det.yaml" --ocr "configs\ocr_$ocr.yaml"
```

The detector run must have been evaluated (`anpr-eval-detector`), since its operating threshold comes from there.

### Publishing a version for the devices

The edge devices download models from the models bucket (Terraform output `models_bucket_name` of
`infrastructure/envs/dev`); the run name is the version. The upload uses your AWS credentials.

```powershell
uv run anpr-export-detector --config configs\detector_v2.yaml   # writes runs\detector\v2\model.onnx
uv run anpr-publish-model detector v2 --bucket <models bucket>
uv run anpr-publish-model ocr v3 --bucket <models bucket>      # model.onnx and plate_config.yaml of the run
```

Publishing changes no device: a device runs the versions of its configuration in device-management
(`models.detector`, `models.ocr`, View 4), which accepts only published versions, and switches to new ones without
a restart.

### Analysis of a version

```powershell
uv run jupyter lab                    # open a notebook with Open With -> Notebook
```

| Notebook | First cell |
|---|---|
| `notebooks/01_detector.py` | `VERSION = "v2"`, `BASELINE = "v1"` (detector) |
| `notebooks/02_ocr.py` | `VERSION = "v2"`, `BASELINE = "v1"` (OCR) |
| `notebooks/03_pipeline.py` | `DETECTOR = "v2"`, `OCR = "v2"`, `BASELINE_DETECTOR = "v2"`, `BASELINE_OCR = "v1"` |

Set the versions and run all cells. For PyCharm, create or refresh the paired `.ipynb` first (with its tab
closed):

```powershell
uv run jupytext --sync notebooks/02_ocr.py
```

## Layout

```
ml-models/
├── README.md, ML_ASSUMPTIONS.md, CLAUDE.md
├── PLATE_FORMAT.md                 Polish registration numbers per position, from the regulation (verified)
├── pyproject.toml, uv.lock
├── src/anpr_ml/
│   ├── paths.py                    every location the tooling reads or writes
│   ├── tracking.py                 Weights & Biases: one W&B run per training run
│   ├── pipeline.py                 anpr-eval-pipeline: detector + OCR on the val frames
│   ├── publish.py                  anpr-publish-model: a version into the models bucket
│   ├── analysis.py                 notebook helpers: plot style, version selection, config comparison
│   ├── common/
│   │   ├── geometry.py             plate width, boxes from corners, IoU
│   │   ├── preprocess.py           resize_for_detector(), rectify_plate(): same pixels on the Pi
│   │   └── labels.py               splits.json, the validated .jsonl labels, batch names, width buckets
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
│       ├── export.py               anpr-export-detector: ONNX for the edge node, checked against the weights
│       └── report.py               evaluation report in W&B (metrics, validation frames table)
│   └── ocr/
│       ├── backend.py              Keras 3 on the torch backend
│       ├── config.py               run config, pretrained model files (pinned checksums), run state
│       ├── dataset.py              anpr-ocr-dataset
│       ├── train.py                anpr-train-ocr
│       ├── readability.py          the readability head (second head: readable / unreadable)
│       ├── export.py               ONNX export without TensorFlow
│       ├── predict.py              ONNX Runtime inference, as on the Pi
│       ├── metrics.py              exact match, CER, per position, confusions, confidence coverage
│       ├── evaluate.py             anpr-eval-ocr
│       └── report.py               evaluation report in W&B (metrics, val crops table)
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
are distributed through S3 (`anpr-publish-model`).

## Notebooks

Notebooks are [jupytext](https://jupytext.readthedocs.io/) percent-format `.py` files paired with a gitignored
`.ipynb` that holds the outputs. Open them with `uv run jupyter lab` (*Open With -> Notebook*), or open the
`.ipynb` in PyCharm and sync afterwards with `uv run jupytext --sync notebooks/<name>.py` (with the notebook
closed in the IDE, which otherwise saves over the sync).

| Notebook | Analyses | Versions in the first cell | Environment overrides |
|---|---|---|---|
| `01_detector.py` | one detector run against a baseline run | `VERSION`, `BASELINE` | `ANPR_DETECTOR_VERSION`, `ANPR_DETECTOR_BASELINE` |
| `02_ocr.py` | one OCR run on the val crops against a baseline run | `VERSION`, `BASELINE` | `ANPR_OCR_VERSION`, `ANPR_OCR_BASELINE` |
| `03_pipeline.py` | a detector + OCR pair end to end against a baseline pair | `DETECTOR`, `OCR`, `BASELINE_DETECTOR`, `BASELINE_OCR` | `ANPR_PIPELINE_DETECTOR`, `ANPR_PIPELINE_OCR`, `ANPR_PIPELINE_BASELINE_DETECTOR`, `ANPR_PIPELINE_BASELINE_OCR` |

The shared helpers (plot style, version selection, config comparison) are in `anpr_ml.analysis`. The written
conclusions are kept in `notebooks/conclusions/` (`detector_<v>.md`, `ocr_<v>.md`, `pipeline_<det>__<ocr>.md`)
and shown at the end of each notebook.

Frames, crops and plate texts are personal data. Cells that draw frames or crops run only when
`ANPR_SHOW_IMAGES` is not `0`, and reports in `notebooks/reports/` are executed with `ANPR_SHOW_IMAGES=0`; the
tables that reach a report identify errors by frame and width, never by plate text. The environment overrides
replace the first cell, so a report needs no edit of the notebook (`none` as a baseline means no comparison):

```powershell
$env:ANPR_SHOW_IMAGES = "0"; $env:ANPR_DETECTOR_VERSION = "v1"; $env:ANPR_DETECTOR_BASELINE = "v0"
uv run jupytext --to ipynb --output notebooks/reports/01_detector_v1.ipynb notebooks/01_detector.py
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/reports/01_detector_v1.ipynb
```

## Experiment tracking

Runs are tracked in private Weights & Biases projects (`wandb` section of the config), `anpr-detector` and
`anpr-ocr`: hyperparameters, epoch metrics, the final evaluation and, for reviewing errors, a table of the
validation frames with labels and predictions drawn (detector) or of the validation crops with their true and
read text (OCR). Validation frames and crops are the only images that leave the machine.

## Quality checks

```powershell
uv run pytest
uv run ruff check src tests notebooks
```
