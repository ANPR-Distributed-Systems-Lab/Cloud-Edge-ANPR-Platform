"""The alert list of the device's owner (GET /api/v1/alerts of operations-service, AlertPage).

A device gets every alert of its owner in one response and polls it with If-None-Match. Only what the device
needs is read; the other fields of AlertResponse (createdAt, lastDetectedAt, version) are ignored. Plate numbers
are upper-case letters and digits without spaces, the same form as the OCR reads them.
"""
from dataclasses import dataclass

from detection.contract.configuration import UUID
from detection.contract.parsing import array, matching, parse

PLATE = r"[A-Z0-9]{2,10}"


@dataclass(frozen=True)
class Alert:
    alert_id: str = matching(UUID)
    plate: str = matching(PLATE)
    alert_text: str | None = matching(r"(?s).*")  # shown to the driver; null when the owner wrote none


@dataclass(frozen=True)
class AlertList:
    items: tuple[Alert, ...] = array(min_items=0)

    @classmethod
    def from_document(cls, document) -> "AlertList":
        """Raises ContractError naming every alert that breaks the contract."""
        return parse(cls, document)
