"""The in-car hardware in collection mode (common/peripherals.py): a short press of the tact switch starts / stops
recording, the LED is on while recording, the buzzer confirms, and the 4x20 LCD shows the status and the IP address
to open in the browser. A long press of the switch is main.py's: it switches to the detection mode.

Every part is optional: whatever is missing is skipped, the web UI keeps working.
"""
import threading

from collection.camera_service import CameraService
from common.jsonlog import log
from common.peripherals import Peripherals
from common.system_info import local_ip


class Hardware:
    def __init__(self, camera: CameraService, peripherals: Peripherals) -> None:
        self.camera = camera
        self.peripherals = peripherals
        self._stop = threading.Event()
        self._busy = threading.Lock()
        if peripherals.switch is not None:
            peripherals.switch.on_press = self._toggle
        threading.Thread(target=self._loop, name="hardware", daemon=True).start()

    def _beep(self, count: int = 1, length: float = 0.12) -> None:
        self.peripherals.beep(count, length)

    def _toggle(self) -> None:
        if not self._busy.acquire(blocking=False):  # ignore presses while the previous one is still being handled
            return
        try:
            if self.camera.recording_status() is None:
                self.camera.start_recording("button")
                self._beep(1)
            else:
                self.camera.stop_recording("button")
                self._beep(2)
        except Exception as e:
            log("button_action_failed", error=str(e))
            self._beep(1, 0.8)
        finally:
            self._busy.release()

    def _lines(self) -> list[str]:
        status = self.camera.status()
        cam, rec, usb = status["camera"], status["recording"], status["storage"]
        fps = self.camera.store.get()["recording"]["fps"]
        if rec is not None:
            first = f"REC {rec['saved']:6d} {fps:g}fps"
            if rec["dropped"]:
                first += f" d{rec['dropped']}"
        else:
            first = f"IDLE {fps:g}fps"

        if usb["usage"]:
            second = f"USB {usb['usage']['free'] / 1e9:.1f}GB free"
        elif usb["error"]:
            second = "USB error"
        else:
            second = "USB: not mounted" if usb["device"] else "USB: none"

        actual = cam["actual"]
        if cam["error"] or not cam["running"]:
            third = "CAMERA ERROR"
        elif actual["exposure_us"]:
            third = f"1/{round(1e6 / actual['exposure_us'])}s ISO{round(actual['gain'] * 100)}"
        else:
            third = "camera starting"

        temp = status["system"]["temp_c"]
        power = status["system"]["power"] or {}
        warn = " UV!" if power.get("undervoltage_now") else ""
        fourth = f"{local_ip()} {temp:.0f}C{warn}" if temp is not None else local_ip()
        return [first, second, third, fourth]

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                if self.peripherals.led is not None:
                    self.peripherals.led.value = 1 if self.camera.recording_status() is not None else 0
                self.peripherals.show(self._lines())
            except Exception as e:
                log("hardware_error", error=repr(e))

    def close(self) -> None:
        """Stops the status updates; main.py clears the LED, the screen and the short press (Peripherals.reset)."""
        self._stop.set()
