from datetime import UTC, datetime, timedelta

from samples import configuration_document, detection_event

from common import system_info
from detection.config.store import ConfigurationStore
from detection.contract.metrics import FixType
from detection.delivery.queues import Queues
from detection.gps.source import FixedLocationSource, NoLocationSource
from detection.metrics import MetricsSampler
from detection.throughput import FrameCounter

T0 = datetime(2026, 11, 13, 4, 0, 0, tzinfo=UTC)


def sampler(tmp_path, gps):
    queues = Queues.open(tmp_path / "outbox")
    store = ConfigurationStore(tmp_path / "config")
    store.apply(configuration_document(), None)
    frames, now = FrameCounter(), [T0]
    return MetricsSampler(queues, gps, frames, store, tmp_path, clock=lambda: now[0]), queues, frames, now


def test_a_measurement_has_the_state_of_the_device_and_is_queued(tmp_path, monkeypatch):
    monkeypatch.setattr(system_info, "cpu_temp_c", lambda: 54.0)
    sampler_, queues, frames, now = sampler(tmp_path, FixedLocationSource(52.2, 21.0))
    queues.detections.add([detection_event(1), detection_event(2)])
    for _ in range(40):
        frames.tick()
    now[0] += timedelta(seconds=20)

    metric = sampler_.measure_once()

    assert metric.processing_fps == 2.0  # 40 frames in 20 s
    assert metric.cpu_temperature_c == 54.0 and metric.recorded_at == T0 + timedelta(seconds=20)
    assert metric.queues.detections_pending == 2 and metric.queues.locations_pending == 0
    assert metric.gps.fix is FixType.FIX_3D
    assert metric.disk_free_mb > 0 and metric.uptime_seconds > 0
    assert queues.metrics.oldest(1)[0].item == metric


def test_the_rate_is_measured_since_the_previous_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(system_info, "cpu_temp_c", lambda: 50.0)
    sampler_, _, frames, now = sampler(tmp_path, NoLocationSource())
    for _ in range(30):
        frames.tick()
    now[0] += timedelta(seconds=30)
    assert sampler_.measure_once().processing_fps == 1.0
    now[0] += timedelta(seconds=60)
    assert sampler_.measure_once().processing_fps == 0.0  # no frames in the last minute


def test_without_a_temperature_nothing_is_made_up(tmp_path, monkeypatch):
    monkeypatch.setattr(system_info, "cpu_temp_c", lambda: None)
    sampler_, queues, _, _ = sampler(tmp_path, NoLocationSource())
    assert sampler_.measure_once() is None and queues.metrics.pending() == 0
