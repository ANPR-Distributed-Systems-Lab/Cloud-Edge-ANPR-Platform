"""The local store-and-forward buffer of one stream: items wait here, in SQLite on the SD card, until sent.

  <name>             waiting to be sent, oldest first; deleted once the platform accepted them
  <name>_quarantine  refused with an error a resend cannot fix (400, 413, 415), kept for diagnosis

Every write is a committed transaction with synchronous=FULL, so an item that was added survives a power cut.
Items older than the retention, and the oldest beyond max_rows, are dropped (prune). Detections hold plate texts
and locations hold coordinates (personal data): only what is to be sent is stored, and never for longer than the
retention.
"""
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class ItemCodec[T]:
    """How a queue stores its items: as the JSON document that is sent, read back into the same dataclass."""
    to_document: Callable[[T], dict]
    from_document: Callable[[dict], T]
    key_of: Callable[[T], str]  # unique id of an item; adding it twice keeps one
    time_of: Callable[[T], float]  # Unix seconds, for the retention and the age of the oldest item


@dataclass(frozen=True)
class Queued[T]:
    row_id: int  # to delete or quarantine the row after the answer
    item: T


@dataclass(frozen=True)
class Batch[T]:
    queued: tuple[Queued[T], ...]  # in the order they are sent, so fields[].index of an error points into it
    pending: int  # items waiting when the batch was taken, the batch included

    @property
    def items(self) -> tuple[T, ...]:
        return tuple(q.item for q in self.queued)

    @property
    def row_ids(self) -> list[int]:
        return [q.row_id for q in self.queued]


class PersistentQueue[T]:
    def __init__(self, path: Path, name: str, codec: ItemCodec[T], retention_days: float, max_rows: int,
                 clock: Callable[[], float] = time.time) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.name = name  # also the table name: a fixed identifier of this code, never user input
        self.codec = codec
        self.retention_seconds = retention_days * SECONDS_PER_DAY
        self.max_rows = max_rows
        self.clock = clock
        # One connection shared by the producer (writes) and the sender (reads, deletes), behind a lock.
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(f"""
                CREATE TABLE IF NOT EXISTS {name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_key TEXT NOT NULL UNIQUE,
                    item_time REAL NOT NULL,  -- Unix seconds, for the retention
                    body TEXT NOT NULL        -- the item exactly as it is sent
                );
                CREATE TABLE IF NOT EXISTS {name}_quarantine (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_key TEXT NOT NULL,
                    item_time REAL NOT NULL,
                    quarantined_at REAL NOT NULL,
                    status INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    body TEXT NOT NULL
                );""")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def add(self, items: list[T]) -> None:
        """The items of one moment (e.g. the detections of a frame), in one transaction."""
        codec = self.codec
        rows = [(codec.key_of(i), codec.time_of(i), json.dumps(codec.to_document(i), separators=(",", ":")))
                for i in items]
        with self._lock, self._db:
            self._db.executemany(
                f"INSERT OR IGNORE INTO {self.name} (item_key, item_time, body) VALUES (?, ?, ?)", rows)

    def oldest(self, limit: int) -> list[Queued[T]]:
        with self._lock:
            rows = self._db.execute(f"SELECT id, body FROM {self.name} ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [Queued(row_id, self.codec.from_document(json.loads(body))) for row_id, body in rows]

    def take_due(self, size: int, max_delay_seconds: float) -> tuple[Batch[T] | None, float]:
        """A batch that is due now, or None and how long to wait for one: a batch leaves when `size` items wait,
        or when the oldest has waited max_delay_seconds."""
        pending, age = self.pending(), self.oldest_age_seconds()
        if pending == 0:
            return None, 0.0
        if pending < size and age < max_delay_seconds:
            return None, max_delay_seconds - age
        return Batch(tuple(self.oldest(size)), pending), 0.0

    def pending(self) -> int:
        return self._count(self.name)

    def quarantined(self) -> int:
        return self._count(f"{self.name}_quarantine")

    def oldest_age_seconds(self) -> float | None:
        """Age of the oldest waiting item by its own time, None when nothing waits."""
        with self._lock:
            row = self._db.execute(f"SELECT MIN(item_time) FROM {self.name}").fetchone()
        return None if row[0] is None else max(self.clock() - row[0], 0.0)

    def delete(self, row_ids: list[int]) -> None:
        with self._lock, self._db:
            self._db.executemany(f"DELETE FROM {self.name} WHERE id = ?", [(i,) for i in row_ids])

    def quarantine(self, row_ids: list[int], status: int, reason: str) -> None:
        now = self.clock()
        with self._lock, self._db:
            for row_id in row_ids:
                self._db.execute(
                    f"INSERT INTO {self.name}_quarantine (item_key, item_time, quarantined_at, status, reason, body) "
                    f"SELECT item_key, item_time, ?, ?, ?, body FROM {self.name} WHERE id = ?",
                    (now, status, reason, row_id))
                self._db.execute(f"DELETE FROM {self.name} WHERE id = ?", (row_id,))

    def prune(self) -> list[T]:
        """Drops the items past the retention and beyond max_rows. Returns the waiting items that were dropped."""
        cutoff = self.clock() - self.retention_seconds
        with self._lock, self._db:
            doomed = self._db.execute(
                f"SELECT id, body FROM {self.name} WHERE item_time < ? "
                f"OR id NOT IN (SELECT id FROM {self.name} ORDER BY id DESC LIMIT ?)",
                (cutoff, self.max_rows)).fetchall()
            self._db.executemany(f"DELETE FROM {self.name} WHERE id = ?", [(row_id,) for row_id, _ in doomed])
            quarantine = f"{self.name}_quarantine"
            self._db.execute(f"DELETE FROM {quarantine} WHERE item_time < ?", (cutoff,))
            self._db.execute(f"DELETE FROM {quarantine} WHERE id NOT IN "
                             f"(SELECT id FROM {quarantine} ORDER BY id DESC LIMIT ?)", (self.max_rows,))
        return [self.codec.from_document(json.loads(body)) for _, body in doomed]

    def _count(self, table: str) -> int:
        with self._lock:
            return self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
