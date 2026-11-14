import re
from datetime import UTC, datetime

import numpy as np
from samples import DEVICE_ID, LOCATION

from detection.contract.ingest import DetectionBatch, DetectionEvent
from detection.contract.wire import iso_ms, parse_iso_ms, uuid7

UUID7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
CAPTURED = datetime(2026, 1, 2, 3, 4, 5, 999_999, tzinfo=UTC)
CORNERS = np.array([[1014, 760], [2028, 760], [2028, 1520], [1014, 1520]], float)
FRAME_ID = "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c"


def event():
    return DetectionEvent.of(device_id=DEVICE_ID, frame_id=FRAME_ID, captured_at=CAPTURED, plate="WA12345",
                             ocr_confidence=0.912345, detector_confidence=0.5, corners_px=CORNERS,
                             frame_size=(4056, 3040), location=LOCATION)


def test_uuid7_is_time_ordered():
    first, second = uuid7(), uuid7()
    assert UUID7.fullmatch(first)
    assert first[:8] <= second[:8]  # the leading bits are the Unix milliseconds


def test_timestamps_have_milliseconds_and_z_and_read_back():
    assert iso_ms(CAPTURED) == "2026-01-02T03:04:05.999Z"
    assert parse_iso_ms("2026-01-02T03:04:05.999Z") == CAPTURED.replace(microsecond=999_000)


def test_a_new_event_is_normalized_rounded_and_carries_the_photo_key():
    e = event()
    assert UUID7.fullmatch(e.detection_id) and e.frame_id == FRAME_ID
    assert e.ocr_confidence == 0.9123
    assert e.corners[0] == (0.25, 0.25) and e.corners[2] == (0.5, 0.5)
    assert e.image_key == f"images/{DEVICE_ID}/2026/01/02/{FRAME_ID}.jpg"
    assert e.location == LOCATION


def test_the_document_has_the_contract_fields_and_reads_back_unchanged():
    document = event().to_document()
    assert set(document) == {"detectionId", "frameId", "detectedAt", "plate", "ocrConfidence", "detectorConfidence",
                             "imageKey", "corners", "location"}
    assert document["detectedAt"] == "2026-01-02T03:04:05.999Z"
    assert document["corners"][1] == [0.5, 0.25]
    assert document["location"] == {"lat": 52.229676, "lon": 21.012229, "accuracyM": 4.5, "fixAgeMs": 300}
    assert DetectionEvent.from_document(document).to_document() == document


def test_a_batch_id_is_stable_for_the_same_detections():
    first, second = event(), event()
    assert DetectionBatch((first, second)).batch_id == DetectionBatch((first, second)).batch_id
    assert DetectionBatch((first, second)).batch_id != DetectionBatch((second, first)).batch_id
    batch = DetectionBatch((first,))
    assert batch.to_document() == {"batchId": batch.batch_id, "detections": [first.to_document()]}
    assert batch.trace_id == batch.batch_id
