"""The outbox on a real SQLite file in a temporary directory (embedded, no server, milliseconds)."""
from datetime import UTC, datetime

from detection.contract.ingest import DetectionEvent
from detection.delivery import outbox as outbox_module
from detection.delivery.outbox import Outbox

DAY = 86400.0


def event(n: int, at: float = 0.0) -> DetectionEvent:
    """Detection n, captured `at` Unix seconds."""
    return DetectionEvent(f"id-{n}", "frame", datetime.fromtimestamp(at, UTC), "WA12345", 0.9, 0.8,
                          ((0.1, 0.1), (0.2, 0.1), (0.2, 0.12), (0.1, 0.12)))


def ids(box: Outbox) -> list[str]:
    return [q.event.detection_id for q in box.oldest(100)]


def test_detections_come_back_oldest_first_unchanged_and_survive_a_reopen(tmp_path):
    box = Outbox(tmp_path / "outbox.sqlite3", clock=lambda: 1000.0)
    box.add([event(1, 990.0), event(2, 990.0)])
    box.add([event(3, 995.0)])
    box.close()

    box = Outbox(tmp_path / "outbox.sqlite3", clock=lambda: 1000.0)
    assert box.pending() == 3
    first, second = box.oldest(2)
    assert first.event == event(1, 990.0) and second.event.detection_id == "id-2"
    assert box.oldest_age_seconds() == 10.0


def test_adding_the_same_detection_twice_keeps_one(tmp_path):
    box = Outbox(tmp_path / "o.sqlite3")
    box.add([event(1)])
    box.add([event(1)])
    assert box.pending() == 1


def test_delete_and_quarantine_remove_from_the_waiting_detections(tmp_path):
    box = Outbox(tmp_path / "o.sqlite3", clock=lambda: 50.0)
    box.add([event(1, 10.0), event(2, 10.0), event(3, 10.0)])
    first, _, third = box.oldest(3)
    box.delete([first.row_id])
    box.quarantine([third.row_id], status=400, reason="VALIDATION_FAILED")
    assert ids(box) == ["id-2"]
    assert box.quarantined() == 1


def test_prune_drops_detections_past_the_retention(tmp_path):
    now = 100 * DAY
    box = Outbox(tmp_path / "o.sqlite3", clock=lambda: now)
    box.add([event(1, now - 31 * DAY)])
    box.add([event(2, now - 29 * DAY)])
    assert box.prune() == 1
    assert ids(box) == ["id-2"]


def test_prune_keeps_the_newest_rows_over_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox_module, "MAX_ROWS", 2)
    box = Outbox(tmp_path / "o.sqlite3", clock=lambda: 10.0)
    box.add([event(n, 9.0) for n in range(5)])
    assert box.prune() == 3
    assert ids(box) == ["id-3", "id-4"]


def test_empty_outbox_has_no_age(tmp_path):
    assert Outbox(tmp_path / "o.sqlite3").oldest_age_seconds() is None
