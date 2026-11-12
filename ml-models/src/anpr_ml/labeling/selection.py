"""anpr-select: picks the frames of a new labeling batch.

Per session, near-duplicates are dropped (a frame is kept only if its dHash differs enough from the last kept
frame), frames already in any batch are skipped, the requested count is spread over the sessions in proportion
to what is left, and frames are picked evenly in time. The content is not inspected.

The frames are hard-linked (copied if linking fails) into labeling/batches/<batch>/, the folder CVAT reads as
its file share, and every pick is appended to labeling/selected.csv, so a frame is never offered twice.
"""
import argparse
import csv
import os
import shutil

import numpy as np

from ..common.labels import SPLITS, batch_file_name, load_splits
from ..paths import BATCHES_DIR, DATA_DIR, SELECTED_FILE
from .frame_index import load_index
from .frames import hamming, session_frames

# Minimum Hamming distance (of 64 bits) to the last kept frame. Lowered from 8 after a visual review of kept
# and dropped frames: 8 dropped frames that differed in content (train_001 was selected with 8).
DEFAULT_THRESHOLD = 5
SWEEP_THRESHOLDS = (2, 4, 5, 6, 8, 10, 12, 16)


def dedupe(hashes: list[int], threshold: int) -> list[int]:
    """Indices of the frames to keep: each kept frame differs from the previous kept one by >= threshold."""
    kept: list[int] = []
    for i, h in enumerate(hashes):
        if not kept or hamming(h, hashes[kept[-1]]) >= threshold:
            kept.append(i)
    return kept


def allocate(sizes: list[int], count: int) -> list[int]:
    """Splits `count` over pools proportionally to their size (largest remainder), never above a pool's size."""
    total = sum(sizes)
    if total == 0:
        return [0] * len(sizes)
    count = min(count, total)
    raw = [count * s / total for s in sizes]
    alloc = [min(int(r), s) for r, s in zip(raw, sizes)]
    by_remainder = sorted(range(len(sizes)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    for i in by_remainder * 2:  # a second pass when capped pools leave part of the count unassigned
        if sum(alloc) >= count:
            break
        if alloc[i] < sizes[i]:
            alloc[i] += 1
    return alloc


def evenly(items: list, n: int) -> list:
    """n items spread evenly over the list, first and last included."""
    if n >= len(items):
        return list(items)
    if n <= 0:
        return []
    idx = np.unique(np.linspace(0, len(items) - 1, n).round().astype(int))
    return [items[i] for i in idx]


def load_selected() -> set[tuple[str, str]]:
    """(session, file) of every frame already in a batch."""
    if not SELECTED_FILE.is_file():
        return set()
    with open(SELECTED_FILE, newline="") as f:
        return {(r["session"], r["file"]) for r in csv.DictReader(f)}


def candidates(session: str, index: dict, already: set, threshold: int) -> list[str]:
    files = [f for f in session_frames(session) if (session, f) in index]
    kept = dedupe([index[(session, f)] for f in files], threshold)
    return [files[i] for i in kept if (session, files[i]) not in already]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=SPLITS, default="train")
    parser.add_argument("--batch", help="batch name, e.g. train_002")
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--sweep", action="store_true", help="only print how many frames survive each threshold")
    args = parser.parse_args()

    index = load_index()
    if not index:
        raise SystemExit("labeling/frame_index.csv is empty, run `uv run anpr-index` first")
    sessions = load_splits()[args.split]
    already = load_selected()

    if args.sweep:
        for t in SWEEP_THRESHOLDS:
            kept = sum(len(candidates(s, index, already, t)) for s in sessions)
            print(f"threshold {t:2d}: {kept} frames left in {args.split}")
        return
    if not args.batch:
        raise SystemExit("--batch is required")
    out_dir = BATCHES_DIR / args.batch
    if out_dir.exists():
        raise SystemExit(f"{out_dir} already exists")

    pools = [candidates(s, index, already, args.threshold) for s in sessions]
    picks = [(s, f) for s, pool, n in zip(sessions, pools, allocate([len(p) for p in pools], args.count))
             for f in evenly(pool, n)]
    out_dir.mkdir(parents=True)
    new_file = not SELECTED_FILE.is_file()
    with open(SELECTED_FILE, "a", newline="") as ledger:
        writer = csv.writer(ledger)
        if new_file:
            writer.writerow(["batch", "split", "session", "file"])
        for session, file in picks:
            src, dst = DATA_DIR / session / file, out_dir / batch_file_name(session, file)
            try:
                os.link(src, dst)  # same volume: no extra disk space
            except OSError:
                shutil.copy2(src, dst)
            writer.writerow([args.batch, args.split, session, file])
    print(f"{len(picks)} frames from {len({s for s, _ in picks})} sessions -> {out_dir}")


if __name__ == "__main__":
    main()
