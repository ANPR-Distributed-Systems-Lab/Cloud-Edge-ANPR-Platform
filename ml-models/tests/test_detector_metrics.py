import numpy as np
import pytest

from anpr_ml.common.labels import plate_width_px
from anpr_ml.detector.metrics import evaluate, frame_results, match_image
from anpr_ml.detector.predict import Prediction
from samples import FAR, PLATE, SMALL, W, record


def test_prediction_box_defaults_to_the_box_of_its_corners():
    assert list(Prediction(0.5, np.array(PLATE)).box) == pytest.approx([0.4, 0.4, 0.6, 0.46])


def test_perfect_prediction_and_known_corner_shift():
    r = record()
    shift = np.array([2 / W, 0.0])  # 2 px on the original
    res = evaluate([r], {r["image"]: [Prediction(0.9, np.array(PLATE) + shift)]}, min_plate_px=70)
    assert res["best"]["precision"] == 1.0 and res["best"]["recall"] == 1.0
    assert res["corner_error"]["mean_px"] == pytest.approx(2.0)
    assert res["corner_error"]["mean_rel_width"] == pytest.approx(2.0 / plate_width_px(PLATE, r))


def test_detection_on_an_ignored_region_is_not_a_false_positive():
    r = record()
    m = match_image(r, [Prediction(0.9, np.array(PLATE)), Prediction(0.8, np.array(FAR))], min_plate_px=70)
    assert [x.gt for x in m.matches] == [0]
    m = match_image(r, [Prediction(0.7, np.array(PLATE) + [0.3, -0.3])], min_plate_px=70)
    assert [x.gt for x in m.matches] == [None]


def test_small_plates_are_neither_targets_nor_errors():
    r = record(plates=(PLATE, SMALL), ignore=())
    m = match_image(r, [Prediction(0.9, np.array(SMALL))], min_plate_px=70)
    assert len(m.plates) == 1 and m.matches == [] and m.missed == [0]


def test_frame_results_apply_the_operating_threshold():
    r = record()
    preds = {r["image"]: [Prediction(0.3, np.array(PLATE)), Prediction(0.9, np.array(PLATE) + [0.3, -0.3])]}
    (res,) = frame_results([r], preds, min_plate_px=70, conf=0.5)
    assert res.missed == [0] and len(res.false_positives) == 1 and res.hits == []
