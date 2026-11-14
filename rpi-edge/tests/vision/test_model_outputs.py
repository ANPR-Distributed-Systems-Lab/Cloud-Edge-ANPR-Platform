"""Decoding of the two models' outputs, on synthetic arrays (no model files)."""
import numpy as np
import pytest

from detection.vision.detector import parse_output
from detection.vision.ocr import PlateConfig, decode

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
CONFIG = PlateConfig(ALPHABET, "_", 10, (128, 64), ("readable", "unreadable"))


def detector_row(conf, corners):
    corners = np.asarray(corners, float)
    box = [*corners.min(axis=0), *corners.max(axis=0)]
    keypoints = np.hstack([corners, np.full((4, 1), 0.9)]).ravel()
    return np.array([*box, conf, 0, *keypoints], np.float32)


def test_parse_output_scales_corners_to_the_frame_and_applies_the_threshold():
    corners = [[100, 200], [140, 200], [140, 210], [100, 210]]
    rows = np.stack([detector_row(0.8, corners), detector_row(0.3, corners), np.zeros(18, np.float32)])
    found = parse_output(rows, input_size=(1280, 960), frame_size=(4056, 3040), min_confidence=0.4)
    assert len(found) == 1
    assert found[0].confidence == pytest.approx(0.8)
    assert found[0].corners[0] == pytest.approx([100 * 4056 / 1280, 200 * 3040 / 960])
    assert found[0].corners.shape == (4, 2)


def plate_probs(text, confidence=0.9):
    probs = np.full((10, len(ALPHABET)), (1 - confidence) / (len(ALPHABET) - 1), np.float32)
    for slot, char in enumerate(text.ljust(10, "_")):
        probs[slot, ALPHABET.index(char)] = confidence
    return probs


def test_decode_strips_padding_and_takes_the_weakest_slot():
    probs = plate_probs("WA12345")
    probs[3] = plate_probs("WA12345", 0.6)[3]  # one uncertain character
    reading = decode(probs, np.array([0.85, 0.15], np.float32), CONFIG)
    assert reading.text == "WA12345"
    assert reading.confidence == pytest.approx(0.6)
    assert reading.readable == pytest.approx(0.85)


def test_decode_of_all_padding_is_no_text():
    reading = decode(plate_probs(""), np.array([0.1, 0.9], np.float32), CONFIG)
    assert reading.text == "" and reading.readable == pytest.approx(0.1)


def test_a_model_without_readability_head_has_no_readable_probability():
    config = PlateConfig(ALPHABET, "_", 10, (128, 64), ())
    assert decode(plate_probs("WA12345"), None, config).readable is None


def test_plate_config_is_read_from_yaml(tmp_path):
    path = tmp_path / "plate_config.yaml"
    path.write_text("max_plate_slots: 10\nalphabet: 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_\npad_char: _\n"
                    "img_height: 64\nimg_width: 128\nkeep_aspect_ratio: false\nimage_color_mode: rgb\n"
                    "plate_regions:\n- readable\n- unreadable\n")
    assert PlateConfig.load(str(path)) == CONFIG


def test_plate_config_refuses_a_grayscale_model(tmp_path):
    path = tmp_path / "plate_config.yaml"
    path.write_text("max_plate_slots: 9\nalphabet: AB_\npad_char: _\nimg_height: 64\nimg_width: 128\n"
                    "keep_aspect_ratio: false\nimage_color_mode: grayscale\n")
    with pytest.raises(ValueError):
        PlateConfig.load(str(path))
