"""Helpers shared by the analysis notebooks: plot style, version selection and config comparison.

A version is the suffix of a config file: detector `v1` is configs/detector_v1.yaml, OCR `v0` is
configs/ocr_v0.yaml. Report generation sets versions through environment variables, which override the
values in a notebook's first cell (from_env says so in the output).
"""
import os
from pathlib import Path

from .paths import CONFIGS_DIR

# Reference palette, fixed roles: train / precision = blue, val / recall = orange, F1 = aqua, baseline = gray.
COLORS = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "ink": "#0b0b0b", "ink_2": "#52514e",
          "grid": "#e4e3df", "base": "#8f8d87", "paper": "#fcfcfb"}


def plot_style() -> None:
    import matplotlib.pyplot as plt
    import pandas as pd

    c = COLORS
    plt.rcParams.update({
        "figure.facecolor": c["paper"], "axes.facecolor": c["paper"], "axes.edgecolor": c["ink_2"],
        "axes.labelcolor": c["ink"], "text.color": c["ink"], "xtick.color": c["ink_2"],
        "ytick.color": c["ink_2"], "axes.grid": True, "grid.color": c["grid"], "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2, "font.size": 10,
        "legend.frameon": False,
    })
    pd.set_option("display.precision", 3)


def show_images() -> bool:
    """Whether cells may draw frames or crops (personal data); reports run with ANPR_SHOW_IMAGES=0."""
    return os.environ.get("ANPR_SHOW_IMAGES", "1") == "1"


def from_env(name: str, value: str | None) -> str | None:
    """`value` unless the environment variable `name` is set. "none" (or an empty value) means None, since
    PowerShell cannot set an empty variable: ANPR_DETECTOR_BASELINE=none gives a report without a baseline."""
    env = os.environ.get(name)
    if env is None:
        return value
    print(f"{name}={env} overrides the value {value!r} of the first cell")
    return None if env.strip().lower() in ("", "none") else env


def config_path(kind: str, version: str) -> Path:
    return CONFIGS_DIR / f"{kind}_{version}.yaml"


def versions(kind: str) -> list[str]:
    return [p.stem.removeprefix(f"{kind}_") for p in sorted(CONFIGS_DIR.glob(f"{kind}_*.yaml"))]


def config_header(path: Path) -> str:
    """The comment block at the top of a config, which states what the version is for."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        lines.append(line.lstrip("# "))
    return " ".join(lines)


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        out.update(flatten(v, f"{prefix}{k}.") if isinstance(v, dict) else {f"{prefix}{k}": v})
    return out


def config_diff(a: dict, b: dict, name_a: str, name_b: str) -> list[dict]:
    """The settings two configs disagree on, one row per dotted key."""
    fa, fb = flatten(a), flatten(b)
    return [{"setting": k, name_a: str(fa.get(k, "-")), name_b: str(fb.get(k, "-"))}
            for k in sorted(fa.keys() | fb.keys()) if fa.get(k) != fb.get(k)]
