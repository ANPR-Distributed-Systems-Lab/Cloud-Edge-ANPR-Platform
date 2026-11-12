import threading
from collections import Counter
from datetime import UTC, datetime

import numpy as np
from samples import configuration_document
from test_outbox import event

from detection.config.store import ConfigurationStore
from detection.contract.configuration import ModelVersions
from detection.delivery.outbox import Outbox
from detection.loop import Summary, run_loop
from detection.pipeline import FrameResult
from detection.vision.frame import Frame
from detection.vision.models import LoadedModels, ModelSlot


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
        return Frame(np.zeros((4, 4, 3), np.uint8), datetime.now(UTC))

    def close(self):
        self.is_open = False


class OneEventPerFrame:
    """A pipeline that records which models each frame ran with."""

    def __init__(self):
        self.n = 0
        self.versions = []

    def process(self, frame, configuration, models):
        self.n += 1
        self.versions.append(models.versions)
        return FrameResult(events=[event(self.n, 100.0)], rejected=Counter(cooldown=1))


def test_the_loop_buffers_events_and_reopens_a_failed_camera(tmp_path, monkeypatch):
    monkeypatch.setattr("detection.loop.CAMERA_RETRY_SECONDS", 0)
    stop = threading.Event()
    store = ConfigurationStore(tmp_path / "config")
    store.apply(configuration_document(camera={"fps": 11.7}), None)
    slot = ModelSlot()
    slot.put(LoadedModels(ModelVersions("v2", "v3"), None, None))
    camera, outbox, pipeline = FakeCamera(stop, frames=3), Outbox(tmp_path / "outbox.sqlite3"), OneEventPerFrame()
    seen = []
    run_loop(camera, pipeline, store, slot, outbox, stop, on_frame=seen.append)
    assert camera.opened == 2  # once at the start, once after the failure
    assert len(seen) == 3  # every analysed frame reaches the feedback
    assert outbox.pending() == 3 and not camera.is_open
    assert pipeline.versions == [ModelVersions("v2", "v3")] * 3


def test_summary_counts_and_resets():
    summary = Summary()
    summary.add(FrameResult(events=[event(1)], rejected=Counter(too_small=2), detect_ms=500, ocr_ms=80), 0.6)
    summary.add(FrameResult(rejected=Counter(too_small=1, cooldown=1), detect_ms=480), 0.5)
    fields = summary.flush()
    assert fields["frames"] == 2 and fields["events"] == 1
    assert fields["rejected"] == {"too_small": 3, "cooldown": 1}
    assert fields["detect_ms_median"] == 500.0
    assert summary.frames == 0
