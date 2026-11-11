"""OCR metrics on crops with known text (ML_ASSUMPTIONS section 8).

A crop whose true text is empty is a reject: the OCR should decline it (Reading.declined: no text, or not
readable for the readability head). A declined reading is never sent. Rejects are only counted in the reject_*
metrics; all others are over the readable crops, where reading quality (exact, cer, ...) is measured on the
text whatever the decline, and a declined crop is a false reject.

crops               readable crops
exact               share of plates read entirely right: the number that matters for a plate reader
cer                 character error rate, edit distance over the length of the true texts
false_rejects       readable crops declined
reject_crops        crops whose true text is empty
reject_rate         share of them declined (NaN without rejects)
by_width            exact match per plate width bucket on the original frame
positions           error rate per character position, over the reads of the right length
confusions          most frequent (true, read) character pairs at those positions
coverage            for a threshold on the reading's confidence: share of readable crops sent (not declined,
                    at or above the threshold), exact match among them and the rejects that would be sent too;
                    the input for the rule deciding which reads the edge node trusts
readability_curve   with the readability head, the same over a threshold on P(readable) instead of the default
"""
from collections import Counter

import numpy as np

from ..common.labels import SMALL_PLATE_PX, WIDTH_BUCKETS, width_bucket_name, width_bucket_of
from .predict import Reading

CONF_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 0.99)
READABLE_GRID = (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
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


def threshold_curve(key: str, grid, correct: np.ndarray, score: np.ndarray, eligible: np.ndarray,
                    reject_score: np.ndarray) -> list[dict]:
    """What a threshold on a score keeps. correct, score, eligible: per readable crop, which is kept when
    eligible and its score is at or above the threshold. reject_score: the scores of the eligible rejects."""
    out = []
    for t in grid:
        kept = eligible & (score >= t)
        out.append({key: t, "kept": float(kept.mean()) if len(kept) else 0.0, "n_kept": int(kept.sum()),
                    "exact": float(correct[kept].mean()) if kept.any() else float("nan"),
                    "rejects_sent": int((reject_score >= t).sum())})
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
    declined = np.array([r.declined for r in readings], dtype=bool)
    conf = np.array([r.conf for r in readings])
    positions, confusions = position_errors(texts, reads)
    total_chars = sum(len(t) for t in texts)
    nan = float("nan")
    res = {
        "crops": len(texts),
        "exact": float(correct.mean()) if len(correct) else nan,
        "cer": sum(edit_distance(r, t) for r, t in zip(reads, texts)) / total_chars if total_chars else nan,
        "wrong_length": sum(len(t) != len(r) for t, r in zip(texts, reads)),
        "mean_conf": float(conf.mean()) if len(conf) else nan,
        "false_rejects": int(declined.sum()),
        "reject_crops": len(rejects),
        "reject_rate": sum(r.declined for r in rejects) / len(rejects) if rejects else nan,
        "by_width": exact_by_width(correct, widths),
        "positions": positions,
        "confusions": [{"true": a, "read": b, "count": n}
                       for (a, b), n in confusions.most_common(top_confusions)],
        "coverage": threshold_curve("conf", CONF_GRID, correct, conf, ~declined,
                                    np.array([r.conf for r in rejects if not r.declined])),
    }
    if readings and readings[0].readable is not None:
        # The readability threshold in place of the default one; reads without a text stay declined.
        res["readability_curve"] = threshold_curve(
            "readable", READABLE_GRID, correct, np.array([r.readable for r in readings]),
            np.array([bool(r.text) for r in readings]), np.array([r.readable for r in rejects if r.text]))
    return res
