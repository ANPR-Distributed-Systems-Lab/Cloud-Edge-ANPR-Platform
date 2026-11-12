"""Optional in-car hardware: tact switch (GPIO22) starts/stops recording, LED (GPIO17) shows it, buzzer (GPIO27)
confirms, the 4x20 LCD shows status and the IP address to open in the browser.

Every part is optional: whatever fails to initialise is logged and skipped, the web UI keeps working.
"""
import threading

from collection.camera_service import CameraService
from common.jsonlog import log
from common.peripherals import Beeper, Lcd, open_led
from common.system_info import local_ip

BUTTON_PIN = 22


class Hardware:
    def __init__(self, camera: CameraService) -> None:
        self.camera = camera
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self.led, self.beeper, self.lcd = open_led(), Beeper.open(), Lcd.open()
        self.button = None
        try:
            from gpiozero import Button

            self.button = Button(BUTTON_PIN, bounce_time=0.05)
            self.button.when_pressed = lambda: threading.Thread(target=self._toggle, daemon=True).start()
        except Exception as e:
            log("gpio_unavailable", error=repr(e))
        threading.Thread(target=self._loop, name="hardware", daemon=True).start()

    def _beep(self, count: int = 1, length: float = 0.12) -> None:
        if self.beeper is not None:
            self.beeper.beep(count, length)

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
                if self.led is not None:
                    self.led.value = 1 if self.camera.recording_status() is not None else 0
                if self.lcd is not None:
                    self.lcd.show(self._lines())
            except OSError as e:  # I2C glitches happen, the next second tries again
                log("lcd_error", error=str(e))
            except Exception as e:
                log("hardware_error", error=repr(e))

    def close(self) -> None:
        self._stop.set()
        try:
            if self.led is not None:
                self.led.off()
            if self.lcd is not None:
                self.lcd.clear()
        except Exception:
            pass
