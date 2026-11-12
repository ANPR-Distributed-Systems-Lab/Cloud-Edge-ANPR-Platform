"""The dataset definition files and the validated labels every training step reads.

- labeling/splits.json: which recording session belongs to train, val or test (sessions, never frames).
- labeling/exports/<batch>.jsonl: one validated frame per line, written by anpr-validate:

      {"image": "<batch>/<session>__<subdir>__<file>.jpg", "width": 4056, "height": 3040,
       "plates": [{"corners": [[x, y], ...], "text": "WA12345", "readable": true,
                   "occlusion": "none", "type": "standard"}],
       "ignore": [{"corners": [[x, y], ...]}]}

  Corners are TL, TR, BR, BL relative to the plate, normalized to 0-1 by the frame size.
"""
import json
from collections import Counter
from pathlib import Path

import numpy as np

from ..paths import EXPORTS_DIR, SPLITS_FILE
from .geometry import plate_width

SPLITS = ("train", "val", "test")

# Labeling rule: a plate narrower than this on the original frame is labeled plate_ignore. Raising it later is
# lossless (plates become ignored); lowering it needs relabeling, because plate_ignore carries no attributes.
SMALL_PLATE_PX = 70
# Plate width buckets (px on the original) shared by every metric reported per plate size.
WIDTH_BUCKETS = ((70, 90), (90, 110), (110, 140), (140, 200), (200, float("inf")))


def width_bucket_name(lo: float, hi: float) -> str:
    """"70-90"; the open last bucket is "200-"."""
    return f"{lo:g}-" if hi == float("inf") else f"{lo:g}-{hi:g}"


def width_bucket_of(width: float) -> str | None:
    """Name of the bucket a width falls into; None below the first bucket."""
    return next((width_bucket_name(lo, hi) for lo, hi in WIDTH_BUCKETS if lo <= width < hi), None)


def batch_file_name(session: str, file: str) -> str:
    """Name of a frame inside a batch folder: the session and the path inside it, joined by '__'."""
    return f"{session}__{file.replace('/', '__')}"


def session_of(image: str) -> str:
    """Session of a labeled frame, from its batch file name (see batch_file_name)."""
    return Path(image).name.split("__")[0]


def load_splits() -> dict:
    with open(SPLITS_FILE) as f:
        return json.load(f)


def export_paths(batches: list[str]) -> list[Path]:
    return [EXPORTS_DIR / f"{b}.jsonl" for b in batches]


def load_records(paths: list[Path]) -> list[dict]:
    """Records of all given label files. A frame labeled in two batches is an error, not a duplicate sample."""
    records = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            records.extend(json.loads(line) for line in f if line.strip())
    counts = Counter(Path(r["image"]).name for r in records)
    duplicates = [name for name, n in counts.items() if n > 1]
    if duplicates:
        raise ValueError(f"frames labeled in more than one export: {duplicates[:5]}")
    return records


def split_records(records: list[dict], splits: dict) -> dict[str, list[dict]]:
    """Records grouped by the split of their session; the batch a frame came from plays no role."""
    split_of = {s: name for name in SPLITS for s in splits[name]}
    out: dict[str, list[dict]] = {name: [] for name in SPLITS}
    for r in records:
        session = session_of(r["image"])
        if session not in split_of:
            raise ValueError(f"{r['image']}: session {session} is not in splits.json")
        out[split_of[session]].append(r)
    return out


def frame_size(record: dict) -> np.ndarray:
    """(width, height) of the original frame; multiplies normalized corners into pixels."""
    return np.array([record["width"], record["height"]], dtype=float)


def plate_width_px(corners: np.ndarray, record: dict) -> float:
    """Width on the original frame of a plate given by normalized corners."""
    return plate_width(np.asarray(corners) * frame_size(record))
