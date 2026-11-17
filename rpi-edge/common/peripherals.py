"""The in-car peripherals both modes share: the 4x20 I2C LCD, the buzzer, six LEDs and two tact switches (pins below,
wiring in RASPBERRY_PI_SETUP.md).

main.py opens them once and hands them to whichever mode runs, so a mode switch never has to release and claim the
GPIO pins again. Each one is optional: whatever fails to initialise (not connected, no GPIO on a PC) is logged and
left out, and the modes work without it. The libraries are imported here, so the rest of the code imports without
them.
"""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from enum import Enum

from common.jsonlog import log

LCD_COLS = 20
LCD_ROWS = 4
LCD_I2C_ADDRESS = 0x27  # the PCF8574 backpack
BUZZER_PIN = 27
RUN_SWITCH_PIN = 22
PAGE_SWITCH_PIN = 23
LED_PINS = {"run": 5, "net": 6, "gps": 13, "queue": 19, "alert": 26, "fault": 12}  # Lights field -> BCM GPIO
SWITCH_BOUNCE_SECONDS = 0.05
SWITCH_HOLD_SECONDS = 2.0  # a press at least this long is a long press
BLINK_SECONDS = 0.5  # on and off: 1 Hz


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
        """Writes LCD_ROWS lines, each padded or cut to LCD_COLS; missing ones are blank. Raises OSError on an I2C
        glitch."""
        for row in range(LCD_ROWS):
            text = lines[row] if row < len(lines) else ""
            self.device.cursor_pos = (row, 0)
            self.device.write_string(text.ljust(LCD_COLS)[:LCD_COLS])

    def clear(self) -> None:
        self.device.clear()


class Beeper:
    def __init__(self, buzzer) -> None:
        self.buzzer = buzzer
        self._lock = threading.Lock()  # one pattern at a time: two at once would merge into noise

    @classmethod
    def open(cls) -> "Beeper | None":
        try:
            from gpiozero import Buzzer

            return cls(Buzzer(BUZZER_PIN))
        except Exception as e:
            log("buzzer_unavailable", error=repr(e))
            return None

    def beep(self, count: int = 1, length: float = 0.12, pause: float = 0.1) -> None:
        """Blocks for the length of the pattern (and of any pattern still playing); call it from a thread that may
        wait."""
        with self._lock:
            try:
                for _ in range(count):
                    self.buzzer.on()
                    time.sleep(length)
                    self.buzzer.off()
                    time.sleep(pause)
            except Exception as e:
                log("buzzer_error", error=repr(e))


class LightState(Enum):
    OFF = "off"
    ON = "on"
    BLINK = "blink"


class Light:
    """One LED. set() acts only on a change, so the modes may set the state on every refresh without restarting the
    blink. Without an LED (`led` None) it does nothing."""

    def __init__(self, led) -> None:
        self.led = led
        self.state = LightState.OFF

    @classmethod
    def open(cls, pin: int) -> "Light":
        try:
            from gpiozero import LED

            return cls(LED(pin))
        except Exception as e:
            log("led_unavailable", pin=pin, error=repr(e))
            return cls(None)

    def set(self, state: LightState) -> None:
        if state is self.state or self.led is None:
            return
        self.state = state
        if state is LightState.ON:
            self.led.on()  # on() and off() also end a blink
        elif state is LightState.OFF:
            self.led.off()
        else:
            self.led.blink(on_time=BLINK_SECONDS, off_time=BLINK_SECONDS)


def _no_light() -> Light:
    return Light(None)


@dataclass(frozen=True)
class Lights:
    """The six LEDs; what each one means in each mode is in DETECTION.md and DATA_COLLECTION.md."""
    run: Light = field(default_factory=_no_light)  # green
    net: Light = field(default_factory=_no_light)  # green
    gps: Light = field(default_factory=_no_light)  # green
    queue: Light = field(default_factory=_no_light)  # yellow
    alert: Light = field(default_factory=_no_light)  # red
    fault: Light = field(default_factory=_no_light)  # red

    @classmethod
    def open(cls) -> "Lights":
        return cls(**{name: Light.open(pin) for name, pin in LED_PINS.items()})

    def show(self, **states: LightState) -> None:
        """Sets the named lights; the others are switched off, so a mode never leaves one on by accident."""
        for f in fields(self):
            getattr(self, f.name).set(states.get(f.name, LightState.OFF))

    def off(self) -> None:
        self.show()


class TactSwitch:
    """A short press calls `on_press`, a long press of SWITCH_HOLD_SECONDS `on_hold`. A press is short only once it
    is released without having been held, so a long press never also counts as a short one. The callbacks run in a
    thread of their own: gpiozero's event thread must not wait for them."""

    def __init__(self, button) -> None:
        self.on_press: Callable[[], None] | None = None
        self.on_hold: Callable[[], None] | None = None
        self._held = False
        button.when_pressed = self.pressed
        button.when_held = self.held
        button.when_released = self.released
        self._button = button  # the gpiozero device stays open as long as this object

    @classmethod
    def open(cls, pin: int) -> "TactSwitch | None":
        try:
            from gpiozero import Button

            return cls(Button(pin, bounce_time=SWITCH_BOUNCE_SECONDS, hold_time=SWITCH_HOLD_SECONDS))
        except Exception as e:
            log("switch_unavailable", pin=pin, error=repr(e))
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


@dataclass(frozen=True)
class Peripherals:
    """The parts a mode may use; the LCD, the buzzer and the switches may be None, a missing LED is a Light that does
    nothing.

    run_switch   short press: the mode's start / stop (recording, detection); long press: main.py switches the mode
    page_switch  short press: the next LCD page; long press: back to the first page (common/display.py)
    """
    lcd: Lcd | None = None
    beeper: Beeper | None = None
    lights: Lights = field(default_factory=Lights)
    run_switch: TactSwitch | None = None
    page_switch: TactSwitch | None = None

    @classmethod
    def open(cls) -> "Peripherals":
        return cls(Lcd.open(), Beeper.open(), Lights.open(), TactSwitch.open(RUN_SWITCH_PIN),
                   TactSwitch.open(PAGE_SWITCH_PIN))

    def show(self, lines: list[str]) -> None:
        if self.lcd is not None:
            try:
                self.lcd.show(lines)
            except OSError as e:  # an I2C glitch: the next write tries again
                log("lcd_error", error=str(e))

    def beep(self, count: int = 1, length: float = 0.12) -> None:
        if self.beeper is not None:
            self.beeper.beep(count, length)

    def beep_later(self, count: int = 1, length: float = 0.12) -> None:
        """Beeps in a thread of its own, for callers that must not wait (the frame loop, the screen refresh)."""
        if self.beeper is not None:
            threading.Thread(target=self.beeper.beep, args=(count, length), name="beep", daemon=True).start()

    def reset(self) -> None:
        """What a mode leaves behind is cleared before the next one starts: lights off, empty screen, no callbacks
        of the mode on the switches (the long press of the run switch stays main.py's)."""
        if self.run_switch is not None:
            self.run_switch.on_press = None
        if self.page_switch is not None:
            self.page_switch.on_press = self.page_switch.on_hold = None
        try:
            self.lights.off()
            if self.lcd is not None:
                self.lcd.clear()
        except Exception as e:  # the next mode starts anyway
            log("peripherals_reset_error", level="warning", error=repr(e))
