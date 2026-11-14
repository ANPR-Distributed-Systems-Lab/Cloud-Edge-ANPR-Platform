from datetime import UTC, datetime, timedelta

import pytest
from test_nmea import GGA, GGA_NO_FIX, GSA, GSV, RMC, RMC_NO_FIX, sentence

from detection.contract.metrics import FixType
from detection.gps.source import FixedLocationSource, NoLocationSource, locate
from detection.gps.tracker import ACCURACY_M_PER_HDOP, GpsTracker

T0 = datetime(2026, 11, 13, 2, 19, 45, 500_000, tzinfo=UTC)


def rmc_at(seconds: int, speed_knots: float = 13.5):
    """An RMC of the epoch `seconds` after T0 (device clock and GPS clock agree)."""
    moment = T0 + timedelta(seconds=seconds)
    body = f"GNRMC,{moment:%H%M%S}.000,A,5213.78056,N,02100.73374,E,{speed_knots},87.4,{moment:%d%m%y},,,A,V"
    return sentence(body), moment


def test_a_fix_carries_the_position_accuracy_speed_and_heading():
    tracker = GpsTracker()
    tracker.feed(GGA, T0)
    tracker.feed(RMC, T0)
    fix = tracker.latest_fix()
    assert fix.lat == pytest.approx(52.229676, abs=1e-6) and fix.lon == pytest.approx(21.012229, abs=1e-6)
    assert fix.accuracy_m == pytest.approx(0.90 * ACCURACY_M_PER_HDOP)
    assert fix.speed_mps == pytest.approx(6.94, abs=0.01) and fix.heading_deg == 87.4
    assert fix.satellites_used == 13 and fix.received_at == T0


def test_a_stationary_fix_has_no_heading():
    tracker = GpsTracker()
    line, moment = rmc_at(0, speed_knots=0.04)
    tracker.feed(line, moment)
    assert tracker.latest_fix().heading_deg is None


def test_a_fix_without_a_position_is_not_a_fix():
    tracker = GpsTracker()
    tracker.feed(RMC_NO_FIX, T0)
    tracker.feed(GGA_NO_FIX, T0)
    assert tracker.latest_fix() is None


def test_a_frame_gets_the_fix_that_was_current_when_it_was_captured():
    tracker = GpsTracker()
    for second in range(3):
        line, moment = rmc_at(second)
        tracker.feed(line, moment + timedelta(milliseconds=200))
    captured = T0 + timedelta(seconds=1, milliseconds=500)
    fix = tracker.fix_at(captured)
    assert fix.received_at == T0 + timedelta(seconds=1, milliseconds=200)
    assert fix.location_at(captured).fix_age_ms == 300
    assert tracker.fix_at(T0) is None  # captured before the first fix arrived


def test_old_fixes_are_forgotten():
    tracker = GpsTracker()
    for second in (0, 1, 100):
        line, moment = rmc_at(second)
        tracker.feed(line, moment)
    assert tracker.fix_at(T0 + timedelta(seconds=2)) is None
    assert tracker.fix_at(T0 + timedelta(seconds=100)) is not None


def test_the_status_follows_the_module():
    tracker = GpsTracker()
    assert not tracker.status(T0).receiving
    tracker.feed(GSV, T0)
    tracker.feed(GGA, T0)
    tracker.feed(GSA, T0)
    status = tracker.status(T0)
    assert status.receiving and status.fix is FixType.NONE and status.satellites_in_view == 9  # no position yet
    tracker.feed(RMC, T0)
    status = tracker.status(T0 + timedelta(seconds=1))
    assert status.fix is FixType.FIX_3D and status.satellites_used == 13
    assert tracker.status(T0 + timedelta(seconds=4)).fix is FixType.NONE  # the fix is gone
    assert not tracker.status(T0 + timedelta(seconds=10)).receiving  # the module is silent


def test_garbled_lines_change_nothing():
    tracker = GpsTracker()
    tracker.feed("$GNRMC,021945.250,A,5213.78056,N,02100.73374,E,13.50,87.40,131126,,,A,V*00", T0)
    tracker.feed("noise", T0)
    assert tracker.latest_fix() is None and not tracker.status(T0).receiving


def test_a_wrong_device_clock_is_reported(capsys):
    tracker = GpsTracker()
    line, moment = rmc_at(0)
    tracker.feed(line, moment + timedelta(hours=2))
    assert "clock_skew" in capsys.readouterr().out


def test_locate_gives_a_position_only_for_a_recent_fix():
    tracker = GpsTracker()
    tracker.feed(RMC, T0)
    assert locate(tracker, T0 + timedelta(seconds=1)).fix_age_ms == 1000
    assert locate(tracker, T0 + timedelta(seconds=31)) is None  # too old to be the position of a moving car
    assert locate(tracker, T0 - timedelta(seconds=1)) is None


def test_the_other_sources_answer_the_same_questions():
    assert locate(NoLocationSource(), T0) is None
    location = locate(FixedLocationSource(52.229676, 21.012229), T0)
    assert (location.lat, location.lon, location.fix_age_ms) == (52.229676, 21.012229, 0)
    assert FixedLocationSource(1.0, 2.0).status(T0).fix is FixType.FIX_3D
    assert NoLocationSource().status(T0).receiving is False
