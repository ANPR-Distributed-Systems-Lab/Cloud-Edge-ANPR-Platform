"""Plate geometry shared by validation, dataset conversion and evaluation."""
import numpy as np


def plate_width_px(corners_px: np.ndarray) -> float:
    """Width of a TL-TR-BR-BL quad: the mean length of its top and bottom edges."""
    c = np.asarray(corners_px, dtype=float)
    return float((np.linalg.norm(c[1] - c[0]) + np.linalg.norm(c[2] - c[3])) / 2)


def quad_box(corners: np.ndarray) -> np.ndarray:
    """Axis-aligned box (x1, y1, x2, y2) enclosing the corners."""
    c = np.asarray(corners, dtype=float)
    return np.array([c[:, 0].min(), c[:, 1].min(), c[:, 0].max(), c[:, 1].max()])


def box_intersection(a: np.ndarray, b: np.ndarray) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0.0) * max(h, 0.0)


def box_area(a: np.ndarray) -> float:
    return max(a[2] - a[0], 0.0) * max(a[3] - a[1], 0.0)


def box_iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = box_intersection(a, b)
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 0 else 0.0
