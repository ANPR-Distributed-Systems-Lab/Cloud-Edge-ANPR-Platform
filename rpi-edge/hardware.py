"""Optional in-car hardware: tact switch (GPIO22) starts/stops recording, LED (GPIO17) shows it, buzzer (GPIO27)
confirms, the 4x20 LCD shows status and the IP address to open in the browser.

Every part is optional: whatever fails to initialise is logged and skipped, the web UI keeps working.
"""
import socket
import threading
import time

from camera_service import CameraService
from jsonlog import log

LCD_COLS = 20
LCD_ROWS = 4


def local_ip() -> str:
    """IP of the interface that would be used to reach the network (no packet is sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]
    except OSError:
        return "no network"
    finally:
        sock.close()


class Hardware:
    def __init__(self, camera: CameraService) -> None:
        self.camera = camera
        self.led = self.buzzer = self.button = self.lcd = None
        self._stop = threading.Event()
        self._busy = threading.Lock()
        try:
            from gpiozero import LED, Button, Buzzer

            self.led, self.buzzer = LED(17), Buzzer(27)
            self.button = Button(22, bounce_time=0.05)
            self.button.when_pressed = lambda: threading.Thread(target=self._toggle, daemon=True).start()
        except Exception as e:
            log("gpio_unavailable", error=repr(e))
        try:
            from RPLCD.i2c import CharLCD

            self.lcd = CharLCD(i2c_expander="PCF8574", address=0x27, port=1, cols=LCD_COLS, rows=LCD_ROWS,
                               dotsize=8, charmap="A02", auto_linebreaks=False)
            self.lcd.clear()
        except Exception as e:
            log("lcd_unavailable", error=repr(e))
        threading.Thread(target=self._loop, name="hardware", daemon=True).start()

    def _beep(self, count: int = 1, length: float = 0.12) -> None:
        if self.buzzer is None:
            return
        try:
            for _ in range(count):
                self.buzzer.on()
                time.sleep(length)
                self.buzzer.off()
                time.sleep(0.1)
        except Exception as e:
            log("buzzer_error", error=repr(e))

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
                    for row, text in enumerate(self._lines()):
                        self.lcd.cursor_pos = (row, 0)
                        self.lcd.write_string(text.ljust(LCD_COLS)[:LCD_COLS])
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
