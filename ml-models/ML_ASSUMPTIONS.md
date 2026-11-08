# ML assumptions: plate detection and OCR

Working assumptions for building the Polish license plate models (detection with 4 corners, then OCR).
Last updated: 2026-11-06. Items marked **OPEN** are deliberately undecided, see the last section.

## 1. Decision summary

| Area | Decision |
|---|---|
| Labeling tool | CVAT, self-hosted (docker) |
| Pre-labeling | Iterative loop with our own model |
| Detection model | YOLO11n-pose (Ultralytics), 1 class, 4 keypoints (plate corners); YOLO26n-pose compared at the Pi benchmark |
| OCR model | `fast-plate-ocr` as baseline. Final model **OPEN** (needs per-position character rules) |
| Labeling resolution | Original frames, 4056x3040 |
| Detector input resolution | **OPEN**, 1280x960 for detector v0; final after a benchmark on the Pi |
| Ignore regions in training | Painted gray (114) in the downscaled train and val images |
| Frame selection | Perceptual-hash deduplication, then diverse frames that contain plates |
| Test set | ~150 frames from separate sessions, labeled from scratch |
| Data storage | Local only |
| Training hardware | Local PC: i5-9600KF, GTX 1660 Super |
| Experiment tracking | Weights & Biases, private project; metrics plus validation frames for review |
| Notebooks | jupytext `.py` committed, outputs in a gitignored `.ipynb`; reports in `notebooks/reports/` without frames |
| Inference runtime on the Pi | ONNX Runtime |
| Document language | English |

## 2. Code organization

The directory layout and every command are described in [README.md](README.md).

- The environment is separate from `rpi-edge` (torch and Ultralytics are heavy). Reusable logic lives in the `anpr_ml` package (`common`, `labeling`, `detector`); notebooks import it and never reimplement it.
- Training runs from a terminal with `anpr-train-detector --config configs/<config>.yaml`, never inside a notebook: a run of an hour or more must not depend on a kernel or an IDE, and the command plus the config make it reproducible. One config per run; finished runs and built datasets are never overwritten.
- Per the repository-wide standards, model weights (`.onnx`) are not stored in the repository. The edge node downloads them from S3 at startup.

### Notebooks in git

- The `.py` file (jupytext percent format) is committed. The paired `.ipynb` working copy, which holds the outputs, is gitignored, so no output-stripping filter is needed.
- `notebooks/reports/` holds executed reports, committed with their outputs (tables, learning curves, histograms) so GitHub renders them.
- **No frames or crops in committed notebooks** (decided 2026-11-05): license plates are personal data. Cells that draw frames run only when `ANPR_SHOW_IMAGES` is not `0`; reports are executed with `ANPR_SHOW_IMAGES=0`.

## 3. Data

### Storage
- Images and labels are stored **locally only** (the ML work is owned by one person). There is no cloud copy and no DVC.
- Keep a second copy of the dataset and of exported CVAT annotations on a separate disk.
- The repo contains only code, configs and, optionally, a manifest (file name, size, checksum).
- Experiment tracking: metrics and hyperparameters go to W&B. **Exception decided on 2026-11-05:** the private W&B project (accessible to the project owner only) also receives the validation frames of each evaluated run, with labels and predictions drawn, as a sortable table for visual error review. No training images, crops or raw data are uploaded, and frames never appear in anything committed to git. Ultralytics' built-in W&B integration stays off (`yolo settings wandb=False`, the default); everything sent is chosen in `anpr_ml.tracking`.

### Frame selection
- Source: frames recorded by the data-collection app (`rpi-edge`), full resolution 4056x3040 JPEG.
- Remove near-duplicates with a perceptual hash, for example when the car is stationary. The Hamming-distance threshold was tuned by eye on a sample: a frame is kept when its 64-bit dHash differs from the last kept frame by at least 5 bits (`train_001` was selected with 8, which dropped too many frames that differed in content).
- From what remains, pick diverse frames (distance, angle, lighting, road type) that contain at least one plate. Frames without plates are kept only as a small share of negatives.
- Always split by **recording session**, never by frame. Consecutive frames are almost identical, so a random split inflates validation results.

### Test set
- ~150 frames from sessions that never appear in training or validation.
- Labeled from scratch, without model suggestions. Never used to train a pre-labeling model.
- Train / validation / test are all split by session.

## 4. Labeling

### Tool and resolution
- Tool: CVAT, self-hosted with docker compose.
- Label on the **original 4056x3040 frames**: the corners drive the perspective transform, so accuracy matters. Far plates also need zoom anyway.
- Stored coordinates are **normalized (0-1)**, so changing resolution later does not break labels. The converter divides CVAT pixel coordinates by the image size.
- If the browser becomes too slow with 12 MP images, fall back to 2028x1520 copies. Normalized labels map exactly back to the originals (error about 1 px).

### Annotation scheme
Each plate is a polygon with exactly **4 points** (set as "Number of points = 4" when drawing in CVAT; `anpr-validate` enforces it on export). The operational rules are in [labeling/README.md](labeling/README.md).

- **Corner order:** TL, TR, BR, BL, clockwise, relative to the plate itself, not the image. Start at the plate's own top-left corner.
- **Corner position:** the intersection of the plate's outer edges, not the rounded corner.
- **Attributes:**
  - `text`: the plate number, uppercase, no spaces.
  - `readable`: yes / no. Unreadable plates stay in detection data but are excluded from OCR.
  - `occlusion`: none / partial (named so it does not clash with CVAT's built-in `occluded` flag).
  - `type`: standard / two-line / motorcycle / other (values fixed in the labeling guide).
- **Small plates:** plates narrower than about **70 px on the original** are not labeled as regular plates. They get a separate label (`plate_ignore`, 4 points, no text) so the detector is not trained on noise. 70 px is about 22 px at a 1280 px detector input (33 px at 1920), near the ~30 px a keypoint detector needs. The first batch (`train_001`) started at 80 px, and was lowered to 70 px because plates of 70 px and wider were often still readable. The threshold is confirmed with a histogram of plate widths after the first ~100 labels.

### Pre-labeling loop
1. Label ~150-300 frames by hand to bootstrap.
2. Train detector v0, predict on the next ~500 frames, import the predictions into CVAT as pre-annotations (CVAT for images 1.1 XML with attributes), correct them.
3. Retrain, repeat until corrections become rare.
4. Text: run a pretrained OCR on the rectified crops to pre-fill `text`, then correct by hand.
5. Guard against accepting model mistakes without looking: spot-check, and keep the test set independent of the loop.
6. Validate exports with a script: exactly 4 points per plate, valid corner order (positive area, clockwise), `text` present when `readable = yes`, text matches the allowed character set.

## 5. Resolution and geometry

Sensor pixel pitch 1.55 um, lens 6 mm, so the focal length is about 3870 px. A Polish plate is about 0.52 m wide, so on the original frame its width is about **2013 / distance[m]** px (plate facing the camera; angled plates are narrower by cos(angle)).

| Distance | Original | 1920 px wide | 1280 px wide | 960 px wide |
|---|---|---|---|---|
| 5 m | 403 | 191 | 127 | 95 |
| 10 m | 201 | 95 | 63 | 48 |
| 20 m | 101 | 48 | 32 | 24 |
| 30 m | 67 | 32 | 21 | 16 |
| 40 m | 50 | 24 | 16 | 12 |

Rules of thumb used for the decisions below:
- OCR needs roughly 100 px of plate width (character height >= 20-25 px), which gives a useful range of about 20 m on the original frame. Labeling of `train_001` suggests the real range is wider: some plates of 70 px and more are readable. Re-measure it from `readable` against plate width once enough labels exist.
- A keypoint detector needs roughly 30 px of plate width.
- At 1280x960 the detection range (about 20-25 m) matches the OCR range, so it is the leading candidate for the detector input.

These are theory-based estimates. After the first ~100 labels, compare them against a histogram of real plate widths.

### Close range (3-5 m), oncoming cars passing on the left
Much of the best data is expected to be oncoming cars passing on the left side of the frame. Notes for that case:
- Plates are huge there (about 400 px on the original at 5 m, 670 px at 3 m by the same formula), far above what OCR needs, so resolution is not a concern. The OCR crop (about 256x56) is a downscale of the original crop.
- The horizontal field of view is about 55 degrees (half-angle 27.6 degrees). An oncoming car in the adjacent lane is roughly 3 m to the side, so its plate leaves the frame at a forward distance of about 3 m / tan(27.6 degrees) = **~6 m**. Distances of 3-5 m are only reachable with a smaller lateral offset (e.g. the camera aimed slightly to the left, or a very close pass).
- The plate is seen at an angle: at 3 m lateral and 5 m forward the line of sight is ~31 degrees off the plate normal, so the apparent width is about 0.86 of the table value and the perspective distortion is strong. These frames are exactly what the 4-corner labels and the perspective transform are for. Make sure the dataset has many of them.
- Plates near the left edge are partially cut off. Label them only if all 4 corners are visible; otherwise draw them as `plate_ignore` (see the labeling guide).
- Capture rate: with a closing speed of about 28 m/s (two cars at ~50 km/h) the cars move ~14 m between frames at 2 fps, so only a few frames per pass fall into this range. Consider a higher recording fps for dedicated passes, within the exposure and storage limits of the collection app.

### Two resolutions in one pipeline
- **Detector:** runs on the frame downscaled to the detector input size (candidates 1024x768, 1280x960, 1920x1440; **OPEN**).
- **OCR:** crops are cut from the **full-resolution frame**, using the detected corners scaled back to the original size. The Pi keeps the full frame in memory (about 18 MB of YUV).

### Train / inference consistency
1. One shared function, e.g. `resize_for_detector()` using `cv2.resize(..., interpolation=cv2.INTER_AREA)`, used both when preparing the dataset and on the Pi. A test checks that both sides produce identical pixels.
2. Downscale the dataset **offline** to the exact detector input size, so the training library does not resample again.
3. On the Pi, take the full frame from the `main` stream and resize it ourselves. Do not use the ISP-scaled `lores` stream: its scaling filter differs from `INTER_AREA`.
4. The dataset is JPEG (quality 92) while live frames are not. After a 3x downscale the difference is negligible. Mild JPEG augmentation can be added for OCR crops.

## 6. Detection model

- **Model:** YOLO11n-pose, 1 class (`plate`), 4 keypoints (`kpt_shape: [4, 3]`), starting from COCO-pose weights (the keypoint head is rebuilt). Chosen for v0 as the mature option; YOLO26n-pose (NMS-free, built for edge CPUs) is compared at the Pi benchmark.
- **Ignore regions:** Ultralytics has no ignore label, so `plate_ignore` regions and plates below the small-plate threshold are painted gray (114, the letterbox color) with a 3 px margin in the downscaled train and val images; pixels of real plates are never painted. The evaluation on original frames (unpainted) drops detections on those regions instead of counting them as false positives.
- **Label format:** `0 cx cy w h x1 y1 v1 x2 y2 v2 x3 y3 v3 x4 y4 v4`, all normalized. The box is derived from the 4 corners. `v` is the visibility flag.
- **Augmentation:** horizontal flip is disabled (`fliplr = 0`), because a mirrored plate is not a real case and would swap the TL/TR corner order.
- **Input size:** **OPEN**. Candidates 1024x768, 1280x960, 1920x1440. All are divisible by 32.
- **Licensing:** Ultralytics models are AGPL-3.0. Acceptable for the thesis; reconsider before any commercial use. The label format is model-neutral, so switching to an Apache-2.0 alternative (e.g. RTMPose or RF-DETR based) stays possible.
- **Hardware caveat:** the GTX 1660 Super has 6 GB VRAM and no tensor cores. Measured at 1280 in FP32: batch 4 needs 3.6 GB per training step, batch 8 needs 7.2 GB, so v0 trains with batch 4 (gradients accumulate to 64 images). Deterministic cuDNN kernels (`deterministic=True`) need about 10 GB at batch 4 and are 8x slower, so they are off: runs with the same seed are close but not bit-identical. Mixed precision is unreliable on 16-series cards: Ultralytics' AMP check disables it on the GTX 1660 Super, so training runs in FP32 (confirmed on the first run, 2026-11-05).
- **Export:** ONNX, run with ONNX Runtime on the Pi.

## 7. OCR model

- **Input:** the plate rectified with a perspective transform from the 4 corners to a fixed size. The aspect ratio of a standard plate is about 4.5:1 (520x114 mm), so about **256x56 px** is the working size (final value depends on the model).
- **Baseline:** `fast-plate-ocr` (MIT), fine-tuned on Polish plates, ONNX.
- **Final model: OPEN.** The target model should encode Polish plate rules, e.g. which characters may appear in the district code and in which positions of the registration number. Candidate approaches:
  - generic model plus rule-based post-processing (regex or per-position masks),
  - constrained decoding (per-slot output heads or masked CTC),
  - alternatives to `fast-plate-ocr`: PaddleOCR PP-OCRv5 recognition model, or a custom CRNN/CTC in PyTorch.
- **Rules document:** the exact character rules per position must be written down and verified against official sources before they are used.
- **Training data:**
  - rectified real crops from verified labels (only `readable = yes`),
  - **corner jitter** (a few pixels) when rectifying during training, so OCR tolerates detector inaccuracy,
  - synthetic Polish plates (layout, EU strip, random characters, perspective, blur, noise) are likely and mixed with real data. Exact ratio decided after the baseline.
- **Export:** ONNX.

## 8. Metrics

Thresholds (acceptance criteria) are set after the first baseline run. Until then these are reported:

**Detection**
- mAP (box and keypoint/OKS),
- mean corner error in pixels on the original frame and as a fraction of plate width,
- recall by plate size bucket (width in px on the original).

**OCR**
- exact-match accuracy of the whole plate,
- character error rate (CER),
- confusion matrix (e.g. 0/O, 1/I, 8/B), and errors per position.

**End to end**
- plate read correctly from frame to text, on the test set, split by distance/size bucket.

Development decisions (checkpoints, thresholds, model variants) are made on the val split; the reported numbers are computed once on the session-split test set, which no decision has seen. Metrics are logged to Weights & Biases as described in section 3.

## 9. Deployment on the Pi

- Runtime: ONNX Runtime for both models.
- Models are downloaded from S3 at startup (repository-wide edge MLOps standard).
- Pipeline: full-resolution frame from the `main` stream, `resize_for_detector()`, detector, corners scaled back to the original, perspective crop, OCR.
- Logging: structured JSON, per project convention.
- Benchmark to run before fixing the detector input size: a nano model at 1024x768, 1280x960 and 1920x1440 on the Pi 5, measuring latency. Required frame rate in the car is the deciding input (2-3 fps is assumed to be enough).

## 10. Open items

| # | Item | How it gets decided |
|---|---|---|
| 1 | Detector input resolution | Pi 5 latency benchmark, plus plate-width histogram from real labels |
| 2 | Final OCR model and rule handling | After the baseline, once per-position character rules are written down |
| 3 | Share of synthetic data for OCR | After the baseline, based on errors on rare characters |
| 4 | Small-plate threshold (~70 px on the original) | Histogram after the first ~100 labels |
| 5 | Metric acceptance thresholds | After the first baseline run |
| 6 | Perceptual-hash distance threshold for deduplication | **Decided 2026-11-04: 5** (kept at a distance of 5 or more), after a visual review of kept and dropped frames in 4 train sessions |
| 7 | Mixed precision on the GTX 1660 Super | **Decided 2026-11-05: off.** Ultralytics disables AMP on this GPU; training is FP32 |
