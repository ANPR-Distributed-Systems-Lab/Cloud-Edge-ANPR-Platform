"""What an answer of the platform means for the items that were sent (docs/api/ingest-detections.md, section 4).

The ingest Lambda and the device-management endpoints answer in the same way, so every sender decides the same:

  ACCEPTED   2xx: the platform has them, delete them
  REFUSED    400, 413, 415: a resend cannot succeed; quarantine what the error names
  FORBIDDEN  403: not a device token, a configuration problem; keep the data and wait long
  RETRY      429, 5xx and anything else (404, a wrong URL): keep the data, back off, send the same again
             (401 never gets here: Api renewed the token and retried once)
"""
from enum import Enum

REFUSED_STATUSES = (400, 413, 415)


class Outcome(Enum):
    ACCEPTED = "accepted"
    REFUSED = "refused"
    FORBIDDEN = "forbidden"
    RETRY = "retry"


def outcome_of(status: int) -> Outcome:
    if 200 <= status < 300:
        return Outcome.ACCEPTED
    if status in REFUSED_STATUSES:
        return Outcome.REFUSED
    if status == 403:
        return Outcome.FORBIDDEN
    return Outcome.RETRY


def retry_after(headers: dict) -> float | None:
    """Seconds from the Retry-After header (lower-case names), when the platform asks for a pause."""
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
