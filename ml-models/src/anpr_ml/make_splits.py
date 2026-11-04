"""Assigns whole recording sessions to train / val / test (never frames), deterministically.

Sessions are shuffled within each recording day and then dealt out round-robin over the days, so the
test and validation sets cover different days instead of one long drive.

Sessions recorded later are added with --add: only they are assigned, with the same rules and seed, and
every session that already has a split keeps it (labels made so far stay valid).
"""
import argparse
import json
import random
from collections import defaultdict
from itertools import zip_longest

from .frames import list_sessions
from .paths import SPLITS_FILE


def make_splits(sessions: list[str], n_test: int, n_val: int, seed: int) -> dict:
    by_day = defaultdict(list)
    for s in sessions:
        by_day[s.split("_")[1]].append(s)
    rng = random.Random(seed)
    for day in by_day.values():
        rng.shuffle(day)
    days = sorted(by_day)
    rng.shuffle(days)
    order = [s for group in zip_longest(*(by_day[d] for d in days)) for s in group if s]
    return {
        "seed": seed,
        "test": sorted(order[:n_test]),
        "val": sorted(order[n_test:n_test + n_val]),
        "train": sorted(order[n_test + n_val:]),
    }


def add_new_sessions(splits: dict, sessions: list[str], n_test: int, n_val: int) -> dict:
    """`splits` plus the sessions it does not contain yet; existing assignments never change."""
    assigned = {s for name in ("test", "val", "train") for s in splits[name]}
    new = make_splits([s for s in sessions if s not in assigned], n_test, n_val, splits["seed"])
    return {"seed": splits["seed"], **{name: sorted(splits[name] + new[name]) for name in ("test", "val", "train")}}


def load_splits() -> dict:
    with open(SPLITS_FILE) as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", type=int, default=4, help="number of test sessions (with --add: among the new ones)")
    parser.add_argument("--val", type=int, default=4, help="number of validation sessions (with --add: among the new ones)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="overwrite an existing splits.json (invalidates earlier batches!)")
    parser.add_argument("--add", action="store_true", help="assign only sessions missing from splits.json, keep the rest")
    args = parser.parse_args()

    if args.add:
        if not SPLITS_FILE.exists():
            raise SystemExit(f"{SPLITS_FILE} does not exist yet; run without --add first.")
        old = load_splits()
        splits = add_new_sessions(old, list_sessions(), args.test, args.val)
        if splits == old:
            print("no new sessions")
            return
        SPLITS_FILE.write_text(json.dumps(splits, indent=2) + "\n")
        for name in ("train", "val", "test"):
            print(f"{name}: {len(splits[name])} sessions (+{len(splits[name]) - len(old[name])})")
        return

    if SPLITS_FILE.exists() and not args.force:
        raise SystemExit(f"{SPLITS_FILE} already exists. Splits must stay fixed once labeling started; use --force to overwrite.")
    splits = make_splits(list_sessions(), args.test, args.val, args.seed)
    SPLITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SPLITS_FILE.write_text(json.dumps(splits, indent=2) + "\n")
    for name in ("train", "val", "test"):
        print(f"{name}: {len(splits[name])} sessions")


if __name__ == "__main__":
    main()
