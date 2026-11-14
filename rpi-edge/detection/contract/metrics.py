"""Health of the device (POST /api/v1/device/metrics of device-management, ReportMetricsRequest).

  {"metrics": [{"recordedAt", "cpuTemperatureC", "cpuUsagePercent", "ramUsagePercent", "processingFps",
                "queues": {"detectionsPending", "locationsPending", "imagesPending"}, "diskFreeMb", "uptimeSeconds",
                "gps": {"fix", "satellites"}}, ...]}

A measurement is identified by the device and its recordedAt: sending it again overwrites it. The service refuses
the whole batch when one measurement is invalid, so the values are brought into the ranges of the contract here.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from detection.contract.wire import iso_ms, parse_iso_ms, stable_id

MAX_BATCH = 100  # measurements per request (the contract)
CPU_TEMPERATURE_RANGE = (-40.0, 125.0)
PERCENT_RANGE = (0.0, 100.0)
MAX_SATELLITES = 100


class FixType(StrEnum):
    NONE = "NONE"
    FIX_2D = "FIX_2D"
    FIX_3D = "FIX_3D"


def clamp(value: float, low_high: tuple[float, float]) -> float:
    low, high = low_high
    return min(max(value, low), high)


@dataclass(frozen=True)
class QueueLengths:
    """Items waiting on the device to be sent (store-and-forward)."""
    detections_pending: int
    locations_pending: int
    images_pending: int

    def to_document(self) -> dict:
        return {"detectionsPending": self.detections_pending, "locationsPending": self.locations_pending,
                "imagesPending": self.images_pending}

    @classmethod
    def from_document(cls, document: dict) -> "QueueLengths":
        return cls(document["detectionsPending"], document["locationsPending"], document["imagesPending"])


@dataclass(frozen=True)
class GpsState:
    fix: FixType
    satellites: int  # used in the solution

    def to_document(self) -> dict:
        return {"fix": self.fix.value, "satellites": min(max(self.satellites, 0), MAX_SATELLITES)}

    @classmethod
    def from_document(cls, document: dict) -> "GpsState":
        return cls(FixType(document["fix"]), document["satellites"])


@dataclass(frozen=True)
class DeviceMetric:
    recorded_at: datetime
    cpu_temperature_c: float
    cpu_usage_percent: float
    ram_usage_percent: float
    processing_fps: float  # frames analysed per second since the previous measurement
    queues: QueueLengths
    disk_free_mb: int
    uptime_seconds: int
    gps: GpsState

    def to_document(self) -> dict:
        return {
            "recordedAt": iso_ms(self.recorded_at),
            "cpuTemperatureC": round(clamp(self.cpu_temperature_c, CPU_TEMPERATURE_RANGE), 1),
            "cpuUsagePercent": round(clamp(self.cpu_usage_percent, PERCENT_RANGE), 1),
            "ramUsagePercent": round(clamp(self.ram_usage_percent, PERCENT_RANGE), 1),
            "processingFps": round(max(self.processing_fps, 0.0), 2),
            "queues": self.queues.to_document(),
            "diskFreeMb": max(self.disk_free_mb, 0),
            "uptimeSeconds": max(self.uptime_seconds, 0),
            "gps": self.gps.to_document(),
        }

    @classmethod
    def from_document(cls, document: dict) -> "DeviceMetric":
        """The inverse of to_document(), for measurements read back from the outbox."""
        return cls(parse_iso_ms(document["recordedAt"]), document["cpuTemperatureC"], document["cpuUsagePercent"],
                   document["ramUsagePercent"], document["processingFps"],
                   QueueLengths.from_document(document["queues"]), document["diskFreeMb"],
                   document["uptimeSeconds"], GpsState.from_document(document["gps"]))


@dataclass(frozen=True)
class MetricsBatch:
    measurements: tuple[DeviceMetric, ...]

    @property
    def trace_id(self) -> str:
        """Stable for the same measurements, so a resend is the same request in the logs."""
        return stable_id(iso_ms(m.recorded_at) for m in self.measurements)

    def to_document(self) -> dict:
        return {"metrics": [m.to_document() for m in self.measurements]}
