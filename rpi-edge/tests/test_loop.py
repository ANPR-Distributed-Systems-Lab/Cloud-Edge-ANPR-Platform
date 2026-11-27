import threading
from collections import Counter
from datetime import UTC, datetime, timedelta

import numpy as np
from samples import LOCATION, configuration, configuration_document, detection_event

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


class RecordingCamera:
    """Records what it was opened and configured with; serves `frames` frames, then stops the loop."""

    def __init__(self, stop, frames):
        self.stop, self.frames, self.captured = stop, frames, 0
        self.is_open, self.opened_with, self.applied = False, [], []

    def open(self, camera):
        self.is_open = True
        self.opened_with.append(camera)

    def apply(self, camera):
        self.applied.append(camera)

    def capture(self):
        self.captured += 1
        if self.captured >= self.frames:
            self.stop.set()
        return Frame(np.zeros((4, 4, 3), np.uint8), datetime.now(UTC))

    def close(self):
        self.is_open = False


class ChangingStore:
    """A store whose configuration changes after the given reads, as the config poller would change it."""

    def __init__(self, *configurations):
        self.configurations = list(configurations)

    @property
    def current(self):
        return self.configurations.pop(0) if len(self.configurations) > 1 else self.configurations[0]


def test_each_frame_runs_with_one_configuration_and_a_new_one_reaches_the_camera_on_the_next_frame(tmp_path):
    first, second = (configuration(camera={"fps": 11.7}), configuration(camera={"fps": 11.7, "vflip": False}))
    stop = threading.Event()
    camera, pipeline = RecordingCamera(stop, frames=3), RecordingPipeline()
    slot = ModelSlot()
    slot.put(LoadedModels(ModelVersions("v2", "v3"), None, None))
    detections = PersistentQueue(tmp_path / "d.sqlite3", "detections", DETECTION_CODEC, 30, 1000)
    FrameLoop(camera, pipeline, ChangingStore(first, second), slot, NoLocationSource(), detections).run(stop)
    assert camera.opened_with == [first.camera] and camera.applied == [second.camera]  # applied once, not per frame
    assert pipeline.configurations == [first, second, second]


def test_the_fix_age_limit_of_the_configuration_decides_the_position_of_a_frame(tmp_path):
    class StaleFix(FixedLocationSource):
        def fix_at(self, moment):  # the latest fix arrived 45 s before the capture
            return self._fix(moment - timedelta(seconds=45))

    seen = []
    for max_age in (30, 60):
        stop = threading.Event()
        pipeline = RecordingPipeline()
        slot = ModelSlot()
        slot.put(LoadedModels(ModelVersions("v2", "v3"), None, None))
        store = ChangingStore(configuration(camera={"fps": 11.7}, gps={"maxFixAgeSeconds": max_age}))
        detections = PersistentQueue(tmp_path / f"d{max_age}.sqlite3", "detections", DETECTION_CODEC, 30, 1000)
        FrameLoop(RecordingCamera(stop, 1), pipeline, store, slot, StaleFix(52.2, 21.0), detections).run(stop)
        seen.append(pipeline.locations[0])
    assert seen[0] is None and seen[1].fix_age_ms == 45_000


class RecordingPipeline:
    def __init__(self):
        self.configurations, self.locations = [], []

    def process(self, frame, configuration, models, location):
        self.configurations.append(configuration)
        self.locations.append(location)
        return FrameResult()


def test_summary_counts_and_resets():
    summary = Summary()
    summary.add(FrameResult(events=[detection_event(1)], rejected=Counter(too_small=2), detect_ms=500, ocr_ms=80), 0.6)
    summary.add(FrameResult(rejected=Counter(too_small=1, cooldown=1), detect_ms=480), 0.5)
    fields = summary.flush()
    assert fields["frames"] == 2 and fields["events"] == 1
    assert fields["rejected"] == {"too_small": 3, "cooldown": 1}
    assert fields["detect_ms_median"] == 500.0
    assert summary.frames == 0


class FailingCamera(FakeCamera):
    """Fails `failures` captures in a row, then serves one frame."""

    def __init__(self, stop, failures):
        super().__init__(stop, frames=1)
        self.failures = failures

    def capture(self):
        if self.failures:
            self.failures -= 1
            raise OSError("camera hiccup")
        self.failed = True
        return super().capture()


def test_a_loop_failing_three_times_in_a_row_is_a_fault_until_a_frame_goes_through(tmp_path, monkeypatch):
    monkeypatch.setattr("detection.loop.CAMERA_RETRY_SECONDS", 0)
    for failures, expected in ((2, []), (3, ["frame_loop_failed"])):
        loop, stop, _, _, _ = loop_for(tmp_path / str(failures), FixedLocationSource(52.2, 21.0), frames=1)
        loop.camera = FailingCamera(stop, failures)
        seen = []
        loop.observers = (lambda frame, result, loop=loop, seen=seen: seen.append(
            [f.code for f in loop.faults.active()]),)
        loop.run(stop)
        assert seen == [expected]  # while the frame that went through is observed
        assert loop.faults.active() == []


def test_a_held_loop_closes_the_camera_and_analyses_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("detection.loop.HOLD_CHECK_SECONDS", 0)
    loop, stop, pipeline, _, _ = loop_for(tmp_path, FixedLocationSource(52.2, 21.0))
    loop.camera.is_open = True
    assert loop.hold.toggle() is True
    waits = []
    stop.wait = lambda seconds: waits.append(seconds) or (len(waits) >= 3 and stop.set())
    loop.run(stop)
    assert not loop.camera.is_open and pipeline.n == 0 and waits == [0, 0, 0]
    assert loop.hold.toggle() is False
