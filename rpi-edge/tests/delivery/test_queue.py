"""The queue on a real SQLite file in a temporary directory (embedded, no server, milliseconds)."""
from samples import detection_event

from detection.delivery import queue as queue_module
from detection.delivery.queue import PersistentQueue
from detection.delivery.queues import DETECTION_CODEC

DAY = 86400.0


def open_queue(tmp_path, clock=lambda: 1000.0, retention_days=30, max_rows=100_000):
    return PersistentQueue(tmp_path / "detections.sqlite3", "detections", DETECTION_CODEC, retention_days, max_rows,
                           clock)


def ids(box) -> list[str]:
    return [q.item.detection_id for q in box.oldest(100)]


def test_items_come_back_oldest_first_unchanged_and_survive_a_reopen(tmp_path):
    box = open_queue(tmp_path)
    box.add([detection_event(1, 990.0), detection_event(2, 990.0)])
    box.add([detection_event(3, 995.0)])
    box.close()

    box = open_queue(tmp_path)
    assert box.pending() == 3
    first, second = box.oldest(2)
    assert first.item == detection_event(1, 990.0) and second.item.detection_id == "id-2"
    assert box.oldest_age_seconds() == 10.0


def test_adding_the_same_item_twice_keeps_one(tmp_path):
    box = open_queue(tmp_path)
    box.add([detection_event(1)])
    box.add([detection_event(1)])
    assert box.pending() == 1


def test_delete_and_quarantine_remove_from_the_waiting_items(tmp_path):
    box = open_queue(tmp_path, clock=lambda: 50.0)
    box.add([detection_event(1, 10.0), detection_event(2, 10.0), detection_event(3, 10.0)])
    first, _, third = box.oldest(3)
    box.delete([first.row_id])
    box.quarantine([third.row_id], status=400, reason="VALIDATION_FAILED")
    assert ids(box) == ["id-2"]
    assert box.quarantined() == 1


def test_a_batch_is_due_when_full_or_when_the_oldest_has_waited_long_enough(tmp_path):
    box = open_queue(tmp_path)
    assert box.take_due(3, 10.0) == (None, 0.0)  # nothing waits
    box.add([detection_event(1, 996.0), detection_event(2, 996.0)])
    batch, wait = box.take_due(3, 10.0)  # 4 s old, 2 of 3: not due, 6 s to go
    assert batch is None and wait == 6.0
    batch, _ = box.take_due(2, 10.0)  # full
    assert [i.detection_id for i in batch.items] == ["id-1", "id-2"] and batch.pending == 2
    batch, _ = box.take_due(3, 4.0)  # old enough
    assert batch is not None and len(batch.row_ids) == 2


def test_prune_drops_items_past_the_retention_and_returns_them(tmp_path):
    now = 100 * DAY
    box = open_queue(tmp_path, clock=lambda: now)
    box.add([detection_event(1, now - 31 * DAY)])
    box.add([detection_event(2, now - 29 * DAY)])
    dropped = box.prune()
    assert [d.detection_id for d in dropped] == ["id-1"]
    assert ids(box) == ["id-2"]


def test_prune_keeps_the_newest_rows_over_the_limit(tmp_path):
    box = open_queue(tmp_path, clock=lambda: 10.0, max_rows=2)
    box.add([detection_event(n, 9.0) for n in range(5)])
    assert len(box.prune()) == 3
    assert ids(box) == ["id-3", "id-4"]


def test_the_limits_apply_to_the_quarantine_too(tmp_path, monkeypatch):
    box = open_queue(tmp_path, clock=lambda: 10.0, max_rows=1)
    box.add([detection_event(n, 9.0) for n in range(3)])
    box.quarantine([q.row_id for q in box.oldest(3)], 400, "X")
    box.prune()
    assert box.quarantined() == 1 and queue_module.SECONDS_PER_DAY == DAY


def test_empty_queue_has_no_age(tmp_path):
    assert open_queue(tmp_path).oldest_age_seconds() is None
