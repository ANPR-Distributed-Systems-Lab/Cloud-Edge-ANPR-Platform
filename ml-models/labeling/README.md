# Labeling

Plates are labeled in a local CVAT. Each plate is a 4-point polygon plus a few attributes. The rules below
are the labeling guide; the decisions behind them are in [../ML_ASSUMPTIONS.md](../ML_ASSUMPTIONS.md).

## One-time setup

```powershell
# from ml-models/
uv sync
uv run anpr-index                 # perceptual hash of every frame (a few minutes, incremental)
uv run anpr-splits                # assigns whole sessions to train / val / test, writes labeling/splits.json
.\labeling\cvat.ps1 up            # needs Docker Desktop running; first start pulls several GB
.\labeling\cvat.ps1 superuser     # create your admin account (you type the password)
```

CVAT opens at http://localhost:8080. `cvat.ps1` always uses the `desktop-linux` Docker context. Do not start
CVAT with the default context, which points at the Raspberry Pi.

`splits.json` must not change once labeling started (`--force` is needed to overwrite it): it is what keeps
the test sessions out of training.

## Making a batch

```powershell
uv run anpr-select --split train --sweep                       # how many frames survive each dedupe threshold
uv run anpr-select --split train --batch train_001 --count 300 # bootstrap batch, labeled by hand
uv run anpr-select --split test  --batch test_001  --count 150 # test set, labeled by hand from scratch
```

Frames are hard-linked into `labeling/batches/<batch>/` (no extra disk space) and recorded in
`labeling/selected.csv`, so a frame is never offered twice. The dedupe threshold is the Hamming distance
(of 64 bits) to the last kept frame; pick it with `--sweep` and a look at the result.

## Creating the project and tasks in CVAT

1. **Projects -> Create**: name `plates`, in *Constructor* switch to the *Raw* tab and paste
   [cvat_labels.json](cvat_labels.json).
2. **Tasks -> Create**, one task per batch: project `plates`, tab *Connected file share*, select the
   `<batch>` folder. Under *Advanced configuration* set the image quality to 100 so the corners are judged on
   the real pixels.
3. Open the job. For polygons set **Number of points = 4** in the draw form, so the shape closes itself after
   the fourth corner. CVAT cannot enforce this in the label definition, so the validator below does.

## Rules

- **Plates**: draw every plate whose four corners are visible, label `plate`.
- **Corner order**: TL, TR, BR, BL, clockwise, relative to the plate itself, not the image. Start at the
  plate's own top-left corner.
- **Corner position**: where the outer edges of the plate meet (extend the straight edges), not the rounded corner.
  The plate is the whole rectangle including the blue EU strip, not just the block of characters. If unsure,
  err slightly outside (1-2 px), evenly on all sides, never tighter than the characters and never on one side only
  (an uneven margin distorts the characters when the plate is rectified).
- **Small plates**: narrower than about 80 px on the original frame go to label `plate_ignore` (4 points, no
  attributes). The threshold is confirmed with the width statistics from `anpr-validate` after the first ~100 labels.
- **Cut off at the frame edge**: label the plate only if all four corners are inside the image. Otherwise draw
  it as `plate_ignore`.
- **Attributes of `plate`**:
  - `text`: the plate number, uppercase letters and digits, no spaces or separators.
  - `readable`: `yes` if you can read every character, `no` otherwise (the plate stays in detection
    data and is dropped for OCR; leave `text` empty).
  - `occlusion`: `none` or `partial` (part of the plate hidden, the corners are still estimated).
  - `type`: `standard`, `two-line`, `motorcycle` or `other`.
- **Pre-annotations** (later, when a model exists): correct them, do not just accept them. The test batches are
  always labeled without any model suggestion.

## Export and validation

In CVAT: task -> Actions -> *Export task dataset* -> format **CVAT for images 1.1**, "Save images" off. Save
the zip into `labeling/exports/`, then:

```powershell
uv run anpr-validate labeling\exports\train_001.zip --out labeling\exports\train_001.jsonl
```

The validator checks the point count, corner order, convexity, the image bounds, the attributes and the
text, and prints the plate width distribution on the original frame. It exits non-zero on errors, and only
writes the `.jsonl` (corners normalized to 0-1) when there are none.
