"""NMEA 0183 sentences of a GNSS module, parsed into dataclasses. Only the four kinds the device needs:

  RMC  time, date, status (A valid / V not), position, speed over ground in knots, course
  GGA  fix quality (0 none), satellites used, HDOP
  GSA  fix type (1 none, 2 2D, 3 3D), one per constellation
  GSV  satellites in view, per constellation (the talker: GP GPS, GL GLONASS, GA Galileo, GB BeiDou)

Everything else, and anything with a wrong checksum or a missing field the sentence needs, parses to None: a module
sends noise now and then, and a garbled sentence must never become a position.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import reduce
from operator import xor

KNOTS_TO_MPS = 0.514444


@dataclass(frozen=True)
class Rmc:
    time: datetime  # UTC, from the time and date of the sentence
    valid: bool  # status A
    lat: float | None  # WGS84 decimal degrees, None without a fix
    lon: float | None
    speed_mps: float | None
    course_deg: float | None


@dataclass(frozen=True)
class Gga:
    quality: int  # 0 no fix, 1 GPS, 2 differential, ...
    satellites_used: int
    hdop: float | None


@dataclass(frozen=True)
class Gsa:
    fix_type: int  # 1 no fix, 2 2D, 3 3D


@dataclass(frozen=True)
class Gsv:
    talker: str  # GP, GL, GA, GB, ...
    satellites_in_view: int


Sentence = Rmc | Gga | Gsa | Gsv


def checksum_ok(line: str) -> bool:
    """The XOR of the characters between $ and * must equal the two hex digits after the *."""
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, given = line[1:].partition("*")
    return len(given) >= 2 and given[:2].upper() == f"{reduce(xor, map(ord, body), 0):02X}"


def parse(line: str) -> Sentence | None:
    """One line of the module to a sentence of a kind the device uses; None for anything else or anything broken."""
    line = line.strip()
    if not checksum_ok(line):
        return None
    fields = line[1:].partition("*")[0].split(",")
    talker, kind = fields[0][:-3], fields[0][-3:]
    try:
        match kind:
            case "RMC":
                return _rmc(fields)
            case "GGA":
                return _gga(fields)
            case "GSA":
                return Gsa(int(fields[2]))
            case "GSV":
                return Gsv(talker, int(fields[3]))
    except (ValueError, IndexError):
        return None
    return None


def _rmc(fields: list[str]) -> Rmc:
    valid = fields[2] == "A"
    return Rmc(
        time=_utc(fields[1], fields[9]),
        valid=valid,
        lat=_coordinate(fields[3], fields[4], digits=2) if valid else None,
        lon=_coordinate(fields[5], fields[6], digits=3) if valid else None,
        speed_mps=float(fields[7]) * KNOTS_TO_MPS if valid and fields[7] else None,
        course_deg=float(fields[8]) if valid and fields[8] else None,
    )


def _gga(fields: list[str]) -> Gga:
    return Gga(int(fields[6]), int(fields[7] or 0), float(fields[8]) if fields[8] else None)


def _utc(time: str, date: str) -> datetime:
    """hhmmss.sss and ddmmyy; the module reports 1980-01-06 until it has received the time from a satellite."""
    whole = datetime.strptime(date + time[:6], "%d%m%y%H%M%S").replace(tzinfo=UTC)
    return whole.replace(microsecond=round(float("0" + time[6:]) * 1_000_000)) if len(time) > 6 else whole


def _coordinate(value: str, hemisphere: str, digits: int) -> float:
    """ddmm.mmmm (latitude) or dddmm.mmmm (longitude) and N/S/E/W to signed decimal degrees."""
    degrees = float(value[:digits]) + float(value[digits:]) / 60
    return -degrees if hemisphere in ("S", "W") else degrees
