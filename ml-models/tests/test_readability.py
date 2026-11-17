import numpy as np
import pytest
import yaml

from anpr_ml.detector.predict import Prediction
from anpr_ml.ocr.metrics import evaluate
from anpr_ml.ocr.predict import Reading
from anpr_ml.ocr.readability import (
    READABILITY_CLASSES,
    batch_targets,
    is_readability,
    readable_prob,
    transfer_weights,
    write_plate_config,
)
from anpr_ml.pipeline import Read, summarize
from samples import PLATE


def reading(text, conf=0.99, readable=None):
    return Reading(text, np.full(10, conf), readable)


class Layer:
    """The part of a Keras layer that transfer_weights() uses."""

    def __init__(self, name, *shapes):
        self.name = name
        self.weights = [np.zeros(s) for s in shapes]

    def get_weights(self):
        return [w.copy() for w in self.weights]

    def set_weights(self, weights):
        self.weights = weights


class Model:
    def __init__(self, *layers):
        self.layers = list(layers)

    def get_layer(self, name):
        return next(layer for layer in self.layers if layer.name == name)


class Pool(Layer):
    """A layer of another type."""


def test_batch_targets_weigh_readable_crops_evenly_and_rejects_zero():
    targets, weights = batch_targets(["WA12345", "", "KR9876C"])
    assert targets.tolist() == [[1, 0], [0, 1], [1, 0]]
    assert weights.tolist() == [0.5, 0.0, 0.5]  # summed text loss = mean over the readable crops
    assert batch_targets(["", ""])[1].tolist() == [0.0, 0.0]  # no readable crop: no text loss, no NaN


def test_readable_prob_from_the_likelier_class():
    assert readable_prob("readable", 0.8) == pytest.approx(0.8)
    assert readable_prob("unreadable", 0.8) == pytest.approx(0.2)


def test_plate_config_keeps_everything_but_the_regions(tmp_path):
    src, out = tmp_path / "pretrained.yaml", tmp_path / "plate_config.yaml"
    src.write_text(yaml.safe_dump({"max_plate_slots": 10, "alphabet": "AB_", "plate_regions": ["Poland", "Spain"]}))
    write_plate_config(src, out)
    cfg = yaml.safe_load(out.read_text())
    assert cfg == {"max_plate_slots": 10, "alphabet": "AB_", "plate_regions": list(READABILITY_CLASSES)}
    assert is_readability(cfg["plate_regions"]) and not is_readability(["Poland", "Spain"])


def test_transfer_weights_pairs_layers_by_position_and_skips_only_the_new_head():
    source = Model(Layer("mlp", (3, 3), (3,)), Layer("dropout"), Layer("region", (8, 66), (66,)))
    source.layers[0].weights = [np.ones((3, 3)), np.ones(3)]
    target = Model(Layer("mlp_10", (3, 3), (3,)), Layer("dropout_3"), Layer("region", (8, 2), (2,)))
    transfer_weights(source, target)
    assert np.all(target.get_layer("mlp_10").weights[0] == 1)
    assert target.get_layer("region").weights[0].shape == (8, 2)
    with pytest.raises(ValueError, match="mlp_11"):
        transfer_weights(source, Model(Layer("mlp_11", (3, 4), (4,)), Layer("dropout"), Layer("region")))
    with pytest.raises(ValueError, match="different layers"):
        transfer_weights(source, Model(Pool("mlp", (3, 3), (3,)), Layer("dropout"), Layer("region")))


def test_reading_is_declined_without_text_or_when_not_readable():
    assert reading("").declined
    assert reading("WA12345", readable=0.3).declined
    assert not reading("WA12345", readable=0.7).declined
    assert not reading("WA12345").declined  # a model without the readability head


def test_ocr_metrics_judge_the_text_apart_from_the_decline():
    texts = ["WA12345", "KR9876C", "", ""]
    reads = [reading("WA12345", readable=0.9), reading("KR9876C", readable=0.2),
             reading("GD1111A", readable=0.1), reading("X", readable=0.6)]
    res = evaluate(texts, reads, [80, 150, 90, 100])
    assert res["exact"] == 1.0 and res["false_rejects"] == 1  # right text, declined anyway
    assert res["reject_rate"] == 0.5
    cov = {c["conf"]: c for c in res["coverage"]}
    assert (cov[0.0]["n_kept"], cov[0.0]["rejects_sent"]) == (1, 1)
    curve = {c["readable"]: c for c in res["readability_curve"]}
    assert (curve[0.1]["n_kept"], curve[0.1]["rejects_sent"]) == (2, 2)
    assert (curve[0.7]["n_kept"], curve[0.7]["rejects_sent"]) == (1, 0)
    assert "readability_curve" not in evaluate(["WA12345"], [reading("WA12345")], [80])


def test_pipeline_does_not_send_a_right_text_the_head_declines():
    det = Prediction(0.9, np.array(PLATE))
    reads = [Read("f", "correct", reading("A", readable=0.9), det),
             Read("f", "correct", reading("B", readable=0.1), det)]
    res = summarize(reads, [{"bucket": "70-90", "detected": True, "read_correct": True},
                            {"bucket": "70-90", "detected": True, "read_correct": False}])
    assert res["curve"][0]["sent"] == 1 and res["rejected"]["correct"] == 1
    curve = {c["readable"]: c for c in res["readability_curve"]}
    assert curve[0.05]["sent"] == 2 and curve[0.95]["sent"] == 0
    assert curve[0.05]["precision"] == 1.0 and curve[0.05]["recall"] == 1.0
