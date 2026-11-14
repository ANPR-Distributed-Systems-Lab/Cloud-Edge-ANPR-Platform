# ML assumptions: plate detection and OCR

Working assumptions for building the Polish license plate models (detection with 4 corners, then OCR).
Last updated: 2026-11-09. Items marked **OPEN** are deliberately undecided, see the last section.

## 1. Decision summary

| Area | Decision |
|---|---|
| Labeling tool | CVAT, self-hosted (docker) |
| Pre-labeling | Iterative loop with our own model |
| Detection model | YOLO11n-pose (Ultralytics), 1 class, 4 keypoints (plate corners); YOLO26n-pose compared at the Pi benchmark |
| OCR model | `fast-plate-ocr` `cct-s-v2-global`, fine-tuned with Keras 3 on the torch backend (no TensorFlow); input 128x64 RGB, rectified with an 8 % margin. Final model **OPEN** (per-position character rules in PLATE_FORMAT.md) |
| Labeling resolution | Original frames, 4056x3040 |
| Detector input resolution | **OPEN**, 1280x960 for detector v0; final after a benchmark on the Pi |
| Ignore regions in training | Painted gray (114) in the downscaled train and val images |
| Frame selection | Perceptual-hash deduplication, then diverse frames that contain plates |
| Test set | ~150 frames from separate sessions, labeled from scratch |
| Data storage | Local only |
| Training hardware | Local PC: i5-9600KF, GTX 1660 Super |
| Experiment tracking | Weights & Biases, private projects; metrics plus validation frames (detector) and validation plate crops (OCR) for review |
| Notebooks | jupytext `.py` committed, outputs in a gitignored `.ipynb`; reports in `notebooks/reports/` without frames |
| Inference runtime on the Pi | ONNX Runtime |
| Document language | English |

## 2. Code organization

The directory layout and every command are described in [README.md](README.md).

- The environment is separate from `rpi-edge` (torch and Ultralytics are heavy). Reusable logic lives in the `anpr_ml` package (`common`, `labeling`, `detector`, `ocr`, plus `pipeline` for both models together); notebooks import it and never reimplement it.
- Training runs from a terminal with `anpr-train-detector` / `anpr-train-ocr --config configs/<config>.yaml`, never inside a notebook: a run must not depend on a kernel or an IDE, and the command plus the config make it reproducible. One config per run; finished runs and built datasets are never overwritten.
- Each model has its own analysis notebook (`01_detector.py`, `02_ocr.py`) and the pair has one (`03_pipeline.py`); the analysed versions are variables in the first cell.
- Per the repository-wide standards, model weights (`.onnx`) are not stored in the repository. The edge node downloads them from S3 at startup.

### Notebooks in git

- The `.py` file (jupytext percent format) is committed. The paired `.ipynb` working copy, which holds the outputs, is gitignored, so no output-stripping filter is needed.
- `notebooks/reports/` holds executed reports, committed with their outputs (tables, learning curves, histograms) so GitHub renders them.
- **No frames, crops or plate texts in committed notebooks** (decided 2026-11-05): license plates are personal data. Cells that draw frames or crops run only when `ANPR_SHOW_IMAGES` is not `0`; reports are executed with `ANPR_SHOW_IMAGES=0`, and tables that reach a report identify errors by frame and width, not by plate text.

## 3. Data

### Storage
- Images and labels are stored **locally only** (the ML work is owned by one person). There is no cloud copy and no DVC.
- Keep a second copy of the dataset and of exported CVAT annotations on a separate disk.
- The repo contains only code, configs and, optionally, a manifest (file name, size, checksum).
- Experiment tracking: metrics and hyperparameters go to W&B. **Exceptions:** the private W&B projects (accessible to the project owner only) also receive, as sortable tables for visual error review, the validation frames of each evaluated detector run with labels and predictions drawn (decided 2026-11-05) and the validation plate crops of each evaluated OCR run with their true and read text (decided 2026-11-09; the same val frames are already in the detector project, so the crops show nothing new). No training images, training crops or raw data are uploaded, and frames never appear in anything committed to git. Ultralytics' built-in W&B integration stays off (`yolo settings wandb=False`, the default); everything sent is chosen in `anpr_ml.tracking`.

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
  - `readable`: yes / no. Unreadable plates stay in detection data; for OCR they are rejects (to be read as no text, section 7).
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
1. One shared function, e.g. `resize_for_detector()` using `cv2.resize(..., interpolation=cv2.INTER_AREA)`, used both when preparing the dataset and on the Pi. Golden checksums in `tests/test_common.py` (and the same ones in `rpi-edge/tests/vision/test_preprocess.py`) check the pixels. **Measured 2026-11-12 on the Pi 5 (aarch64, opencv-python-headless 5.0.0.93):** `resize_for_detector()` is bit-identical to x86, `rectify_plate()` is not: OpenCV's warpPerspective takes other SIMD paths on ARM (rounding the transform matrix does not help). On 22 plates the difference is at most 1 grey level, in at most 0.05 % of the values (mean 0.008 %). So the rule is: **identical on x86, within ±1 on ARM** (at most 1 level in at most 0.1 % of the values, checked on the Pi against reference crops stored from x86). The OCR does not notice a difference of this size.
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

- **Input (decided 2026-11-09):** the plate rectified with a perspective transform from the 4 corners (`rectify_plate()`, shared with the Pi), **128x64 RGB**, the input of the pretrained model, whose weights a different size would not fit. The quad is first widened by an **8 % margin** about its center: the pretrained model saw plates with surroundings, and on val_001 it read 0.918 of tight crops, 0.986 with the margin and 0.973 of axis-aligned boxes with 10 % margin. Rectifying keeps oblique close-range plates undistorted. The 4.5:1 plate is stretched to 2:1; the model is trained that way.
- **Model (decided 2026-11-09):** `fast-plate-ocr` `cct-s-v2-global` (MIT; trained on plates of about 70 countries, Poland included, 98.4 % plate accuracy on its own Polish val set), fine-tuned on our crops. Output: 10 fixed slots over 36 characters plus padding, each with its probability, which suits per-position rules. The second head (the plate's country in the pretrained model) is kept: up to v2 it is trained on "Poland" for readable plates and "Unknown" for rejects, from v3 it is a readability head (below).
- **Training stack (decided 2026-11-09):** Keras 3 on the **torch backend**, for training and for the ONNX export; TensorFlow is not installed. fast-plate-ocr's own export fails on Windows and needs a dynamic batch that the torch exporter cannot convert, so `anpr_ml.ocr.export` exports with **batch size 1** and names the outputs `plate` / `region` like the official models. Verified: the export of the pretrained weights reads exactly like the official ONNX (largest probability difference 1e-6).
- **Baseline (OCR v0):** the pretrained model without fine-tuning: exact 0.945 (137 of 145) on the val_001 + val_002 crops; behind detector v2, 134 of 143 readable val plates read right.
- **Fine-tuning on readable plates only (OCR v1):** exact 0.952 (138 of 145), CER 0.007; behind detector v2, 137 of 143. But it reads a plausible Polish plate into everything: behind detector v2 the median confidence of its reads of unreadable plates rose from 0.51 (v0) to 0.80, and its region head calls 90 of 92 don't-care regions Polish (v0: 35). Confidence alone then cannot stop garbage reads (precision of sent reads 0.81 at a threshold of 0.95).
- **Rejects (decided 2026-11-10):** the OCR is trained to answer with **no text** (every slot padding) and the region "Unknown" where there is nothing to read: plates labeled `readable = no` and `plate_ignore` regions, at least 70 px wide (narrower detections never reach the OCR on the Pi), cut and jittered like the readable plates (train 1824 reject crops next to 2160 readable ones, val 137 next to 145). An empty reading is never sent. First trained in OCR v2: 102 of 137 val rejects read as no text, but reading got worse (exact 0.917 against v1's 0.952, some reads cut short), so the way rejects are trained is not final.
- **Readability head (OCR v3, 2026-11-11):** the country head becomes a 2-class head, `readable` / `unreadable` (`plate_config.yaml` lists them as `plate_regions`, so fast-plate-ocr's inference and the ONNX outputs stay unchanged; the country is not needed, since foreign plates are out of scope). Rejects get the `unreadable` class and a text loss weight of 0, so the text head learns from readable plates only, as in v1. A reading is declined when it has no text or when P(readable) < 0.5; the threshold is a parameter. Results on val (same crops as v2): readable crops exact 0.959 (139 of 145, v1 138, v2 133), CER 0.006, 0 reads of the wrong length; 101 of 137 rejects declined (0.737); behind detector v2, 135 of 143 readable plates read right (v2 132). With width >= 70 px and the format check, P(readable) >= 0.8 and conf >= 0.8 give precision 0.91 / recall 0.89 (v2 at conf 0.8: 0.90 / 0.88); P(readable) ranks right reads above garbage with AUC 0.94, the confidence 0.91, their product 0.95. The readability head stops at about 86 % val accuracy and overfits after a few epochs, while the text head is already at its best then (checkpoint on the total val loss). Tried on scratch runs, without a gain beyond a few val plates: readability weight 0.5 instead of 0.1, the checkpoint on the text loss alone (better text loss, same reads, worse head), label smoothing on the readability head (worse head), and the head trained alone on a frozen v1 (best calibrated head, same send-rule trade-off). The limit is the data (228 distinct reject plates, a subjective label), not the training scheme. **Decided 2026-11-11: v3 goes on**, in this simplest form (one training run, v1's settings): better reading than v2 and two independent thresholds. The thresholds stay **OPEN**.
- **Final model: OPEN.** The target model should encode Polish plate rules, e.g. which characters may appear in the district code and in which positions of the registration number. Candidate approaches:
  - generic model plus rule-based post-processing (regex or per-position masks),
  - constrained decoding (per-slot output heads or masked CTC),
  - alternatives to `fast-plate-ocr`: PaddleOCR PP-OCRv5 recognition model, or a custom CRNN/CTC in PyTorch.
- **Rules document:** the exact character rules per position must be written down and verified against official sources before they are used.
- **Training data:**
  - rectified real crops from verified labels (`readable = yes`, plus the rejects above), split by session like everything else,
  - **corner jitter (decided 2026-11-09):** 8 crops per train plate, built offline, each from corners displaced at random (normal, per corner and axis, sigma = 1.5 % of the plate width, the order of detector v1's corner error), so OCR tolerates detector inaccuracy; val crops come from the labeled corners. fast-plate-ocr's default augmentation runs on top,
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
- confusion matrix (e.g. 0/O, 1/I, 8/B), and errors per position,
- with rejects: share of reject crops declined (no text, or below the readability threshold), readable crops declined (false rejects); exact match is judged on the text alone,
- with a readability head: share of readable crops kept and rejects sent over the P(readable) threshold.

**End to end** (`anpr-eval-pipeline`)
- plate read correctly from frame to text, on the test set, split by distance/size bucket,
- every detection is read, as on the Pi, and classified: correct, wrong, unreadable plate, don't-care region, background; precision of the reads that pass (a text at or above the OCR confidence threshold) and share of readable plates read right, over that threshold, and over the P(readable) threshold for a readability head; declined reads per category.

Development decisions (checkpoints, thresholds, model variants) are made on the val split; the reported numbers are computed once on the session-split test set, which no decision has seen. Metrics are logged to Weights & Biases as described in section 3.

## 9. Deployment on the Pi

- Runtime: ONNX Runtime for both models.
- Models are downloaded from S3 (repository-wide edge MLOps standard). **Decided 2026-11-12:** a version is published once, with `anpr-publish-model <detector|ocr> <run>` (the run name is the version), into the models bucket of the infrastructure (`models/<model>/<version>/` with `release.json` listing SHA-256 and size). Which versions a device runs is part of its configuration in device-management (`models.detector`, `models.ocr`); the device downloads them through presigned URLs (`GET /api/v1/device/models`), checks the SHA-256, keeps them on the SD card and switches to new versions without a restart. The detector is exported with `anpr-export-detector` (ONNX, NMS inside, checked against the PyTorch weights on val frames); the OCR export is part of `anpr-train-ocr`.
- Pipeline: full-resolution frame from the `main` stream, `resize_for_detector()`, detector, corners scaled back to the original, `rectify_plate()` (128x64, 8 % margin), OCR. Both preprocessing functions are covered by golden checksums in `tests/test_common.py`, which the Pi implementation matches exactly on x86 and within ±1 grey level on ARM (section 5). Measured on the Pi 5 (detector v2 at 1280x960, FP32, ONNX Runtime with 4 threads): 1.4-1.7 frames per second, the detector with its resize about 490-530 ms, the OCR about 40-70 ms per plate; below the assumed 2-3 fps, which is input for the benchmark below.
- OCR outputs: `plate` (10 slots, the text with its per-slot probabilities, padding stripped) and `region`. For a readability model (`plate_regions` = `[readable, unreadable]` in its `plate_config.yaml`), P(readable) is the `region` output at the index of `readable`; for older models there is no readability.
- Send rule (shape recommended, thresholds **OPEN**, every threshold part of the device configuration in device-management, starting points 0.40 / 0.80 / 0.80 / 70 px / 10 px): geometry before the OCR (plate width >= 70 px, corners >= 10 px from the frame edge), then per frame the Polish format check ([PLATE_FORMAT.md](PLATE_FORMAT.md): ordinary car plates and individual plates, verified against the registration regulation), the OCR confidence threshold and the P(readable) threshold, then one event per tracked pass with agreement across frames (on the Pi for now: one event per plate text within a cooldown).
- Logging: structured JSON, per project convention.
- Benchmark to run before fixing the detector input size: a nano model at 1024x768, 1280x960 and 1920x1440 on the Pi 5, measuring latency. Required frame rate in the car is the deciding input (2-3 fps is assumed to be enough).

## 10. Open items

| # | Item | How it gets decided |
|---|---|---|
| 1 | Detector input resolution | Pi 5 latency benchmark, plus plate-width histogram from real labels |
| 2 | Final OCR model and rule handling | After the baseline; the per-position character rules are written down in [PLATE_FORMAT.md](PLATE_FORMAT.md) (2026-11-12) |
| 3 | Share of synthetic data for OCR | After the baseline, based on errors on rare characters |
| 4 | Small-plate threshold (~70 px on the original) | Histogram after the first ~100 labels |
| 5 | Metric acceptance thresholds | After the first baseline run |
| 6 | Perceptual-hash distance threshold for deduplication | **Decided 2026-11-04: 5** (kept at a distance of 5 or more), after a visual review of kept and dropped frames in 4 train sessions |
| 7 | Mixed precision on the GTX 1660 Super | **Decided 2026-11-05: off.** Ultralytics disables AMP on this GPU; training is FP32 |
| 8 | OCR model, input and training data | **Decided 2026-11-09:** fast-plate-ocr `cct-s-v2-global` fine-tuned with Keras 3 on torch, 128x64 rectified with an 8 % margin, 8 jittered crops per train plate; **2026-11-10:** plus rejects (no text) from unreadable plates and `plate_ignore` regions of 70 px and more; **2026-11-11:** rejects through a readability head instead (v3, chosen over v2); see section 7 |
