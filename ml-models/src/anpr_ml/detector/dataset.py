"""anpr-yolo-dataset: validated labels (.jsonl) -> YOLO-pose dataset at the detector input size.

Every frame is downscaled offline with resize_for_detector(), so the training library never resamples it and
the pixels match what the edge node feeds the detector. Images are written as PNG to avoid a second lossy JPEG
step. A frame's split comes from splits.json (its session), never from the batch name.

Ultralytics has no ignore label, so plate_ignore regions and plates narrower than the small-plate threshold
are painted with a neutral gray: the detector is then neither trained to find them nor penalized for finding
them. Pixels of real plates are never painted, even where an ignore region overlaps them.

Label line per plate: `0 cx cy w h x1 y1 2 x2 y2 2 x3 y3 2 x4 y4 2`, corners TL, TR, BR, BL, all normalized;
the box is derived from the corners.

A dataset directory is written once and never overwritten: manifest.json records the label files (by checksum)
and the parameters it was built from, and ensure_dataset() refuses one that no longer matches its config.
"""
import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

from ..common.geometry import quad_box
from ..common.labels import (
    SMALL_PLATE_PX,
    export_paths,
    load_records,
    load_splits,
    plate_width_px,
    split_records,
)
from ..common.preprocess import DETECTOR_SIZE, read_image, resize_for_detector
from ..paths import BATCHES_DIR, DATASETS_DIR, EXPORTS_DIR
from .config import dataset_dir

IGNORE_FILL = 114  # Ultralytics' letterbox gray, already a "nothing here" color for the model
IGNORE_MARGIN_PX = 3  # at detector scale; ignore corners are clicked roughly, so err outside
FLIP_IDX = [1, 0, 3, 2]  # TL<->TR, BR<->BL; only used if horizontal flip is ever enabled


def ignore_mask(
    size: tuple[int, int], ignore: list[np.ndarray], keep: list[np.ndarray], margin_px: int
) -> np.ndarray:
    """Boolean (h, w) mask of the pixels to paint; polygons are in pixels of the target size."""
    w, h = size
    mask = np.zeros((h, w), np.uint8)
    for poly in ignore:
        cv2.fillPoly(mask, [np.round(poly).astype(np.int32)], 1)
    if margin_px > 0 and mask.any():
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin_px + 1, 2 * margin_px + 1))
        mask = cv2.dilate(mask, kernel)
    protected = np.zeros_like(mask)
    for poly in keep:
        cv2.fillPoly(protected, [np.round(poly).astype(np.int32)], 1)
    return (mask > 0) & (protected == 0)


def label_line(corners: np.ndarray) -> str:
    """YOLO-pose label line of one plate from its normalized corners; every keypoint is visible (2)."""
    c = np.clip(np.asarray(corners, dtype=float), 0.0, 1.0)
    x1, y1, x2, y2 = quad_box(c)
    values = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]
    for x, y in c:
        values += [x, y, 2]
    return "0 " + " ".join(f"{v:.6f}" if not isinstance(v, int) else str(v) for v in values)


def convert_record(
    record: dict, image: np.ndarray, size: tuple[int, int], min_plate_px: float, margin_px: int, fill: int
) -> tuple[np.ndarray, list[str], Counter]:
    """The resized and painted image of one frame, its label lines and counters for the manifest."""
    stats = Counter()
    scale = np.array(size, dtype=float)
    keep, ignore, lines = [], [], []
    for plate in record["plates"]:
        corners = np.array(plate["corners"])
        if plate_width_px(corners, record) < min_plate_px:
            ignore.append(corners * scale)
            stats["plates_demoted_small"] += 1
            continue
        keep.append(corners * scale)
        lines.append(label_line(corners))
        stats["plates"] += 1
    for region in record["ignore"]:
        ignore.append(np.array(region["corners"]) * scale)
        stats["ignore_regions"] += 1

    resized = resize_for_detector(image, size)
    resized[ignore_mask(size, ignore, keep, margin_px)] = fill
    stats["images"] += 1
    stats["negatives"] += not lines
    return resized, lines, stats


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataset(
    exports: list[Path],
    out_dir: Path,
    size: tuple[int, int] = DETECTOR_SIZE,
    min_plate_px: float = SMALL_PLATE_PX,
    margin_px: int = IGNORE_MARGIN_PX,
    fill: int = IGNORE_FILL,
    images_dir: Path = BATCHES_DIR,
    splits: dict | None = None,
) -> dict:
    """Writes images/<split>, labels/<split>, data.yaml and manifest.json into out_dir; returns the manifest."""
    if out_dir.exists():
        raise FileExistsError(f"{out_dir} already exists; pick another name or delete it after checking it")
    by_split = split_records(load_records(exports), splits if splits is not None else load_splits())
    tmp = out_dir.with_name(out_dir.name + ".partial")
    if tmp.exists():
        raise FileExistsError(f"{tmp} is left over from an interrupted run; check and delete it")

    counts: dict[str, dict] = {}
    for split, records in by_split.items():
        if not records:
            continue
        (tmp / "images" / split).mkdir(parents=True)
        (tmp / "labels" / split).mkdir(parents=True)
        total = Counter()
        for r in records:
            image, lines, stats = convert_record(
                r, read_image(images_dir / r["image"]), size, min_plate_px, margin_px, fill
            )
            stem = Path(r["image"]).stem
            if not cv2.imwrite(str(tmp / "images" / split / f"{stem}.png"), image):
                raise OSError(f"cannot write {stem}.png")
            (tmp / "labels" / split / f"{stem}.txt").write_text("".join(line + "\n" for line in lines))
            total += stats
        counts[split] = dict(total)

    data = {
        "path": str(out_dir.resolve()),
        **{split: f"images/{split}" for split in counts},
        "kpt_shape": [4, 3],
        "flip_idx": FLIP_IDX,
        "names": {0: "plate"},
    }
    (tmp / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    manifest = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "size": list(size),
        "resize": "cv2.resize INTER_AREA (anpr_ml.common.preprocess.resize_for_detector)",
        "opencv": cv2.__version__,
        "min_plate_px": min_plate_px,
        "ignore_margin_px": margin_px,
        "ignore_fill": fill,
        "sources": {p.name: sha256_file(p) for p in exports},
        "counts": counts,
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
    tmp.rename(out_dir)  # a dataset directory only ever exists complete
    return manifest


def ensure_dataset(cfg: dict) -> dict:
    """Builds the config's dataset if it is missing and returns its manifest. Refuses a dataset built from other
    label files or parameters, so a relabeled batch never trains silently on stale data."""
    d = cfg["dataset"]
    exports = export_paths(d["exports"])
    out = dataset_dir(cfg)
    if not (out / "manifest.json").exists():
        build_dataset(exports, out, d["size"], d["min_plate_px"], d["ignore_margin_px"])
    manifest = json.loads((out / "manifest.json").read_text())
    expected = {
        "sources": {p.name: sha256_file(p) for p in exports},
        "size": list(d["size"]),
        "min_plate_px": d["min_plate_px"],
        "ignore_margin_px": d["ignore_margin_px"],
    }
    stale = {k: {"dataset": manifest[k], "config": v} for k, v in expected.items() if manifest[k] != v}
    if stale:
        raise ValueError(f"{out} does not match the config, give the dataset a new name: {stale}")
    return manifest


def parse_size(text: str) -> tuple[int, int]:
    w, h = (int(v) for v in text.lower().split("x"))
    if w % 32 or h % 32:
        raise argparse.ArgumentTypeError("both sides must be divisible by 32 (the YOLO stride)")
    return w, h


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="dataset name, written to datasets/<name>/")
    parser.add_argument("--exports", nargs="*", help="batch names (default: every labeling/exports/*.jsonl)")
    parser.add_argument("--size", type=parse_size, default=DETECTOR_SIZE, help="WxH, e.g. 1280x960")
    parser.add_argument("--min-plate-px", type=float, default=SMALL_PLATE_PX)
    parser.add_argument("--margin-px", type=int, default=IGNORE_MARGIN_PX)
    args = parser.parse_args()

    exports = export_paths(args.exports) if args.exports else sorted(EXPORTS_DIR.glob("*.jsonl"))
    manifest = build_dataset(exports, DATASETS_DIR / args.name, args.size, args.min_plate_px, args.margin_px)
    print(json.dumps(manifest["counts"], indent=2))
    print(f"written {DATASETS_DIR / args.name}")


if __name__ == "__main__":
    main()
