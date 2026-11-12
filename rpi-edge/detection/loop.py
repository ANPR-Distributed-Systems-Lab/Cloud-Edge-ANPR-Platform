"""The frame loop: capture, pipeline, outbox; a summary every SUMMARY_SECONDS (counters only, no plate texts).

Each frame runs with the configuration and the models current at that moment: a new configuration re-applies the
camera settings, and a new set of models (cloud/model_updater.py) is used from the next frame on.
"""
import threading
import time
from collections import Counter
from collections.abc import Callable

from common import system_info
from common.jsonlog import log
from detection.config.store import ConfigurationStore
from detection.delivery.outbox import Outbox
from detection.pipeline import FrameResult, Pipeline
from detection.vision.camera import Camera
from detection.vision.models import ModelSlot
from detection.vision.replay import ReplayCamera

SUMMARY_SECONDS = 30.0
CAMERA_RETRY_SECONDS = 5.0


def run_loop(camera: Camera | ReplayCamera, pipeline: Pipeline, configuration: ConfigurationStore, models: ModelSlot,
             outbox: Outbox, stop: threading.Event,
             on_frame: Callable[[FrameResult], None] = lambda result: None) -> None:
    """Analyses frames until stopped; expects a configuration and models to be there. on_frame gets every
    result once it is buffered (feedback.py). Any failure closes the camera, which opens again a little later."""
    applied_version = None
    summary = Summary()
    while not stop.is_set():
        try:
            current = configuration.current
            if not camera.is_open:
                camera.open(current.camera)
                applied_version = configuration.version
            elif applied_version != configuration.version:
                camera.apply(current.camera)
                applied_version = configuration.version
            started = time.monotonic()
            frame = camera.capture()
            loaded = models.get()
            result = pipeline.process(frame, current, loaded)
            _buffer(result, outbox)
            on_frame(result)
            summary.add(result, time.monotonic() - started)
            if summary.due():
                log("detection_summary", **summary.flush(), pending=outbox.pending(), quarantined=outbox.quarantined(),
                    detector=loaded.versions.detector, ocr=loaded.versions.ocr, temp_c=system_info.cpu_temp_c())
            stop.wait(max(0.0, 1 / current.camera.fps - (time.monotonic() - started)))
        except Exception as e:  # the loop must outlive any camera or model error
            log("detection_loop_error", level="error", error=repr(e))
            camera.close()
            stop.wait(CAMERA_RETRY_SECONDS)
    camera.close()


def _buffer(result: FrameResult, outbox: Outbox) -> None:
    if not result.events:
        return
    outbox.add(result.events)
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
