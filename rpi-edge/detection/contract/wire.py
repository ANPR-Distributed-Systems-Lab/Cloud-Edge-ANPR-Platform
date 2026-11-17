"""What every document of the platform shares: identifiers, timestamps and what a batch request must offer."""
import os
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

# Fixed namespace of batch ids, so the same set of items always gets the same id (a resend reuses it).
BATCH_NAMESPACE = uuid.UUID("6f1d3a52-6a0e-4c4e-9a43-0c5b7d1e2f30")
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def uuid7() -> str:
    """Time-ordered UUID (RFC 9562, version 7): 48 bits of Unix milliseconds, then random bits.
    Python gets uuid.uuid7() only in 3.14; the Pi runs Debian trixie's 3.13."""
    value = (time.time_ns() // 1_000_000) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC variant
    return str(uuid.UUID(int=value))


def stable_id(parts: Iterable[str]) -> str:
    """The same parts always give the same UUID (v5), so a resend of a batch needs no stored id."""
    return str(uuid.uuid5(BATCH_NAMESPACE, ",".join(parts)))


def iso_ms(moment: datetime) -> str:
    """RFC 3339 UTC with milliseconds and Z, as the ingest contracts require."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_iso_ms(text: str) -> datetime:
    """The inverse of iso_ms()."""
    return datetime.strptime(text, TIMESTAMP_FORMAT).replace(tzinfo=UTC)


class Request(Protocol):
    """A batch request to the platform: its JSON body, and the id that is also its X-Trace-Id."""

    @property
    def trace_id(self) -> str: ...

    def to_document(self) -> dict: ...
