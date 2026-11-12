import re
from datetime import UTC, datetime

import numpy as np
from samples import configuration

from detection.contract.configuration import ModelVersions
from detection.pipeline import Pipeline
from detection.rules.send_rule import is_clockwise_convex
from detection.vision.detector import Detection
from detection.vision.frame import Frame
from detection.vision.models import LoadedModels
from detection.vision.ocr import Reading

CONFIG = configuration()

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
PLATE = np.array([[1000, 1000], [1120, 1000], [1120, 1027], [1000, 1027]], float)
SMALL = np.array([[2000, 1000], [2050, 1000], [2050, 1011], [2000, 1011]], float)


class FakeDetector:
    def __init__(self, detections):
        self.detections = detections
        self.min_confidence = None

    def detect(self, image, min_confidence):
        self.min_confidence = min_confidence
        return self.detections


class FakeReader:
    def __init__(self, *readings):
        self.readings = list(readings)
        self.crops = []

    def read(self, crop):
        self.crops.append(crop.shape)
        return self.readings.pop(0)


def models(detector, reader):
    return LoadedModels(ModelVersions("v2", "v3"), detector, reader)


def frame():
    return Frame(np.zeros((3040, 4056, 3), np.uint8), datetime(2026, 11, 12, 9, 14, 22, 381_500, tzinfo=UTC))


def test_an_accepted_reading_becomes_an_event():
    detector = FakeDetector([Detection(0.88, PLATE)])
    reader = FakeReader(Reading("WA12345", 0.9412, 0.97))
    result = Pipeline(clock=lambda: 0.0).process(frame(), CONFIG, models(detector, reader))

    assert detector.min_confidence == CONFIG.ml.detector_min_confidence
    assert reader.crops == [(64, 128, 3)]
    [event] = result.events
    assert UUID.fullmatch(event.detection_id) and UUID.fullmatch(event.frame_id)
    assert event.detected_at == frame().captured_at
    assert event.plate == "WA12345"
    assert event.ocr_confidence == 0.9412 and event.detector_confidence == 0.88
    corners = np.array(event.corners)
    assert ((corners >= 0) & (corners <= 1)).all() and is_clockwise_convex(corners * [4056, 3040])
    assert event.corners[0] == (round(1000 / 4056, 5), round(1000 / 3040, 5))


def test_rejected_detections_are_counted_and_not_read_twice():
    detector = FakeDetector([Detection(0.9, SMALL), Detection(0.9, PLATE), Detection(0.9, PLATE + [0, 100])])
    reader = FakeReader(Reading("WA12345", 0.5, 0.97), Reading("KR1AC23", 0.95, 0.4))
    result = Pipeline(clock=lambda: 0.0).process(frame(), CONFIG, models(detector, reader))
    assert result.events == []
    assert dict(result.rejected) == {"too_small": 1, "low_confidence": 1, "unreadable": 1}
    assert len(reader.crops) == 2  # the small plate never reached the OCR


def test_two_plates_of_one_frame_share_the_frame_id_and_cooldown_applies_across_frames_and_models():
    now = [0.0]
    pipeline = Pipeline(clock=lambda: now[0])
    first = pipeline.process(frame(), CONFIG, models(
        FakeDetector([Detection(0.9, PLATE), Detection(0.9, PLATE + [0, 200])]),
        FakeReader(Reading("WA12345", 0.9, 0.9), Reading("KR1AC23", 0.9, 0.9))))
    assert len(first.events) == 2
    assert first.events[0].frame_id == first.events[1].frame_id
    assert first.events[0].detection_id != first.events[1].detection_id

    now[0] = 30.0  # within plateCooldownSeconds (60), and with a new set of models
    second = pipeline.process(frame(), CONFIG, models(
        FakeDetector([Detection(0.9, PLATE), Detection(0.9, PLATE + [0, 200])]),
        FakeReader(Reading("WA12345", 0.9, 0.9), Reading("PO123AC", 0.9, 0.9))))
    assert [e.plate for e in second.events] == ["PO123AC"]
    assert second.rejected["cooldown"] == 1
