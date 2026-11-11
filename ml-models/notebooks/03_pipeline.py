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
# # Pipeline analysis: detector + OCR on the val frames
#
# Runs a detector version and an OCR version together, the way the edge node will, and compares the pair
# with a baseline pair. **To switch versions, change `DETECTOR` and `OCR` (and optionally the baseline pair)
# in the first code cell and run all cells.** Each model has its own notebook (`01_detector.py`,
# `02_ocr.py`); this one answers what comes out of the whole chain:
#
# full frame -> `resize_for_detector()` -> detector -> corners on the original -> `rectify_plate()` -> OCR
#
# The detector runs at its operating threshold (best F1 on val). Every detection is read, as on the edge
# node, and each read is one of: `correct` / `wrong` (a readable plate), `unreadable` (a plate labeled not
# readable), `dont_care` (an ignore region or a plate below the small-plate threshold), `background` (no
# plate). Only `correct` reads are good output; the rest is what a filter on the edge node has to stop. An OCR
# trained with rejects (v2 on) can also read nothing: such a read is never sent, and is counted as `rejected`
# in its category (for a readable plate that is a plate lost).
#
# **Privacy.** Cells that draw crops run only when `SHOW_IMAGES` is on; committed reports are executed with
# `ANPR_SHOW_IMAGES=0`. Tables here show frame names and widths, never plate texts.
#
# **Running it.** Both runs must be finished and the detector evaluated (`anpr-eval-detector`). The same
# evaluation from a terminal:
#
# ```powershell
# uv run anpr-eval-pipeline --detector configs/detector_v2.yaml --ocr configs/ocr_v2.yaml
# ```
#
# A report: set `$env:ANPR_SHOW_IMAGES = "0"`, `ANPR_PIPELINE_DETECTOR`, `ANPR_PIPELINE_OCR` (and the
# `_BASELINE_` variants), then convert and execute as for the other notebooks
# (`notebooks/reports/03_pipeline_<detector>__<ocr>.ipynb`).

# %% tags=["parameters"]
DETECTOR = "v2"           # configs/detector_<DETECTOR>.yaml
OCR = "v2"                # configs/ocr_<OCR>.yaml
BASELINE_DETECTOR = "v2"  # the pair compared against; None for no comparison
BASELINE_OCR = "v1"

# %%
import json
import os

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import Markdown, display

from anpr_ml.analysis import COLORS, config_header, config_path, from_env, plot_style, show_images
from anpr_ml.common.labels import frame_size
from anpr_ml.common.preprocess import read_image, rectify_plate
from anpr_ml.detector import config as detector_config
from anpr_ml.ocr import config as ocr_config
from anpr_ml.paths import BATCHES_DIR, ROOT, RUNS_DIR
from anpr_ml.pipeline import CATEGORIES, evaluate_pipeline

os.chdir(ROOT)  # Ultralytics downloads helper weights into the working directory; *.pt is gitignored there

DETECTOR = from_env("ANPR_PIPELINE_DETECTOR", DETECTOR)
OCR = from_env("ANPR_PIPELINE_OCR", OCR)
BASELINE_DETECTOR = from_env("ANPR_PIPELINE_BASELINE_DETECTOR", BASELINE_DETECTOR)
BASELINE_OCR = from_env("ANPR_PIPELINE_BASELINE_OCR", BASELINE_OCR)
BASELINE = (BASELINE_DETECTOR, BASELINE_OCR) if BASELINE_DETECTOR and BASELINE_OCR else None
if BASELINE == (DETECTOR, OCR):
    BASELINE = None
SHOW_IMAGES = show_images()

det_cfg = detector_config.load_config(config_path("detector", DETECTOR))
ocr_cfg = ocr_config.load_config(config_path("ocr", OCR))

plot_style()
BLUE, ORANGE, AQUA, INK_2, BASE = (COLORS[k] for k in ("blue", "orange", "aqua", "ink_2", "base"))
CATEGORY_COLORS = {"correct": AQUA, "wrong": ORANGE, "unreadable": BLUE, "dont_care": BASE,
                   "background": INK_2}

display(Markdown(f"**Detector {DETECTOR}.** {config_header(config_path('detector', DETECTOR))}\n\n"
                 f"**OCR {OCR}.** {config_header(config_path('ocr', OCR))}"))

# %% [markdown]
# ## 1. End to end on the val frames
#
# `evaluate_pipeline()` is what `anpr-eval-pipeline` runs; it writes
# `runs/pipeline/<detector>__<ocr>/eval_val.json`.

# %%
ev = evaluate_pipeline(det_cfg, ocr_cfg)
res = ev.result
ocr_alone = json.loads((ocr_config.run_dir(ocr_cfg) / "eval_val.json").read_text())
pd.Series({
    "detector operating conf": res["detector_conf"],
    "readable plates": res["readable_plates"],
    "detected": res["detected"],
    "read right": res["read_correct"],
    "read right / readable": res["recall"],
    "OCR alone on labeled corners (exact)": ocr_alone["exact"],
}, name=f"detector {DETECTOR} + OCR {OCR}").to_frame()

# %% [markdown]
# The gap between `read right / readable` and the OCR alone is what the detector costs: missed plates and
# corners less exact than the labels.

# %%
pd.DataFrame([res["reads"], res["rejected"]], index=["reads", "of them read as no text"])

# %% [markdown]
# ## 2. What would be sent
#
# For a threshold on the OCR confidence: the reads that pass (a text at or above the threshold), by category.
# `precision` is the share of passing reads that are right, `recall` the share of readable plates read right.
# This is what the filter on the edge node trades off; format rules and agreement across frames come on top of
# it later.

# %%
curve = pd.DataFrame(res["curve"])
fig, axes = plt.subplots(1, 2, figsize=(14, 3.8))
axes[0].plot(curve["conf"], curve["precision"], color=BLUE, label="precision of sent reads")
axes[0].plot(curve["conf"], curve["recall"], color=ORANGE, label="readable plates read right")
axes[0].set_xlabel("OCR confidence threshold")
axes[0].set_ylim(0, 1.02)
axes[0].legend()
axes[0].set_title("sent reads", loc="left")
bottom = np.zeros(len(curve))
x = np.arange(len(curve))
for c in CATEGORIES:
    axes[1].bar(x, curve[c], bottom=bottom, color=CATEGORY_COLORS[c], label=c, edgecolor=COLORS["paper"])
    bottom += curve[c].to_numpy()
axes[1].set_xticks(x, [f"{t:g}" for t in curve["conf"]], rotation=45)
axes[1].set_xlabel("OCR confidence threshold")
axes[1].set_ylabel("reads")
axes[1].legend(ncols=3, fontsize=8)
axes[1].set_title("reads passing the threshold, by category", loc="left")
fig.tight_layout()

# %%
curve.set_index("conf")[["sent", *CATEGORIES, "precision", "recall"]]

# %% [markdown]
# ## 3. By plate width

# %%
pd.DataFrame(res["by_width"]).set_index("width_px")

# %% [markdown]
# ## 4. Comparison with the baseline pair
#
# Read from the baseline pair's saved `eval_val.json` (run `anpr-eval-pipeline` for it first). Comparable when
# both detector configs use the same val frames.

# %%
def summary(r):
    at = {c["conf"]: c for c in r["curve"]}
    # Evaluations written before rejects existed have no "rejected": their OCR never read nothing.
    rejected = r.get("rejected", dict.fromkeys(CATEGORIES, 0))
    return {"read right / readable": r["recall"], "detected": r["detected"],
            **{f"sent @0 {c}": at[0.0][c] for c in CATEGORIES},
            **{f"no text: {c}": rejected[c] for c in CATEGORIES},
            **{f"precision @{t}": at[t]["precision"] for t in (0.0, 0.5, 0.9) if t in at}}


if BASELINE:
    base_det, base_ocr = BASELINE
    base_file = RUNS_DIR / "pipeline" / f"{base_det}__{base_ocr}" / "eval_val.json"
    if base_file.exists():
        base = json.loads(base_file.read_text())
        cmp = pd.DataFrame({f"{base_det} + {base_ocr}": summary(base), f"{DETECTOR} + {OCR}": summary(res)})
        cmp["change"] = cmp.iloc[:, 1] - cmp.iloc[:, 0]
        display(cmp)
    else:
        print(f"{base_file} is missing: run `uv run anpr-eval-pipeline "
              f"--detector configs/detector_{base_det}.yaml --ocr configs/ocr_{base_ocr}.yaml`")
else:
    print("no baseline pair")

# %% [markdown]
# ### Error review (private)
#
# Crops as the edge node cuts them, from the detector's corners: wrong reads of readable plates (no text
# included), then the most confident texts read where there is no plate to read (unreadable, don't-care,
# background): the ones a confidence threshold alone would let through.

# %%
def crop_of(read):
    record = next(r for r in ev.records if r["image"] == read.frame)
    frame = read_image(BATCHES_DIR / read.frame)
    crop = rectify_plate(frame, read.detection.corners * frame_size(record), ocr_cfg["dataset"]["size"],
                         ocr_cfg["dataset"]["margin"])
    return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)


def show_reads(reads, title, label, n=8):
    if not reads:
        print(f"{title}: none")
        return
    reads = reads[:n]
    fig, axes = plt.subplots(1, len(reads), figsize=(2.1 * len(reads), 1.5), squeeze=False)
    for ax, read in zip(axes[0], reads):
        ax.imshow(crop_of(read))
        ax.set_title(label(read), fontsize=8, loc="left")
        ax.axis("off")
    fig.suptitle(title, x=0.01, ha="left")
    fig.tight_layout()


if SHOW_IMAGES:
    wrong = [r for r in ev.reads if r.category == "wrong"]
    show_reads(wrong, f"wrong reads ({len(wrong)})",
               lambda r: f"{r.truth} -> {r.reading.text or '(none)'} {r.reading.conf:.2f}")
    junk = sorted((r for r in ev.reads if r.category in ("unreadable", "dont_care", "background")
                   and r.reading.text), key=lambda r: -r.reading.conf)
    show_reads(junk, "most confident texts read on non-targets",
               lambda r: f"{r.category}: {r.reading.text} {r.reading.conf:.2f}")
else:
    print("SHOW_IMAGES is off: crops are not shown.")
pd.DataFrame([{"frame": r.frame.split("/")[-1], "category": r.category, "no text": not r.reading.text,
               "conf": r.reading.conf, "width_px": r.width_px} for r in ev.reads if r.category != "correct"]) \
    .sort_values(["no text", "conf"], ascending=[True, False]).head(15)

# %% [markdown]
# ## 5. Conclusions
#
# Written per pair in `notebooks/conclusions/pipeline_<detector>__<ocr>.md`.

# %%
conclusions = ROOT / "notebooks" / "conclusions" / f"pipeline_{DETECTOR}__{OCR}.md"
display(Markdown(conclusions.read_text(encoding="utf-8")) if conclusions.exists()
        else Markdown(f"_No conclusions yet: write them in `notebooks/conclusions/{conclusions.name}`._"))
