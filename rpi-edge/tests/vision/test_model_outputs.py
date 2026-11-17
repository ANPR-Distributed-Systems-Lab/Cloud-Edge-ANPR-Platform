"""Decoding of the two models' outputs, on synthetic arrays (no model files)."""
import numpy as np
import pytest

from detection.vision import detector as detector_module
from detection.vision import ocr as ocr_module
from detection.vision.detector import Detector, parse_crop, parse_output
from detection.vision.ocr import PlateConfig, Reader, decode

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


def test_parse_output_of_a_crop_band_maps_the_rows_back_to_the_whole_frame():
    corners = [[100, 100], [140, 100], [140, 110], [100, 110]]
    rows = np.stack([detector_row(0.8, corners)])
    found = parse_output(rows, input_size=(1024, 352), frame_size=(4056, 3040), min_confidence=0.4,
                         crop=(0.337, 0.795))
    # y = y0 + y * (y1 - y0) / H with the band 1024..2417 of the frame
    assert found[0].corners[0] == pytest.approx([100 * 4056 / 1024, 1024 + 100 * 1393 / 352])
    assert found[0].corners[2] == pytest.approx([140 * 4056 / 1024, 1024 + 110 * 1393 / 352])


def test_the_crop_metadata_is_read_strictly():
    assert parse_crop(None) is None and parse_crop("") is None
    assert parse_crop("0.337,0.795") == (0.337, 0.795)
    for bad in ("0.3", "a,b", "0.8,0.3", "-0.1,0.5", "0.2,1.5", "0.5,0.5"):
        with pytest.raises(ValueError):
            parse_crop(bad)


class FakeSession:
    """Stands in for an ONNX Runtime session: a (1, 3, 352, 1024) input, one detection, the metadata given."""

    def __init__(self, metadata):
        self.metadata, self.blob = metadata, None

    def get_inputs(self):
        return [type("Input", (), {"name": "images", "shape": [1, 3, 352, 1024]})()]

    def get_modelmeta(self):
        return type("Meta", (), {"custom_metadata_map": self.metadata})()

    def run(self, _outputs, feed):
        self.blob = feed["images"]
        return [np.stack([detector_row(0.9, [[512, 176], [532, 176], [532, 186], [512, 186]])])[None]]


def detector_with(monkeypatch, metadata):
    monkeypatch.setattr(detector_module.onnx, "session", lambda _path: FakeSession(metadata))
    return Detector("model.onnx")


def test_a_detector_with_a_crop_sees_only_its_band(monkeypatch):
    detector = detector_with(monkeypatch, {"crop": "0.337,0.795"})
    frame = np.zeros((3040, 4056, 3), np.uint8)
    frame[:1024] = 255  # above the band: must not reach the model
    found = detector.detect(frame, 0.4)
    assert detector.crop == (0.337, 0.795)
    assert detector.session.blob.shape == (1, 3, 352, 1024) and detector.session.blob.max() == 0
    assert found[0].corners[0] == pytest.approx([512 * 4056 / 1024, 1024 + 176 * 1393 / 352])


def test_a_detector_without_a_crop_sees_the_whole_frame(monkeypatch):
    detector = detector_with(monkeypatch, {})
    frame = np.full((3040, 4056, 3), 255, np.uint8)
    found = detector.detect(frame, 0.4)
    assert detector.crop is None and detector.session.blob.min() == 1.0
    assert found[0].corners[0] == pytest.approx([512 * 4056 / 1024, 176 * 3040 / 352])


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


PLATE_CONFIG_YAML = ("max_plate_slots: 10\nalphabet: 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_\npad_char: _\n"
                     "img_height: 64\nimg_width: 128\nkeep_aspect_ratio: false\nimage_color_mode: rgb\n")


class FakeOcrSession:
    def __init__(self, shape):
        self.shape = shape

    def get_inputs(self):
        return [type("Input", (), {"name": "input", "shape": self.shape})()]

    def get_outputs(self):
        return [type("Output", (), {"name": "plate"})()]


def reader_with(monkeypatch, tmp_path, shape):
    (tmp_path / "plate_config.yaml").write_text(PLATE_CONFIG_YAML)
    monkeypatch.setattr(ocr_module.onnx, "session", lambda _path: FakeOcrSession(shape))
    return Reader("model.onnx", str(tmp_path / "plate_config.yaml"))


def test_the_ocr_input_size_comes_from_the_plate_config(monkeypatch, tmp_path):
    assert reader_with(monkeypatch, tmp_path, [1, 64, 128, 3]).input_size == (128, 64)


def test_an_ocr_whose_input_disagrees_with_its_plate_config_is_refused(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="96x48"):
        reader_with(monkeypatch, tmp_path, [1, 48, 96, 3])
