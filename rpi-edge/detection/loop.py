"""The frame loop: capture, position, pipeline, queue; a summary every SUMMARY_SECONDS (counters only, no plates).

Each frame runs with the configuration and the models current at that moment: a new configuration re-applies the
camera settings, and a new set of models (cloud/model_updater.py) is used from the next frame on. The position of a
frame is the fix of the GNSS module that was current when the frame was captured.
"""
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from common import system_info
from common.jsonlog import log
from detection.config.store import ConfigurationStore
from detection.contract.ingest import DetectionEvent
from detection.delivery.queue import PersistentQueue
from detection.gps.source import LocationSource, locate
from detection.pipeline import FrameResult, Pipeline
from detection.vision.camera import Camera
from detection.vision.frame import Frame
from detection.vision.models import ModelSlot
from detection.vision.replay import ReplayCamera

SUMMARY_SECONDS = 30.0
CAMERA_RETRY_SECONDS = 5.0

FrameObserver = Callable[[Frame, FrameResult], None]  # told about every analysed frame (feedback, photos, counters)


@dataclass
class FrameLoop:
    camera: Camera | ReplayCamera
    pipeline: Pipeline
    configuration: ConfigurationStore
    models: ModelSlot
    locations: LocationSource
    detections: PersistentQueue[DetectionEvent]
    observers: Sequence[FrameObserver] = ()

    def run(self, stop: threading.Event) -> None:
        """Analyses frames until stopped; expects a configuration and models to be there. Any failure closes the
        camera, which opens again a little later."""
        applied_version = None
        summary = Summary()
        while not stop.is_set():
            try:
                current = self.configuration.current
                if not self.camera.is_open:
                    self.camera.open(current.camera)
                    applied_version = self.configuration.version
                elif applied_version != self.configuration.version:
                    self.camera.apply(current.camera)
                    applied_version = self.configuration.version
                started = time.monotonic()
                frame = self.camera.capture()
                loaded = self.models.get()
                result = self.pipeline.process(frame, current, loaded, locate(self.locations, frame.captured_at))
                self._buffer(result)
                for observe in self.observers:
                    observe(frame, result)
                summary.add(result, time.monotonic() - started)
                if summary.due():
                    log("detection_summary", **summary.flush(), pending=self.detections.pending(),
                        quarantined=self.detections.quarantined(), detector=loaded.versions.detector,
                        ocr=loaded.versions.ocr, temp_c=system_info.cpu_temp_c())
                stop.wait(max(0.0, 1 / current.camera.fps - (time.monotonic() - started)))
            except Exception as e:  # the loop must outlive any camera or model error
                log("detection_loop_error", level="error", error=repr(e))
                self.camera.close()
                stop.wait(CAMERA_RETRY_SECONDS)
        self.camera.close()

    def _buffer(self, result: FrameResult) -> None:
        if not result.events:
            return
        self.detections.add(result.events)
        for event in result.events:  # the detectionId is the trace id of a detection
            log("detection_buffered", traceId=event.detection_id, frameId=event.frame_id,
                ocrConfidence=event.ocr_confidence, detectorConfidence=event.detector_confidence)


class Summary:
    """Counters and timings of the frames since the last summary."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.started = time.monotonic()
        self.frames, self.events = 0, 0
        self.rejected: Counter = Counter()
        self.frame_ms, self.detect_ms, self.ocr_ms = [], [], []  # frame = capture + processing

    def add(self, result: FrameResult, seconds: float) -> None:
        self.frames += 1
        self.events += len(result.events)
        self.rejected.update(result.rejected)
        self.frame_ms.append(seconds * 1000)
        self.detect_ms.append(result.detect_ms)
        self.ocr_ms.append(result.ocr_ms)

    def due(self) -> bool:
        return time.monotonic() - self.started >= SUMMARY_SECONDS

    def flush(self) -> dict:
        elapsed = time.monotonic() - self.started
        fields = {
            "frames": self.frames,
            "fps": round(self.frames / elapsed, 2) if elapsed > 0 else 0.0,
            "events": self.events,
            "rejected": dict(self.rejected),
            "frame_ms_median": _median(self.frame_ms),
            "detect_ms_median": _median(self.detect_ms),
            "ocr_ms_median": _median(self.ocr_ms),
        }
        self.reset()
        return fields


def _median(values: list[float]) -> float | None:
    return round(sorted(values)[len(values) // 2], 1) if values else None
