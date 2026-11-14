"""Where the position of the device comes from: the GNSS module, a fixed position for development, or nothing.

All three answer the same questions (LocationSource), so the rest of the mode never asks which one it has.
"""
from datetime import UTC, datetime, timedelta
from typing import Protocol

from detection.contract.locations import Location
from detection.contract.metrics import FixType
from detection.gps.tracker import Fix, GpsStatus

MAX_FIX_AGE_SECONDS = 30.0  # an older fix is not a position of the device any more: it moves
FIXED_ACCURACY_M = 5.0


class LocationSource(Protocol):
    def fix_at(self, moment: datetime) -> Fix | None:
        """The latest fix received at or before `moment`."""

    def latest_fix(self) -> Fix | None: ...

    def status(self, now: datetime) -> GpsStatus: ...


def locate(source: LocationSource, captured_at: datetime) -> Location | None:
    """The position for a frame captured at captured_at, or None when there is no fix within MAX_FIX_AGE_SECONDS of
    it. The platform requires a position with every detection, and the position at that moment cannot be recovered
    later, so a frame without one is not read at all (rejection no_location)."""
    fix = source.fix_at(captured_at)
    if fix is None or (captured_at - fix.received_at) > timedelta(seconds=MAX_FIX_AGE_SECONDS):
        return None
    return fix.location_at(captured_at)


class NoLocationSource:
    """No GNSS module configured (GPS_DEVICE and GPS_FIXED_LOCATION unset): there is never a position."""

    def fix_at(self, moment: datetime) -> Fix | None:
        return None

    def latest_fix(self) -> Fix | None:
        return None

    def status(self, now: datetime) -> GpsStatus:
        return GpsStatus(receiving=False, fix=FixType.NONE, satellites_used=0, satellites_in_view=0)


class FixedLocationSource:
    """A position that never changes (GPS_FIXED_LOCATION), for development and for replaying recorded frames."""

    def __init__(self, lat: float, lon: float) -> None:
        self.lat, self.lon = lat, lon

    def fix_at(self, moment: datetime) -> Fix | None:
        return self._fix(moment)

    def latest_fix(self) -> Fix | None:
        return self._fix(datetime.now(UTC))

    def status(self, now: datetime) -> GpsStatus:
        return GpsStatus(receiving=True, fix=FixType.FIX_3D, satellites_used=0, satellites_in_view=0)

    def _fix(self, moment: datetime) -> Fix:
        return Fix(received_at=moment, recorded_at=moment, lat=self.lat, lon=self.lon, accuracy_m=FIXED_ACCURACY_M,
                   speed_mps=0.0, heading_deg=None, satellites_used=None)
