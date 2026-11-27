"""The measured faults of the detection mode (common/fault_catalog.py), read at each refresh of the screen; the
reported ones come from the FaultBoard of the threads that see them (cloud/, delivery/, loop.py).

  refused items       rows the platform refused (400, 413, 415) since the mode started; older ones stay in the
                      quarantine for diagnosis (up to 30 days, the device cannot clear them) and do not count
  GPS not configured  neither GPS_DEVICE nor GPS_FIXED_LOCATION is set: no frame gets a position, none is read
  GPS module silent   GPS_DEVICE is set but no sentence arrived for GPS_SILENT_SECONDS (wiring, power, the port)
  clock wrong by      the clock of the device is off GPS time: the platform refuses what is stamped with it
  SD card low         under SD_LOW_FREE_MB free: the queues, the photos and the models live there
  the Pi              power too low, CPU throttled, CPU hot (common/fault_catalog.system_faults)
"""
import time
from collections.abc import Callable
from datetime import datetime

from common import fault_catalog as kinds
from common.fault_catalog import system_faults
from common.faults import Fault
from detection.delivery.queues import Queues
from detection.gps.source import LocationSource
from detection.gps.tracker import CLOCK_SKEW_WARNING_SECONDS

SD_LOW_FREE_MB = 1000
GPS_SILENT_SECONDS = 60.0  # the module sends several sentences a second; a minute of silence is not a glitch


class MeasuredFaults:
    """Keeps what a measured fault needs from one refresh to the next: the quarantine at the start of the mode, and
    since when the GPS module is silent."""

    def __init__(self, queues: Queues, gps: LocationSource, gps_kind: str,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.queues = queues
        self.gps = gps
        self.gps_kind = gps_kind  # module, fixed or none (detection/main.py)
        self.clock = clock
        self._quarantined_at_start = self.quarantined()
        self._gps_silent_since: float | None = None

    def quarantined(self) -> int:
        q = self.queues
        return sum(queue.quarantined() for queue in (q.detections, q.locations, q.metrics, q.images))

    def read(self, now: datetime, sd_free_mb: int | None, power: dict | None, temp_c: float | None) -> list[Fault]:
        faults = []
        refused = self._refused_since_start()
        if refused > 0:
            faults.append(kinds.REFUSED_ITEMS.fault(str(refused)))
        faults += self._gps(now)
        skew = self.gps.clock_skew_seconds()
        if skew is not None and abs(skew) >= CLOCK_SKEW_WARNING_SECONDS:
            faults.append(kinds.CLOCK_WRONG.fault(f"{abs(skew):.0f}s"))
        if sd_free_mb is not None and sd_free_mb < SD_LOW_FREE_MB:
            faults.append(kinds.SD_LOW.fault(f"{sd_free_mb}MB"))
        return faults + system_faults(power, temp_c)

    def _refused_since_start(self) -> int:
        quarantined = self.quarantined()
        # The retention prunes old rows: the count from the start goes down with them, so new ones still count.
        self._quarantined_at_start = min(self._quarantined_at_start, quarantined)
        return quarantined - self._quarantined_at_start

    def _gps(self, now: datetime) -> list[Fault]:
        if self.gps_kind == "none":
            return [kinds.GPS_NOT_CONFIGURED.fault()]
        if self.gps_kind != "module" or self.gps.status(now).receiving:
            self._gps_silent_since = None
            return []
        if self._gps_silent_since is None:
            self._gps_silent_since = self.clock()
        return [kinds.GPS_SILENT.fault()] if self.clock() - self._gps_silent_since >= GPS_SILENT_SECONDS else []
