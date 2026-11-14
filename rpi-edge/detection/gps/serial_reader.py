"""Reads the NMEA stream of the GNSS module from its serial port into the GpsTracker.

The module talks as soon as it is powered (the LC76G at 115200 baud by default) and needs no commands. When the port
cannot be opened or the module goes quiet, the reader says so once and opens the port again every few seconds, so
a module that is plugged in later, or a loose wire, heals by itself.
"""
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from common.jsonlog import log
from detection.gps.tracker import GpsTracker

RETRY_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 1.0


class LineReader(Protocol):
    def readline(self) -> bytes: ...

    def close(self) -> None: ...


def open_serial(device: str, baud: int) -> LineReader:
    import serial  # pyserial; imported here so that the rest of the mode imports without a serial port

    return serial.Serial(device, baud, timeout=READ_TIMEOUT_SECONDS)


class SerialGpsReader:
    def __init__(self, tracker: GpsTracker, device: str, baud: int,
                 opener: Callable[[str, int], LineReader] = open_serial,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.tracker = tracker
        self.device = device
        self.baud = baud
        self.opener = opener
        self.clock = clock
        self._failing = False

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self._read(stop)
            except Exception as e:  # the port is gone, the module unplugged: try again later
                if not self._failing:
                    log("gps_unavailable", level="warning", device=self.device, error=repr(e))
                    self._failing = True
                stop.wait(RETRY_SECONDS)

    def _read(self, stop: threading.Event) -> None:
        port = self.opener(self.device, self.baud)
        try:
            log("gps_port_opened", device=self.device, baud=self.baud)
            self._failing = False
            while not stop.is_set():
                line = port.readline()
                if line:  # empty after the read timeout: the module is quiet
                    self.tracker.feed(line.decode("ascii", errors="ignore"), self.clock())
        finally:
            port.close()
