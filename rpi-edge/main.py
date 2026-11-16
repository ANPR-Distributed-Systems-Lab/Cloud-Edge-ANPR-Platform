"""Entry point of the container: runs one mode at a time and switches between them on a long press of the tact switch.

  collection  tune the camera, record full-resolution frames for training (DATA_COLLECTION.md)
  detection   read plates and send them to the cloud (DETECTION.md)

EDGE_MODE (rpi-edge/.env) picks the mode the container starts in. A long press (common/peripherals.py) stops the
running mode completely, camera, threads and web server, before the other one starts, so the two never hold the
camera at once. The peripherals are opened here once and handed to whichever mode runs.
"""
import os
import signal
import sys
import threading
from collections.abc import Callable

from common.jsonlog import log
from common.peripherals import Peripherals

MODES = ("collection", "detection")
DEFAULT_MODE = "detection"

Mode = Callable[[threading.Event, Peripherals], None]  # runs until the event is set, then releases what it holds


class ModeSwitcher:
    def __init__(self, modes: dict[str, Mode], peripherals: Peripherals) -> None:
        self.modes = modes
        self.peripherals = peripherals
        self._shutdown = threading.Event()
        self._stop = threading.Event()  # stops the running mode: a switch or the shutdown
        self._switch = False
        if peripherals.switch is not None:
            peripherals.switch.on_hold = self.request_switch

    def run(self, mode: str) -> None:
        """Runs `mode`, and the other one after each switch, until shutdown()."""
        while not self._shutdown.is_set():
            self._stop.clear()
            self._switch = False
            log("mode_started", mode=mode)
            self._run_once(mode)
            self.peripherals.reset()
            if self._switch and not self._shutdown.is_set():
                mode = other(mode)
                log("mode_switched", mode=mode)
                self.peripherals.show(["SWITCHING TO", mode.upper()])
                self.peripherals.beep(2, 0.3)

    def request_switch(self) -> None:
        self._switch = True
        self._stop.set()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._stop.set()

    def _run_once(self, mode: str) -> None:
        try:
            self.modes[mode](self._stop, self.peripherals)
        except Exception as e:
            log("mode_failed", level="error", mode=mode, error=repr(e))
        if not self._stop.is_set():
            # A mode that ended by itself (e.g. detection without its environment) leaves the device waiting, so a
            # long press can still switch to the other one.
            log("mode_ended", level="warning", mode=mode, hint="hold the tact switch to switch the mode")
            self.peripherals.show([mode.upper(), "not running", "see the log", "hold switch: change"])
            self._stop.wait()


def other(mode: str) -> str:
    return MODES[1 - MODES.index(mode)]


def run_collection(stop: threading.Event, peripherals: Peripherals) -> None:
    from collection.main import run  # imported on use: each mode loads only its own libraries

    run(stop, peripherals)


def run_detection(stop: threading.Event, peripherals: Peripherals) -> None:
    from detection.main import run

    run(stop, peripherals)


def main() -> None:
    mode = os.environ.get("EDGE_MODE") or DEFAULT_MODE
    if mode not in MODES:
        log("unknown_mode", level="error", mode=mode, allowed=MODES)
        sys.exit(2)
    switcher = ModeSwitcher({"collection": run_collection, "detection": run_detection}, Peripherals.open())
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: switcher.shutdown())
    switcher.run(mode)
    log("stopped")


if __name__ == "__main__":
    main()
