"""Detection events in the shape of the ingest contract (docs/api/ingest-detections.md), and their identifiers."""
import os
import time
import uuid
from datetime import datetime

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


def batch_id(detection_ids: list[str]) -> str:
    """A resend of the same detections reuses the batchId, as the contract asks, without storing it."""
    return str(uuid.uuid5(BATCH_NAMESPACE, ",".join(detection_ids)))


def iso_ms(moment: datetime) -> str:
    """RFC 3339 UTC with milliseconds and Z, as the ingest contract requires."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def detection_event(frame_id: str, captured_at: datetime, plate: str, ocr_confidence: float,
                    detector_confidence: float, corners_px: np.ndarray, frame_size: tuple[int, int]) -> dict:
    """One detection; the corners are normalized to the frame. location and imageKey are still missing."""
    width, height = frame_size
    return {
        "detectionId": uuid7(),
        "frameId": frame_id,
        "detectedAt": iso_ms(captured_at),
        "plate": plate,
        "ocrConfidence": round(ocr_confidence, CONFIDENCE_DECIMALS),
        "detectorConfidence": round(detector_confidence, CONFIDENCE_DECIMALS),
        "corners": [[round(float(x) / width, CORNER_DECIMALS), round(float(y) / height, CORNER_DECIMALS)]
                    for x, y in corners_px],
    }
