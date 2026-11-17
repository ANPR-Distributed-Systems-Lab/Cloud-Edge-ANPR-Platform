"""Which sent detections are alerts: the plate is on the alert list of the device's owner.

Only accepted detections are matched (after the send rule and the cooldown), so a passing car raises one alert,
from a reading good enough to be sent. The list holds plate numbers (personal data): it is kept in memory only,
never written to disk or logged.
"""
import threading

from detection.contract.alerts import Alert, AlertList


class AlertWatch:
    """The current alert list, replaced as a whole by the poller (cloud/alert_poll.py)."""

    def __init__(self) -> None:
        self._by_plate: dict[str, Alert] = {}
        self._lock = threading.Lock()
        self.etag: str | None = None
        self.loaded = False  # False until the first list arrived: the device cannot tell "no alerts" yet

    def replace(self, alerts: AlertList, etag: str | None) -> None:
        by_plate = {alert.plate: alert for alert in alerts.items}
        with self._lock:
            self._by_plate, self.etag, self.loaded = by_plate, etag, True

    def match(self, plate: str) -> Alert | None:
        return self._by_plate.get(plate)

    def __len__(self) -> int:
        return len(self._by_plate)
