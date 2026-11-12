import pytest

from detection.cloud.transport import NetworkError
from detection.config.schema import EdgeSettings
from detection.config.settings import DEFAULTS, merge
from detection.delivery.events import batch_id
from detection.delivery.outbox import Outbox
from detection.delivery.sender import FORBIDDEN_WAIT_SECONDS, Sender
from fakes import FakeApi, response

URL = "https://api.example/api/v1/ingest/detections"


class FixedSettings:
    def __init__(self, **batching):
        self.current = EdgeSettings.from_document(merge(DEFAULTS, {"batching": batching}))


def setup(tmp_path, *answers, count=3, age=0.0, **batching):
    now = 1000.0
    box = Outbox(tmp_path / "o.sqlite3", clock=lambda: now)
    box.add([{"detectionId": f"d{n}", "plate": "WA12345"} for n in range(count)], detected_at=now - age)
    api = FakeApi(*answers)
    settings = FixedSettings(**({"detectionsBatchSize": 3, "maxBatchDelaySeconds": 10} | batching))
    return box, api, Sender(box, api, URL, settings)


def test_a_full_batch_is_sent_and_deleted_on_202(tmp_path):
    box, api, sender = setup(tmp_path, response(202, {"accepted": 3}))
    sender.send_once()
    [sent] = api.requests
    assert sent["method"] == "POST" and sent["url"] == URL
    assert [d["detectionId"] for d in sent["body"]["detections"]] == ["d0", "d1", "d2"]
    assert sent["body"]["batchId"] == batch_id(["d0", "d1", "d2"]) == sent["headers"]["X-Trace-Id"]
    assert sent["headers"]["Content-Type"] == "application/json"
    assert box.pending() == 0


def test_a_partial_batch_waits_until_the_delay_is_over(tmp_path):
    box, api, sender = setup(tmp_path, count=2, age=4.0)
    assert sender.send_once() == pytest.approx(1.0)
    assert api.requests == []

    box, api, sender = setup(tmp_path / "late", response(202), count=2, age=11.0)
    sender.send_once()
    assert len(api.requests) == 1 and box.pending() == 0


def test_only_the_detections_named_by_a_400_are_quarantined(tmp_path):
    problem = {"code": "VALIDATION_FAILED", "fields": [{"index": 1, "field": "detections[1].plate", "code": "PATTERN"}]}
    box, api, sender = setup(tmp_path, response(400, problem))
    assert sender.send_once() == 0.0  # the rest goes again right away
    assert [body["detectionId"] for _, body in box.oldest(10)] == ["d0", "d2"]
    assert box.quarantined() == 1


def test_a_400_without_indexes_quarantines_the_whole_batch(tmp_path):
    box, api, sender = setup(tmp_path, response(400, {"code": "INVALID_JSON"}))
    sender.send_once()
    assert box.pending() == 0 and box.quarantined() == 3


@pytest.mark.parametrize("failure", [response(503), response(429), NetworkError("no route"), response(404)])
def test_temporary_failures_keep_the_batch_and_back_off(tmp_path, failure):
    box, api, sender = setup(tmp_path, failure, response(202))
    first = sender.send_once()
    assert box.pending() == 3 and first >= 1.0
    sender.send_once()
    assert api.requests[0]["body"]["batchId"] == api.requests[1]["body"]["batchId"]  # the same batch again
    assert box.pending() == 0


def test_backoff_grows_with_consecutive_failures(tmp_path):
    box, api, sender = setup(tmp_path, *[response(503)] * 6)
    waits = [sender.send_once() for _ in range(6)]
    assert waits[-1] > waits[0] and all(w <= 300 for w in waits)


def test_retry_after_is_honoured(tmp_path):
    box, api, sender = setup(tmp_path, response(429, headers={"Retry-After": "120"}))
    assert sender.send_once() >= 120


def test_403_keeps_the_data_and_waits_long(tmp_path):
    box, api, sender = setup(tmp_path, response(403, {"code": "FORBIDDEN"}))
    assert sender.send_once() == FORBIDDEN_WAIT_SECONDS
    assert box.pending() == 3


def test_nothing_to_send_makes_no_request(tmp_path):
    box, api, sender = setup(tmp_path, count=0)
    sender.send_once()
    assert api.requests == []
