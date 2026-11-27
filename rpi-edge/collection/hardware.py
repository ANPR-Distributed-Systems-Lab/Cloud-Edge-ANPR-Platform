"""The in-car hardware in collection mode (common/peripherals.py); what the LCD and the LEDs show is in
indicators.py. The web UI works the same without any of it.

Run switch: a short press starts / stops recording (one beep: started, two: stopped, one long: failed); a long press
is main.py's (switch to the detection mode). Page switch: the next LCD page; a long press the home page. A fault
sounds the buzzer for 3 s when it appears (common/faults.py).
"""
import threading

from collection.camera_service import CameraService
from collection.indicators import collection_faults, home_lines, light_states
from common.display import Pages, fault_lines
from common.faults import FaultMonitor
from common.jsonlog import log
from common.peripherals import Peripherals

REFRESH_SECONDS = 1.0
STARTED_BEEPS, STOPPED_BEEPS, FAILED_BEEPS = (1, 0.12), (2, 0.12), (1, 0.8)
PAGES = 2  # home, FAULTS


class Hardware:
    def __init__(self, camera: CameraService, peripherals: Peripherals) -> None:
        self.camera = camera
        self.peripherals = peripherals
        self.pages = Pages(PAGES, peripherals.page_switch)
        self.monitor = FaultMonitor(peripherals.beep_later)
        self._stop = threading.Event()
        self._busy = threading.Lock()
        if peripherals.run_switch is not None:
            peripherals.run_switch.on_press = self._toggle
        threading.Thread(target=self._loop, name="hardware", daemon=True).start()

    def _toggle(self) -> None:
        if not self._busy.acquire(blocking=False):  # ignore presses while the previous one is still being handled
            return
        try:
            if self.camera.recording_status() is None:
                self.camera.start_recording("button")
                self.peripherals.beep(*STARTED_BEEPS)
            else:
                self.camera.stop_recording("button")
                self.peripherals.beep(*STOPPED_BEEPS)
        except Exception as e:
            log("button_action_failed", error=str(e))
            self.peripherals.beep(*FAILED_BEEPS)
        finally:
            self._busy.release()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.pages.wait(REFRESH_SECONDS)
            if self._stop.is_set():
                break
            try:
                self.refresh()
            except Exception as e:
                log("hardware_error", error=repr(e))

    def refresh(self) -> None:
        status = self.camera.status()
        faults = collection_faults(status)
        self.monitor.check(faults)
        self.peripherals.lights.show(**light_states(status, faults))
        if self.pages.index == 0:
            self.peripherals.show(home_lines(status, self.camera.store.get()["recording"]["fps"]))
        else:
            self.peripherals.show(fault_lines(faults, self.pages))

    def close(self) -> None:
        """Stops the updates; main.py clears the LEDs, the screen and the switches (Peripherals.reset)."""
        self._stop.set()
