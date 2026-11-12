"""The optional in-car peripherals both modes use: the 4x20 I2C LCD, the buzzer (GPIO27) and the LED (GPIO17).

Each one is optional: whatever fails to initialise (not connected, no GPIO on a PC) is logged and replaced by
None, and the mode works without it. The libraries are imported here, so the rest of the code imports without them.
"""
import time

from common.jsonlog import log

LCD_COLS = 20
LCD_ROWS = 4
LCD_I2C_ADDRESS = 0x27  # the PCF8574 backpack
BUZZER_PIN = 27
LED_PIN = 17


class Lcd:
    def __init__(self, device) -> None:
        self.device = device

    @classmethod
    def open(cls) -> "Lcd | None":
        try:
            from RPLCD.i2c import CharLCD

            device = CharLCD(i2c_expander="PCF8574", address=LCD_I2C_ADDRESS, port=1, cols=LCD_COLS, rows=LCD_ROWS,
                             dotsize=8, charmap="A02", auto_linebreaks=False)
            device.clear()
            return cls(device)
        except Exception as e:
            log("lcd_unavailable", error=repr(e))
            return None

    def show(self, lines: list[str]) -> None:
        """Writes up to LCD_ROWS lines, each padded or cut to LCD_COLS. Raises OSError on an I2C glitch."""
        for row, text in enumerate(lines[:LCD_ROWS]):
            self.device.cursor_pos = (row, 0)
            self.device.write_string(text.ljust(LCD_COLS)[:LCD_COLS])

    def clear(self) -> None:
        self.device.clear()


class Beeper:
    def __init__(self, buzzer) -> None:
        self.buzzer = buzzer

    @classmethod
    def open(cls) -> "Beeper | None":
        try:
            from gpiozero import Buzzer

            return cls(Buzzer(BUZZER_PIN))
        except Exception as e:
            log("buzzer_unavailable", error=repr(e))
            return None

    def beep(self, count: int = 1, length: float = 0.12, pause: float = 0.1) -> None:
        """Blocks for the length of the pattern; call it from a thread that may wait."""
        try:
            for _ in range(count):
                self.buzzer.on()
                time.sleep(length)
                self.buzzer.off()
                time.sleep(pause)
        except Exception as e:
            log("buzzer_error", error=repr(e))


def open_led():
    try:
        from gpiozero import LED

        return LED(LED_PIN)
    except Exception as e:
        log("led_unavailable", error=repr(e))
        return None
