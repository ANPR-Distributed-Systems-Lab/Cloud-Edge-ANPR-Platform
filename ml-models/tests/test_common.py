import hashlib
import json

import cv2
import numpy as np
import pytest

from anpr_ml.common.geometry import box_iou, plate_width, quad_box
from anpr_ml.common.labels import batch_file_name, load_records, plate_width_px, session_of, split_records
from anpr_ml.common.preprocess import OCR_SIZE, rectify_plate, resize_for_detector
from samples import PLATE, W, record

# SHA-256 prefixes of the preprocessing on the seeded frames below, computed with opencv 5.0.0. If one changes,
# the datasets and the edge node may no longer produce the same pixels.
GOLDEN_RESIZE = "2b2164cc869b5e20"
GOLDEN_RECTIFY = {"large": "5a6c6056a22f957c", "small": "c37da4690b8a6aa8"}
QUADS = {"large": [[200, 300], [560, 280], [570, 370], [205, 395]],  # downscaled to the OCR size
         "small": [[100, 100], [160, 104], [158, 118], [99, 115]]}  # upscaled to it


def test_resize_for_detector_reference_pixels():
    frame = np.random.default_rng(7).integers(0, 256, (3040, 4056, 3), dtype=np.uint8)
    out = resize_for_detector(frame, (1280, 960))
    assert out.shape == (960, 1280, 3) and out.dtype == np.uint8
    assert np.array_equal(out, cv2.resize(frame, (1280, 960), interpolation=cv2.INTER_AREA))
    assert hashlib.sha256(out.tobytes()).hexdigest()[:16] == GOLDEN_RESIZE


@pytest.mark.parametrize("name", QUADS)
def test_rectify_plate_reference_pixels(name):
    frame = np.random.default_rng(11).integers(0, 256, (600, 800, 3), dtype=np.uint8)
    out = rectify_plate(frame, np.array(QUADS[name], float))
    assert out.shape == (OCR_SIZE[1], OCR_SIZE[0], 3) and out.dtype == np.uint8
    assert hashlib.sha256(out.tobytes()).hexdigest()[:16] == GOLDEN_RECTIFY[name]


def test_rectify_plate_maps_the_quad_onto_the_crop():
    frame = np.zeros((300, 400, 3), np.uint8)
    quad = np.array([[100, 120], [300, 100], [310, 160], [105, 175]], float)  # a tilted, perspective plate
    cv2.fillPoly(frame, [quad.astype(np.int32)], (255, 255, 255))
    tight = rectify_plate(frame, quad, margin=0.0)
    assert tight[8:-8, 8:-8].min() > 200  # the plate fills the crop
    wide = rectify_plate(frame, quad, margin=0.2)
    assert wide[:, :3].max() < 50 and wide[32, 64].min() > 200  # dark surroundings at the edge, plate inside


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
