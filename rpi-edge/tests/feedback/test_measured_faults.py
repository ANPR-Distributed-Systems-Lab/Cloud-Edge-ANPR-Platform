"""The faults the detection mode reads at each refresh: the quarantine, the GPS, the clock, the SD card, the Pi."""
from datetime import UTC, datetime

from detection.contract.metrics import FixType
from detection.delivery.queues import Queues
from detection.feedback.faults import GPS_SILENT_SECONDS, SD_LOW_FREE_MB, MeasuredFaults
from detection.gps.tracker import GpsStatus

NOW = datetime(2026, 11, 28, tzinfo=UTC)


class FakeGps:
    def __init__(self, receiving=True, skew=None):
        self.receiving, self.skew = receiving, skew

    def status(self, now):
        return GpsStatus(self.receiving, FixType.FIX_3D if self.receiving else FixType.NONE, 0, 0)

    def clock_skew_seconds(self):
        return self.skew


def codes(measured, sd_free_mb=10_000, power=None, temp_c=50.0):
    return [f.code for f in measured.read(NOW, sd_free_mb, power, temp_c)]


def test_a_working_device_has_none(tmp_path):
    assert codes(MeasuredFaults(Queues.open(tmp_path), FakeGps(skew=0.4), "module")) == []


def test_without_a_gps_source_nothing_is_read(tmp_path):
    assert codes(MeasuredFaults(Queues.open(tmp_path), FakeGps(receiving=False), "none")) == ["gps_not_configured"]


def test_a_module_silent_for_a_minute(tmp_path):
    clock = [0.0]
    gps = FakeGps(receiving=False)
    measured = MeasuredFaults(Queues.open(tmp_path), gps, "module", clock=lambda: clock[0])
    assert codes(measured) == []
    clock[0] += GPS_SILENT_SECONDS
    assert codes(measured) == ["gps_silent"]
    gps.receiving = True
    assert codes(measured) == []


def test_a_wrong_clock_the_sd_card_and_the_pi(tmp_path):
    measured = MeasuredFaults(Queues.open(tmp_path), FakeGps(skew=-12.3), "module")
    faults = measured.read(NOW, SD_LOW_FREE_MB - 1, {"undervoltage_now": True}, 50.0)
    assert [f.text for f in faults] == ["clock wrong by 12s", "SD card low 999MB", "power too low"]
