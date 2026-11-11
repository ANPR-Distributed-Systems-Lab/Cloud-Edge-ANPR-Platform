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
- Datasets (`datasets/<name>/`) and runs (`runs/detector/<run>/`, `runs/ocr/<run>/`) are never overwritten: a
  change gets a new name.
- Images leave the PC only as the validation frames table (`anpr-detector`, decided 2026-11-05) and the
  validation crops table (`anpr-ocr`, decided 2026-11-09) in the private W&B projects. No training images,
  training crops or raw data are uploaded, and no frame, crop or plate text appears in anything committed to git.

## Code conventions

- `anpr_ml` is split by stage: `common` (geometry, preprocessing, label files), `labeling`, `detector`, `ocr`
  (mirrors `detector`: config, dataset, train, export, predict, metrics, evaluate, report), `pipeline` (both
  models together), plus `tracking` (W&B), `analysis` (notebook helpers) and `paths`.
- Each command is a module with a `main()` registered as an `anpr-*` entry point in `pyproject.toml`; its module
  docstring is the `--help` text.
- torch, Ultralytics, Keras, fast-plate-ocr and wandb are imported inside functions, so the labeling tools and the
  unit tests run without them. Keras is only ever imported through `anpr_ml.ocr.backend.keras_torch()`, which
  selects the torch backend first (Keras defaults to TensorFlow, which is not installed).
- The OCR export reuses two internal helpers of fast-plate-ocr, so its version is pinned exactly; check
  `anpr_ml.ocr.export` before upgrading it.
- Training always runs from a terminal (`anpr-train-detector`, `anpr-train-ocr`), never in a notebook; notebooks
  analyse finished runs through the same functions the commands use. One notebook per model plus
  `03_pipeline.py` for the pair; versions are variables in the first cell.
- Unit tests in `tests/` use synthetic data only (`tests/samples.py`): no GPU, network or real frames.
- Quality checks for code changes: `uv run pytest` and `uv run ruff check src tests notebooks`.

## Environment

- Windows 10, PowerShell (Git Bash is also available). Paths are relative to `ml-models/`.
- Python 3.11, environment managed by **uv**, separate from `rpi-edge`. Groups `dev` (pytest, ruff), `train`
  (torch 2.14 + CUDA 12.6 from the PyTorch index pinned in `pyproject.toml`, torchvision, ultralytics 8.4, wandb)
  `ocr` (fast-plate-ocr 1.1.0, keras 3, albumentations, onnx, onnxscript, onnxruntime; no TensorFlow) and
  `notebook` (jupyterlab, jupytext, ipykernel, matplotlib, pandas); all installed by default. Only `opencv-python`
  is installed: the `opencv-python-headless` that fast-plate-ocr and albumentations ask for is overridden away in
  `pyproject.toml`, because both ship the same `cv2` package.
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

## Current state (2026-11-10)

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
- **train_002**: 300 more train frames, validated. **Detector v1** (`configs/detector_v1.yaml`: v0 plus
  train_002, 600 frames / 400 plates, otherwise unchanged): finished; on val_001 precision and recall 1.000 at
  conf 0.40, corner error median 2.2 px / p90 4.8 px. val_001 no longer separates detectors: a larger val set
  (val_002) is needed for the next comparisons.
- **OCR**: readable plates train 270 (183 texts), val 145 (val_001 + val_002, 65 texts), all `standard`. Dataset
  `ocr_128x64_v0` (train 2160 jittered crops, val 145). **OCR v0** (pretrained, `configs/ocr_v0.yaml`): finished,
  val exact 0.945 (137 of 145), CER 0.011, reported to W&B `anpr-ocr`. **OCR v1** (`configs/ocr_v1.yaml`,
  fine-tuning): finished, best epoch 34 of 54 (early stop), val exact 0.952 (138 of 145), CER 0.007.
  **Pipeline detector v2 + OCR v0 / v1**: 134 / 137 of 143 readable val plates (at or above 70 px) read right;
  every detection is read, so 61 reads of unreadable plates, 92 of don't-care regions and 2 of background come
  out too. v1 is confident on them (median conf on unreadable plates 0.80, v0 0.51), so confidence alone does not
  stop them (precision of sent reads at conf 0.95: v0 0.93, v1 0.81).
- **Send rule analysis (2026-11-10, scratch scripts, nothing committed)**: on val, a width of at least 70 px and
  10 px from the frame edge removes 49 of 297 reads and no correct one; the Polish format (2-3 letter county code
  plus the official vehicle-part patterns, 412 of 415 labeled texts pass, 3 special shapes do not) removes most
  garbage with v0 but little with v1; requiring the same text in a neighboring raw frame (+-2, ~0.7 s) removes
  wrong reads and most don't-care reads, but not unreadable plates: v1 reads the same text on them in consecutive
  frames of moving cars. Hence OCR v2 with rejects. Recommended shape of the rule on the Pi (not decided): geometry
  before OCR, format and confidence per frame, then one event per tracked pass with agreement across frames.
- **OCR v2** (`configs/ocr_v2.yaml`): v1 plus rejects (empty text, region Unknown) from unreadable plates and
  `plate_ignore` regions of at least 70 px. Dataset `ocr_128x64_v1` built: train 2160 readable crops (byte-identical
  to `ocr_128x64_v0`) + 936 unreadable + 888 ignore; val 145 + 62 + 75. **Trained (2026-11-10):** best epoch 12 of
  32 (val loss rises after it: the rejects are memorized), readable val crops exact 0.917 (133 of 145, v1 138),
  CER 0.032, 5 reads of the wrong length, 0 read as no text; 102 of 137 val rejects read as no text. Behind
  detector v2: 132 of 143 readable plates read right (v1 137), 4 of them read as no text; no text on 32 of 61
  unreadable plates and 78 of 92 don't-care regions. With width >= 70 px, the format check and conf >= 0.8: v2
  precision 0.90 / recall 0.88 (v0 0.88 / 0.90, v1 0.78 / 0.95); agreement across frames adds nothing for v2.
  Rejecting with an empty text costs reading quality; not decided which OCR goes on.
- **test_001 does not exist yet**: ~150 frames from the test split, labeled from scratch, never with
  model suggestions.
- **val_002** is labeled (150 frames, 72 readable plates) and `configs/detector_v2.yaml` (v1 plus val_002 for
  validation) is committed; detector v2 on val_001 + val_002 (207 plates): precision and recall 0.986 at conf
  0.40 (3 FP, 3 FN). The OCR configs and the pipeline validate on val_001 + val_002 too.
- Committed: the package restructuring, detector v1 and v2 configs, the version-agnostic detector notebook, the
  OCR and pipeline code (v0 / v1), `anpr_ml.analysis` and notebooks 02 / 03. Uncommitted: the OCR rejects (v2).

## Roadmap

The order agreed so far; confirm each step with the project owner before starting it.

1. **Done (2026-11-08):** commit the package restructuring.
2. Create and label `test_001` (test split, ~150 frames, from scratch). More train batches as needed (`train_002`).
3. **Done (2026-11-05):** converter `anpr-yolo-dataset` (`.jsonl` -> YOLO-pose, offline `resize_for_detector()`,
   `plate_ignore` painted gray, small-plate threshold applied). The Pi must reproduce `resize_for_detector()`
   exactly; `tests/test_common.py` holds a golden checksum for that.
4. **Done (2026-11-06):** detector v0 = YOLO11n-pose at 1280x960, `fliplr = 0`, FP32, trained with
   `anpr-train-detector` and tracked in W&B. Left: review of its errors, written conclusions, report.
5. Pre-labeling loop: predictions exported as CVAT for images 1.1 XML, imported as pre-annotations, corrected.
6. Pi 5 latency benchmark at 1024x768 / 1280x960 / 1920x1440 to close the detector input size.
7. OCR. **Done (2026-11-09):** rectified 128x64 crops with an 8 % margin and corner jitter (`anpr-ocr-dataset`),
   fast-plate-ocr `cct-s-v2-global` on Keras 3 + torch with ONNX export (`anpr-train-ocr`), baseline v0, the
   end-to-end evaluation (`anpr-eval-pipeline`) and notebooks 02 / 03. **Done (2026-11-10):** v1 trained, rejects
   added (v2 configured). Left: train v2, the send rule on the Pi (geometry, format, agreement across frames), a
   written and verified document of the Polish per-position character rules, then the final model.
8. Export both models to ONNX (OCR: done by `anpr-train-ocr`). The S3 bucket for model distribution does not exist in `infrastructure/` yet; that
   belongs to the infrastructure session.
