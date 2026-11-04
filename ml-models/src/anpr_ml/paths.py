"""Locations used by the tooling. The data directory can be moved with ANPR_DATA_DIR."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # ml-models/
DATA_DIR = Path(os.environ.get("ANPR_DATA_DIR", ROOT / "data"))
LABELING_DIR = ROOT / "labeling"
BATCHES_DIR = LABELING_DIR / "batches"
EXPORTS_DIR = LABELING_DIR / "exports"
FRAME_INDEX = LABELING_DIR / "frame_index.csv"
SPLITS_FILE = LABELING_DIR / "splits.json"
SELECTED_FILE = LABELING_DIR / "selected.csv"
