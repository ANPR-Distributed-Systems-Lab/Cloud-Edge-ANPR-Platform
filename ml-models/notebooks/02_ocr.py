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
# # OCR analysis: plate crops -> text
#
# Analyses one finished OCR run on the val crops and compares it with a baseline run. **To switch versions,
# change `VERSION` (and optionally `BASELINE`) in the first code cell and run all cells.** A version `vN`
# means the config `configs/ocr_vN.yaml` and the run directory `runs/ocr/vN/`. This measures the OCR alone,
# on crops cut from the labeled corners; the OCR behind the real detector is analysed in `03_pipeline.py`.
#
# **Pipeline shared by all versions** (decided 2026-11-09):
# - fast-plate-ocr `cct-s-v2-global` (MIT, trained on plates of about 70 countries including Poland),
#   fine-tuned with Keras 3 on the torch backend and exported to ONNX the same way; no TensorFlow.
# - Input 128x64 RGB: the plate quad, widened by a margin, rectified from the full-resolution frame with
#   `rectify_plate()`, the function the Pi uses on detected corners.
# - Only plates labeled `readable = yes`. Train plates get several crops from randomly displaced corners, so
#   the OCR learns the detector's corner error; val crops come from the labeled corners.
# - Output: one character per fixed slot (10 slots, padding included) with its probability; a reading's
#   confidence is its weakest slot.
#
# **Privacy.** Crops show licence plates. Cells that draw them run only when `SHOW_IMAGES` is on; committed
# reports are executed with `ANPR_SHOW_IMAGES=0`. Val crops go only to the private W&B project `anpr-ocr`.
#
# **Running it.** Train first from a terminal in `ml-models/`, then run all cells:
#
# ```powershell
# uv run anpr-train-ocr --config configs/ocr_v1.yaml
# ```
#
# A report without editing the notebook:
#
# ```powershell
# $env:ANPR_SHOW_IMAGES = "0"; $env:ANPR_OCR_VERSION = "v1"; $env:ANPR_OCR_BASELINE = "v0"
# uv run jupytext --to ipynb --output notebooks/reports/02_ocr_v1.ipynb notebooks/02_ocr.py
# uv run jupyter nbconvert --to notebook --execute --inplace notebooks/reports/02_ocr_v1.ipynb
# ```

# %% tags=["parameters"]
VERSION = "v1"   # the analysed run: configs/ocr_<VERSION>.yaml
BASELINE = "v0"  # the run it is compared against; None for no comparison

# %%
import json
import platform

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import Markdown, display

from anpr_ml.analysis import (
    COLORS,
    config_diff,
    config_header,
    config_path,
    from_env,
    plot_style,
    show_images,
)
from anpr_ml.analysis import versions as config_versions
from anpr_ml.common.preprocess import read_image
from anpr_ml.ocr.config import TRAINING_LOG, dataset_dir, load_config, run_dir, run_state
from anpr_ml.ocr.dataset import ensure_dataset, read_crops
from anpr_ml.ocr.evaluate import evaluate_run
from anpr_ml.ocr.metrics import SUMMARY_KEYS
from anpr_ml.paths import ROOT

VERSION = from_env("ANPR_OCR_VERSION", VERSION)
BASELINE = from_env("ANPR_OCR_BASELINE", BASELINE)
if BASELINE == VERSION:
    BASELINE = None
SHOW_IMAGES = show_images()

cfg = load_config(config_path("ocr", VERSION))
base_cfg = load_config(config_path("ocr", BASELINE)) if BASELINE else None

plot_style()
BLUE, ORANGE, AQUA, INK_2, BASE = (COLORS[k] for k in ("blue", "orange", "aqua", "ink_2", "base"))

pd.Series({"version": VERSION, "baseline": BASELINE or "none", "python": platform.python_version(),
           "opencv": cv2.__version__, "show images": SHOW_IMAGES}, name="environment").to_frame()

# %% [markdown]
# ## 0. Experiment
#
# All OCR configs and the state of their runs; any finished one can be put in `VERSION` or `BASELINE`.

# %%
pd.DataFrame([
    {"version": v, "state": run_state(run_dir(c)), "dataset": c["dataset"]["name"],
     "fine-tuned": c["train"] is not None}
    for v, c in ((v, load_config(config_path("ocr", v))) for v in config_versions("ocr"))
]).set_index("version")

# %%
display(Markdown(f"**{VERSION}.** {config_header(config_path('ocr', VERSION))}"))
if base_cfg:
    display(Markdown(f"Settings that differ from {BASELINE}:"))
    display(pd.DataFrame(config_diff(base_cfg, cfg, BASELINE, VERSION)).set_index("setting"))

# %% [markdown]
# ## 1. Crops
#
# Built once by `anpr_ml.ocr.dataset` into `datasets/<name>/` and reused; the manifest records the label files
# and parameters, and a dataset that no longer matches its config is refused. `plates` counts physical plates,
# `crops` the images (train: one per jitter copy), `texts` the distinct plate numbers.

# %%
manifest = ensure_dataset(cfg)
pd.DataFrame(manifest["counts"]).T.drop(columns="types")

# %%
crops = {split: pd.DataFrame(read_crops(cfg, split)) for split in ("train", "val")}
plates = {split: df.drop_duplicates(["frame", "plate"]) for split, df in crops.items()}
fig, axes = plt.subplots(1, 2, figsize=(11, 3.2), sharex=True)
bins = np.arange(60, 560, 20)
for ax, (split, df), color in zip(axes, plates.items(), (BLUE, ORANGE)):
    ax.hist(df["width_px"], bins=bins, color=color, edgecolor=COLORS["paper"], linewidth=2)
    ax.set_title(f"{split}: {len(df)} readable plates", loc="left")
    ax.set_xlabel("plate width on the original frame (px)")
axes[0].set_ylabel("plates")
fig.tight_layout()

# %%
pd.DataFrame({split: df["text"].str.len().value_counts().sort_index() for split, df in plates.items()}) \
    .fillna(0).astype(int).rename_axis("text length")

# %% [markdown]
# ### Visual check of the crops (private)
#
# Top: the jittered train copies of one plate, as the model sees them during fine-tuning (before
# augmentation). Bottom: val crops, cut from the labeled corners.

# %%
def show_grid(rows, title, n=8):
    fig, axes = plt.subplots(1, n, figsize=(2.1 * n, 1.4), squeeze=False)
    for ax, (_, row) in zip(axes[0], rows.head(n).iterrows()):
        ax.imshow(cv2.cvtColor(read_image(row["path"]), cv2.COLOR_BGR2RGB))
        ax.set_title(row.get("label", row["text"]), fontsize=8, loc="left")
        ax.axis("off")
    for ax in axes[0][len(rows.head(n)):]:
        ax.axis("off")
    fig.suptitle(title, x=0.01, ha="left")
    fig.tight_layout()


if SHOW_IMAGES:
    train = crops["train"]
    first = train.iloc[0]
    show_grid(train[(train["frame"] == first["frame"]) & (train["plate"] == first["plate"])],
              "train: jittered copies of one plate")
    val = crops["val"]
    show_grid(val.sample(min(8, len(val)), random_state=0), "val: crops from the labeled corners")
else:
    print("SHOW_IMAGES is off: crops are not shown.")

# %% [markdown]
# ## 2. Training run
#
# Trained by `uv run anpr-train-ocr --config configs/ocr_<VERSION>.yaml`. A baseline run (`train: null`) has
# no training log. The val loss selects the checkpoint: near the top, val accuracy only moves in steps of
# single plates, while the loss still ranks models that read the same plates.

# %%
RUN = run_dir(cfg)
state = run_state(RUN)
if state != "finished":
    raise RuntimeError(f"{RUN} is {state}: train it first with "
                       f"`uv run anpr-train-ocr --config configs/ocr_{VERSION}.yaml`")
log_file = RUN / TRAINING_LOG
if log_file.exists():
    hist = pd.read_csv(log_file)
    hist["epoch"] += 1
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.6))
    for ax, metric, title in zip(axes, ("plate_loss", "plate_acc"), ("plate loss", "plate accuracy")):
        ax.plot(hist["epoch"], hist[metric], color=BLUE, label="train (augmented)")
        ax.plot(hist["epoch"], hist[f"val_{metric}"], color=ORANGE, label="val")
        ax.set_title(title, loc="left")
        ax.set_xlabel("epoch")
        ax.legend()
    best_epoch = int(hist.loc[hist[cfg["train"]["monitor"]].idxmin(), "epoch"])
    axes[0].axvline(best_epoch, color=INK_2, linewidth=1, linestyle="--")
    axes[0].set_title(f"plate loss; dashed: selected epoch {best_epoch}", loc="left")
    fig.tight_layout()
else:
    print(f"{VERSION} is a baseline run: the pretrained model, not trained here.")

# %% [markdown]
# ## 3. Evaluation on the val crops
#
# `evaluate_run()` is what `anpr-eval-ocr` runs (and reports to W&B); it reads every val crop with the run's
# `model.onnx` through ONNX Runtime on the CPU, as the edge node will, and writes
# `runs/ocr/<run>/eval_val.json`.

# %%
evaluation = evaluate_run(cfg)
res = evaluation.result
pd.Series({k: res[k] for k in SUMMARY_KEYS}, name=VERSION).to_frame()

# %%
pd.DataFrame(res["by_width"]).set_index("width_px")

# %% [markdown]
# Errors per character position (reads of the right length only) and the most frequent confusions. With the
# Polish plate rules written down, these show which positions a rule could correct.

# %%
display(pd.DataFrame(res["positions"]).set_index("position").T)
display(pd.DataFrame(res["confusions"]) if res["confusions"] else Markdown("_No character confusions._"))

# %% [markdown]
# ### Confidence
#
# Share of crops kept and exact match among them, for a threshold on the reading's confidence (its weakest
# slot). On val crops every plate is readable; how confidence separates good reads from reads of unreadable
# plates and of non-plates is in `03_pipeline.py`.

# %%
cov = pd.DataFrame(res["coverage"])
fig, ax = plt.subplots(figsize=(7, 3.6))
ax.plot(cov["conf"], cov["kept"], color=BLUE, label="share kept")
ax.plot(cov["conf"], cov["exact"], color=ORANGE, label="exact among kept")
ax.set_xlabel("confidence threshold")
ax.set_ylim(0, 1.02)
ax.set_title(f"{VERSION} on {res['crops']} val crops", loc="left")
ax.legend()
fig.tight_layout()

# %% [markdown]
# ## 4. Comparison with the baseline
#
# Meaningful only on the same val crops; the check compares the val annotation files of both datasets.

# %%
base_file = run_dir(base_cfg) / "eval_val.json" if base_cfg else None
base_res = json.loads(base_file.read_text()) if base_file and base_file.exists() else None
if base_cfg and base_res is None:
    print(f"{base_file} is missing: run `uv run anpr-eval-ocr --config configs/ocr_{BASELINE}.yaml`")


def summary(r):
    return {**{k: r[k] for k in SUMMARY_KEYS if k != "crops"},
            **{f"exact {b['width_px']} px": b["exact"] for b in r["by_width"]}}


if base_res is not None:
    same_val = ((dataset_dir(cfg) / "val" / "annotations.csv").read_bytes()
                == (dataset_dir(base_cfg) / "val" / "annotations.csv").read_bytes())
    print("val crops:", "identical" if same_val else "DIFFERENT: the numbers below are not comparable")
    cmp = pd.DataFrame({BASELINE: summary(base_res), VERSION: summary(res)})
    cmp["change"] = cmp[VERSION] - cmp[BASELINE]
    display(cmp)

# %% [markdown]
# ### Error review (private)
#
# Every wrong read, then the least confident right reads. Label errors show up here too: a confident read that
# disagrees with the label is worth checking in CVAT (train and val only, never test).

# %%
rows = pd.DataFrame([{**c, "read": r.text, "conf": r.conf}
                     for c, r in zip(evaluation.crops, evaluation.readings)])
rows["correct"] = rows["read"] == rows["text"]
conf_label = rows["conf"].map(" {:.2f}".format)
if SHOW_IMAGES:
    wrong = rows[~rows["correct"]].assign(label=rows["text"] + " -> " + rows["read"] + conf_label)
    if len(wrong):
        show_grid(wrong, f"wrong reads ({len(wrong)})")
    else:
        print("wrong reads: none")
    unsure = rows[rows["correct"]].assign(label=rows["text"] + conf_label).nsmallest(8, "conf")
    show_grid(unsure, "least confident right reads")
else:
    print("SHOW_IMAGES is off: crops are not shown.")
# Plate texts are personal data too: the table that also lands in reports shows where the errors are, not what
# the plates say.
rows.loc[~rows["correct"], ["frame", "plate", "width_px", "conf"]]

# %% [markdown]
# ## 5. Summary and conclusions
#
# The written conclusions of a version live in `notebooks/conclusions/ocr_<VERSION>.md`.

# %%
display(pd.Series(summary(res), name=f"OCR {VERSION}, val crops").to_frame())
conclusions = ROOT / "notebooks" / "conclusions" / f"ocr_{VERSION}.md"
display(Markdown(conclusions.read_text(encoding="utf-8")) if conclusions.exists()
        else Markdown(f"_No conclusions yet: write them in `notebooks/conclusions/{conclusions.name}`._"))
