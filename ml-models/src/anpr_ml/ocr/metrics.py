"""OCR metrics on crops with known text (ML_ASSUMPTIONS section 8).

A crop whose true text is empty is a reject: the right reading is no text at all. An empty reading is the OCR
declining to read, never sent. Rejects are only counted in the reject_* metrics; all others are over the
readable crops, where an empty reading is a false reject and counts as wrong.

crops          readable crops
exact          share of plates read entirely right: the number that matters for a plate reader
cer            character error rate, edit distance over the length of the true texts
false_rejects  readable crops read as no text
reject_crops   crops whose true text is empty
reject_rate    share of them read as no text (NaN without rejects)
by_width       exact match per plate width bucket on the original frame
positions      error rate per character position, over the reads of the right length
confusions     most frequent (true, read) character pairs at those positions
coverage       for a threshold on the reading's confidence: share of readable crops sent (a text at or above
               the threshold), exact match among them and the rejects that would be sent too; the input for
               the rule deciding which reads the edge node trusts
"""
from collections import Counter

import numpy as np

from ..common.labels import SMALL_PLATE_PX, WIDTH_BUCKETS, width_bucket_name, width_bucket_of
from .predict import Reading

CONF_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 0.99)
# The scalars of evaluate(). Evaluations written before rejects existed lack the last three.
SUMMARY_KEYS = ("crops", "exact", "cer", "wrong_length", "mean_conf", "false_rejects", "reject_crops",
                "reject_rate")
BELOW_SMALL = f"<{SMALL_PLATE_PX}"  # bucket of readable plates labeled below the small-plate threshold


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance: insertions, deletions and substitutions all cost 1."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def coverage_curve(correct: np.ndarray, conf: np.ndarray, empty: np.ndarray, reject_conf: np.ndarray,
                   grid=CONF_GRID) -> list[dict]:
    """correct, conf, empty: per readable crop. reject_conf: the confidences of the rejects read as a text."""
    out = []
    for t in grid:
        kept = (conf >= t) & ~empty
        out.append({"conf": t, "kept": float(kept.mean()) if len(kept) else 0.0, "n_kept": int(kept.sum()),
                    "exact": float(correct[kept].mean()) if kept.any() else float("nan"),
                    "rejects_sent": int((reject_conf >= t).sum())})
    return out


def exact_by_width(correct: np.ndarray, widths: list[float]) -> list[dict]:
    buckets: dict[str, list[bool]] = {}
    for w, ok in zip(widths, correct):
        buckets.setdefault(width_bucket_of(w) or BELOW_SMALL, []).append(bool(ok))
    order = [BELOW_SMALL] + [width_bucket_name(lo, hi) for lo, hi in WIDTH_BUCKETS]
    return [{"width_px": b, "crops": len(buckets[b]), "exact": float(np.mean(buckets[b]))}
            for b in order if b in buckets]


def position_errors(texts: list[str], reads: list[str]) -> tuple[list[dict], Counter]:
    """Errors per position and (true, read) confusions, over reads as long as their true text: a read of
    another length is shifted, and comparing it position by position would blame the wrong characters."""
    same_length = [(t, r) for t, r in zip(texts, reads) if len(t) == len(r)]
    positions = []
    for i in range(max((len(t) for t in texts), default=0)):
        pairs = [(t[i], r[i]) for t, r in same_length if len(t) > i]
        errors = sum(a != b for a, b in pairs)
        positions.append({"position": i + 1, "reads": len(pairs), "errors": errors,
                          "error_rate": errors / len(pairs) if pairs else float("nan")})
    confusions = Counter((a, b) for t, r in same_length for a, b in zip(t, r) if a != b)
    return positions, confusions


def evaluate(texts: list[str], readings: list[Reading], widths: list[float],
             top_confusions: int = 15) -> dict:
    rejects = [r for t, r in zip(texts, readings) if not t]
    readable = [(t, r, w) for t, r, w in zip(texts, readings, widths) if t]
    texts, readings, widths = (list(x) for x in zip(*readable)) if readable else ([], [], [])
    reads = [r.text for r in readings]
    correct = np.array([r == t for r, t in zip(reads, texts)], dtype=bool)
    empty = np.array([not r for r in reads], dtype=bool)
    conf = np.array([r.conf for r in readings])
    positions, confusions = position_errors(texts, reads)
    total_chars = sum(len(t) for t in texts)
    nan = float("nan")
    return {
        "crops": len(texts),
        "exact": float(correct.mean()) if len(correct) else nan,
        "cer": sum(edit_distance(r, t) for r, t in zip(reads, texts)) / total_chars if total_chars else nan,
        "wrong_length": sum(len(t) != len(r) for t, r in zip(texts, reads)),
        "mean_conf": float(conf.mean()) if len(conf) else nan,
        "false_rejects": int(empty.sum()),
        "reject_crops": len(rejects),
        "reject_rate": sum(not r.text for r in rejects) / len(rejects) if rejects else nan,
        "by_width": exact_by_width(correct, widths),
        "positions": positions,
        "confusions": [{"true": a, "read": b, "count": n}
                       for (a, b), n in confusions.most_common(top_confusions)],
        "coverage": coverage_curve(correct, conf, empty, np.array([r.conf for r in rejects if r.text])),
    }
