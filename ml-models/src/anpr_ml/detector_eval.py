"""Detector metrics on the original frame that Ultralytics does not report (ML_ASSUMPTIONS section 8).

Predictions are matched greedily by confidence to ground-truth plates (box IoU). A prediction that matches
no plate but lies mostly inside a plate_ignore region, or on a plate demoted as too small, is dropped
instead of counted as a false positive, mirroring how those regions are treated in training.
"""
from dataclasses import dataclass, field

import numpy as np

from .geometry import box_area, box_intersection, box_iou, plate_width_px, quad_box

IOU_MATCH = 0.5
IGNORE_IOA = 0.5  # share of a prediction's box inside an ignore region that makes it "don't care"
WIDTH_BUCKETS = ((70, 90), (90, 110), (110, 140), (140, 200), (200, float("inf")))
CONF_GRID = tuple(round(t, 2) for t in np.arange(0.05, 0.96, 0.05))


@dataclass
class Prediction:
    conf: float
    corners: np.ndarray  # (4, 2) normalized TL, TR, BR, BL
    box: np.ndarray | None = None  # normalized x1, y1, x2, y2; derived from the corners if missing

    def __post_init__(self):
        self.corners = np.asarray(self.corners, dtype=float)
        self.box = quad_box(self.corners) if self.box is None else np.asarray(self.box, dtype=float)


@dataclass
class Match:
    conf: float
    gt: int | None  # index into the image's plates, None for a false positive
    corner_error_px: float | None = None  # mean over the 4 corners, on the original frame
    width_px: float | None = None  # ground-truth plate width on the original frame
    pred: Prediction | None = None


@dataclass
class ImageResult:
    matches: list[Match] = field(default_factory=list)
    gt_widths: list[float] = field(default_factory=list)


def match_image(
    record: dict, preds: list[Prediction], min_plate_px: float, iou_thr: float = IOU_MATCH
) -> ImageResult:
    orig = np.array([record["width"], record["height"]], dtype=float)
    plates, dont_care = [], []
    for p in record["plates"]:
        corners = np.array(p["corners"])
        (plates if plate_width_px(corners * orig) >= min_plate_px else dont_care).append(corners)
    dont_care += [np.array(r["corners"]) for r in record["ignore"]]
    gt_boxes = [quad_box(c) for c in plates]
    dc_boxes = [quad_box(c) for c in dont_care]

    result = ImageResult(gt_widths=[plate_width_px(c * orig) for c in plates])
    taken: set[int] = set()
    for pred in sorted(preds, key=lambda p: p.conf, reverse=True):
        ious = [(box_iou(pred.box, b), i) for i, b in enumerate(gt_boxes) if i not in taken]
        best_iou, best = max(ious, default=(0.0, None))
        if best is not None and best_iou >= iou_thr:
            taken.add(best)
            err = np.linalg.norm((pred.corners - plates[best]) * orig, axis=1).mean()
            result.matches.append(Match(pred.conf, best, float(err), result.gt_widths[best], pred))
            continue
        area = box_area(pred.box)
        if area > 0 and any(box_intersection(pred.box, b) / area >= IGNORE_IOA for b in dc_boxes):
            continue
        result.matches.append(Match(pred.conf, None, pred=pred))
    return result


def evaluate(
    records: list[dict],
    predictions: dict[str, list[Prediction]],
    min_plate_px: float,
    conf_grid: tuple[float, ...] = CONF_GRID,
) -> dict:
    """Precision / recall / F1 over a confidence grid, plus size buckets and corner error at the best F1."""
    results = [match_image(r, predictions.get(r["image"], []), min_plate_px) for r in records]
    n_gt = sum(len(r.gt_widths) for r in results)
    matches = [m for r in results for m in r.matches]

    curve = []
    for t in conf_grid:
        tp = sum(m.gt is not None and m.conf >= t for m in matches)
        fp = sum(m.gt is None and m.conf >= t for m in matches)
        p = tp / (tp + fp) if tp + fp else 1.0
        rc = tp / n_gt if n_gt else 0.0
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        curve.append({"conf": t, "precision": p, "recall": rc, "f1": f1, "tp": tp, "fp": fp, "fn": n_gt - tp})
    best = max(curve, key=lambda row: row["f1"])
    t = best["conf"]

    hits = [m for m in matches if m.gt is not None and m.conf >= t]
    widths = np.array([w for r in results for w in r.gt_widths])
    hit_widths = np.array([m.width_px for m in hits])
    buckets = []
    for lo, hi in WIDTH_BUCKETS:
        n = int(((widths >= lo) & (widths < hi)).sum())
        k = int(((hit_widths >= lo) & (hit_widths < hi)).sum())
        buckets.append({"width_px": f"{lo}-{'' if hi == float('inf') else int(hi)}", "plates": n,
                        "detected": k, "recall": k / n if n else float("nan")})

    err = np.array([m.corner_error_px for m in hits])
    rel = np.array([m.corner_error_px / m.width_px for m in hits])
    corner = {
        "matched": len(hits),
        "mean_px": float(err.mean()) if len(err) else float("nan"),
        "median_px": float(np.median(err)) if len(err) else float("nan"),
        "p90_px": float(np.percentile(err, 90)) if len(err) else float("nan"),
        "mean_rel_width": float(rel.mean()) if len(rel) else float("nan"),
        "p90_rel_width": float(np.percentile(rel, 90)) if len(rel) else float("nan"),
    }
    return {"plates": n_gt, "best": best, "curve": curve, "by_width": buckets, "corner_error": corner}
