# ML assumptions: plate detection and OCR

Working assumptions for building the Polish license plate models (detection with 4 corners, then OCR).
Last updated: 2026-10-11. Items marked **OPEN** are deliberately undecided, see the last section.

## 1. Decision summary

| Area | Decision |
|---|---|
| Labeling tool | CVAT, self-hosted (docker) |
| Pre-labeling | Iterative loop with our own model |
| Detection model | YOLO-pose, nano size, 1 class, 4 keypoints (plate corners) |
| OCR model | `fast-plate-ocr` as baseline. Final model **OPEN** (needs per-position character rules) |
| Labeling resolution | Original frames, 4056x3040 |
| Detector input resolution | **OPEN**, decided after a benchmark on the Pi |
| Frame selection | Perceptual-hash deduplication, then diverse frames that contain plates |
| Test set | ~150 frames from separate sessions, labeled from scratch |
| Data storage | Local only |
| Training hardware | Local PC: i5-9600KF, GTX 1660 Super |
| Experiment tracking | Weights & Biases |
| Notebooks | jupytext `.py` + nbstripout + `notebooks/reports/` |
| Inference runtime on the Pi | ONNX Runtime |
| Document language | English |

## 2. Repository layout

```
ml-models/
├── pyproject.toml, uv.lock       # separate environment from rpi-edge (torch etc. are heavy)
├── ML_ASSUMPTIONS.md             # this file
├── notebooks/                    # jupytext percent-format .py files
│   └── reports/                  # final notebooks, committed WITH outputs
├── src/anpr_ml/                  # reusable logic: data, train, eval, export
├── configs/                      # hyperparameters (YAML)
├── data/                         # gitignored
└── models/                       # gitignored
```

- Notebooks are for exploration and visualization. Anything repeated (loading, splitting, metrics, export) lives in `src/anpr_ml/` and is imported.
- Per CLAUDE.md, model weights (`.onnx`) are not stored in the repository. The edge node downloads them from S3 at startup.

### Notebooks in git

- The `.py` file (jupytext percent format) is committed. Plain `.ipynb` working copies are gitignored.
- Any `.ipynb` that is committed goes through the `nbstripout` git filter (outputs removed).
- `notebooks/reports/` is excluded from the filter in `.gitattributes`. Notebooks there keep their outputs (plots, confusion matrices, example detections) so GitHub renders them.
- `nbdime` is optional for diffing and merging `.ipynb` files.

## 3. Data

### Storage
- Images and labels are stored **locally only** (the ML work is owned by one person). There is no cloud copy and no DVC.
- Keep a second copy of the dataset and of exported CVAT annotations on a separate disk.
- The repo contains only code, configs and, optionally, a manifest (file name, size, checksum).
- Experiment tracking must stay consistent with this: log metrics and hyperparameters to W&B, **do not upload dataset images or crops**.

### Frame selection
- Source: frames recorded by the data-collection app (`rpi-edge`), full resolution 4056x3040 JPEG.
- Remove near-duplicates with a perceptual hash, for example when the car is stationary. The Hamming-distance threshold is tuned by eye on a sample.
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
Each plate is a polygon with exactly **4 points** (CVAT point limit = 4).

- **Corner order:** TL, TR, BR, BL, clockwise, relative to the plate itself, not the image. Start at the plate's own top-left corner.
- **Corner position:** the intersection of the plate's outer edges, not the rounded corner.
- **Attributes:**
  - `text`: the plate number, uppercase, no spaces.
  - `readable`: yes / no. Unreadable plates stay in detection data but are excluded from OCR.
  - `occluded`: none / partial.
  - `type`: standard / two-line / motorcycle / other (values fixed in the labeling guide).
- **Small plates:** plates narrower than about **80 px on the original** are not labeled as regular plates. They get a separate label (`plate_ignore`, 4 points, no text) so the detector is not trained on noise. The threshold is confirmed with a histogram of plate widths after the first ~100 labels.

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
- OCR needs roughly 100 px of plate width (character height >= 20-25 px), which gives a useful range of about 20 m on the original frame.
- A keypoint detector needs roughly 30 px of plate width.
- At 1280x960 the detection range (about 20-25 m) matches the OCR range, so it is the leading candidate for the detector input.

These are theory-based estimates. After the first ~100 labels, compare them against a histogram of real plate widths.

### Close range (3-5 m), oncoming cars passing on the left
Much of the best data is expected to be oncoming cars passing on the left side of the frame. Notes for that case:
- Plates are huge there (about 400 px on the original at 5 m, 670 px at 3 m by the same formula), far above what OCR needs, so resolution is not a concern. The OCR crop (about 256x56) is a downscale of the original crop.
- The horizontal field of view is about 55 degrees (half-angle 27.6 degrees). An oncoming car in the adjacent lane is roughly 3 m to the side, so its plate leaves the frame at a forward distance of about 3 m / tan(27.6 degrees) = **~6 m**. Distances of 3-5 m are only reachable with a smaller lateral offset (e.g. the camera aimed slightly to the left, or a very close pass).
- The plate is seen at an angle: at 3 m lateral and 5 m forward the line of sight is ~31 degrees off the plate normal, so the apparent width is about 0.86 of the table value and the perspective distortion is strong. These frames are exactly what the 4-corner labels and the perspective transform are for. Make sure the dataset has many of them.
- Plates near the left edge are partially cut off. Label them only if all 4 corners are visible; otherwise mark them as `occluded` or `plate_ignore` (decide in the labeling guide).
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

- **Model:** YOLO-pose, nano size, 1 class (`plate`), 4 keypoints (`kpt_shape: [4, 3]`).
- **Label format:** `0 cx cy w h x1 y1 v1 x2 y2 v2 x3 y3 v3 x4 y4 v4`, all normalized. The box is derived from the 4 corners. `v` is the visibility flag.
- **Augmentation:** horizontal flip is disabled (`fliplr = 0`), because a mirrored plate is not a real case and would swap the TL/TR corner order.
- **Input size:** **OPEN**. Candidates 1024x768, 1280x960, 1920x1440. All are divisible by 32.
- **Licensing:** Ultralytics models are AGPL-3.0. Acceptable for the thesis; reconsider before any commercial use. The label format is model-neutral, so switching to an Apache-2.0 alternative (e.g. RTMPose or RF-DETR based) stays possible.
- **Hardware caveat:** the GTX 1660 Super has 6 GB VRAM and no tensor cores. The nano model at 1280x960 should fit with a moderate batch size. Mixed precision can be unreliable on 16-series cards (it may fall back to FP32 or produce NaN losses), so check this on the first training run.
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

All metrics are computed on the session-split test set and logged to Weights & Biases (metrics and hyperparameters only).

## 9. Deployment on the Pi

- Runtime: ONNX Runtime for both models.
- Models are downloaded from S3 at startup (CLAUDE.md, edge MLOps standard).
- Pipeline: full-resolution frame from the `main` stream, `resize_for_detector()`, detector, corners scaled back to the original, perspective crop, OCR.
- Logging: structured JSON, per project convention.
- Benchmark to run before fixing the detector input size: a nano model at 1024x768, 1280x960 and 1920x1440 on the Pi 5, measuring latency. Required frame rate in the car is the deciding input (2-3 fps is assumed to be enough).

## 10. Open items

| # | Item | How it gets decided |
|---|---|---|
| 1 | Detector input resolution | Pi 5 latency benchmark, plus plate-width histogram from real labels |
| 2 | Final OCR model and rule handling | After the baseline, once per-position character rules are written down |
| 3 | Share of synthetic data for OCR | After the baseline, based on errors on rare characters |
| 4 | Small-plate threshold (~80 px on the original) | Histogram after the first ~100 labels |
| 5 | Metric acceptance thresholds | After the first baseline run |
| 6 | Perceptual-hash distance threshold for deduplication | Tuned by eye on a sample of frames |
| 7 | Mixed precision on the GTX 1660 Super | Check on the first training run |
