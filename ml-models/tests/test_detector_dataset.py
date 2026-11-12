import json

import cv2
import numpy as np
import pytest
import yaml

from anpr_ml.detector.dataset import IGNORE_FILL, build_dataset, convert_record, ignore_mask, label_line
from samples import FAR, PLATE, SMALL, H, W, record


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
    far_x, far_y = np.mean(FAR, axis=0)
    assert (out[int(far_y * 150), int(far_x * 200)] == IGNORE_FILL).all()  # ignore region
    assert (out[int(0.11 * 150), int(0.125 * 200)] == IGNORE_FILL).all()  # demoted small plate
    assert (out[int(0.43 * 150), int(0.5 * 200)] == 200).all()  # real plate untouched


def test_frames_without_plates_count_as_negatives():
    _, lines, stats = convert_record(record(plates=(), ignore=()), np.zeros((H, W, 3), np.uint8),
                                     (200, 150), 70, 0, IGNORE_FILL)
    assert lines == [] and stats["negatives"] == 1


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
