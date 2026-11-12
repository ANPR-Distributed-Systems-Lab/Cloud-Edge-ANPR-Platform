"""Detections for the ingest Lambda (POST /api/v1/ingest/detections, docs/api/ingest-detections.md).

  {"batchId": "...", "detections": [{"detectionId", "frameId", "detectedAt", "plate", "ocrConfidence",
                                     "detectorConfidence", "corners"}, ...]}

The contract's location and imageKey are not sent yet (no GPS, no photo upload).
"""
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

# Fixed namespace of batch ids, so the same set of detections always gets the same batchId.
BATCH_NAMESPACE = uuid.UUID("6f1d3a52-6a0e-4c4e-9a43-0c5b7d1e2f30")
CONFIDENCE_DECIMALS = 4
CORNER_DECIMALS = 5  # about 0.02 px on the 4056 px wide frame


def uuid7() -> str:
    """Time-ordered UUID (RFC 9562, version 7): 48 bits of Unix milliseconds, then random bits.
    Python gets uuid.uuid7() only in 3.14; the Pi runs Debian trixie's 3.13."""
    value = (time.time_ns() // 1_000_000) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC variant
    return str(uuid.UUID(int=value))


def iso_ms(moment: datetime) -> str:
    """RFC 3339 UTC with milliseconds and Z, as the ingest contract requires."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


@dataclass(frozen=True)
class DetectionEvent:
    """One plate read in one frame; the detection_id is its trace id in the logs."""
    detection_id: str  # uuid7
    frame_id: str  # uuid7, shared by the plates of one frame
    detected_at: datetime  # capture time of the frame, UTC
    plate: str
    ocr_confidence: float
    detector_confidence: float
    corners: tuple[tuple[float, float], ...]  # TL, TR, BR, BL as fractions of the frame width and height

    @classmethod
    def of(cls, frame_id: str, captured_at: datetime, plate: str, ocr_confidence: float, detector_confidence: float,
           corners_px: np.ndarray, frame_size: tuple[int, int]) -> "DetectionEvent":
        """A new detection, rounded as it is stored and sent; frame_size is (width, height)."""
        width, height = frame_size
        return cls(
            detection_id=uuid7(),
            frame_id=frame_id,
            detected_at=captured_at,
            plate=plate,
            ocr_confidence=round(float(ocr_confidence), CONFIDENCE_DECIMALS),
            detector_confidence=round(float(detector_confidence), CONFIDENCE_DECIMALS),
            corners=tuple((round(float(x) / width, CORNER_DECIMALS), round(float(y) / height, CORNER_DECIMALS))
                          for x, y in corners_px),
        )

    def to_document(self) -> dict:
        return {
            "detectionId": self.detection_id,
            "frameId": self.frame_id,
            "detectedAt": iso_ms(self.detected_at),
            "plate": self.plate,
            "ocrConfidence": self.ocr_confidence,
            "detectorConfidence": self.detector_confidence,
            "corners": [list(corner) for corner in self.corners],
        }

    @classmethod
    def from_document(cls, document: dict) -> "DetectionEvent":
        """The inverse of to_document(), for events read back from the outbox (written by this code)."""
        return cls(
            detection_id=document["detectionId"],
            frame_id=document["frameId"],
            detected_at=datetime.strptime(document["detectedAt"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC),
            plate=document["plate"],
            ocr_confidence=document["ocrConfidence"],
            detector_confidence=document["detectorConfidence"],
            corners=tuple((x, y) for x, y in document["corners"]),
        )


@dataclass(frozen=True)
class DetectionBatch:
    detections: tuple[DetectionEvent, ...]

    @property
    def batch_id(self) -> str:
        """A resend of the same detections reuses the batchId, as the contract asks, without storing it; it is
        also the trace id of the request."""
        return str(uuid.uuid5(BATCH_NAMESPACE, ",".join(d.detection_id for d in self.detections)))

    def to_document(self) -> dict:
        return {"batchId": self.batch_id, "detections": [d.to_document() for d in self.detections]}
