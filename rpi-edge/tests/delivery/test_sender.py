import pytest
from fakes import FakeApi, response
from samples import configuration, detection_event

from detection.cloud.transport import NetworkError
from detection.contract.ingest import DetectionBatch
from detection.delivery.queue import PersistentQueue
from detection.delivery.queues import DETECTION_CODEC
from detection.delivery.sender import FORBIDDEN_WAIT_SECONDS, Sender, Stream

URL = "https://api.example/api/v1/ingest/detections"


class FixedConfiguration:
    def __init__(self, **batching):
        self.current = configuration(batching=batching)


def setup(tmp_path, *answers, count=3, age=0.0, **batching):
    now = 1000.0
    queue = PersistentQueue(tmp_path / "d.sqlite3", "detections", DETECTION_CODEC, 30, 1000, lambda: now)
    queue.add([detection_event(n, now - age) for n in range(count)])
    api = FakeApi(*answers)
    config = FixedConfiguration(**({"detectionsBatchSize": 3, "maxBatchDelaySeconds": 10} | batching))
    stream = Stream("detections", URL, queue, DetectionBatch, lambda c: c.batching.detections_batch_size,
                    lambda c: c.batching.max_batch_delay_seconds)
    return queue, api, Sender(stream, api, config)


def test_a_full_batch_is_sent_and_deleted_on_202(tmp_path):
    box, api, sender = setup(tmp_path, response(202, {"accepted": 3}))
    expected = DetectionBatch(tuple(q.item for q in box.oldest(3)))
    sender.send_once()
    [sent] = api.requests
    assert sent["method"] == "POST" and sent["url"] == URL
    assert sent["body"] == expected.to_document()
    assert sent["body"]["batchId"] == sent["headers"]["X-Trace-Id"]
    assert sent["headers"]["Content-Type"] == "application/json"
    assert box.pending() == 0


def test_a_204_is_a_success_too(tmp_path):
    box, api, sender = setup(tmp_path, response(204))
    sender.send_once()
    assert box.pending() == 0


def test_a_partial_batch_waits_until_the_delay_is_over(tmp_path):
    box, api, sender = setup(tmp_path, count=2, age=4.0)
    assert sender.send_once() == pytest.approx(1.0)
    assert api.requests == []

    box, api, sender = setup(tmp_path / "late", response(202), count=2, age=11.0)
    sender.send_once()
    assert len(api.requests) == 1 and box.pending() == 0


def test_only_the_items_named_by_a_400_are_quarantined(tmp_path):
    problem = {"code": "VALIDATION_FAILED", "fields": [{"index": 1, "field": "detections[1].plate", "code": "PATTERN"}]}
    box, api, sender = setup(tmp_path, response(400, problem))
    assert sender.send_once() == 0.0  # the rest goes again right away
    assert [q.item.detection_id for q in box.oldest(10)] == ["id-0", "id-2"]
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


def test_nothing_is_sent_before_the_first_configuration(tmp_path):
    box, api, sender = setup(tmp_path)
    sender.configuration.current = None
    sender.send_once()
    assert api.requests == [] and box.pending() == 3
