from types import SimpleNamespace

import numpy as np
import pytest

from anpr_ml import tracking
from anpr_ml.detector.predict import Prediction
from anpr_ml.detector.report import box_overlays, draw_frame
from samples import PLATE, SMALL, record


def test_overlays_use_fractions_and_leave_out_small_plates():
    r = record(plates=(PLATE, SMALL))
    preds = [Prediction(0.8, np.array(PLATE))]
    boxes = box_overlays(r, preds, min_plate_px=70)
    assert len(boxes["ground_truth"]["box_data"]) == 1
    pos = boxes["predictions"]["box_data"][0]["position"]
    assert pos == pytest.approx({"minX": 0.4, "minY": 0.4, "maxX": 0.6, "maxY": 0.46})
    drawn = draw_frame(np.zeros((150, 200, 3), np.uint8), r, preds, min_plate_px=70)
    assert drawn.shape == (150, 200, 3) and drawn.any()


class FakeWandb:
    def __init__(self):
        self.steps = []

    def log(self, values, step=None):
        self.steps.append(step)

    def finish(self):
        pass


def test_final_validation_after_training_is_not_logged_as_an_epoch(monkeypatch, tmp_path):
    fake = FakeWandb()
    monkeypatch.setattr(tracking, "start", lambda *args, **kwargs: fake)
    cfg = {"dataset": {"size": (1280, 960)}}
    callbacks = tracking.training_callbacks(cfg, {})

    def trainer(epoch, epochs=3):
        return SimpleNamespace(epoch=epoch, epochs=epochs, args=SimpleNamespace(), save_dir=tmp_path, tloss=None,
                               label_loss_items=lambda loss, prefix: {}, metrics={"m": 1.0}, lr={})

    callbacks["on_train_start"](trainer(0))
    for epoch in range(3):
        callbacks["on_fit_epoch_end"](trainer(epoch))
    callbacks["on_fit_epoch_end"](trainer(2))  # final validation, counter unchanged
    callbacks["on_fit_epoch_end"](trainer(3))  # final validation after a resume, counter one past the end
    assert fake.steps == [1, 2, 3]
