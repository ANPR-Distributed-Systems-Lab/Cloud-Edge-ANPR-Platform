import threading
from datetime import UTC, datetime, timedelta

from samples import configuration_document
from test_nmea import GGA, RMC

from detection.config.store import ConfigurationStore
from detection.delivery.queue import PersistentQueue
from detection.delivery.queues import LOCATION_CODEC
from detection.gps.recorder import STATIONARY_SAMPLE_SECONDS, LocationRecorder
from detection.gps.serial_reader import SerialGpsReader
from detection.gps.source import FixedLocationSource
from detection.gps.tracker import Fix, GpsTracker

T0 = datetime(2026, 11, 13, 2, 19, 45, tzinfo=UTC)


class FakePort:
    """Serves its lines, then asks the reader to stop (as if the process were shutting down)."""

    def __init__(self, lines, stop):
        self.lines, self.stop, self.closed = list(lines), stop, False

    def readline(self):
        if self.lines:
            return self.lines.pop(0)
        self.stop.set()
        return b""

    def close(self):
        self.closed = True


def test_the_reader_feeds_the_tracker_and_closes_the_port():
    stop, tracker = threading.Event(), GpsTracker()
    port = FakePort([GGA.encode() + b"\r\n", b"\xff\xfe garbage\r\n", RMC.encode() + b"\r\n"], stop)
    SerialGpsReader(tracker, "/dev/ttyAMA0", 115200, opener=lambda device, baud: port, clock=lambda: T0).run(stop)
    assert tracker.latest_fix().satellites_used == 13 and port.closed


def test_a_port_that_cannot_be_opened_is_retried(monkeypatch, capsys):
    monkeypatch.setattr("detection.gps.serial_reader.RETRY_SECONDS", 0)
    stop, tracker, attempts = threading.Event(), GpsTracker(), []

    def opener(device, baud):
        attempts.append(device)
        if len(attempts) < 3:
            raise OSError("no such device")
        return FakePort([RMC.encode()], stop)

    SerialGpsReader(tracker, "/dev/ttyAMA0", 115200, opener=opener, clock=lambda: T0).run(stop)
    assert len(attempts) == 3 and tracker.latest_fix() is not None
    assert capsys.readouterr().out.count("gps_unavailable") == 1  # said once, not on every retry


class Recorder:
    """A recorder over a source whose latest fix the test sets, and a clock the test moves."""

    def __init__(self, tmp_path, **config):
        self.now = T0
        self.fix = None
        self.store = ConfigurationStore(tmp_path / "config")
        self.store.apply(configuration_document(intervals={"locationSampleSeconds": 5} | config), None)
        self.queue = PersistentQueue(tmp_path / "l.sqlite3", "locations", LOCATION_CODEC, 30, 1000)
        self.recorder = LocationRecorder(self, self.queue, self.store, clock=lambda: self.now)

    def latest_fix(self):
        return self.fix

    def arrive(self, seconds, speed):
        """A fix `seconds` after T0 at `speed` m/s, received just now."""
        self.now = T0 + timedelta(seconds=seconds)
        self.fix = Fix(self.now, self.now, 52.2, 21.0, 4.5, speed, 90.0 if speed else None, 10)
        return self.recorder.record_once()


def test_a_moving_device_records_a_point_every_sample_interval(tmp_path):
    r = Recorder(tmp_path)
    assert [r.arrive(second, speed=14.0) for second in range(0, 12)] == [
        True, False, False, False, False, True, False, False, False, False, True, False]
    assert r.queue.pending() == 3
    first = r.queue.oldest(1)[0].item
    assert first.speed_mps == 14.0 and first.heading_deg == 90.0


def test_a_stationary_device_records_a_point_a_minute(tmp_path):
    r = Recorder(tmp_path)
    recorded = [r.arrive(second, speed=0.0) for second in range(0, 130)]
    assert sum(recorded) == 3 and recorded[0] and recorded[int(STATIONARY_SAMPLE_SECONDS)]


def test_nothing_is_recorded_without_a_fresh_fix_or_a_configuration(tmp_path):
    r = Recorder(tmp_path)
    assert r.recorder.record_once() is False  # no fix at all
    r.arrive(0, speed=14.0)
    r.now += timedelta(seconds=10)  # the fix is 10 s old now: lost
    assert r.recorder.record_once() is False
    r.store.current = None
    assert r.arrive(20, speed=14.0) is False
    assert FixedLocationSource(1.0, 2.0).latest_fix() is not None
