"""One frame in, the detection events to buffer out: detector, send rule, OCR (DETECTION.md, "Pipeline")."""
import time
from collections import Counter
from dataclasses import dataclass, field

from detection.config.schema import EdgeSettings
from detection.delivery.events import detection_event, uuid7
from detection.rules.send_rule import Cooldown, geometry_rejection, reading_rejection
from detection.vision.detector import Detection, Detector
from detection.vision.frame import Frame
from detection.vision.ocr import Reader, Reading
from detection.vision.preprocess import rectify_plate


@dataclass
class FrameResult:
    detections: list[dict] = field(default_factory=list)  # events in the shape of the ingest contract
    rejected: Counter = field(default_factory=Counter)  # reason -> number of detections
    detect_ms: float = 0.0  # resize + detector
    ocr_ms: float = 0.0  # rectify + OCR, all plates of the frame


class Pipeline:
    def __init__(self, detector: Detector, reader: Reader, clock=time.monotonic) -> None:
        self.detector = detector
        self.reader = reader
        self.cooldown = Cooldown()
        self.clock = clock

    def process(self, frame: Frame, settings: EdgeSettings) -> FrameResult:
        result = FrameResult()
        started = time.perf_counter()
        found = self.detector.detect(frame.image, settings.ml.detector_min_confidence)
        result.detect_ms = (time.perf_counter() - started) * 1000

        frame_id = None  # assigned only when the frame produces an event
        for detection in found:
            reason, reading = self._judge(frame, detection, settings, result)
            if reason is not None:
                result.rejected[reason] += 1
                continue
            frame_id = frame_id or uuid7()
            result.detections.append(detection_event(
                frame_id, frame.captured_at, reading.text, reading.confidence, detection.confidence,
                detection.corners, _size(frame)))
        return result

    def _judge(self, frame: Frame, detection: Detection, settings: EdgeSettings,
               result: FrameResult) -> tuple[str | None, Reading | None]:
        """(why the detection is not sent, or None; its reading, when it reached the OCR)."""
        reason = geometry_rejection(detection.corners, _size(frame), settings.ml)
        if reason is not None:
            return reason, None
        started = time.perf_counter()
        reading = self.reader.read(rectify_plate(frame.image, detection.corners))
        result.ocr_ms += (time.perf_counter() - started) * 1000
        reason = reading_rejection(reading, settings.ml)
        if reason is None and not self.cooldown.accept(reading.text, self.clock(), settings.plate_cooldown_seconds):
            reason = "cooldown"
        return reason, reading


def _size(frame: Frame) -> tuple[int, int]:
    height, width = frame.image.shape[:2]
    return width, height
