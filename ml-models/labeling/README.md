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
.\labeling\cvat.ps1 superuser     # create the admin account (the password is typed interactively)
```

CVAT opens at http://localhost:8080. `cvat.ps1` always uses the `desktop-linux` Docker context. Do not start
CVAT with the default context, which points at the Raspberry Pi. Other commands: `.\labeling\cvat.ps1 status`,
`logs` and `down`.

Rules that keep the labels safe:

- Start CVAT only through `cvat.ps1`. A plain `docker compose up` in `labeling/cvat/` does not mount the batch
  folders: jobs then show "Could not receive image data" (`FileNotFoundError` under `/home/django/share` in the
  server logs).
- Never delete or rename a batch folder while its task exists: CVAT reads the images from it every time.
- Never run `docker compose down -v`: the `cvat_*` volumes hold the database with all annotations.

`splits.json` must not change once labeling started (`--force` is needed to overwrite it): it is what keeps
the test sessions out of training.

## New recordings

When new sessions are copied into `data/`, add them without touching anything labeled so far:

```powershell
uv run anpr-index                           # hashes only the frames not indexed yet
uv run anpr-splits --add --test 3 --val 3   # assigns only the new sessions; the others keep their split
```

`--test` and `--val` count the new sessions only. Pick them so test and validation keep roughly their share
(about 1 in 7 sessions each). The new frames then appear in the next `anpr-select` batches; frames already in
a batch are never offered again.

## Making a batch

```powershell
uv run anpr-select --split train --sweep                       # how many frames survive each dedupe threshold
uv run anpr-select --split train --batch train_001 --count 300 # bootstrap batch, labeled by hand
uv run anpr-select --split test  --batch test_001  --count 150 # test set, labeled by hand from scratch
```

Frames are hard-linked into `labeling/batches/<batch>/` (no extra disk space) and recorded in
`labeling/selected.csv`, so a frame is never offered twice. The dedupe threshold is the Hamming distance
(of 64 bits) to the last kept frame: a frame is kept when the distance is at least `--threshold` (default 5,
so a distance of 4 or less counts as a duplicate). `train_001` was selected with 8, which dropped too many
frames that differed in content; `--sweep` shows how many frames survive each threshold.

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
- **Small plates**: narrower than about 70 px on the original frame go to label `plate_ignore` (4 points, no
  attributes). The threshold is confirmed with the width statistics from `anpr-validate` after the first ~100 labels.
  From 70 px up label the plate as `plate` and set `readable` honestly, even when it is hard to read: the
  `readable` values per width show how far OCR can reach.
- **Cut off at the frame edge**: label the plate only if all four corners are inside the image. Otherwise draw
  it as `plate_ignore`.
- **Attributes of `plate`**:
  - `text`: the plate number, uppercase letters and digits, no spaces or separators.
  - `readable`: `yes` if you can read every character, `no` otherwise (the plate stays in detection
    data and is dropped for OCR; leave `text` empty).
  - `occlusion`: `none` or `partial` (part of the plate hidden, the corners are still estimated).
  - `type`: `standard`, `two-line`, `motorcycle` or `other`.
- **Pre-annotations** (detector predictions imported into a task): correct them, do not just accept them. Test
  batches are always labeled without any model suggestion.

## Export and validation

In CVAT: task -> Actions -> *Export task dataset* -> format **CVAT for images 1.1**, "Save images" off. Save
the zip into `labeling/exports/`, then:

```powershell
uv run anpr-validate labeling\exports\train_001.zip --out labeling\exports\train_001.jsonl
```

The validator checks the point count, corner order, convexity, the image bounds, the attributes and the
text, and prints the plate width distribution on the original frame. It exits non-zero on errors, and only
writes the `.jsonl` (corners normalized to 0-1) when there are none. When reporting a problem, use the frame
number CVAT shows: it is the `id` of the `<image>` element in `annotations.xml` (0-based).

The validated `.jsonl` files are what the training steps read; see the [README](../README.md) for building the
dataset and training the detector.
