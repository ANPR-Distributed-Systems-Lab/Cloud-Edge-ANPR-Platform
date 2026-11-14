"""One frame in, the detection events to buffer out: detector, send rule, OCR (DETECTION.md, "Pipeline")."""
import time
from collections import Counter
from dataclasses import dataclass, field

from detection.contract.configuration import DeviceConfiguration
from detection.contract.ingest import DetectionEvent
from detection.contract.locations import Location
from detection.contract.wire import uuid7
from detection.rules.send_rule import Cooldown, geometry_rejection, reading_rejection
from detection.vision.detector import Detection
from detection.vision.frame import Frame
from detection.vision.models import LoadedModels
from detection.vision.ocr import Reading
from detection.vision.preprocess import rectify_plate

NO_LOCATION = "no_location"


@dataclass
class FrameResult:
    frame_id: str | None = None  # assigned when the frame produced events; also names the photo of the frame
    events: list[DetectionEvent] = field(default_factory=list)
    rejected: Counter = field(default_factory=Counter)  # reason -> number of detections
    detect_ms: float = 0.0  # resize + detector
    ocr_ms: float = 0.0  # rectify + OCR, all plates of the frame


class Pipeline:
    """Holds what outlives a frame: the cooldown per plate, kept across model swaps."""

    def __init__(self, clock=time.monotonic) -> None:
        self.cooldown = Cooldown()
        self.clock = clock

    def process(self, frame: Frame, configuration: DeviceConfiguration, models: LoadedModels,
                location: Location | None) -> FrameResult:
        """`location` is the position at the capture of the frame, None without a fix: the platform requires one with
        every detection and it cannot be recovered later, so the plates of such a frame are not read."""
        result = FrameResult()
        started = time.perf_counter()
        found = models.detector.detect(frame.image, configuration.ml.detector_min_confidence)
        result.detect_ms = (time.perf_counter() - started) * 1000
        if location is None:
            result.rejected[NO_LOCATION] += len(found)
            return result

        for detection in found:
            reason, reading = self._judge(frame, detection, configuration, models, result)
            if reason is not None:
                result.rejected[reason] += 1
                continue
            result.frame_id = result.frame_id or uuid7()
            result.events.append(DetectionEvent.of(
                device_id=configuration.device_id, frame_id=result.frame_id, captured_at=frame.captured_at,
                plate=reading.text, ocr_confidence=reading.confidence, detector_confidence=detection.confidence,
                corners_px=detection.corners, frame_size=frame.size, location=location))
        return result

    def _judge(self, frame: Frame, detection: Detection, configuration: DeviceConfiguration, models: LoadedModels,
               result: FrameResult) -> tuple[str | None, Reading | None]:
        """(why the detection is not sent, or None; its reading, when it reached the OCR)."""
        reason = geometry_rejection(detection.corners, frame.size, configuration.ml)
        if reason is not None:
            return reason, None
        started = time.perf_counter()
        reading = models.reader.read(rectify_plate(frame.image, detection.corners))
        result.ocr_ms += (time.perf_counter() - started) * 1000
        reason = reading_rejection(reading, configuration.ml)
        if reason is None and not self.cooldown.accept(reading.text, self.clock(),
                                                       configuration.plate_cooldown_seconds):
            reason = "cooldown"
        return reason, reading
