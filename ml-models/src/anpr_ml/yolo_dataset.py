"""anpr-yolo-dataset: validated labels (.jsonl) -> YOLO-pose dataset at the detector input size.

Every frame is downscaled offline with resize_for_detector(), so the training library never resamples it
and the pixels match what the edge node feeds the detector. Images are written as PNG to avoid a second
lossy JPEG step. A frame's split comes from splits.json (its session), never from the batch name.

plate_ignore regions, and plates narrower than --min-plate-px on the original, are painted with a neutral
gray: the detector is then neither trained to find them nor penalized for finding them. Pixels of real
plates are never painted, even where an ignore region overlaps them.

Label line per plate: `0 cx cy w h x1 y1 2 x2 y2 2 x3 y3 2 x4 y4 2`, corners TL, TR, BR, BL, normalized.
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

from .geometry import plate_width_px, quad_box
from .make_splits import load_splits
from .paths import BATCHES_DIR, DATASETS_DIR, EXPORTS_DIR
from .preprocess import DETECTOR_SIZE, read_image, resize_for_detector

MIN_PLATE_PX = 70  # same as IGNORE_WIDTH_PX in validate_export; raising it here is lossless
IGNORE_FILL = 114  # Ultralytics letterbox gray, already a "nothing here" color for the model
IGNORE_MARGIN_PX = 3  # at detector scale: ignore corners are clicked roughly, err outside
FLIP_IDX = [1, 0, 3, 2]  # TL<->TR, BR<->BL; only used if horizontal flip is ever enabled


def session_of(image: str) -> str:
    """Batch file names are `<session>__<subdir>__<file>` (see select_frames.batch_name)."""
    return Path(image).name.split("__")[0]


def load_records(exports: list[Path]) -> list[dict]:
    records = []
    for path in exports:
        with open(path, encoding="utf-8") as f:
            records.extend(json.loads(line) for line in f if line.strip())
    names = Counter(Path(r["image"]).name for r in records)
    duplicates = [n for n, c in names.items() if c > 1]
    if duplicates:
        raise ValueError(f"frames labeled in more than one export: {duplicates[:5]}")
    return records


def split_records(records: list[dict], splits: dict) -> dict[str, list[dict]]:
    split_of = {s: k for k in ("train", "val", "test") for s in splits[k]}
    out: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for r in records:
        session = session_of(r["image"])
        if session not in split_of:
            raise ValueError(f"{r['image']}: session {session} is not in splits.json")
        out[split_of[session]].append(r)
    return out


def ignore_mask(
    size: tuple[int, int], ignore: list[np.ndarray], keep: list[np.ndarray], margin_px: int
) -> np.ndarray:
    """Boolean mask (h, w) of pixels to paint. Polygons are in pixels at the target size."""
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
    """YOLO-pose line from normalized TL-TR-BR-BL corners; the box is derived from the corners."""
    c = np.clip(np.asarray(corners, dtype=float), 0.0, 1.0)
    x1, y1, x2, y2 = quad_box(c)
    values = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]
    for x, y in c:
        values += [x, y, 2]
    return "0 " + " ".join(f"{v:.6f}" if not isinstance(v, int) else str(v) for v in values)


def convert_record(
    record: dict, image: np.ndarray, size: tuple[int, int], min_plate_px: float, margin_px: int, fill: int
) -> tuple[np.ndarray, list[str], Counter]:
    """Resized and painted image, its label lines and counters for the manifest."""
    stats = Counter()
    orig = np.array([record["width"], record["height"]], dtype=float)
    scale = np.array(size, dtype=float)
    keep, ignore, lines = [], [], []
    for plate in record["plates"]:
        corners = np.array(plate["corners"])
        if plate_width_px(corners * orig) < min_plate_px:
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
    mask = ignore_mask(size, ignore, keep, margin_px)
    resized[mask] = fill
    stats["images"] += 1
    stats["negatives"] += not lines
    return resized, lines, stats


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataset(
    exports: list[Path],
    out_dir: Path,
    size: tuple[int, int] = DETECTOR_SIZE,
    min_plate_px: float = MIN_PLATE_PX,
    margin_px: int = IGNORE_MARGIN_PX,
    fill: int = IGNORE_FILL,
    images_dir: Path = BATCHES_DIR,
    splits: dict | None = None,
) -> dict:
    """Writes images/<split>, labels/<split>, data.yaml and manifest.json into out_dir (must not exist)."""
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
        "resize": "cv2.resize INTER_AREA (anpr_ml.preprocess.resize_for_detector)",
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


def parse_size(text: str) -> tuple[int, int]:
    w, h = (int(v) for v in text.lower().split("x"))
    if w % 32 or h % 32:
        raise argparse.ArgumentTypeError("both sides must be divisible by 32 (YOLO stride)")
    return w, h


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="dataset name, written to datasets/<name>/")
    parser.add_argument("--exports", nargs="*", help="batch names (default: every labeling/exports/*.jsonl)")
    parser.add_argument("--size", type=parse_size, default=DETECTOR_SIZE, help="WxH, e.g. 1280x960")
    parser.add_argument("--min-plate-px", type=float, default=MIN_PLATE_PX)
    parser.add_argument("--margin-px", type=int, default=IGNORE_MARGIN_PX)
    args = parser.parse_args()

    exports = (
        [EXPORTS_DIR / f"{b}.jsonl" for b in args.exports]
        if args.exports
        else sorted(EXPORTS_DIR.glob("*.jsonl"))
    )
    manifest = build_dataset(exports, DATASETS_DIR / args.name, args.size, args.min_plate_px, args.margin_px)
    print(json.dumps(manifest["counts"], indent=2))
    print(f"written {DATASETS_DIR / args.name}")


if __name__ == "__main__":
    main()
