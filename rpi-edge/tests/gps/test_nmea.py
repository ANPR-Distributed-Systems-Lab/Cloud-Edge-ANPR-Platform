"""NMEA sentences as the LC76G sends them (checksums computed; positions are the examples of the contract)."""
from datetime import UTC, datetime
from functools import reduce
from operator import xor

import pytest

from detection.gps import nmea


def sentence(body: str) -> str:
    return f"${body}*{reduce(xor, map(ord, body), 0):02X}"


RMC = sentence("GNRMC,021945.250,A,5213.78056,N,02100.73374,E,13.50,87.40,131126,,,A,V")
RMC_NO_FIX = sentence("GNRMC,001049.012,V,,,,,,,060180,,,N,V")
GGA = sentence("GNGGA,021945.000,5213.78056,N,02100.73374,E,1,13,0.90,244.457,M,42.238,M,,")
GGA_NO_FIX = sentence("GNGGA,001050.012,,,,,0,00,99.99,,M,,M,,")
GSA = sentence("GNGSA,A,3,32,03,02,17,28,19,,,,,,,1.77,0.90,1.52,1")
GSV = sentence("GPGSV,3,1,09,32,17,046,34,03,68,283,42,02,48,148,18,17,38,288,43,1")


def test_the_checksum_is_checked():
    assert nmea.checksum_ok(RMC)
    assert not nmea.checksum_ok(RMC[:-2] + "00")
    assert not nmea.checksum_ok("$GNRMC,no checksum")
    assert not nmea.checksum_ok("GNRMC*00")


def test_a_valid_rmc_gives_the_time_position_speed_and_course():
    rmc = nmea.parse(RMC)
    assert rmc.valid and rmc.time == datetime(2026, 11, 13, 2, 19, 45, 250_000, tzinfo=UTC)
    assert rmc.lat == pytest.approx(52 + 13.78056 / 60)
    assert rmc.lon == pytest.approx(21 + 0.73374 / 60)
    assert rmc.speed_mps == pytest.approx(13.50 * 0.514444)
    assert rmc.course_deg == 87.40


def test_southern_and_western_hemispheres_are_negative():
    rmc = nmea.parse(sentence("GNRMC,021945.000,A,3352.00000,S,15112.00000,W,0.0,0.0,131126,,,A,V"))
    assert rmc.lat == pytest.approx(-(33 + 52 / 60)) and rmc.lon == pytest.approx(-(151 + 12 / 60))


def test_an_rmc_without_a_fix_has_no_position():
    rmc = nmea.parse(RMC_NO_FIX)
    assert not rmc.valid and rmc.lat is None and rmc.lon is None and rmc.speed_mps is None


def test_gga_gsa_and_gsv_give_quality_fix_type_and_satellites():
    assert nmea.parse(GGA) == nmea.Gga(quality=1, satellites_used=13, hdop=0.90)
    assert nmea.parse(GGA_NO_FIX) == nmea.Gga(quality=0, satellites_used=0, hdop=99.99)
    assert nmea.parse(GSA) == nmea.Gsa(fix_type=3)
    assert nmea.parse(GSV) == nmea.Gsv(talker="GP", satellites_in_view=9)


@pytest.mark.parametrize("line", [
    "",
    "garbage",
    sentence("GNVTG,357.57,T,,M,0.06,N,0.12,K,A"),  # a kind the device does not use
    sentence("GNRMC,021945.250,A,5213.78056"),  # truncated
    sentence("GNRMC,,A,,,,,,,,,,A,V"),  # valid status without a time
])
def test_anything_else_or_broken_is_ignored(line):
    assert nmea.parse(line) is None
