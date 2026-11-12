import re
from datetime import datetime, timezone

import numpy as np

from detection.delivery.events import batch_id, detection_event, iso_ms, uuid7

UUID7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def test_uuid7_is_time_ordered_and_batch_ids_are_stable():
    first, second = uuid7(), uuid7()
    assert UUID7.fullmatch(first)
    assert first[:8] <= second[:8]  # the leading bits are the Unix milliseconds
    assert batch_id(["a", "b"]) == batch_id(["a", "b"]) != batch_id(["a", "c"])


def test_iso_ms_truncates_to_milliseconds_with_z():
    assert iso_ms(datetime(2026, 1, 2, 3, 4, 5, 999_999, tzinfo=timezone.utc)) == "2026-01-02T03:04:05.999Z"


def test_detection_event_normalizes_the_corners_and_rounds():
    corners = np.array([[1014, 760], [2028, 760], [2028, 1520], [1014, 1520]], float)
    event = detection_event("frame-1", datetime(2026, 1, 2, tzinfo=timezone.utc), "WA12345", 0.912345, 0.5,
                            corners, (4056, 3040))
    assert UUID7.fullmatch(event["detectionId"]) and event["frameId"] == "frame-1"
    assert event["ocrConfidence"] == 0.9123
    assert event["corners"][0] == [0.25, 0.25] and event["corners"][2] == [0.5, 0.5]
