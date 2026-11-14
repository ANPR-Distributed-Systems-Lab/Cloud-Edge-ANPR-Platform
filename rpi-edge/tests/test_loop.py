import threading
from collections import Counter
from datetime import UTC, datetime

import numpy as np
from samples import LOCATION, configuration_document, detection_event

from detection.config.store import ConfigurationStore
from detection.contract.configuration import ModelVersions
from detection.delivery.queue import PersistentQueue
from detection.delivery.queues import DETECTION_CODEC
from detection.gps.source import FixedLocationSource, NoLocationSource
from detection.loop import FrameLoop, Summary
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
    """A pipeline that records the models and the position each frame ran with."""

    def __init__(self):
        self.n = 0
        self.seen = []

    def process(self, frame, configuration, models, location):
        self.n += 1
        self.seen.append((models.versions, location))
        return FrameResult(frame_id=f"f{self.n}", events=[detection_event(self.n, 100.0)], rejected=Counter(cooldown=1))


def loop_for(tmp_path, locations, frames=3):
    stop = threading.Event()
    store = ConfigurationStore(tmp_path / "config")
    store.apply(configuration_document(camera={"fps": 11.7}), None)
    slot = ModelSlot()
    slot.put(LoadedModels(ModelVersions("v2", "v3"), None, None))
    detections = PersistentQueue(tmp_path / "d.sqlite3", "detections", DETECTION_CODEC, 30, 1000)
    pipeline, observed = OneEventPerFrame(), []
    loop = FrameLoop(FakeCamera(stop, frames), pipeline, store, slot, locations, detections,
                     observers=(lambda frame, result: observed.append(result.frame_id),))
    return loop, stop, pipeline, detections, observed


def test_the_loop_buffers_events_and_reopens_a_failed_camera(tmp_path, monkeypatch):
    monkeypatch.setattr("detection.loop.CAMERA_RETRY_SECONDS", 0)
    loop, stop, pipeline, detections, observed = loop_for(tmp_path, FixedLocationSource(52.229676, 21.012229))
    loop.run(stop)
    assert loop.camera.opened == 2  # once at the start, once after the failure
    assert detections.pending() == 3 and not loop.camera.is_open
    assert observed == ["f1", "f2", "f3"]  # every analysed frame reaches the observers
    assert all(versions == ModelVersions("v2", "v3") and location.lat == LOCATION.lat
               for versions, location in pipeline.seen)


def test_a_frame_without_a_fix_gets_no_location(tmp_path, monkeypatch):
    monkeypatch.setattr("detection.loop.CAMERA_RETRY_SECONDS", 0)
    loop, stop, pipeline, _, _ = loop_for(tmp_path, NoLocationSource(), frames=1)
    loop.run(stop)
    assert [location for _, location in pipeline.seen] == [None]


def test_summary_counts_and_resets():
    summary = Summary()
    summary.add(FrameResult(events=[detection_event(1)], rejected=Counter(too_small=2), detect_ms=500, ocr_ms=80), 0.6)
    summary.add(FrameResult(rejected=Counter(too_small=1, cooldown=1), detect_ms=480), 0.5)
    fields = summary.flush()
    assert fields["frames"] == 2 and fields["events"] == 1
    assert fields["rejected"] == {"too_small": 3, "cooldown": 1}
    assert fields["detect_ms_median"] == 500.0
    assert summary.frames == 0
