"""anpr-eval-pipeline: detector + OCR end to end on the val split, the way the edge node runs them.

Full frame -> resize_for_detector() -> detector -> corners on the original -> rectify_plate() -> OCR.
The detector runs at its operating threshold (best F1 on val, from its eval_val.json). Every kept detection
is read, because on the edge node every detection is, and each read falls into one category:

    correct      a readable plate, read right
    wrong        a readable plate, read wrong
    unreadable   a plate labeled readable = no: any text is a wrong output
    dont_care    a plate_ignore region or a plate below the small-plate threshold
    background   no plate at all (a detector false positive)

An empty reading is the OCR declining to read (an OCR trained with rejects does that): it is never sent and
is counted under `rejected` by category, where the readable plates (category wrong) are the reads lost.

Only `correct` reads are good output. The curve over the OCR confidence threshold shows, for the reads that
would be sent, their precision and the share of readable plates read right: the input for the rule that
decides what the edge node trusts. Format rules and agreement across frames come on top of this later.

Writes runs/pipeline/<detector run>__<ocr run>/eval_val.json.
"""
import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .common.labels import WIDTH_BUCKETS, frame_size, plate_width_px, width_bucket_name, width_bucket_of
from .common.preprocess import read_image, rectify_plate
from .detector import config as detector_config
from .detector.evaluate import val_records
from .detector.metrics import match_image
from .detector.predict import Prediction, predict_records
from .ocr import config as ocr_config
from .ocr.metrics import CONF_GRID
from .ocr.predict import Reader, Reading
from .paths import BATCHES_DIR, CONFIGS_DIR, RUNS_DIR

CATEGORIES = ("correct", "wrong", "unreadable", "dont_care", "background")


@dataclass
class Read:
    """One detection on a val frame and what the OCR made of it."""
    frame: str  # record["image"]
    category: str
    reading: Reading
    detection: Prediction
    truth: str | None = None  # text of the matched plate, when it is readable
    width_px: float | None = None  # width of the matched plate on the original frame


@dataclass
class PipelineEvaluation:
    detector_run: Path
    ocr_run: Path
    detector_conf: float
    records: list[dict]
    reads: list[Read]
    plates: list[dict]  # one row per readable plate at or above the small-plate threshold
    result: dict


def operating_conf(det_cfg: dict) -> float:
    path = detector_config.run_dir(det_cfg) / "eval_val.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: run `uv run anpr-eval-detector` for that config first")
    return json.loads(path.read_text())["best"]["conf"]


def match_detections(record: dict, detections: list[Prediction], min_plate_px: float) -> list[tuple]:
    """(detection, target, plate index) for every detection on one frame.

    target is "readable" or "unreadable" for a detection matched to a plate, whose index into
    record["plates"] is given, and "dont_care" or "background" otherwise (index None).
    """
    # match_image() numbers the plates at or above the threshold in their record order.
    kept = [i for i, p in enumerate(record["plates"]) if plate_width_px(p["corners"], record) >= min_plate_px]
    # Predictions hold arrays, so they are told apart by identity rather than by value.
    matches = {id(m.pred): m for m in match_image(record, detections, min_plate_px).matches}
    out = []
    for det in detections:
        m = matches.get(id(det))
        if m is None:
            out.append((det, "dont_care", None))
        elif m.gt is None:
            out.append((det, "background", None))
        else:
            i = kept[m.gt]
            out.append((det, "readable" if record["plates"][i]["readable"] else "unreadable", i))
    return out


def read_category(target: str, text: str, truth: str | None) -> str:
    if target == "readable":
        return "correct" if text == truth else "wrong"
    return target


def readable_plates(record: dict, min_plate_px: float, read_right: dict[int, bool]) -> list[dict]:
    """The readable plates of one frame and whether the pipeline found and read them; read_right maps the
    plate indices that a detection matched to whether the read was right."""
    rows = []
    for i, p in enumerate(record["plates"]):
        width = plate_width_px(p["corners"], record)
        if p["readable"] and width >= min_plate_px:
            rows.append({"frame": record["image"], "width_px": width, "bucket": width_bucket_of(width),
                         "detected": i in read_right, "read_correct": read_right.get(i, False)})
    return rows


def summarize(reads: list[Read], plates: list[dict], grid=CONF_GRID) -> dict:
    n = len(plates)
    conf = np.array([r.reading.conf for r in reads])
    cats = np.array([r.category for r in reads])
    rejected = np.array([not r.reading.text for r in reads], dtype=bool)
    nan = float("nan")
    curve = []
    for t in grid:
        sent = (conf >= t) & ~rejected
        counts = {c: int(((cats == c) & sent).sum()) for c in CATEGORIES}
        total = int(sent.sum())
        curve.append({"conf": t, "sent": total, **counts,
                      "precision": counts["correct"] / total if total else nan,
                      "recall": counts["correct"] / n if n else nan})
    by_width = []
    for lo, hi in WIDTH_BUCKETS:
        name = width_bucket_name(lo, hi)
        rows = [p for p in plates if p["bucket"] == name]
        right = sum(p["read_correct"] for p in rows)
        by_width.append({"width_px": name, "plates": len(rows), "detected": sum(p["detected"] for p in rows),
                         "read_correct": right, "recall": right / len(rows) if rows else nan})
    right = sum(p["read_correct"] for p in plates)
    return {
        "readable_plates": n,
        "detected": sum(p["detected"] for p in plates),
        "read_correct": right,
        "recall": right / n if n else nan,
        "reads": {c: int((cats == c).sum()) for c in CATEGORIES},
        "rejected": {c: int(((cats == c) & rejected).sum()) for c in CATEGORIES},
        "curve": curve,
        "by_width": by_width,
    }


def evaluate_pipeline(det_cfg: dict, ocr_cfg: dict) -> PipelineEvaluation:
    det_run, ocr_run = detector_config.run_dir(det_cfg), ocr_config.run_dir(ocr_cfg)
    if detector_config.run_state(det_run) != "finished" or ocr_config.run_state(ocr_run) != "finished":
        raise RuntimeError(f"both runs must be finished: {det_run}, {ocr_run}")
    min_px = det_cfg["dataset"]["min_plate_px"]
    conf = operating_conf(det_cfg)
    records = val_records(det_cfg)
    detections = predict_records(det_run / "weights" / "best.pt", records, det_cfg["dataset"]["size"],
                                 conf=conf, device=det_cfg["train"]["device"])
    reader = Reader(ocr_run)
    size, margin = ocr_cfg["dataset"]["size"], ocr_cfg["dataset"]["margin"]

    reads, plates = [], []
    for r in records:
        matched = match_detections(r, detections.get(r["image"], []), min_px)
        frame = read_image(BATCHES_DIR / r["image"]) if matched else None
        read_right = {}
        for det, target, i in matched:
            plate = r["plates"][i] if i is not None else None
            reading = reader.read(rectify_plate(frame, det.corners * frame_size(r), size, margin))
            truth = plate["text"] if target == "readable" else None
            category = read_category(target, reading.text, truth)
            if target == "readable":
                read_right[i] = category == "correct"
            width = plate_width_px(plate["corners"], r) if plate is not None else None
            reads.append(Read(r["image"], category, reading, det, truth, width))
        plates += readable_plates(r, min_px, read_right)

    result = {"detector_run": det_run.name, "ocr_run": ocr_run.name, "detector_conf": conf,
              **summarize(reads, plates)}
    out = RUNS_DIR / "pipeline" / f"{det_run.name}__{ocr_run.name}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_val.json").write_text(json.dumps(result, indent=2))
    return PipelineEvaluation(det_run, ocr_run, conf, records, reads, plates, result)


def print_summary(ev: PipelineEvaluation) -> None:
    res = ev.result
    reads = ", ".join(f"{k} {v}" for k, v in res["reads"].items())
    print(f"detector {res['detector_run']} (conf {res['detector_conf']}) + OCR {res['ocr_run']}: "
          f"{res['read_correct']} of {res['readable_plates']} readable val plates read right "
          f"({res['recall']:.3f}), {res['detected']} detected; reads: {reads}")
    if any(res["rejected"].values()):
        print("rejected by the OCR (never sent): " + ", ".join(f"{k} {v}" for k, v in res["rejected"].items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--detector", type=Path, default=CONFIGS_DIR / "detector_v2.yaml",
                        help="detector config")
    parser.add_argument("--ocr", type=Path, default=CONFIGS_DIR / "ocr_v0.yaml", help="OCR config")
    args = parser.parse_args()
    ev = evaluate_pipeline(detector_config.load_config(args.detector), ocr_config.load_config(args.ocr))
    print_summary(ev)


if __name__ == "__main__":
    main()
