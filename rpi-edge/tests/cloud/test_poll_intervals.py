"""The background workers wait the intervals of the configuration, and a short fixed time before there is one."""
from fakes import FakeApi, response
from samples import configuration_document

from common.faults import FaultBoard
from detection.cloud.alert_poll import UNCONFIGURED_POLL_SECONDS, AlertPoller
from detection.cloud.config_poll import ConfigPoller
from detection.config.store import ConfigurationStore
from detection.delivery.queues import Queues
from detection.gps.source import NoLocationSource
from detection.metrics import FIRST_MEASUREMENT_SECONDS, MetricsSampler
from detection.rules.alerts import AlertWatch
from detection.throughput import FrameCounter

URL = "https://api.example/api/v1"


class StopAfter:
    """A stop event that records every wait and stops the worker after `waits` of them."""

    def __init__(self, waits: int) -> None:
        self.waits, self.limit = [], waits

    def is_set(self) -> bool:
        return len(self.waits) >= self.limit

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        return self.is_set()


def store_with(tmp_path, **intervals):
    store = ConfigurationStore(tmp_path / "config")
    store.apply(configuration_document(intervals=intervals), None)
    return store


def test_the_configuration_is_polled_at_its_own_interval_once_there_is_one(tmp_path):
    store = ConfigurationStore(tmp_path / "config")
    api = FakeApi(response(200, configuration_document(intervals={"configPollSeconds": 45}), {"ETag": '"1"'}),
                  response(304))
    stop = StopAfter(2)
    ConfigPoller(api, URL, store, FaultBoard()).run(stop)
    assert stop.waits == [45, 45]  # the first answer already sets the interval


def test_without_a_configuration_the_poll_retries_soon(tmp_path):
    stop, faults = StopAfter(2), FaultBoard()
    ConfigPoller(FakeApi(response(500), response(500)), URL, ConfigurationStore(tmp_path / "config"), faults).run(stop)
    assert stop.waits == [10.0, 10.0]
    assert [f.code for f in faults.active()] == ["no_config"]


def test_the_alert_list_is_polled_at_its_interval(tmp_path):
    stop = StopAfter(2)
    store = store_with(tmp_path, alertsPollSeconds=20)
    AlertPoller(FakeApi(response(304), response(304)), URL, AlertWatch(), store, FaultBoard()).run(stop)
    assert stop.waits == [20, 20]
    stop = StopAfter(1)
    AlertPoller(FakeApi(response(304)), URL, AlertWatch(), ConfigurationStore(tmp_path / "none"),
                FaultBoard()).run(stop)
    assert stop.waits == [UNCONFIGURED_POLL_SECONDS]


def test_metrics_are_measured_soon_after_the_start_then_at_their_interval(tmp_path, monkeypatch):
    monkeypatch.setattr("common.system_info.cpu_temp_c", lambda: 50.0)
    store = store_with(tmp_path, metricsSeconds=15)
    queues = Queues.open(tmp_path / "outbox")
    stop = StopAfter(3)
    MetricsSampler(queues, NoLocationSource(), FrameCounter(), store, tmp_path).run(stop)
    assert stop.waits == [FIRST_MEASUREMENT_SECONDS, 15, 15] and queues.metrics.pending() == 2
