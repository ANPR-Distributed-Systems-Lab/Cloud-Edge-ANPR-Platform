"""Detections for the ingest Lambda (POST /api/v1/ingest/detections, docs/api/ingest-detections.md).

  {"batchId": "...", "detections": [{"detectionId", "frameId", "detectedAt", "plate", "ocrConfidence",
                                     "detectorConfidence", "imageKey", "corners", "location"}, ...]}
"""
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from detection.contract.images import image_key
from detection.contract.locations import Location
from detection.contract.wire import iso_ms, parse_iso_ms, stable_id, uuid7

CONFIDENCE_DECIMALS = 4
CORNER_DECIMALS = 5  # about 0.02 px on the 4056 px wide frame


@dataclass(frozen=True)
class DetectionEvent:
    """One plate read in one frame; the detection_id is its trace id in the logs."""
    detection_id: str  # uuid7
    frame_id: str  # uuid7, shared by the plates of one frame
    detected_at: datetime  # capture time of the frame, UTC
    plate: str
    ocr_confidence: float
    detector_confidence: float
    image_key: str  # S3 key of the photo of the frame (contract/images.py); the photo may arrive later
    corners: tuple[tuple[float, float], ...]  # TL, TR, BR, BL as fractions of the frame width and height
    location: Location

    @classmethod
    def of(cls, *, device_id: str, frame_id: str, captured_at: datetime, plate: str, ocr_confidence: float,
           detector_confidence: float, corners_px: np.ndarray, frame_size: tuple[int, int],
           location: Location) -> "DetectionEvent":
        """A new detection, rounded as it is stored and sent; frame_size is (width, height)."""
        width, height = frame_size
        return cls(
            detection_id=uuid7(),
            frame_id=frame_id,
            detected_at=captured_at,
            plate=plate,
            ocr_confidence=round(float(ocr_confidence), CONFIDENCE_DECIMALS),
            detector_confidence=round(float(detector_confidence), CONFIDENCE_DECIMALS),
            image_key=image_key(device_id, frame_id, captured_at),
            corners=tuple((round(float(x) / width, CORNER_DECIMALS), round(float(y) / height, CORNER_DECIMALS))
                          for x, y in corners_px),
            location=location,
        )

    def to_document(self) -> dict:
        return {
            "detectionId": self.detection_id,
            "frameId": self.frame_id,
            "detectedAt": iso_ms(self.detected_at),
            "plate": self.plate,
            "ocrConfidence": self.ocr_confidence,
            "detectorConfidence": self.detector_confidence,
            "imageKey": self.image_key,
            "corners": [list(corner) for corner in self.corners],
            "location": self.location.to_document(),
        }

    @classmethod
    def from_document(cls, document: dict) -> "DetectionEvent":
        """The inverse of to_document(), for events read back from the outbox (written by this code)."""
        return cls(
            detection_id=document["detectionId"],
            frame_id=document["frameId"],
            detected_at=parse_iso_ms(document["detectedAt"]),
            plate=document["plate"],
            ocr_confidence=document["ocrConfidence"],
            detector_confidence=document["detectorConfidence"],
            image_key=document["imageKey"],
            corners=tuple((x, y) for x, y in document["corners"]),
            location=Location.from_document(document["location"]),
        )


@dataclass(frozen=True)
class DetectionBatch:
    detections: tuple[DetectionEvent, ...]

    @property
    def batch_id(self) -> str:
        """A resend of the same detections reuses the batchId, as the contract asks, without storing it."""
        return stable_id(d.detection_id for d in self.detections)

    @property
    def trace_id(self) -> str:
        return self.batch_id

    def to_document(self) -> dict:
        return {"batchId": self.batch_id, "detections": [d.to_document() for d in self.detections]}
