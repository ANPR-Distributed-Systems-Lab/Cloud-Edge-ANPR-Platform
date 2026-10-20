"""Picks frames for a labeling batch: drops near-duplicates, spreads the pick over the sessions.

The chosen frames are hard-linked (copied if that fails) into labeling/batches/<batch>/, which is the
folder CVAT sees as its file share. Every pick is recorded in labeling/selected.csv, and frames that
were already picked for an earlier batch are never offered again.
"""
import argparse
import csv
import os
import shutil

import numpy as np

from .frame_index import load_index
from .frames import hamming, session_frames
from .make_splits import load_splits
from .paths import BATCHES_DIR, DATA_DIR, SELECTED_FILE

DEFAULT_THRESHOLD = 8  # Hamming distance (of 64 bits) to the last kept frame; tune with --sweep


def dedupe(hashes: list[int], threshold: int) -> list[int]:
    """Indices of the frames to keep: a frame is kept if it differs enough from the last kept one."""
    kept: list[int] = []
    for i, h in enumerate(hashes):
        if not kept or hamming(h, hashes[kept[-1]]) >= threshold:
            kept.append(i)
    return kept


def allocate(sizes: list[int], count: int) -> list[int]:
    """Splits `count` over the sessions proportionally to their size (largest remainder), capped by size."""
    total = sum(sizes)
    if total == 0:
        return [0] * len(sizes)
    count = min(count, total)
    raw = [count * s / total for s in sizes]
    alloc = [min(int(r), s) for r, s in zip(raw, sizes)]
    by_remainder = sorted(range(len(sizes)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    for i in by_remainder * 2:
        if sum(alloc) >= count:
            break
        if alloc[i] < sizes[i]:
            alloc[i] += 1
    return alloc


def evenly(items: list, n: int) -> list:
    if n >= len(items):
        return list(items)
    if n <= 0:
        return []
    idx = np.unique(np.linspace(0, len(items) - 1, n).round().astype(int))
    return [items[i] for i in idx]


def load_selected() -> set[tuple[str, str]]:
    if not SELECTED_FILE.is_file():
        return set()
    with open(SELECTED_FILE, newline="") as f:
        return {(r["session"], r["file"]) for r in csv.DictReader(f)}


def candidates(session: str, index: dict, already: set, threshold: int) -> list[str]:
    files = [f for f in session_frames(session) if (session, f) in index]
    kept = dedupe([index[(session, f)] for f in files], threshold)
    return [files[i] for i in kept if (session, files[i]) not in already]


def batch_name(session: str, file: str) -> str:
    return f"{session}__{file.replace('/', '__')}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["train", "val", "test"], default="train")
    parser.add_argument("--batch", help="batch name, e.g. train_001")
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
        for t in (2, 4, 6, 8, 10, 12, 16):
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
            src, dst = DATA_DIR / session / file, out_dir / batch_name(session, file)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
            writer.writerow([args.batch, args.split, session, file])
    print(f"{len(picks)} frames from {len({s for s, _ in picks})} sessions -> {out_dir}")


if __name__ == "__main__":
    main()
