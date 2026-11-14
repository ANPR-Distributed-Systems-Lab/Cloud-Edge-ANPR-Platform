"""The four queues of the device and the streams that empty them: what is stored where, and where it is sent.

  queue       stored (SD card, /state/outbox/<name>.sqlite3)   sent to
  detections  DetectionEvent, 30 days                           POST /api/v1/ingest/detections
  locations   LocationPoint, 30 days                            POST /api/v1/ingest/device-locations
  metrics     DeviceMetric, 6 days (older ones are refused)     POST /api/v1/device/metrics
  images      ImageJob (the JPEG is a file beside the queue)    POST /api/v1/images/presigned-urls, then PUT to S3
"""
from dataclasses import dataclass
from pathlib import Path

from detection.config.environment import Environment
from detection.contract.ingest import DetectionBatch, DetectionEvent
from detection.contract.locations import LocationBatch, LocationPoint
from detection.contract.metrics import MAX_BATCH as MAX_METRICS_BATCH
from detection.contract.metrics import DeviceMetric, MetricsBatch
from detection.contract.wire import iso_ms
from detection.delivery.queue import ItemCodec, PersistentQueue
from detection.delivery.sender import Stream
from detection.delivery.uploads import IMAGE_CODEC, ImageJob

DETECTION_CODEC = ItemCodec(DetectionEvent.to_document, DetectionEvent.from_document, lambda e: e.detection_id,
                            lambda e: e.detected_at.timestamp())
LOCATION_CODEC = ItemCodec(LocationPoint.to_document, LocationPoint.from_document, lambda p: p.location_id,
                           lambda p: p.recorded_at.timestamp())
METRIC_CODEC = ItemCodec(DeviceMetric.to_document, DeviceMetric.from_document, lambda m: iso_ms(m.recorded_at),
                         lambda m: m.recorded_at.timestamp())

# The platform refuses detections and points older than 30 days, and measurements older than 7 days.
DETECTION_RETENTION_DAYS, DETECTION_MAX_ROWS = 30, 100_000
LOCATION_RETENTION_DAYS, LOCATION_MAX_ROWS = 30, 200_000
METRIC_RETENTION_DAYS, METRIC_MAX_ROWS = 6, 20_000
IMAGE_RETENTION_DAYS, IMAGE_MAX_ROWS = 30, 2_000  # a photo is a file of a few MB on the SD card


@dataclass(frozen=True)
class Queues:
    detections: PersistentQueue[DetectionEvent]
    locations: PersistentQueue[LocationPoint]
    metrics: PersistentQueue[DeviceMetric]
    images: PersistentQueue[ImageJob]

    @classmethod
    def open(cls, directory: Path) -> "Queues":
        def queue(name, codec, retention_days, max_rows):
            return PersistentQueue(directory / f"{name}.sqlite3", name, codec, retention_days, max_rows)

        return cls(queue("detections", DETECTION_CODEC, DETECTION_RETENTION_DAYS, DETECTION_MAX_ROWS),
                   queue("locations", LOCATION_CODEC, LOCATION_RETENTION_DAYS, LOCATION_MAX_ROWS),
                   queue("metrics", METRIC_CODEC, METRIC_RETENTION_DAYS, METRIC_MAX_ROWS),
                   queue("images", IMAGE_CODEC, IMAGE_RETENTION_DAYS, IMAGE_MAX_ROWS))

    def close(self) -> None:
        for queue in (self.detections, self.locations, self.metrics, self.images):
            queue.close()


def streams(queues: Queues, env: Environment) -> list[Stream]:
    """The streams sent as JSON batches (the photos have their own uploader, delivery/uploads.py)."""
    return [
        Stream("detections", env.ingest_url, queues.detections, DetectionBatch,
               lambda c: c.batching.detections_batch_size, lambda c: c.batching.max_batch_delay_seconds),
        Stream("locations", env.locations_url, queues.locations, LocationBatch,
               lambda c: c.batching.locations_batch_size, lambda c: c.batching.max_batch_delay_seconds),
        # One measurement is recorded per interval: it leaves at once, and after an outage the backlog goes in
        # batches of the largest size the contract allows.
        Stream("metrics", env.metrics_url, queues.metrics, MetricsBatch, lambda c: MAX_METRICS_BATCH, lambda c: 0.0),
    ]
