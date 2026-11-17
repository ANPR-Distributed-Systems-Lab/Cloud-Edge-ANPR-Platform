"""The in-car peripherals both modes share: the 4x20 I2C LCD, the buzzer (GPIO27), the LED (GPIO17) and the tact
switch (GPIO22).

main.py opens them once and hands them to whichever mode runs, so a mode switch never has to release and claim the
GPIO pins again. Each one is optional: whatever fails to initialise (not connected, no GPIO on a PC) is logged and
replaced by None, and the modes work without it. The libraries are imported here, so the rest of the code imports
without them.
"""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from common.jsonlog import log

LCD_COLS = 20
LCD_ROWS = 4
LCD_I2C_ADDRESS = 0x27  # the PCF8574 backpack
BUZZER_PIN = 27
LED_PIN = 17
SWITCH_PIN = 22
SWITCH_BOUNCE_SECONDS = 0.05
SWITCH_HOLD_SECONDS = 2.0  # a press at least this long is a long press (main.py: switch the mode)


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


class TactSwitch:
    """A short press is for the running mode (`on_press`, e.g. start / stop recording), a long press of
    SWITCH_HOLD_SECONDS for main.py (`on_hold`, switch the mode). A press is short only once it is released without
    having been held, so a long press never also counts as a short one. The callbacks run in a thread of their own:
    gpiozero's event thread must not wait for them."""

    def __init__(self, button) -> None:
        self.on_press: Callable[[], None] | None = None
        self.on_hold: Callable[[], None] | None = None
        self._held = False
        button.when_pressed = self.pressed
        button.when_held = self.held
        button.when_released = self.released
        self._button = button  # the gpiozero device stays open as long as this object

    @classmethod
    def open(cls) -> "TactSwitch | None":
        try:
            from gpiozero import Button

            return cls(Button(SWITCH_PIN, bounce_time=SWITCH_BOUNCE_SECONDS, hold_time=SWITCH_HOLD_SECONDS))
        except Exception as e:
            log("switch_unavailable", error=repr(e))
            return None

    def pressed(self) -> None:
        self._held = False

    def held(self) -> None:
        self._held = True
        self._call(self.on_hold)

    def released(self) -> None:
        if not self._held:
            self._call(self.on_press)

    @staticmethod
    def _call(callback: Callable[[], None] | None) -> None:
        if callback is not None:
            threading.Thread(target=callback, name="switch", daemon=True).start()


def open_led():
    try:
        from gpiozero import LED

        return LED(LED_PIN)
    except Exception as e:
        log("led_unavailable", error=repr(e))
        return None


@dataclass(frozen=True)
class Peripherals:
    """The parts a mode may use; any of them may be None."""
    lcd: Lcd | None
    beeper: Beeper | None
    led: object | None  # a gpiozero LED
    switch: TactSwitch | None

    @classmethod
    def open(cls) -> "Peripherals":
        return cls(Lcd.open(), Beeper.open(), open_led(), TactSwitch.open())

    def show(self, lines: list[str]) -> None:
        if self.lcd is not None:
            try:
                self.lcd.show(lines)
            except OSError as e:  # an I2C glitch: the next write tries again
                log("lcd_error", error=str(e))

    def beep(self, count: int = 1, length: float = 0.12) -> None:
        if self.beeper is not None:
            self.beeper.beep(count, length)

    def reset(self) -> None:
        """What a mode leaves behind is cleared before the next one starts: LED off, empty screen, no short press."""
        if self.switch is not None:
            self.switch.on_press = None
        try:
            if self.led is not None:
                self.led.off()
            if self.lcd is not None:
                self.lcd.clear()
        except Exception as e:  # the next mode starts anyway
            log("peripherals_reset_error", level="warning", error=repr(e))
