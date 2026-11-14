"""Counts the frames the loop has analysed, for the device metrics (processingFps)."""
import threading


class FrameCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0

    def tick(self) -> None:
        with self._lock:
            self._total += 1

    @property
    def total(self) -> int:
        with self._lock:
            return self._total
