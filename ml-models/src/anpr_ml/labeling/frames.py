"""Recorded sessions and the perceptual hash used to find near-duplicate frames."""
import csv
from pathlib import Path

import numpy as np
from PIL import Image

from ..paths import DATA_DIR

HASH_SIZE = 8  # 8x8 difference hash = 64 bits


def list_sessions(data_dir: Path = DATA_DIR) -> list[str]:
    return sorted(p.name for p in data_dir.glob("session_*") if (p / "frames.csv").is_file())


def session_frames(session: str, data_dir: Path = DATA_DIR) -> list[str]:
    """Frame paths relative to the session directory, in recording order."""
    with open(data_dir / session / "frames.csv", newline="") as f:
        return [row["file"] for row in csv.DictReader(f)]


def dhash(path: Path) -> int:
    """64-bit difference hash: whether each pixel of a 9x8 grayscale thumbnail is brighter than its left
    neighbour. JPEG draft mode decodes at 1/8 scale, about 10x faster than a full 12 MP decode."""
    with Image.open(path) as im:
        im.draft("L", (HASH_SIZE * 32, HASH_SIZE * 32))
        small = im.convert("L").resize((HASH_SIZE + 1, HASH_SIZE), Image.Resampling.BOX)
    px = np.asarray(small, dtype=np.int16)
    bits = (px[:, 1:] > px[:, :-1]).flatten()
    return int.from_bytes(np.packbits(bits).tobytes(), "big")


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two hashes."""
    return (a ^ b).bit_count()
