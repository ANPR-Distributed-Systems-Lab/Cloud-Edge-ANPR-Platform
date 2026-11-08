# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Detector v0: YOLO11n-pose, licence plates with 4 corners
#
# **Goal.** The first plate detector. It bootstraps the pre-labeling loop (ML_ASSUMPTIONS section 4) and is the
# baseline every later detector is compared against. It is not the model that will be deployed.
#
# **Decisions for this run** (2026-11-05):
# - YOLO11n-pose, 1 class, 4 keypoints in the order TL, TR, BR, BL, starting from COCO-pose weights.
# - Input 1280x960. Frames are downscaled offline with `resize_for_detector()` (INTER_AREA), the function the
#   Pi will use, so training never resamples them again.
# - `plate_ignore` regions and plates narrower than 70 px on the original are painted gray (114), so the model
#   is neither trained to find them nor penalized for finding them.
# - Horizontal flip off: a mirrored plate is not a real case and would swap TL and TR.
#
# **Data.** `train_001` (train split) and `val_001` (val split). Every frame gets its split from
# `labeling/splits.json` by session. The test split is not touched here.
#
# **Privacy.** The frames show licence plates, which are personal data. Cells that draw frames run only when
# `SHOW_IMAGES` is on. The committed report in `notebooks/reports/` is executed with `ANPR_SHOW_IMAGES=0` and holds
# metrics and plots only. Validation frames go only to the private W&B project (`anpr_ml.tracking`).
#
# **Running it.** This notebook analyses a finished run; it does not train. Train first from a terminal in
# `ml-models/` (the same command resumes an interrupted run):
#
# ```powershell
# uv run anpr-train-detector --config configs/detector_v0.yaml
# ```
#
# Then open the notebook in JupyterLab (`uv run jupyter lab`, *Open With -> Notebook*) or the paired `.ipynb` in
# PyCharm (after `uv run jupytext --sync notebooks/01_detector_v0.py`). The report:
#
# ```powershell
# $env:ANPR_SHOW_IMAGES = "0"
# uv run jupytext --to ipynb --output notebooks/reports/01_detector_v0.ipynb notebooks/01_detector_v0.py
# uv run jupyter nbconvert --to notebook --execute --inplace notebooks/reports/01_detector_v0.ipynb
# ```

# %%
import os
import platform
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import ultralytics

from anpr_ml.common.labels import export_paths, load_records, load_splits, plate_width_px, split_records
from anpr_ml.common.preprocess import read_image
from anpr_ml.detector.config import dataset_dir, load_config, run_dir, run_state
from anpr_ml.detector.dataset import ensure_dataset
from anpr_ml.detector.evaluate import evaluate_run
from anpr_ml.detector.metrics import frame_results
from anpr_ml.paths import BATCHES_DIR, ROOT

os.chdir(ROOT)  # Ultralytics downloads helper weights into the working directory; *.pt is gitignored there
SHOW_IMAGES = os.environ.get("ANPR_SHOW_IMAGES", "1") == "1"
CONFIG = Path(os.environ.get("ANPR_DETECTOR_CONFIG", ROOT / "configs" / "detector_v0.yaml"))
cfg = load_config(CONFIG)
SIZE = cfg["dataset"]["size"]
MIN_PLATE_PX = cfg["dataset"]["min_plate_px"]

# Reference palette, fixed order: train/precision = blue, val/recall = orange, F1 = aqua.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": INK_2,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "lines.linewidth": 2, "font.size": 10, "legend.frameon": False,
})
pd.set_option("display.precision", 3)

pd.Series({
    "python": platform.python_version(),
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none",
    "ultralytics": ultralytics.__version__,
    "opencv": cv2.__version__,
    "config": CONFIG.name,
    "show images": SHOW_IMAGES,
}, name="environment").to_frame()

# %% [markdown]
# ## 1. Labeled data
#
# Plate width is measured on the original 4056x3040 frame, as the mean of the top and bottom edges. At the
# 1280x960 detector input a plate is about 3.17 times narrower (70 px becomes about 22 px).

# %%
records = load_records(export_paths(cfg["dataset"]["exports"]))
by_split = {k: v for k, v in split_records(records, load_splits()).items() if v}


def widths_of(records):
    return np.array([plate_width_px(p["corners"], r) for r in records for p in r["plates"]])


pd.DataFrame([
    {
        "split": split,
        "frames": len(recs),
        "frames with a plate": sum(bool(r["plates"]) for r in recs),
        "plates": len(widths_of(recs)),
        "plates readable": sum(p["readable"] for r in recs for p in r["plates"]),
        "ignore regions": sum(len(r["ignore"]) for r in recs),
        "median width px": float(np.median(widths_of(recs))),
    }
    for split, recs in by_split.items()
]).set_index("split")

# %%
fig, axes = plt.subplots(1, len(by_split), figsize=(11, 3.2), sharex=True)
bins = np.arange(60, 560, 20)
for ax, (split, recs), color in zip(np.atleast_1d(axes), by_split.items(), (BLUE, ORANGE)):
    w = widths_of(recs)
    ax.hist(w, bins=bins, color=color, edgecolor="#fcfcfb", linewidth=2)
    ax.axvline(MIN_PLATE_PX, color=INK_2, linewidth=1, linestyle="--")
    ax.set_title(f"{split}: {len(w)} plates", loc="left")
    ax.set_xlabel("plate width on the original frame (px)")
np.atleast_1d(axes)[0].set_ylabel("plates")
fig.tight_layout()

# %% [markdown]
# ## 2. YOLO-pose dataset
#
# Built once by `anpr_ml.detector.dataset` into `datasets/<name>/` and reused. The manifest records the label files
# (by checksum) and parameters it was built from; `ensure_dataset` refuses a dataset that no longer matches the
# config, so a relabeled batch never trains silently on stale data. To rebuild, give the dataset a new name.

# %%
DATASET = dataset_dir(cfg)
manifest = ensure_dataset(cfg)
pd.DataFrame(manifest["counts"]).T.fillna(0).astype(int)

# %% [markdown]
# Frames without any plate to learn (`negatives`) are a large share: frames with no plate at all plus frames that
# only contain painted ignore regions. YOLO uses them as background. Their share is a candidate knob for later
# runs (ML_ASSUMPTIONS asks for a small share); v0 keeps every frame so the validation distribution stays real.

# %% [markdown]
# ### Visual check of the training images (private)
#
# Boxes and corners as the model receives them: corner 0 (TL) red, 1 (TR) orange, 2 (BR) green, 3 (BL) blue.
# Gray patches are the painted ignore regions.

# %%
CORNER_COLORS = [(0, 0, 255), (0, 140, 255), (0, 180, 0), (255, 90, 0)]  # BGR


def draw_yolo_labels(image, label_text):
    out = image.copy()
    h, w = out.shape[:2]
    for line in label_text.splitlines():
        v = np.array(line.split(), float)
        cx, cy, bw, bh = v[1:5] * [w, h, w, h]
        cv2.rectangle(out, (int(cx - bw / 2), int(cy - bh / 2)), (int(cx + bw / 2), int(cy + bh / 2)), (255, 255, 255), 1)
        for i, (x, y) in enumerate(v[5:].reshape(4, 3)[:, :2] * [w, h]):
            cv2.circle(out, (int(x), int(y)), 3, CORNER_COLORS[i], -1)
    return out


if SHOW_IMAGES:
    labels = sorted((DATASET / "labels" / "train").glob("*.txt"), key=lambda p: -len(p.read_text().splitlines()))
    fig, axes = plt.subplots(2, 2, figsize=(15, 11.5))
    for ax, lbl in zip(axes.flat, labels[:4]):
        img = cv2.imread(str(DATASET / "images" / "train" / f"{lbl.stem}.png"))
        ax.imshow(cv2.cvtColor(draw_yolo_labels(img, lbl.read_text()), cv2.COLOR_BGR2RGB))
        ax.set_title(lbl.stem, fontsize=8, loc="left")
        ax.axis("off")
    fig.tight_layout()
else:
    print("SHOW_IMAGES is off: frames are not shown.")

# %% [markdown]
# ## 3. Training run
#
# Trained by `uv run anpr-train-detector --config configs/<config>.yaml` (see the top). Hyperparameters are in the
# config and passed to Ultralytics unchanged; everything else is the Ultralytics default. On the GTX 1660 Super
# Ultralytics disables mixed precision (FP32). The first run of v0 died after 7 epochs when the PC ran out of
# memory (CVAT's Docker VM, 4 dataloader workers) and was resumed from `last.pt`.

# %%
RUN = run_dir(cfg)
state = run_state(RUN)
if state != "finished":
    raise RuntimeError(f"{RUN} is {state}: run `uv run anpr-train-detector --config {CONFIG}` in a terminal first")
BEST = RUN / "weights" / "best.pt"
print(f"analysing {BEST}")

# %% [markdown]
# ### Learning curves
#
# `(B)` is the box, `(P)` the pose (keypoints). For a custom keypoint layout Ultralytics computes OKS with the
# same sigma for every keypoint, so pose mAP is comparable between our runs but not to published COCO numbers.

# %%
hist = pd.read_csv(RUN / "results.csv")
hist.columns = [c.strip() for c in hist.columns]
fig, axes = plt.subplots(1, 3, figsize=(15, 3.6))
for ax, loss in zip(axes[:2], ("box_loss", "pose_loss")):
    ax.plot(hist["epoch"], hist[f"train/{loss}"], color=BLUE, label="train")
    ax.plot(hist["epoch"], hist[f"val/{loss}"], color=ORANGE, label="val")
    ax.set_title(loss, loc="left")
    ax.set_xlabel("epoch")
    ax.legend()
axes[2].plot(hist["epoch"], hist["metrics/mAP50-95(B)"], color=BLUE, label="box mAP50-95")
axes[2].plot(hist["epoch"], hist["metrics/mAP50-95(P)"], color=ORANGE, label="pose mAP50-95")
axes[2].set_title("val mAP50-95", loc="left")
axes[2].set_xlabel("epoch")
axes[2].set_ylim(0, 1)
axes[2].legend()
fig.tight_layout()

# %% [markdown]
# ## 4. Ultralytics validation (val split, painted images)
#
# `evaluate_run()` is the same evaluation `anpr-eval-detector` runs (and reports to W&B); it also writes
# `runs/detector/<run>/eval_val.json`.

# %%
evaluation = evaluate_run(cfg)
ultra = evaluation.ultralytics
pd.Series(ultra, name="val").to_frame()

# %% [markdown]
# ## 5. Evaluation on the original frames
#
# The way the edge node will run: original frame -> `resize_for_detector()` -> model, with **unpainted** frames.
# Detections on ignore regions or demoted small plates are dropped, not counted as false positives. A match needs
# box IoU >= 0.5. Corner error is the mean distance of the 4 corners on the original 4056x3040 frame.

# %%
val_records, preds, res = evaluation.records, evaluation.predictions, evaluation.result
pd.DataFrame([res["best"]]).set_index("conf")

# %%
curve = pd.DataFrame(res["curve"])
fig, ax = plt.subplots(figsize=(7, 3.6))
for col, color in (("precision", BLUE), ("recall", ORANGE), ("f1", AQUA)):
    ax.plot(curve["conf"], curve[col], color=color, label=col)
ax.axvline(res["best"]["conf"], color=INK_2, linewidth=1, linestyle="--")
ax.set_xlabel("confidence threshold")
ax.set_ylim(0, 1.02)
ax.set_title(f"val, {res['plates']} plates; dashed: best F1", loc="left")
ax.legend()
fig.tight_layout()

# %%
pd.DataFrame(res["by_width"]).set_index("width_px")

# %%
pd.Series(res["corner_error"], name="corner error at best F1").to_frame()

# %% [markdown]
# ### Error analysis (private)
#
# Crops from the original frame at the best-F1 threshold: missed plates, false positives and the largest corner
# errors. Ground-truth corners green, predicted red, corner 0 (TL) drawn larger.

# %%
def crop_with_corners(record, gt=None, pred=None, pad=0.6):
    img = read_image(BATCHES_DIR / record["image"])
    size = np.array([record["width"], record["height"]])
    pts = np.vstack([c * size for c in (gt, pred) if c is not None])
    (x1, y1), (x2, y2) = pts.min(0), pts.max(0)
    m = pad * max(x2 - x1, 40)
    x1, y1 = int(max(x1 - m, 0)), int(max(y1 - m, 0))
    x2, y2 = int(min(x2 + m, size[0])), int(min(y2 + m, size[1]))
    out = img[y1:y2, x1:x2].copy()
    for corners, color in ((gt, (0, 200, 0)), (pred, (0, 0, 255))):
        if corners is None:
            continue
        for i, (x, y) in enumerate(corners * size - [x1, y1]):
            cv2.circle(out, (int(x), int(y)), 6 if i == 0 else 3, color, -1)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def show_crops(title, items):
    if not items:
        print(f"{title}: none")
        return
    fig, axes = plt.subplots(1, len(items), figsize=(3.2 * len(items), 2.6), squeeze=False)
    for ax, (crop, label) in zip(axes[0], items):
        ax.imshow(crop)
        ax.set_title(label, fontsize=8, loc="left")
        ax.axis("off")
    fig.suptitle(title, x=0.01, ha="left")
    fig.tight_layout()


if SHOW_IMAGES:
    missed, false_pos, worst = [], [], []
    for r, fr in zip(val_records, frame_results(val_records, preds, MIN_PLATE_PX, res["best"]["conf"])):
        missed += [(r, fr.plates[i], fr.gt_widths[i]) for i in fr.missed]
        false_pos += [(r, p) for p in fr.false_positives]
        worst += [(m.corner_error_px, r, fr.plates[m.gt], m.pred) for m in fr.hits]
    show_crops(f"missed plates ({len(missed)})",
               [(crop_with_corners(r, gt=c), f"{w:.0f} px") for r, c, w in missed[:8]])
    show_crops(f"false positives ({len(false_pos)})",
               [(crop_with_corners(r, pred=p.corners), f"conf {p.conf:.2f}") for r, p in false_pos[:8]])
    worst.sort(key=lambda x: -x[0])
    show_crops("largest corner errors",
               [(crop_with_corners(r, gt=g, pred=p.corners), f"{e:.1f} px") for e, r, g, p in worst[:8]])
else:
    print("SHOW_IMAGES is off: frames are not shown.")

# %% [markdown]
# ## 6. Summary
#
# The numbers below are what later runs are compared against (also saved to `runs/detector/<run>/eval_val.json`).
# The written conclusions are added after the run has been reviewed.

# %%
pd.Series({
    **ultra,
    "best F1 conf": res["best"]["conf"],
    "precision @best": res["best"]["precision"],
    "recall @best": res["best"]["recall"],
    "corner error median px": res["corner_error"]["median_px"],
    "corner error p90 px": res["corner_error"]["p90_px"],
    "corner error p90 / width": res["corner_error"]["p90_rel_width"],
}, name="detector v0, val").to_frame()

# %% [markdown]
# ### Conclusions
#
# _Written after reviewing the run._
#
# ### Next steps
#
# 1. Pre-label the next train batch with this model (predictions -> CVAT for images 1.1 XML), correct by hand.
# 2. Use the detections to pick frames with large plates on the left for training batches (never for test).
# 3. Label `test_001` from scratch, without this model.
