import hashlib
import json

import cv2
import numpy as np
import pytest
import yaml

from anpr_ml.detector_eval import Prediction, evaluate, match_image
from anpr_ml.geometry import plate_width_px
from anpr_ml.preprocess import resize_for_detector
from anpr_ml.yolo_dataset import (
    IGNORE_FILL,
    build_dataset,
    convert_record,
    ignore_mask,
    label_line,
    session_of,
    split_records,
)

W, H = 400, 300  # synthetic "original" frame
PLATE = [[0.40, 0.40], [0.60, 0.40], [0.60, 0.46], [0.40, 0.46]]  # 80 px wide on a 400 px frame
SMALL = [[0.10, 0.10], [0.15, 0.10], [0.15, 0.12], [0.10, 0.12]]  # 20 px wide
FAR = [[0.80, 0.80], [0.85, 0.80], [0.85, 0.82], [0.80, 0.82]]


def record(image="b/session_a__0000__img_000001.jpg", plates=(PLATE,), ignore=(FAR,)):
    return {
        "image": image, "width": W, "height": H,
        "plates": [{"corners": c, "text": "", "readable": False, "occlusion": "none", "type": "standard"}
                   for c in plates],
        "ignore": [{"corners": c} for c in ignore],
    }


def test_resize_for_detector_reference_pixels():
    # Golden checksum: the edge node must reproduce these exact pixels from the same input.
    rng = np.random.default_rng(7)
    frame = rng.integers(0, 256, (3040, 4056, 3), dtype=np.uint8)
    out = resize_for_detector(frame, (1280, 960))
    assert out.shape == (960, 1280, 3) and out.dtype == np.uint8
    assert np.array_equal(out, cv2.resize(frame, (1280, 960), interpolation=cv2.INTER_AREA))
    assert hashlib.sha256(out.tobytes()).hexdigest()[:16] == GOLDEN_RESIZE


GOLDEN_RESIZE = "2b2164cc869b5e20"  # opencv 5.0.0; a change here means the Pi and the dataset may disagree


def test_label_line_derives_box_from_corners_and_keeps_order():
    values = [float(v) for v in label_line(np.array(PLATE)).split()]
    assert values[0] == 0
    assert values[1:5] == pytest.approx([0.5, 0.43, 0.2, 0.06])
    kpts = np.array(values[5:]).reshape(4, 3)
    assert kpts[:, :2] == pytest.approx(np.array(PLATE))
    assert list(kpts[:, 2]) == [2, 2, 2, 2]


def test_ignore_mask_covers_region_with_margin_but_never_a_plate():
    size = (100, 100)
    region = np.array([[10, 10], [30, 10], [30, 20], [10, 20]], float)
    plate = np.array([[25, 12], [60, 12], [60, 18], [25, 18]], float)  # overlaps the region
    mask = ignore_mask(size, [region], [plate], margin_px=2)
    assert mask[15, 15] and mask[15, 9]  # inside, and within the margin
    assert not mask[15, 5]  # beyond the margin
    assert not mask[15, 27]  # plate pixels are protected


def test_convert_record_paints_ignored_and_demotes_small_plates():
    image = np.full((H, W, 3), 200, np.uint8)
    out, lines, stats = convert_record(record(plates=(PLATE, SMALL)), image, (200, 150), 70, 0, IGNORE_FILL)
    assert out.shape == (150, 200, 3)
    assert len(lines) == 1 and stats["plates"] == 1 and stats["plates_demoted_small"] == 1
    assert (out[int(0.81 * 150), int(0.825 * 200)] == IGNORE_FILL).all()  # ignore region
    assert (out[int(0.11 * 150), int(0.125 * 200)] == IGNORE_FILL).all()  # demoted small plate
    assert (out[int(0.43 * 150), int(0.5 * 200)] == 200).all()  # real plate untouched


def test_frames_without_plates_count_as_negatives():
    _, lines, stats = convert_record(record(plates=(), ignore=()), np.zeros((H, W, 3), np.uint8), (200, 150), 70, 0, 114)
    assert lines == [] and stats["negatives"] == 1


def test_split_comes_from_the_session_not_the_batch():
    splits = {"train": ["session_a"], "val": ["session_b"], "test": []}
    recs = [record("train_001/session_b__0000__img_000001.jpg"), record("val_001/session_a__0000__img_000002.jpg")]
    by_split = split_records(recs, splits)
    assert [session_of(r["image"]) for r in by_split["val"]] == ["session_b"]
    with pytest.raises(ValueError):
        split_records([record("x/session_zzz__0000__img.jpg")], splits)


def test_build_dataset_writes_yolo_layout_and_refuses_overwrite(tmp_path):
    images = tmp_path / "batches"
    (images / "b").mkdir(parents=True)
    recs = [record("b/session_a__0000__img_000001.jpg"), record("b/session_b__0000__img_000002.jpg", plates=())]
    for r in recs:
        cv2.imwrite(str(images / r["image"]), np.full((H, W, 3), 90, np.uint8))
    export = tmp_path / "b.jsonl"
    export.write_text("".join(json.dumps(r) + "\n" for r in recs))
    splits = {"train": ["session_a"], "val": ["session_b"], "test": []}

    out = tmp_path / "ds"
    manifest = build_dataset([export], out, (64, 64), images_dir=images, splits=splits)
    data = yaml.safe_load((out / "data.yaml").read_text())
    assert data["kpt_shape"] == [4, 3] and data["flip_idx"] == [1, 0, 3, 2] and "test" not in data
    assert (out / "images" / "train" / "session_a__0000__img_000001.png").is_file()
    assert (out / "labels" / "val" / "session_b__0000__img_000002.txt").read_text() == ""
    assert manifest["counts"]["train"]["plates"] == 1 and manifest["counts"]["val"]["negatives"] == 1
    with pytest.raises(FileExistsError):
        build_dataset([export], out, (64, 64), images_dir=images, splits=splits)


def test_eval_perfect_prediction_and_known_corner_shift():
    r = record()
    shift = np.array([2 / W, 0.0])  # 2 px on the original
    preds = {r["image"]: [Prediction(0.9, np.array(PLATE) + shift)]}
    res = evaluate([r], preds, min_plate_px=70)
    assert res["best"]["precision"] == 1.0 and res["best"]["recall"] == 1.0
    assert res["corner_error"]["mean_px"] == pytest.approx(2.0)
    assert res["corner_error"]["mean_rel_width"] == pytest.approx(2.0 / plate_width_px(np.array(PLATE) * [W, H]))


def test_eval_detection_on_ignored_region_is_not_a_false_positive():
    r = record()
    m = match_image(r, [Prediction(0.9, np.array(PLATE)), Prediction(0.8, np.array(FAR))], min_plate_px=70)
    assert [x.gt for x in m.matches] == [0]
    elsewhere = np.array(PLATE) + [0.3, -0.3]
    m = match_image(r, [Prediction(0.7, elsewhere)], min_plate_px=70)
    assert [x.gt for x in m.matches] == [None]


def test_tracking_overlays_use_fractions_and_skip_small_plates():
    from anpr_ml.tracking import _boxes, _draw

    r = record(plates=(PLATE, SMALL))
    preds = [Prediction(0.8, np.array(PLATE))]
    boxes = _boxes(r, preds, min_plate_px=70)
    assert len(boxes["ground_truth"]["box_data"]) == 1  # the 20 px plate is demoted, not ground truth
    pos = boxes["predictions"]["box_data"][0]["position"]
    assert pos == pytest.approx({"minX": 0.4, "minY": 0.4, "maxX": 0.6, "maxY": 0.46})
    drawn = _draw(np.zeros((150, 200, 3), np.uint8), r, preds, min_plate_px=70)
    assert drawn.shape == (150, 200, 3) and drawn.any()
