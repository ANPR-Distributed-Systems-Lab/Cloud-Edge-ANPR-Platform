import re
from datetime import datetime, timezone

import numpy as np

from detection.config.settings import default_settings
from detection.pipeline import Pipeline
from detection.rules.send_rule import is_clockwise_convex
from detection.vision.detector import Detection
from detection.vision.frame import Frame
from detection.vision.ocr import Reading

SETTINGS = default_settings()

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


def frame():
    return Frame(np.zeros((3040, 4056, 3), np.uint8), datetime(2026, 11, 12, 9, 14, 22, 381_500, tzinfo=timezone.utc))


def test_an_accepted_reading_becomes_an_event_in_the_ingest_shape():
    detector = FakeDetector([Detection(0.88, PLATE)])
    reader = FakeReader(Reading("WA12345", 0.9412, 0.97))
    result = Pipeline(detector, reader, clock=lambda: 0.0).process(frame(), SETTINGS)

    assert detector.min_confidence == SETTINGS.ml.detector_min_confidence
    assert reader.crops == [(64, 128, 3)]
    [event] = result.detections
    assert set(event) == {"detectionId", "frameId", "detectedAt", "plate", "ocrConfidence", "detectorConfidence",
                          "corners"}
    assert UUID.fullmatch(event["detectionId"]) and UUID.fullmatch(event["frameId"])
    assert event["detectedAt"] == "2026-11-12T09:14:22.381Z"
    assert event["plate"] == "WA12345"
    assert event["ocrConfidence"] == 0.9412 and event["detectorConfidence"] == 0.88
    corners = np.array(event["corners"])
    assert ((0 <= corners) & (corners <= 1)).all() and is_clockwise_convex(corners * [4056, 3040])
    assert corners[0].tolist() == [round(1000 / 4056, 5), round(1000 / 3040, 5)]


def test_rejected_detections_are_counted_and_not_read_twice():
    detector = FakeDetector([Detection(0.9, SMALL), Detection(0.9, PLATE), Detection(0.9, PLATE + [0, 100])])
    reader = FakeReader(Reading("WA12345", 0.5, 0.97), Reading("KR1AB23", 0.95, 0.4))
    result = Pipeline(detector, reader, clock=lambda: 0.0).process(frame(), SETTINGS)
    assert result.detections == []
    assert dict(result.rejected) == {"too_small": 1, "low_confidence": 1, "unreadable": 1}
    assert len(reader.crops) == 2  # the small plate never reached the OCR


def test_two_plates_of_one_frame_share_the_frame_id_and_cooldown_applies_across_frames():
    now = [0.0]
    pipeline = Pipeline(FakeDetector([Detection(0.9, PLATE), Detection(0.9, PLATE + [0, 200])]),
                        FakeReader(Reading("WA12345", 0.9, 0.9), Reading("KR1AB23", 0.9, 0.9),
                                   Reading("WA12345", 0.9, 0.9), Reading("PO123AC", 0.9, 0.9)),
                        clock=lambda: now[0])
    first = pipeline.process(frame(), SETTINGS)
    assert len(first.detections) == 2
    assert first.detections[0]["frameId"] == first.detections[1]["frameId"]
    assert first.detections[0]["detectionId"] != first.detections[1]["detectionId"]

    now[0] = 30.0  # within plate_cooldown_seconds (60)
    second = pipeline.process(frame(), SETTINGS)
    assert [d["plate"] for d in second.detections] == ["PO123AC"]
    assert second.rejected["cooldown"] == 1

