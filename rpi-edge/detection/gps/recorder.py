"""Records the track of the device: a point of the GNSS module every intervals.locationSampleSeconds while it moves.

The track goes to its own queue and stream (POST /api/v1/ingest/device-locations), independent of the detections.
While the device stands still, one point every STATIONARY_SAMPLE_SECONDS is enough to show where it is and that it
is alive. Without a fresh fix nothing is recorded: the platform refuses a point without a position.
"""
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from detection.config.store import ConfigurationStore
from detection.contract.locations import LocationPoint
from detection.contract.wire import uuid7
from detection.delivery.queue import PersistentQueue
from detection.gps.source import LocationSource
from detection.gps.tracker import MOVING_SPEED_MPS, Fix

STATIONARY_SAMPLE_SECONDS = 60.0
FRESH_FIX_SECONDS = 5.0  # an older latest fix means the fix is lost
POLL_SECONDS = 1.0


class LocationRecorder:
    def __init__(self, source: LocationSource, queue: PersistentQueue[LocationPoint],
                 configuration: ConfigurationStore, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.source = source
        self.queue = queue
        self.configuration = configuration
        self.clock = clock
        self._last: Fix | None = None  # the fix of the last recorded point

    def run(self, stop: threading.Event) -> None:
        while not stop.wait(POLL_SECONDS):
            self.record_once()

    def record_once(self) -> bool:
        """Records the latest fix when its time has come. Returns whether a point was recorded."""
        configuration = self.configuration.current
        fix = self.source.latest_fix()
        if configuration is None or fix is None:
            return False
        if not self._is_due(fix, configuration.intervals.location_sample_seconds):
            return False
        self.queue.add([LocationPoint(uuid7(), fix.recorded_at, fix.lat, fix.lon, fix.accuracy_m, fix.speed_mps,
                                      fix.heading_deg)])
        self._last = fix
        return True

    def _is_due(self, fix: Fix, sample_seconds: float) -> bool:
        if (self.clock() - fix.received_at).total_seconds() > FRESH_FIX_SECONDS:
            return False
        if self._last is None:
            return True
        if fix.received_at <= self._last.received_at:  # the same fix again
            return False
        moving = fix.speed_mps is not None and fix.speed_mps >= MOVING_SPEED_MPS
        interval = sample_seconds if moving else STATIONARY_SAMPLE_SECONDS
        return (fix.received_at - self._last.received_at).total_seconds() >= interval
