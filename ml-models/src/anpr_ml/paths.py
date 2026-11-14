"""Every location the tooling reads or writes, relative to ml-models/. ANPR_DATA_DIR moves the recordings."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # ml-models/

# Recordings from the data-collection app (gitignored)
DATA_DIR = Path(os.environ.get("ANPR_DATA_DIR", ROOT / "data"))

# Labeling: splits.json and selected.csv define the dataset and are committed; the rest is local
LABELING_DIR = ROOT / "labeling"
FRAME_INDEX = LABELING_DIR / "frame_index.csv"
SPLITS_FILE = LABELING_DIR / "splits.json"
SELECTED_FILE = LABELING_DIR / "selected.csv"
BATCHES_DIR = LABELING_DIR / "batches"  # mounted into CVAT as its file share
EXPORTS_DIR = LABELING_DIR / "exports"

# Training
CONFIGS_DIR = ROOT / "configs"
DATASETS_DIR = ROOT / "datasets"  # generated, gitignored
MODELS_DIR = ROOT / "models"  # weights, gitignored (distributed through S3)
RUNS_DIR = ROOT / "runs"  # training runs and W&B files, gitignored
