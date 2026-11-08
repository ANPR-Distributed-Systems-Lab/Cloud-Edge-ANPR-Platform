import hashlib
import json

import cv2
import numpy as np
import pytest

from anpr_ml.common.geometry import box_iou, plate_width, quad_box
from anpr_ml.common.labels import batch_file_name, load_records, plate_width_px, session_of, split_records
from anpr_ml.common.preprocess import resize_for_detector
from samples import PLATE, W, record

# SHA-256 prefix of resize_for_detector() on the seeded frame below, computed with opencv 5.0.0. If it changes,
# the dataset and the edge node may no longer produce the same pixels.
GOLDEN_RESIZE = "2b2164cc869b5e20"


def test_resize_for_detector_reference_pixels():
    frame = np.random.default_rng(7).integers(0, 256, (3040, 4056, 3), dtype=np.uint8)
    out = resize_for_detector(frame, (1280, 960))
    assert out.shape == (960, 1280, 3) and out.dtype == np.uint8
    assert np.array_equal(out, cv2.resize(frame, (1280, 960), interpolation=cv2.INTER_AREA))
    assert hashlib.sha256(out.tobytes()).hexdigest()[:16] == GOLDEN_RESIZE


def test_plate_width_box_and_iou():
    corners = np.array([[0, 0], [100, 10], [100, 30], [0, 20]], float)
    assert plate_width(corners) == pytest.approx(np.hypot(100, 10))
    assert list(quad_box(corners)) == [0, 0, 100, 30]
    assert box_iou(np.array([0, 0, 10, 10]), np.array([5, 0, 15, 10])) == pytest.approx(1 / 3)
    assert plate_width_px(PLATE, record()) == pytest.approx(0.2 * W)


def test_batch_file_name_round_trips_to_the_session():
    name = batch_file_name("session_20261004_111436", "0003/img_000123.jpg")
    assert name == "session_20261004_111436__0003__img_000123.jpg"
    assert session_of(f"train_001/{name}") == "session_20261004_111436"


def test_split_comes_from_the_session_not_the_batch():
    splits = {"train": ["session_a"], "val": ["session_b"], "test": []}
    recs = [record("train_001/session_b__0000__img_000001.jpg"), record("val_001/session_a__0000__img_000002.jpg")]
    by_split = split_records(recs, splits)
    assert [session_of(r["image"]) for r in by_split["val"]] == ["session_b"]
    with pytest.raises(ValueError):
        split_records([record("x/session_zzz__0000__img.jpg")], splits)


def test_a_frame_labeled_in_two_batches_is_rejected(tmp_path):
    for batch in ("a", "b"):
        (tmp_path / f"{batch}.jsonl").write_text(json.dumps(record(f"{batch}/session_a__0000__img_1.jpg")) + "\n")
    with pytest.raises(ValueError):
        load_records([tmp_path / "a.jsonl", tmp_path / "b.jsonl"])
