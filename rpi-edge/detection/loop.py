"""The frame loop: capture, pipeline, outbox; a summary every SUMMARY_SECONDS (counters only, no plate texts)."""
import threading
import time
from collections import Counter

from common import system_info
from common.jsonlog import log
from detection.config.settings import Settings
from detection.delivery.outbox import Outbox
from detection.pipeline import FrameResult, Pipeline
from detection.vision.camera import Camera
from detection.vision.frame import Frame
from detection.vision.replay import ReplayCamera

SUMMARY_SECONDS = 30.0
CAMERA_RETRY_SECONDS = 5.0


def run_loop(camera: Camera | ReplayCamera, pipeline: Pipeline, settings: Settings, outbox: Outbox,
             stop: threading.Event) -> None:
    """Analyses frames until stopped. Any failure closes the camera, which opens again a little later."""
    applied_version = None
    summary = Summary()
    while not stop.is_set():
        try:
            if not camera.is_open:
                camera.open(settings.current.camera)
                applied_version = settings.version
            elif applied_version != settings.version:
                camera.apply(settings.current.camera)
                applied_version = settings.version
            started = time.monotonic()
            frame = camera.capture()
            result = pipeline.process(frame, settings.current)
            _buffer(result, frame, outbox)
            summary.add(result, time.monotonic() - started)
            if summary.due():
                log("detection_summary", **summary.flush(), pending=outbox.pending(), quarantined=outbox.quarantined(),
                    temp_c=system_info.cpu_temp_c())
            stop.wait(max(0.0, 1 / settings.current.camera.fps - (time.monotonic() - started)))
        except Exception as e:  # the loop must outlive any camera or model error
            log("detection_loop_error", level="error", error=repr(e))
            camera.close()
            stop.wait(CAMERA_RETRY_SECONDS)
    camera.close()


def _buffer(result: FrameResult, frame: Frame, outbox: Outbox) -> None:
    if not result.detections:
        return
    outbox.add(result.detections, frame.captured_at.timestamp())
    for d in result.detections:  # the detectionId is the trace id of a detection
        log("detection_buffered", traceId=d["detectionId"], frameId=d["frameId"],
            ocrConfidence=d["ocrConfidence"], detectorConfidence=d["detectorConfidence"])


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
        self.events += len(result.detections)
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
