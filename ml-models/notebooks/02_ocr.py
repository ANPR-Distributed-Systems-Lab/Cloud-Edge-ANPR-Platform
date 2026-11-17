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
# - Plates labeled `readable = yes`. Train plates get several crops from randomly displaced corners, so
#   the OCR learns the detector's corner error; val crops come from the labeled corners.
# - From v2 on (decided 2026-11-10), also rejects: unreadable plates and `plate_ignore` regions of at least
#   70 px, with an empty text and the region `Unknown`, so the OCR learns to read nothing where there is
#   nothing to read. An empty reading is never sent.
# - Output: one character per fixed slot (10 slots, padding included) with its probability; a reading's
#   confidence is its weakest slot.
#
# **Privacy.** Crops show licence plates. Cells that draw them run only when `SHOW_IMAGES` is on; committed
# reports are executed with `ANPR_SHOW_IMAGES=0`. Val crops go only to the private W&B project `anpr-ocr`.
#
# **Running it.** Train first from a terminal in `ml-models/`, then run all cells:
#
# ```powershell
# uv run anpr-train-ocr --config configs/ocr_v2.yaml
# ```
#
# A report without editing the notebook:
#
# ```powershell
# $env:ANPR_SHOW_IMAGES = "0"; $env:ANPR_OCR_VERSION = "v2"; $env:ANPR_OCR_BASELINE = "v1"
# uv run jupytext --to ipynb --output notebooks/reports/02_ocr_v2.ipynb notebooks/02_ocr.py
# uv run jupyter nbconvert --to notebook --execute --inplace notebooks/reports/02_ocr_v2.ipynb
# ```

# %% tags=["parameters"]
VERSION = "v2"   # the analysed run: configs/ocr_<VERSION>.yaml
BASELINE = "v1"  # the run it is compared against; None for no comparison

# %%
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
from anpr_ml.ocr.config import TRAINING_LOG, load_config, run_dir, run_state, uses_readability
from anpr_ml.ocr.dataset import READABLE, ensure_dataset, read_crops
from anpr_ml.ocr.evaluate import evaluate_run
from anpr_ml.ocr.metrics import SUMMARY_KEYS, evaluate
from anpr_ml.ocr.predict import Reader
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
     "fine-tuned": c["train"] is not None, "second head": "readability" if uses_readability(c) else "countries"}
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
# and parameters, and a dataset that no longer matches its config is refused. `plates` counts the readable
# plates, `texts` their distinct numbers, `crops` all images (train: one per jitter copy), rejects included
# (`*_crops`, by source).

# %%
manifest = ensure_dataset(cfg)
pd.DataFrame(manifest["counts"]).T.drop(columns="types")

# %%
crops = {split: pd.DataFrame(read_crops(cfg, split)) for split in ("train", "val")}
plates = {split: df[df["kind"] == READABLE].drop_duplicates(["frame", "plate"]) for split, df in crops.items()}
pd.DataFrame({split: df.drop_duplicates(["frame", "kind", "plate"])["kind"].value_counts()
              for split, df in crops.items()}).fillna(0).astype(int).rename_axis("labeled quads by kind")
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
# augmentation). Then val crops, cut from the labeled corners, and val rejects when the dataset has them.

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
    readable_val = val[val["kind"] == READABLE]
    show_grid(readable_val.sample(min(8, len(readable_val)), random_state=0),
              "val: crops from the labeled corners")
    rejects_val = val[val["kind"] != READABLE]
    if len(rejects_val):
        show_grid(rejects_val.sample(min(8, len(rejects_val)), random_state=0).assign(label=rejects_val["kind"]),
                  "val: rejects (the OCR should read no text)")
else:
    print("SHOW_IMAGES is off: crops are not shown.")

# %% [markdown]
# ## 2. Training run
#
# Trained by `uv run anpr-train-ocr --config configs/ocr_<VERSION>.yaml`. A baseline run (`train: null`) has
# no training log. The val loss selects the checkpoint: near the top, val accuracy only moves in steps of
# single plates, while the loss still ranks models that read the same plates. With the readability head the
# plate loss and accuracy count the readable crops only, and a third panel shows the head's accuracy.

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
    panels = [("plate_loss", "plate loss"), ("plate_acc", "plate accuracy")]
    if uses_readability(cfg):
        panels.append(("region_acc", "readability head accuracy"))
    fig, axes = plt.subplots(1, len(panels), figsize=(6 * len(panels), 3.6))
    for ax, (metric, title) in zip(axes, panels):
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
# `runs/ocr/<run>/eval_val.json`. The reading metrics are over the readable crops and judge the text alone;
# a readable crop the OCR declines (no text, or not readable for the readability head) is a `false_reject`,
# and `reject_rate` is the share of rejects declined.

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
# Share of readable crops kept (a text at or above the threshold on the reading's confidence, its weakest
# slot) and exact match among them; with rejects, also the share of rejects that would be sent. How this
# behaves behind the real detector, on unreadable plates and non-plates, is in `03_pipeline.py`.

# %%
cov = pd.DataFrame(res["coverage"])
fig, ax = plt.subplots(figsize=(7, 3.6))
ax.plot(cov["conf"], cov["kept"], color=BLUE, label="share of readable crops kept")
ax.plot(cov["conf"], cov["exact"], color=ORANGE, label="exact among kept")
if res["reject_crops"]:
    ax.plot(cov["conf"], cov["rejects_sent"] / res["reject_crops"], color=AQUA, label="share of rejects sent")
ax.set_xlabel("confidence threshold")
ax.set_ylim(0, 1.02)
ax.set_title(f"{VERSION} on {res['crops']} readable val crops and {res['reject_crops']} rejects", loc="left")
ax.legend()
fig.tight_layout()

# %% [markdown]
# ### Readability
#
# Only for a run with the readability head: P(readable) of the readable crops against the rejects, and what a
# threshold on it keeps (the default, 0.5, is the head's own decision). The edge node's threshold is chosen
# behind the detector, in `03_pipeline.py`.

# %%
if "readability_curve" in res:
    p_readable = pd.DataFrame({"kind": [c["kind"] for c in evaluation.crops],
                               "readable": [r.readable for r in evaluation.readings]})
    fig, axes = plt.subplots(1, 2, figsize=(13, 3.6))
    bins = np.linspace(0, 1, 21)
    for kind, color in ((READABLE, AQUA), ("unreadable", BLUE), ("ignore", BASE)):
        values = p_readable.loc[p_readable["kind"] == kind, "readable"]
        axes[0].hist(values, bins=bins, color=color, alpha=0.7, label=f"{kind} ({len(values)})")
    axes[0].set_xlabel("P(readable)")
    axes[0].set_ylabel("val crops")
    axes[0].legend()
    axes[0].set_title("P(readable) by crop kind", loc="left")
    rc = pd.DataFrame(res["readability_curve"])
    axes[1].plot(rc["readable"], rc["kept"], color=BLUE, label="share of readable crops kept")
    axes[1].plot(rc["readable"], rc["exact"], color=ORANGE, label="exact among kept")
    axes[1].plot(rc["readable"], rc["rejects_sent"] / res["reject_crops"], color=AQUA,
                 label="share of rejects sent")
    axes[1].set_xlabel("P(readable) threshold")
    axes[1].set_ylim(0, 1.02)
    axes[1].legend()
    axes[1].set_title("what a readability threshold keeps", loc="left")
    fig.tight_layout()
else:
    print(f"{VERSION} has no readability head.")

# %% [markdown]
# ## 4. Comparison with the baseline
#
# The baseline model reads the val crops of this version's dataset here, so both are measured on the same
# crops, rejects included, even when the baseline was trained and evaluated without them.

# %%
def summary(r):
    return {**{k: r[k] for k in SUMMARY_KEYS if k != "crops"},
            **{f"exact {b['width_px']} px": b["exact"] for b in r["by_width"]}}


base_res = None
if base_cfg and run_state(run_dir(base_cfg)) != "finished":
    print(f"{run_dir(base_cfg)} is not finished: train it first")
elif base_cfg:
    base_readings = Reader(run_dir(base_cfg)).read_all([read_image(c["path"]) for c in evaluation.crops])
    base_res = evaluate([c["text"] for c in evaluation.crops], base_readings,
                        [c["width_px"] for c in evaluation.crops])
    cmp = pd.DataFrame({BASELINE: summary(base_res), VERSION: summary(res)})
    cmp["change"] = cmp[VERSION] - cmp[BASELINE]
    display(cmp)
else:
    print("no baseline")

# %% [markdown]
# ### Error review (private)
#
# Every wrong read of a readable plate (an empty one included), the readable plates the OCR declines, the
# rejects it does not decline, then the least confident right reads. Label errors show up here too: a
# confident read that disagrees with the label, or a reject read with confidence, is worth checking in CVAT
# (train and val only, never test).

# %%
rows = pd.DataFrame([{**c, "read": r.text, "conf": r.conf, "readable": r.readable, "declined": r.declined}
                     for c, r in zip(evaluation.crops, evaluation.readings)])
rows["correct"] = rows["read"] == rows["text"]
readable = rows["kind"] == READABLE
label = rows["read"].replace("", "(none)") + rows["conf"].map(" {:.2f}".format)
if SHOW_IMAGES:
    grids = [
        (rows[readable & ~rows["correct"]], "wrong reads", rows["text"] + " -> " + label),
        (rows[readable & rows["declined"]], "readable plates declined", rows["text"] + " -> " + label),
        (rows[~readable & ~rows["declined"]].sort_values("conf", ascending=False),
         "rejects not declined, most confident first", rows["kind"] + ": " + label),
        (rows[readable & rows["correct"]].nsmallest(8, "conf"), "least confident right reads", label),
    ]
    for subset, title, labels in grids:
        if len(subset):
            show_grid(subset.assign(label=labels), f"{title} ({len(subset)})")
        else:
            print(f"{title}: none")
else:
    print("SHOW_IMAGES is off: crops are not shown.")
# Plate texts are personal data too: the table that also lands in reports shows where the errors are, not what
# the plates say.
errors = (readable & (~rows["correct"] | rows["declined"])) | (~readable & ~rows["declined"])
rows.loc[errors, ["frame", "kind", "plate", "width_px", "conf", "readable", "declined"]]

# %% [markdown]
# ## 5. Summary and conclusions
#
# The written conclusions of a version live in `notebooks/conclusions/ocr_<VERSION>.md`.

# %%
display(pd.Series(summary(res), name=f"OCR {VERSION}, val crops").to_frame())
conclusions = ROOT / "notebooks" / "conclusions" / f"ocr_{VERSION}.md"
display(Markdown(conclusions.read_text(encoding="utf-8")) if conclusions.exists()
        else Markdown(f"_No conclusions yet: write them in `notebooks/conclusions/{conclusions.name}`._"))
