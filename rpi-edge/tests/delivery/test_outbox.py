"""The outbox on a real SQLite file in a temporary directory (embedded, no server, milliseconds)."""
from detection.delivery import outbox as outbox_module
from detection.delivery.outbox import Outbox

DAY = 86400.0


def detection(n: int) -> dict:
    return {"detectionId": f"id-{n}", "plate": "WA12345", "n": n}


def test_detections_come_back_oldest_first_and_survive_a_reopen(tmp_path):
    box = Outbox(tmp_path / "outbox.sqlite3", clock=lambda: 1000.0)
    box.add([detection(1), detection(2)], detected_at=990.0)
    box.add([detection(3)], detected_at=995.0)
    box.close()

    box = Outbox(tmp_path / "outbox.sqlite3", clock=lambda: 1000.0)
    assert box.pending() == 3
    assert [body["n"] for _, body in box.oldest(2)] == [1, 2]
    assert box.oldest_age_seconds() == 10.0


def test_adding_the_same_detection_twice_keeps_one(tmp_path):
    box = Outbox(tmp_path / "o.sqlite3")
    box.add([detection(1)], detected_at=1.0)
    box.add([detection(1)], detected_at=1.0)
    assert box.pending() == 1


def test_delete_and_quarantine_remove_from_the_waiting_detections(tmp_path):
    box = Outbox(tmp_path / "o.sqlite3", clock=lambda: 50.0)
    box.add([detection(1), detection(2), detection(3)], detected_at=10.0)
    (id1, _), (id2, _), (id3, _) = box.oldest(3)
    box.delete([id1])
    box.quarantine([id3], status=400, reason="VALIDATION_FAILED")
    assert [body["n"] for _, body in box.oldest(10)] == [2]
    assert box.quarantined() == 1


def test_prune_drops_detections_past_the_retention(tmp_path):
    now = 100 * DAY
    box = Outbox(tmp_path / "o.sqlite3", clock=lambda: now)
    box.add([detection(1)], detected_at=now - 31 * DAY)
    box.add([detection(2)], detected_at=now - 29 * DAY)
    assert box.prune() == 1
    assert [body["n"] for _, body in box.oldest(10)] == [2]


def test_prune_keeps_the_newest_rows_over_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox_module, "MAX_ROWS", 2)
    box = Outbox(tmp_path / "o.sqlite3", clock=lambda: 10.0)
    box.add([detection(n) for n in range(5)], detected_at=9.0)
    assert box.prune() == 3
    assert [body["n"] for _, body in box.oldest(10)] == [3, 4]


def test_empty_outbox_has_no_age(tmp_path):
    assert Outbox(tmp_path / "o.sqlite3").oldest_age_seconds() is None
