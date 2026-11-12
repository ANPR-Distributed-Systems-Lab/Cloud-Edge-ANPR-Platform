"""The local store-and-forward buffer: detections wait here, in SQLite on the SD card, until the cloud has them.

  detections  waiting to be sent, oldest first; deleted once the ingest answers 202
  quarantine  refused by the ingest with an error a resend cannot fix (400, 413, 415), kept for diagnosis

Every write is a committed transaction with synchronous=FULL, so a detection that was added survives a power
cut. Rows hold plate texts (personal data): only what is to be sent, and never longer than RETENTION_DAYS.
"""
import json
import sqlite3
import threading
import time
from pathlib import Path

RETENTION_DAYS = 30  # the ingest refuses detections older than this
MAX_ROWS = 100_000  # of each table, about 50 MB; the oldest rows go first

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id TEXT NOT NULL UNIQUE,
    detected_at REAL NOT NULL,  -- Unix seconds, for the retention
    body TEXT NOT NULL          -- the detection exactly as it is sent
);
CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id TEXT NOT NULL,
    detected_at REAL NOT NULL,
    quarantined_at REAL NOT NULL,
    status INTEGER NOT NULL,
    reason TEXT NOT NULL,
    body TEXT NOT NULL
);
"""


class Outbox:
    def __init__(self, path: Path, clock=time.time) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by the pipeline (writes) and the sender (reads, deletes), behind a lock.
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self.clock = clock
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def add(self, detections: list[dict], detected_at: float) -> None:
        """The detections of one frame, in one transaction."""
        rows = [(d["detectionId"], detected_at, json.dumps(d, separators=(",", ":"))) for d in detections]
        with self._lock, self._db:
            self._db.executemany("INSERT OR IGNORE INTO detections (detection_id, detected_at, body) VALUES (?, ?, ?)",
                                 rows)

    def oldest(self, limit: int) -> list[tuple[int, dict]]:
        with self._lock:
            rows = self._db.execute("SELECT id, body FROM detections ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [(row_id, json.loads(body)) for row_id, body in rows]

    def pending(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM detections").fetchone()[0]

    def quarantined(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]

    def oldest_age_seconds(self) -> float | None:
        """Age of the oldest waiting detection by its capture time, None when nothing waits."""
        with self._lock:
            row = self._db.execute("SELECT MIN(detected_at) FROM detections").fetchone()
        return None if row[0] is None else max(self.clock() - row[0], 0.0)

    def delete(self, ids: list[int]) -> None:
        with self._lock, self._db:
            self._db.executemany("DELETE FROM detections WHERE id = ?", [(i,) for i in ids])

    def quarantine(self, ids: list[int], status: int, reason: str) -> None:
        now = self.clock()
        with self._lock, self._db:
            for row_id in ids:
                self._db.execute(
                    "INSERT INTO quarantine (detection_id, detected_at, quarantined_at, status, reason, body) "
                    "SELECT detection_id, detected_at, ?, ?, ?, body FROM detections WHERE id = ?",
                    (now, status, reason, row_id))
                self._db.execute("DELETE FROM detections WHERE id = ?", (row_id,))

    def prune(self) -> int:
        """Drops rows past the retention and beyond MAX_ROWS. Returns how many waiting detections were dropped."""
        cutoff = self.clock() - RETENTION_DAYS * 86400
        dropped = {}
        with self._lock, self._db:
            for table in ("detections", "quarantine"):  # fixed names, never user input
                too_old = self._db.execute(f"DELETE FROM {table} WHERE detected_at < ?", (cutoff,)).rowcount
                too_many = self._db.execute(
                    f"DELETE FROM {table} WHERE id NOT IN (SELECT id FROM {table} ORDER BY id DESC LIMIT ?)",
                    (MAX_ROWS,)).rowcount
                dropped[table] = too_old + too_many
        return dropped["detections"]
