"""How faults work (the list of them is common/fault_catalog.py, what each means is INDICATORS.md).

A fault is a lasting condition that keeps the device from its job (reading plates, sending them, raising alerts) or
puts data at risk, and needs someone to know or act. It lights the fault LED, is listed on the FAULTS page of the
LCD, is logged when it appears and when it clears (fault_raised / fault_cleared), and sounds the buzzer for
FAULT_TONE_SECONDS when it appears. What recovers by itself and has its own LED (no network, no GPS fix, data
waiting to be sent) is not a fault, and neither is a single event that passes (one failed request, one photo not
saved).

Two sources:
  reported  the thread that sees the condition reports it on the FaultBoard and clears it when it is gone; an
            attempt that may fail now and then (a request, a frame) uses failed() / succeeded(), and the fault lights
            only after FaultKind.raise_after failures in a row
  measured  the screen refresh reads the state each second (temperature, free space, the quarantine) and builds the
            Faults itself
"""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from common.jsonlog import log

FAULT_TONE_SECONDS = 3.0
FAULT_QUIET_SECONDS = 600.0  # a fault that comes back within this time is not sounded again: no beeping on a flap


@dataclass(frozen=True)
class Fault:
    code: str  # stable, for telling a new fault from one still active
    text: str  # for the LCD, at most 20 characters


@dataclass(frozen=True)
class FaultKind:
    code: str
    text: str  # at most 20 characters with its detail
    raise_after: int = 1  # failed attempts in a row before it lights

    def fault(self, detail: str = "") -> Fault:
        return Fault(self.code, f"{self.text} {detail}" if detail else self.text)


class FaultBoard:
    """The reported faults of one run of a mode; a new run starts with a new board."""

    def __init__(self) -> None:
        self._faults: dict[str, Fault] = {}
        self._failures: dict[str, int] = {}
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def report(self, kind: FaultKind, detail: str = "") -> None:
        with self._lock:
            self._faults[kind.code] = kind.fault(detail)

    def clear(self, *kinds: FaultKind) -> None:
        with self._lock:
            for kind in kinds:
                self._faults.pop(kind.code, None)

    def failed(self, kind: FaultKind) -> None:
        """One failed attempt; the fault lights after kind.raise_after of them in a row."""
        with self._lock:
            failures = self._failures.get(kind.code, 0) + 1
            self._failures[kind.code] = failures
            if failures >= kind.raise_after:
                self._faults[kind.code] = kind.fault()

    def succeeded(self, kind: FaultKind) -> None:
        with self._lock:
            self._failures.pop(kind.code, None)
            self._faults.pop(kind.code, None)

    def add(self, kind: FaultKind, n: int) -> None:
        """Counts lost items: the fault shows the total of this run and stays until the next run."""
        with self._lock:
            total = self._counts.get(kind.code, 0) + n
            self._counts[kind.code] = total
            self._faults[kind.code] = kind.fault(str(total))

    def active(self) -> list[Fault]:
        with self._lock:
            return list(self._faults.values())


class FaultMonitor:
    """Logs each fault when it appears and when it clears, and sounds it when it appears, unless it was sounded less
    than FAULT_QUIET_SECONDS ago. Fed all faults, reported and measured, at every refresh."""

    def __init__(self, beep: Callable[[int, float], None], clock: Callable[[], float] = time.monotonic) -> None:
        self.beep = beep  # must not block: the screen refresh calls it
        self.clock = clock
        self._active: set[str] = set()
        self._sounded_at: dict[str, float] = {}

    def check(self, faults: list[Fault]) -> None:
        now, codes = self.clock(), {f.code for f in faults}
        for fault in faults:
            if fault.code not in self._active:
                log("fault_raised", level="error", code=fault.code, text=fault.text)
        for code in self._active - codes:
            log("fault_cleared", code=code)
        new = [code for code in codes - self._active
               if code not in self._sounded_at or now - self._sounded_at[code] >= FAULT_QUIET_SECONDS]
        self._active = codes
        if new:
            self._sounded_at.update(dict.fromkeys(new, now))
            self.beep(1, FAULT_TONE_SECONDS)
