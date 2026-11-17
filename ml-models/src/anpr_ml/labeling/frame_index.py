"""anpr-index: one perceptual hash per recorded frame in labeling/frame_index.csv.

Incremental: only frames missing from the index are hashed and appended, so it is safe to interrupt and rerun.
"""
import argparse
import csv
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..paths import DATA_DIR, FRAME_INDEX
from .frames import dhash, list_sessions, session_frames

FIELDS = ["session", "file", "dhash"]


def load_index(path: Path = FRAME_INDEX) -> dict[tuple[str, str], int]:
    """(session, file) -> dhash."""
    if not path.is_file():
        return {}
    with open(path, newline="") as f:
        return {(r["session"], r["file"]): int(r["dhash"], 16) for r in csv.DictReader(f)}


def _hash_one(item: tuple[str, str]) -> tuple[str, str, int | None]:
    session, file = item
    try:
        return session, file, dhash(DATA_DIR / session / file)
    except OSError:  # listed in frames.csv but missing or truncated on disk
        return session, file, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    args = parser.parse_args()

    done = load_index()
    todo = [(s, f) for s in list_sessions() for f in session_frames(s) if (s, f) not in done]
    print(f"{len(done)} frames already indexed, {len(todo)} to hash")
    if not todo:
        return

    FRAME_INDEX.parent.mkdir(parents=True, exist_ok=True)
    new_file = not FRAME_INDEX.is_file()
    missing = 0
    with open(FRAME_INDEX, "a", newline="") as out, ProcessPoolExecutor(args.workers) as pool:
        writer = csv.writer(out)
        if new_file:
            writer.writerow(FIELDS)
        for i, (session, file, h) in enumerate(pool.map(_hash_one, todo, chunksize=16), 1):
            if h is None:
                missing += 1
                continue
            writer.writerow([session, file, f"{h:016x}"])
            if i % 500 == 0:
                out.flush()  # an interrupted run keeps everything hashed so far
                print(f"  {i}/{len(todo)}", flush=True)
    print(f"done, {missing} listed frames were missing or unreadable")


if __name__ == "__main__":
    main()
