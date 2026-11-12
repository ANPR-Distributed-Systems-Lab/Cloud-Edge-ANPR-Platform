import re
from datetime import UTC, datetime

import numpy as np

from detection.contract.ingest import DetectionBatch, DetectionEvent, iso_ms, uuid7

UUID7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
CAPTURED = datetime(2026, 1, 2, 3, 4, 5, 999_999, tzinfo=UTC)
CORNERS = np.array([[1014, 760], [2028, 760], [2028, 1520], [1014, 1520]], float)


def event():
    return DetectionEvent.of("frame-1", CAPTURED, "WA12345", 0.912345, 0.5, CORNERS, (4056, 3040))


def test_uuid7_is_time_ordered():
    first, second = uuid7(), uuid7()
    assert UUID7.fullmatch(first)
    assert first[:8] <= second[:8]  # the leading bits are the Unix milliseconds


def test_iso_ms_truncates_to_milliseconds_with_z():
    assert iso_ms(CAPTURED) == "2026-01-02T03:04:05.999Z"


def test_a_new_event_is_normalized_and_rounded():
    e = event()
    assert UUID7.fullmatch(e.detection_id) and e.frame_id == "frame-1"
    assert e.ocr_confidence == 0.9123
    assert e.corners[0] == (0.25, 0.25) and e.corners[2] == (0.5, 0.5)


def test_the_document_has_the_contract_fields_and_reads_back_unchanged():
    e = event()
    document = e.to_document()
    assert set(document) == {"detectionId", "frameId", "detectedAt", "plate", "ocrConfidence", "detectorConfidence",
                             "corners"}
    assert document["detectedAt"] == "2026-01-02T03:04:05.999Z"
    assert document["corners"][1] == [0.5, 0.25]
    back = DetectionEvent.from_document(document)
    assert back.to_document() == document


def test_a_batch_id_is_stable_for_the_same_detections():
    first, second = event(), event()
    assert DetectionBatch((first, second)).batch_id == DetectionBatch((first, second)).batch_id
    assert DetectionBatch((first, second)).batch_id != DetectionBatch((second, first)).batch_id
    document = DetectionBatch((first,)).to_document()
    assert document["batchId"] == DetectionBatch((first,)).batch_id
    assert document["detections"] == [first.to_document()]
