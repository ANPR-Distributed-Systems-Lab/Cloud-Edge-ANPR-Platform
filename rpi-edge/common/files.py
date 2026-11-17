import json
import os
from pathlib import Path


def write_json_atomic(path: Path, value) -> None:
    """A power cut leaves either the old or the new file, never a half-written one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
