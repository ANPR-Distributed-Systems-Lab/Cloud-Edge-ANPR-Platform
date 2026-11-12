import threading
from collections import Counter
from datetime import datetime, timezone

import numpy as np

from detection.config.settings import Settings
from detection.delivery.outbox import Outbox
from detection.loop import Summary, run_loop
from detection.pipeline import FrameResult
from detection.vision.frame import Frame


class FakeCamera:
    """Fails on its first capture, then serves frames until the loop has seen `frames` of them."""

    def __init__(self, stop: threading.Event, frames: int) -> None:
        self.stop, self.frames = stop, frames
        self.is_open, self.opened, self.captured, self.failed = False, 0, 0, False

    def open(self, camera):
        self.is_open, self.opened = True, self.opened + 1

    def apply(self, camera):
        pass

    def capture(self):
        if not self.failed:
            self.failed = True
            raise OSError("camera hiccup")
        self.captured += 1
        if self.captured >= self.frames:
            self.stop.set()
        return Frame(np.zeros((4, 4, 3), np.uint8), datetime.now(timezone.utc))

    def close(self):
        self.is_open = False


class OneEventPerFrame:
    def __init__(self):
        self.n = 0

    def process(self, frame, settings):
        self.n += 1
        return FrameResult(detections=[{"detectionId": f"d{self.n}", "frameId": f"f{self.n}", "ocrConfidence": 0.9,
                                        "detectorConfidence": 0.8}], rejected=Counter(cooldown=1))


def test_the_loop_buffers_events_and_reopens_a_failed_camera(tmp_path, monkeypatch):
    monkeypatch.setattr("detection.loop.CAMERA_RETRY_SECONDS", 0)
    stop = threading.Event()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "detection.json").write_text('{"camera": {"fps": 11.7}}')
    settings = Settings(tmp_path / "config")
    camera, outbox = FakeCamera(stop, frames=3), Outbox(tmp_path / "outbox.sqlite3")
    run_loop(camera, OneEventPerFrame(), settings, outbox, stop)
    assert camera.opened == 2  # once at the start, once after the failure
    assert outbox.pending() == 3 and not camera.is_open


def test_summary_counts_and_resets():
    summary = Summary()
    summary.add(FrameResult(detections=[{}], rejected=Counter(too_small=2), detect_ms=500, ocr_ms=80), 0.6)
    summary.add(FrameResult(rejected=Counter(too_small=1, cooldown=1), detect_ms=480), 0.5)
    fields = summary.flush()
    assert fields["frames"] == 2 and fields["events"] == 1
    assert fields["rejected"] == {"too_small": 3, "cooldown": 1}
    assert fields["detect_ms_median"] == 500.0
    assert summary.frames == 0
