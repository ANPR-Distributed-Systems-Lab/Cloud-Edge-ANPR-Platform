"""What the device knows about its position: the fixes the module reported, and the state of the module.

GpsTracker is fed the sentences one by one (gps/serial_reader.py) and answers from memory. It keeps the fixes of the
last HISTORY_SECONDS so that a frame is given the fix that was current when it was captured, not the newest one.
Times of reception are the clock of the device, the same clock that stamps the frames; the time inside a sentence is
GPS time and is only compared with it, to tell when the clock of the device is wrong.
"""
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from common.jsonlog import log
from detection.contract.locations import Location
from detection.contract.metrics import FixType
from detection.gps import nmea

HISTORY_SECONDS = 60
# Below this speed the device counts as stationary: the course over ground is noise (no heading is reported) and the
# track is sparse. A stationary antenna near a window shows speeds up to 0.7 m/s from reflections.
MOVING_SPEED_MPS = 2.0  # 7 km/h
ACCURACY_M_PER_HDOP = 5.0  # horizontal accuracy ~ HDOP x the typical range error of a consumer receiver
SILENCE_SECONDS = 5.0  # no sentence for this long: the module is not talking
FIX_LOST_SECONDS = 3.0  # no valid position for this long: the fix is gone
CLOCK_SKEW_WARNING_SECONDS = 5.0
CLOCK_SKEW_LOG_INTERVAL_SECONDS = 60.0
FIX_TYPES = {1: FixType.NONE, 2: FixType.FIX_2D, 3: FixType.FIX_3D}


@dataclass(frozen=True)
class Fix:
    """One position of the module."""
    received_at: datetime  # device clock, UTC, when it arrived: the time the fix is valid for on the frames
    recorded_at: datetime  # GPS clock, UTC: the time of the fix for the track of the device
    lat: float
    lon: float
    accuracy_m: float | None
    speed_mps: float | None
    heading_deg: float | None  # None when stationary
    satellites_used: int | None

    def location_at(self, captured_at: datetime) -> Location:
        """The position of a frame captured at captured_at, with the age of this fix at that moment."""
        age_ms = max(0, int((captured_at - self.received_at).total_seconds() * 1000))
        return Location(self.lat, self.lon, self.accuracy_m, age_ms)


@dataclass(frozen=True)
class GpsStatus:
    receiving: bool  # sentences arrive at all (the module is connected and powered)
    fix: FixType
    satellites_used: int
    satellites_in_view: int


class GpsTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fixes: deque[Fix] = deque()
        self._gga: nmea.Gga | None = None
        self._fix_type = FixType.NONE
        self._in_view: dict[str, int] = {}
        self._last_sentence_at: datetime | None = None
        self._last_skew_log_at: datetime | None = None

    def feed(self, line: str, now: datetime) -> None:
        """One line from the module, received at `now`; anything unusable is ignored."""
        sentence = nmea.parse(line)
        if sentence is None:
            return
        with self._lock:
            self._last_sentence_at = now
            match sentence:
                case nmea.Rmc(valid=True):
                    self._add_fix(sentence, now)
                case nmea.Gga():
                    self._gga = sentence
                case nmea.Gsa():
                    self._fix_type = FIX_TYPES.get(sentence.fix_type, FixType.NONE)
                case nmea.Gsv():
                    self._in_view[sentence.talker] = sentence.satellites_in_view

    def fix_at(self, moment: datetime) -> Fix | None:
        """The latest fix received at or before `moment`: the fix a frame captured then should carry."""
        with self._lock:
            return next((f for f in reversed(self._fixes) if f.received_at <= moment), None)

    def latest_fix(self) -> Fix | None:
        with self._lock:
            return self._fixes[-1] if self._fixes else None

    def status(self, now: datetime) -> GpsStatus:
        with self._lock:
            receiving = self._within(self._last_sentence_at, now, SILENCE_SECONDS)
            has_fix = bool(self._fixes) and self._within(self._fixes[-1].received_at, now, FIX_LOST_SECONDS)
            fix = self._fix_type if has_fix else FixType.NONE
            used = self._gga.satellites_used if self._gga and has_fix else 0
            return GpsStatus(receiving, fix, used, sum(self._in_view.values()))

    def _add_fix(self, rmc: nmea.Rmc, now: datetime) -> None:
        gga = self._gga if self._gga and self._gga.quality > 0 else None
        moving = rmc.speed_mps is not None and rmc.speed_mps >= MOVING_SPEED_MPS
        self._fixes.append(Fix(
            received_at=now,
            recorded_at=rmc.time,
            lat=rmc.lat,
            lon=rmc.lon,
            accuracy_m=gga.hdop * ACCURACY_M_PER_HDOP if gga and gga.hdop is not None else None,
            speed_mps=rmc.speed_mps,
            heading_deg=rmc.course_deg if moving else None,
            satellites_used=gga.satellites_used if gga else None,
        ))
        cutoff = now - timedelta(seconds=HISTORY_SECONDS)
        while self._fixes[0].received_at < cutoff:
            self._fixes.popleft()
        self._warn_about_clock(rmc.time, now)

    def _warn_about_clock(self, gps_time: datetime, now: datetime) -> None:
        """Detections are stamped with the clock of the device (there is no RTC): say so when it is wrong."""
        skew = (now - gps_time).total_seconds()
        if abs(skew) < CLOCK_SKEW_WARNING_SECONDS:
            return
        if self._last_skew_log_at and (now - self._last_skew_log_at).total_seconds() < CLOCK_SKEW_LOG_INTERVAL_SECONDS:
            return
        self._last_skew_log_at = now
        log("clock_skew", level="warning", skew_seconds=round(skew, 1),
            hint="the clock of the device differs from GPS time: detections carry the wrong detectedAt")

    @staticmethod
    def _within(moment: datetime | None, now: datetime, seconds: float) -> bool:
        return moment is not None and (now - moment).total_seconds() <= seconds
