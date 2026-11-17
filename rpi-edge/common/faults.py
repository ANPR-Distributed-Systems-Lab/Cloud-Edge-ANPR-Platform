"""Faults: what needs someone to act. Each one lights the fault LED, is listed on the FAULTS page of the LCD and,
when it appears, sounds the buzzer for FAULT_TONE_SECONDS once.

What the network or the GPS do is not a fault (they have their own LEDs and recover by themselves); neither is
anything that happens once and passes, such as a photo not saved. The log has the details of each fault.
"""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

CPU_HOT_C = 80.0  # the Pi 5 throttles from 85 °C: time to cool it before frames get slower
FAULT_TONE_SECONDS = 3.0
FAULT_QUIET_SECONDS = 600.0  # a fault that comes back within this time is not sounded again: no beeping on a flap


@dataclass(frozen=True)
class Fault:
    code: str  # stable, for telling a new fault from one still active
    text: str  # for the LCD, at most 20 characters


class FaultBoard:
    """The faults that threads report as they see them (a refused configuration, a model that does not load, a
    failing camera); each reporter clears its fault once it has gone."""

    def __init__(self) -> None:
        self._faults: dict[str, Fault] = {}
        self._lock = threading.Lock()

    def report(self, code: str, text: str) -> None:
        with self._lock:
            self._faults[code] = Fault(code, text)

    def clear(self, *codes: str) -> None:
        with self._lock:
            for code in codes:
                self._faults.pop(code, None)

    def active(self) -> list[Fault]:
        with self._lock:
            return list(self._faults.values())


def system_faults(power: dict | None, temp_c: float | None) -> list[Fault]:
    """The faults of the Pi itself, from system_info.power_flags() and cpu_temp_c()."""
    power = power or {}
    faults = []
    if power.get("undervoltage_now"):
        faults.append(Fault("undervoltage", "power too low"))
    if power.get("throttled_now"):
        faults.append(Fault("throttled", "CPU throttled"))
    if temp_c is not None and temp_c >= CPU_HOT_C:
        faults.append(Fault("cpu_hot", f"CPU hot {temp_c:.0f}C"))
    return faults


class FaultAlarm:
    """Sounds a fault when it appears, unless it was sounded less than FAULT_QUIET_SECONDS ago."""

    def __init__(self, beep: Callable[[int, float], None], clock: Callable[[], float] = time.monotonic) -> None:
        self.beep = beep  # must not block: the screen refresh calls it
        self.clock = clock
        self._active: set[str] = set()
        self._sounded_at: dict[str, float] = {}

    def check(self, faults: list[Fault]) -> None:
        now, codes = self.clock(), {f.code for f in faults}
        new = [code for code in codes - self._active
               if code not in self._sounded_at or now - self._sounded_at[code] >= FAULT_QUIET_SECONDS]
        self._active = codes
        if new:
            self._sounded_at.update(dict.fromkeys(new, now))
            self.beep(1, FAULT_TONE_SECONDS)
