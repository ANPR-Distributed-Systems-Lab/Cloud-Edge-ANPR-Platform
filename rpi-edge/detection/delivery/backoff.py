"""Exponential backoff with jitter, shared by everything that retries against the platform."""
import random


class Backoff:
    def __init__(self, first_seconds: float, max_seconds: float) -> None:
        self.first_seconds = first_seconds
        self.max_seconds = max_seconds
        self.failures = 0  # consecutive failed attempts

    def next_delay(self) -> float:
        """Counts a failure and returns how long to wait; the jitter spreads the retries of many devices after a
        shared outage."""
        self.failures += 1
        delay = min(self.max_seconds, self.first_seconds * 2 ** (self.failures - 1))
        return delay / 2 + random.uniform(0, delay / 2)

    def reset(self) -> None:
        self.failures = 0
