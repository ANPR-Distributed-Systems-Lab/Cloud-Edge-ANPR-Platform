"""anpr-ocr-dataset: validated labels (.jsonl) -> plate crops in fast-plate-ocr's format.

Every plate labeled readable = yes is cut from the full-resolution frame with rectify_plate(), the function
the edge node uses on detected corners. Val gets one crop per plate, from the labeled corners. Train gets
`jitter_copies` crops per plate, each from corners displaced at random (normal, per corner and axis, sigma =
jitter_sigma x plate width), so the OCR learns to read plates cut with the detector's corner error; with
jitter_copies = 0 train gets one exact crop per plate too. A frame's split comes from splits.json; the test
split is never written.

Optionally (`--reject`, `dataset.reject` in a config) the dataset also holds rejects: crops the OCR has to
answer with no text at all (every slot padding) and the region "Unknown". Their sources are plates labeled
readable = no and plate_ignore regions, at least `reject_min_px` wide, cut and jittered like the readable
plates. Without them the OCR only ever sees readable plates and reads a plausible plate into anything.

Layout of datasets/<name>/:

    <split>/images/<frame>__p<plate>[__j<copy>].png   a plate (readable or not)
    <split>/images/<frame>__i<region>[__j<copy>].png  a plate_ignore region
    <split>/annotations.csv   image_path, plate_text, plate_region: exactly the columns fast-plate-ocr reads;
                              plate_text is empty for a reject
    <split>/crops.csv         image_path, frame, kind, plate, session, width_px, type, jitter: for the
                              analysis; kind is readable, unreadable or ignore, plate the index into the
                              record's plates (its ignore regions for kind ignore)
    manifest.json             the label files (by checksum), the crop settings and counts

A dataset directory is written once and never overwritten; ensure_dataset() refuses one that no longer
matches its config.
"""
import argparse
import csv
import json
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from ..common.labels import (
    SMALL_PLATE_PX,
    export_paths,
    frame_size,
    load_records,
    load_splits,
    plate_width_px,
    session_of,
    split_records,
)
from ..common.preprocess import OCR_MARGIN, OCR_SIZE, read_image, rectify_plate
from ..paths import BATCHES_DIR, DATASETS_DIR, EXPORTS_DIR
from .config import dataset_dir, sha256_file

# The pretrained model has a region head. Every readable plate here is Polish and every reject is "Unknown",
# both regions of the pretrained plate config, which keeps that head and the exported model's outputs
# unchanged. A readability model ignores the column and takes its class from the text
# (anpr_ml.ocr.readability).
REGION = "Poland"
REJECT_REGION = "Unknown"
READABLE = "readable"
REJECT_SOURCES = ("unreadable", "ignore")  # the crop kinds a reject can come from
SPLITS_WRITTEN = ("train", "val")
# The text is kept in annotations.csv only, so the two files cannot disagree; read_crops() joins them.
CROP_COLUMNS = ["image_path", "frame", "kind", "plate", "session", "width_px", "type", "jitter"]


@dataclass(frozen=True)
class CropSettings:
    """How crops are cut; recorded in the manifest, so a dataset built differently is never reused."""
    size: tuple[int, int] = OCR_SIZE
    margin: float = OCR_MARGIN
    jitter_copies: int = 8
    # Detector v1 on val_001: mean corner error 2.2 % of the plate width. A per-axis sigma of 1.5 % gives a
    # mean corner displacement of about 1.9 %, the same order.
    jitter_sigma: float = 0.015
    seed: int = 42
    reject_sources: tuple[str, ...] = ()  # empty: readable plates only
    # Narrower detections never reach the OCR on the edge node, so rejects below the threshold teach nothing.
    reject_min_px: float = SMALL_PLATE_PX

    def __post_init__(self):
        unknown = set(self.reject_sources) - set(REJECT_SOURCES)
        if unknown:
            raise ValueError(f"unknown reject sources {sorted(unknown)}; choose from {REJECT_SOURCES}")

    @classmethod
    def from_config(cls, cfg: dict) -> "CropSettings":
        d = cfg["dataset"]
        reject = d.get("reject") or {}
        return cls(tuple(d["size"]), d["margin"], d["jitter_copies"], d["jitter_sigma"], d["seed"],
                   tuple(reject.get("sources", ())), reject.get("min_px", SMALL_PLATE_PX))

    def as_manifest(self) -> dict:
        # "reject" is null without rejects, which also matches the manifests written before rejects existed.
        reject = ({"sources": list(self.reject_sources), "min_px": self.reject_min_px}
                  if self.reject_sources else None)
        return {"size": list(self.size), "margin": self.margin, "jitter_copies": self.jitter_copies,
                "jitter_sigma": self.jitter_sigma, "seed": self.seed, "reject": reject}


DEFAULT_SETTINGS = CropSettings()


@dataclass(frozen=True)
class Target:
    """A labeled quad that becomes crops: a readable plate with its text, or a reject with an empty text."""
    kind: str  # READABLE or one of REJECT_SOURCES
    index: int  # into record["plates"], or record["ignore"] for kind "ignore"
    corners: list
    text: str
    type: str  # the plate type attribute; empty for an ignore region, which has none


def crop_targets(record: dict, settings: CropSettings) -> list[Target]:
    """The readable plates of one frame, followed by its rejects when the settings ask for them."""
    plates = record["plates"]
    targets = [Target(READABLE, k, p["corners"], p["text"], p["type"]) for k, p in enumerate(plates)
               if p["readable"]]
    wide = [k for k, p in enumerate(plates) if plate_width_px(p["corners"], record) >= settings.reject_min_px]
    if "unreadable" in settings.reject_sources:
        targets += [Target("unreadable", k, plates[k]["corners"], "", plates[k]["type"]) for k in wide
                    if not plates[k]["readable"]]
    if "ignore" in settings.reject_sources:
        targets += [Target("ignore", k, g["corners"], "", "") for k, g in enumerate(record["ignore"])
                    if plate_width_px(g["corners"], record) >= settings.reject_min_px]
    return targets


def jitter_corners(corners_px: np.ndarray, sigma_rel: float, rng: np.random.Generator) -> np.ndarray:
    """Corners moved independently by a normal offset of sigma_rel x plate width per axis."""
    width = max(np.linalg.norm(corners_px[1] - corners_px[0]), np.linalg.norm(corners_px[2] - corners_px[3]))
    return corners_px + rng.normal(0.0, sigma_rel * width, corners_px.shape)


def plate_rng(seed: int, frame: str, index: int, ignore: bool = False) -> np.random.Generator:
    """A generator per labeled quad, so its crops do not depend on which other frames or rejects are in the
    dataset. Ignore regions get streams of their own; plates keep the streams of datasets built before
    them."""
    return np.random.default_rng([seed, zlib.crc32(frame.encode()), index, *([1] if ignore else [])])


def record_crops(record: dict, frame: np.ndarray, settings: CropSettings,
                 jitter: bool) -> list[tuple[str, np.ndarray, dict]]:
    """(file name, crop, row) for every crop target of one frame: jittered copies, or one exact crop."""
    stem = Path(record["image"]).stem
    copies = settings.jitter_copies if jitter else 0
    out = []
    for t in crop_targets(record, settings):
        corners = np.asarray(t.corners) * frame_size(record)
        name = f"{stem}__{'i' if t.kind == 'ignore' else 'p'}{t.index}"
        row = {"frame": Path(record["image"]).name, "kind": t.kind, "plate": t.index,
               "session": session_of(record["image"]),
               "width_px": round(plate_width_px(t.corners, record), 1),
               "type": t.type, "text": t.text}
        if copies == 0:
            crop = rectify_plate(frame, corners, settings.size, settings.margin)
            out.append((f"{name}.png", crop, {**row, "jitter": 0}))
            continue
        rng = plate_rng(settings.seed, row["frame"], t.index, ignore=t.kind == "ignore")
        for j in range(copies):
            crop = rectify_plate(frame, jitter_corners(corners, settings.jitter_sigma, rng), settings.size,
                                 settings.margin)
            out.append((f"{name}__j{j}.png", crop, {**row, "jitter": 1}))
    return out


def write_split(out_dir: Path, records: list[dict], settings: CropSettings, jitter: bool,
                images_dir: Path) -> dict:
    """Crops, annotations.csv and crops.csv of one split; returns its counts for the manifest."""
    (out_dir / "images").mkdir(parents=True)
    rows = []
    for r in records:
        for name, crop, row in record_crops(r, read_image(images_dir / r["image"]), settings, jitter):
            if not cv2.imwrite(str(out_dir / "images" / name), crop):
                raise OSError(f"cannot write {name}")
            rows.append({"image_path": f"images/{name}", **row})
    with open(out_dir / "annotations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["image_path", "plate_text", "plate_region"])
        w.writerows((row["image_path"], row["text"], REGION if row["text"] else REJECT_REGION)
                    for row in rows)
    with open(out_dir / "crops.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CROP_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    readable = [row for row in rows if row["kind"] == READABLE]
    kinds = Counter(row["kind"] for row in rows)
    return {"frames": len(records), "plates": len({(row["frame"], row["plate"]) for row in readable}),
            "texts": len({row["text"] for row in readable}), "crops": len(rows),
            **{f"{kind}_crops": kinds[kind] for kind in REJECT_SOURCES if kind in settings.reject_sources},
            "types": dict(Counter(row["type"] for row in readable))}


def build_dataset(exports: list[Path], out_dir: Path, settings: CropSettings = DEFAULT_SETTINGS,
                  images_dir: Path = BATCHES_DIR, splits: dict | None = None) -> dict:
    """Writes the train and val crops and manifest.json into out_dir; returns the manifest."""
    if out_dir.exists():
        raise FileExistsError(f"{out_dir} already exists; pick another name or delete it after checking it")
    tmp = out_dir.with_name(out_dir.name + ".partial")
    if tmp.exists():
        raise FileExistsError(f"{tmp} is left over from an interrupted run; check and delete it")
    by_split = split_records(load_records(exports), splits if splits is not None else load_splits())

    counts = {}
    for split in SPLITS_WRITTEN:
        records = [r for r in by_split[split] if crop_targets(r, settings)]
        if records:
            counts[split] = write_split(tmp / split, records, settings, split == "train", images_dir)

    manifest = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        **settings.as_manifest(),
        "crop": "anpr_ml.common.preprocess.rectify_plate",
        "opencv": cv2.__version__,
        "sources": {p.name: sha256_file(p) for p in exports},
        "counts": counts,
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
    tmp.rename(out_dir)  # a dataset directory only ever exists complete
    return manifest


def ensure_dataset(cfg: dict) -> dict:
    """Builds the config's dataset if it is missing and returns its manifest; refuses a stale one."""
    exports = export_paths(cfg["dataset"]["exports"])
    settings = CropSettings.from_config(cfg)
    out = dataset_dir(cfg)
    if not (out / "manifest.json").exists():
        build_dataset(exports, out, settings)
    manifest = json.loads((out / "manifest.json").read_text())
    expected = {"sources": {p.name: sha256_file(p) for p in exports}, **settings.as_manifest()}
    stale = {k: {"dataset": manifest.get(k), "config": v}
             for k, v in expected.items() if manifest.get(k) != v}
    if stale:
        raise ValueError(f"{out} does not match the config, give the dataset a new name: {stale}")
    return manifest


def read_crops(cfg: dict, split: str) -> list[dict]:
    """The crop rows of one split, joined with their text, with typed values and the absolute image path.
    Datasets built before rejects existed have no kind column: all their crops are readable plates."""
    base = dataset_dir(cfg) / split
    with open(base / "annotations.csv", encoding="utf-8") as f:
        texts = {row["image_path"]: row["plate_text"] for row in csv.DictReader(f)}
    with open(base / "crops.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row.update(text=texts[row["image_path"]], path=base / row["image_path"],
                   kind=row.get("kind", READABLE),
                   plate=int(row["plate"]), width_px=float(row["width_px"]), jitter=int(row["jitter"]))
    return rows


def main() -> None:
    d = DEFAULT_SETTINGS
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="dataset name, written to datasets/<name>/")
    parser.add_argument("--exports", nargs="*", help="batch names (default: every labeling/exports/*.jsonl)")
    parser.add_argument("--margin", type=float, default=d.margin)
    parser.add_argument("--copies", type=int, default=d.jitter_copies, help="jittered crops per train plate")
    parser.add_argument("--sigma", type=float, default=d.jitter_sigma,
                        help="corner jitter as a fraction of the plate width")
    parser.add_argument("--seed", type=int, default=d.seed)
    parser.add_argument("--reject", nargs="*", choices=REJECT_SOURCES, default=[],
                        help="add rejects (empty text) from these sources (default: none)")
    parser.add_argument("--reject-min-px", type=float, default=d.reject_min_px,
                        help="minimum width of a reject on the original frame")
    args = parser.parse_args()

    exports = export_paths(args.exports) if args.exports else sorted(EXPORTS_DIR.glob("*.jsonl"))
    settings = CropSettings(OCR_SIZE, args.margin, args.copies, args.sigma, args.seed, tuple(args.reject),
                            args.reject_min_px)
    manifest = build_dataset(exports, DATASETS_DIR / args.name, settings)
    print(json.dumps(manifest["counts"], indent=2))
    print(f"written {DATASETS_DIR / args.name}")


if __name__ == "__main__":
    main()
