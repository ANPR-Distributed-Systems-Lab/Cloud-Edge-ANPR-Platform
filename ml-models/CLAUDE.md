# ml-models: guide for Claude Code

This directory holds everything about the license plate models of the edge node: dataset preparation, labeling,
the detector (plate with 4 corners) and, after it, the OCR. A session working here deals with `ml-models/` only;
the cloud services, the infrastructure and the Raspberry Pi app have their own sessions. The rules of the root
[CLAUDE.md](../CLAUDE.md) still apply (Conventional Commits, comments, testing levels, model weights in S3).

Read these first; this file does not repeat them:

- [README.md](README.md): the pipeline, every command and the code layout.
- [ML_ASSUMPTIONS.md](ML_ASSUMPTIONS.md): the decisions (models, resolutions, metrics, deployment) and the
  **OPEN** items with how each gets decided.
- [labeling/README.md](labeling/README.md): the labeling rules and the CVAT workflow.

When a decision changes, update those documents in the same change, so they never contradict the code.

## Ways of working

- The ML work has a single owner, who makes the design decisions. Conversation is in Polish; code, comments and
  documents are in English and written impersonally (no names of people).
- Explain what each command or design choice does and why. Decisions on thresholds, split sizes, what to label
  and model choices belong to the owner: ask, with a recommendation rather than a survey.
- **Never commit or push.** Propose a Conventional Commit message instead (scope `ml-models`).
- Before deleting or overwriting anything, look at it first and ask.

## Rules that protect the data

- **Never destroy labeling state.** `labeling/splits.json`, `labeling/selected.csv`, `labeling/frame_index.csv`,
  the batch folders, the exports and the CVAT docker volumes are the result of hours of manual work. Back them up
  before any change, prefer append-only operations, and verify afterwards that nothing old changed.
- `splits.json` never changes for existing sessions (it keeps the test sessions out of training); new sessions
  are added with `anpr-splits --add`. `selected.csv` is append-only.
- CVAT runs only through `labeling/cvat.ps1`, which pins the `desktop-linux` Docker context. **Never start CVAT
  or any heavy container on the `rpi` context.** Never `docker compose down -v`.
- The test split is never enriched, never labeled with model suggestions and never used for a decision.
- Datasets (`datasets/<name>/`) and runs (`runs/detector/<run>/`) are never overwritten: a change gets a new name.
- Frames leave the PC only as the validation frames table in the private W&B project (decided 2026-11-05).
  No training images, raw data or crops are uploaded, and no frame appears in anything committed to git.

## Code conventions

- `anpr_ml` is split by stage: `common` (geometry, preprocessing, label files), `labeling`, `detector`, plus
  `tracking` (W&B) and `paths`. The OCR gets its own subpackage mirroring `detector` (config, dataset, train,
  predict, metrics, evaluate, report).
- Each command is a module with a `main()` registered as an `anpr-*` entry point in `pyproject.toml`; its module
  docstring is the `--help` text.
- torch, Ultralytics and wandb are imported inside functions, so the labeling tools and the unit tests run
  without them.
- Training always runs from a terminal (`anpr-train-detector`), never in a notebook; notebooks analyse finished
  runs through the same functions the commands use.
- Unit tests in `tests/` use synthetic data only (`tests/samples.py`): no GPU, network or real frames.
- Quality checks for code changes: `uv run pytest` and `uv run ruff check src tests notebooks`.

## Environment

- Windows 10, PowerShell (Git Bash is also available). Paths are relative to `ml-models/`.
- Python 3.11, environment managed by **uv**, separate from `rpi-edge`. Groups `dev` (pytest, ruff), `train`
  (torch 2.14 + CUDA 12.6 from the PyTorch index pinned in `pyproject.toml`, torchvision, ultralytics 8.4, wandb)
  and `notebook` (jupyterlab, jupytext, ipykernel, matplotlib, pandas); all installed by default. ONNX and
  onnxruntime are not installed yet.
- The uv cache defaults to C: (too small for torch). Run uv with `$env:UV_CACHE_DIR = "G:\uv-cache"`, or set it
  as a user environment variable.
- Disk C: is almost full (around 10 GB free). The data lives on G:. Do not put large temporary files on C:.
- Ultralytics settings live in `%APPDATA%\Ultralytics\settings.json`. `wandb` must stay `False` there: all W&B
  logging goes through `anpr_ml.tracking`; `check_integrations()` refuses to train otherwise.
- W&B: `uv run wandb login` once per machine (the account owner enters the API key). wandb 0.31 logs tables as
  artifacts and stages their images locally before upload; `anpr_ml.tracking` points `WANDB_DATA_DIR`,
  `WANDB_CACHE_DIR` and `WANDB_ARTIFACT_DIR` to `runs/wandb-local/` so nothing lands on C:.
- Training PC: i5-9600KF, 32 GB RAM, **GTX 1660 Super** (6 GB, no tensor cores), NVIDIA driver 566.14.
  Ultralytics disables AMP on it (FP32). At 1280 px batch 4 fits (3.6 GB), batch 8 does not, and
  `deterministic=True` needs ~10 GB. Beyond 6 GB Windows silently spills into system RAM and training becomes
  10x slower: watch `GPU_mem` in the log.
- Training is GPU-bound: more dataloader workers or `cache: ram` do not speed it up, so configs keep `workers: 2`.
  CVAT can run during training; leave its heavy operations (task creation, imports, exports) for before or after.
- PyCharm keeps a paired `.ipynb` open and saves it over jupytext's sync: close the tab before
  `uv run jupytext --sync notebooks/<nb>.py`.

## Data

- Recorded by the data-collection app in `rpi-edge` (see `rpi-edge/DATA_COLLECTION.md`): 4056x3040 JPEG,
  2-3 fps, JPEG quality 92-95. Each session has `session.json` (camera and recording settings) and `frames.csv`
  (file, UTC time, sensor timestamp, exposure, gains, white balance, lux, bytes). Frames sit in numbered
  subfolders (`0000/img_000000.jpg`).
- **49 sessions, 52 289 frames** indexed: 28 sessions from 2026-10-04 to 2026-10-09 and 21 from 2026-10-20.
  Split: 35 train, 7 val, 7 test sessions, seed 42.
- `anpr-select` does not look at the content (no plate check, no distance or angle balance), although
  ML_ASSUMPTIONS describes a content-aware selection; it is deliberately kept simple for now.

## Labeling decisions taken during train_001

These refine the documents above (which are already updated):

- Small-plate threshold lowered from 80 to **70 px** on the original (`SMALL_PLATE_PX = 70` in
  `anpr_ml.common.labels`), because plates of 70 px and more were often still readable. Final confirmation is
  still open (histogram, detector input size).
- From 70 px up a plate is labeled `plate` with honest `readable` / `text`, even when hard to read. Turning a
  `plate` into an ignore region later is lossless; the opposite is not (`plate_ignore` has no attributes). The
  `readable` values per width will measure the real OCR range (the 100 px assumption looks too strict).
- Below 70 px: `plate_ignore` if it is still recognizable as a plate. Specks that cannot be told from other white
  shapes (well under ~30 px) are left unlabeled, as background.
- Plates cut off by the frame edge: `plate_ignore`.
- Close oncoming cars on the left (the most valuable case in ML_ASSUMPTIONS) are rare in uniformly sampled
  batches: in train_001 only 31 plates of 200 px or more, 11 of them in the left third of the frame. Decision for
  now: no enrichment. Later, use detector v0 predictions to pick such frames for training batches. Never enrich
  the test set; it must reflect the real distribution.

## Current state (2026-11-06)

- **train_001**: 300 frames from the train split, labeled by hand, validated with 0 errors. 180 `plate`,
  186 `plate_ignore`; plate width min 70, median 121, p90 236, max 525 px.
- **val_001**: 150 frames from all 7 val sessions, selected with threshold 5, labeled by hand like the test set
  (uniform, no frames removed, no model suggestions), validated with 0 errors. 103 `plate`, 144 `plate_ignore`;
  plate width min 71, median 122, p90 205, max 515 px.
- **Dataset `pose_1280x960_v0`** built from train_001 + val_001 (train 300 frames / 178 plates, 2 plates of 69.x px
  demoted to ignore; val 150 / 103). Negatives (no plate to learn) are 59 % of train and 55 % of val.
- **Detector v0** (`configs/detector_v0.yaml`, `runs/detector/v0`): finished, 150 epochs in 0.85 h, best epoch 122. On val_001 (103 plates, unpainted frames, best F1
  at conf 0.45): precision 0.971, recall 0.981 (3 FP, 2 FN, both misses at 90-110 px), corner error median 2.8 px
  / p90 6.3 px on the original (p90 4.6 % of plate width); box mAP50-95 0.764, pose mAP50-95 0.984. Reported to
  W&B (`anpr-detector`, run `v0`, with the val frames table). The written conclusions in the notebook and the
  report in `notebooks/reports/` are still to do; the 3 false positives and 2 misses are not reviewed yet.
- **test_001 does not exist yet**: ~150 frames from the test split, labeled from scratch, never with
  model suggestions.
- The detector v0 work, the W&B tracking and the dataset definition (`splits.json`, `selected.csv`) are
  committed. Uncommitted: the package restructuring (`common` / `labeling` / `detector`, README.md) and this file,
  which is not tracked yet.

## Roadmap

The order agreed so far; confirm each step with the project owner before starting it.

1. Commit the package restructuring.
2. Create and label `test_001` (test split, ~150 frames, from scratch). More train batches as needed (`train_002`).
3. **Done (2026-11-05):** converter `anpr-yolo-dataset` (`.jsonl` -> YOLO-pose, offline `resize_for_detector()`,
   `plate_ignore` painted gray, small-plate threshold applied). The Pi must reproduce `resize_for_detector()`
   exactly; `tests/test_common.py` holds a golden checksum for that.
4. **Done (2026-11-06):** detector v0 = YOLO11n-pose at 1280x960, `fliplr = 0`, FP32, trained with
   `anpr-train-detector` and tracked in W&B. Left: review of its errors, written conclusions, report.
5. Pre-labeling loop: predictions exported as CVAT for images 1.1 XML, imported as pre-annotations, corrected.
6. Pi 5 latency benchmark at 1024x768 / 1280x960 / 1920x1440 to close the detector input size.
7. OCR: rectified crops (about 256x56) cut from the full-resolution frame with corner jitter, `fast-plate-ocr`
   baseline, a written and verified document of the Polish per-position character rules, then the final model.
8. Export both models to ONNX. The S3 bucket for model distribution does not exist in `infrastructure/` yet; that
   belongs to the infrastructure session.
