"""Where the device is: the position attached to a detection, and the track of positions sent on its own.

  detection location   {"lat", "lon", "accuracyM", "fixAgeMs"}   in every detection (docs/api/ingest-detections.md)
  device location      POST /api/v1/ingest/device-locations      (docs/api/ingest-device-locations.md)
                       {"batchId": "...", "locations": [{"locationId", "recordedAt", "lat", "lon", "accuracyM",
                                                         "speedMps", "headingDeg"}, ...]}

Coordinates are WGS84 decimal degrees. They are personal data: they are never logged.
"""
from dataclasses import dataclass
from datetime import datetime

from detection.contract.wire import iso_ms, parse_iso_ms, stable_id

COORDINATE_DECIMALS = 6  # about 0.1 m
ACCURACY_DECIMALS = 1
SPEED_DECIMALS = 2
HEADING_DECIMALS = 1
FULL_CIRCLE_DEGREES = 360.0


@dataclass(frozen=True)
class Location:
    """The position of a detection: the latest fix at the moment its frame was captured."""
    lat: float
    lon: float
    accuracy_m: float | None  # horizontal accuracy estimate
    fix_age_ms: int  # age of the fix when the frame was captured

    def to_document(self) -> dict:
        document = {"lat": round(self.lat, COORDINATE_DECIMALS), "lon": round(self.lon, COORDINATE_DECIMALS),
                    "fixAgeMs": self.fix_age_ms}
        if self.accuracy_m is not None:
            document["accuracyM"] = round(self.accuracy_m, ACCURACY_DECIMALS)
        return document

    @classmethod
    def from_document(cls, document: dict) -> "Location":
        """The inverse of to_document(), for detections read back from the outbox."""
        return cls(document["lat"], document["lon"], document.get("accuracyM"), document["fixAgeMs"])


@dataclass(frozen=True)
class LocationPoint:
    """One point of the track of the device."""
    location_id: str  # uuid7, the idempotency key of the point
    recorded_at: datetime  # time of the GPS fix, UTC
    lat: float
    lon: float
    accuracy_m: float | None
    speed_mps: float | None
    heading_deg: float | None  # course over ground; None when stationary

    def to_document(self) -> dict:
        document = {"locationId": self.location_id, "recordedAt": iso_ms(self.recorded_at),
                    "lat": round(self.lat, COORDINATE_DECIMALS), "lon": round(self.lon, COORDINATE_DECIMALS)}
        if self.accuracy_m is not None:
            document["accuracyM"] = round(self.accuracy_m, ACCURACY_DECIMALS)
        if self.speed_mps is not None:
            document["speedMps"] = round(self.speed_mps, SPEED_DECIMALS)
        if self.heading_deg is not None:  # the contract wants 0 up to, not including, 360
            document["headingDeg"] = round(self.heading_deg, HEADING_DECIMALS) % FULL_CIRCLE_DEGREES
        return document

    @classmethod
    def from_document(cls, document: dict) -> "LocationPoint":
        """The inverse of to_document(), for points read back from the outbox."""
        return cls(document["locationId"], parse_iso_ms(document["recordedAt"]), document["lat"], document["lon"],
                   document.get("accuracyM"), document.get("speedMps"), document.get("headingDeg"))


@dataclass(frozen=True)
class LocationBatch:
    points: tuple[LocationPoint, ...]

    @property
    def batch_id(self) -> str:
        return stable_id(p.location_id for p in self.points)

    @property
    def trace_id(self) -> str:
        return self.batch_id

    def to_document(self) -> dict:
        return {"batchId": self.batch_id, "locations": [p.to_document() for p in self.points]}
