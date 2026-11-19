"""Checks the wiring of the in-car peripherals (pins in common/peripherals.py, table in RASPBERRY_PI_SETUP.md).

Lights each LED in turn for LED_SECONDS with its name and pin on the LCD, beeps once, then reports every press of
the two tact switches (short or long) on the LCD and in the log for SWITCH_SECONDS. The application container
holds the pins, so stop it first:

    docker compose stop rpi-edge
    docker compose run --rm rpi-edge /opt/venv/bin/python -m tools.wiring_check
    docker compose start rpi-edge
"""
import threading
import time

from common.jsonlog import log
from common.peripherals import LED_PINS, PAGE_SWITCH_PIN, RUN_SWITCH_PIN, LightState, Peripherals

LED_SECONDS = 2.0
SWITCH_SECONDS = 30.0


def main() -> None:
    peripherals = Peripherals.open()
    log("wiring_check_parts", lcd=peripherals.lcd is not None, buzzer=peripherals.beeper is not None,
        leds=[name for name in LED_PINS if getattr(peripherals.lights, name).led is not None],
        run_switch=peripherals.run_switch is not None, page_switch=peripherals.page_switch is not None)
    for name, pin in LED_PINS.items():
        log("wiring_check_led", led=name, pin=pin)
        peripherals.show(["LED CHECK", f"{name} on GPIO{pin}"])
        peripherals.lights.show(**{name: LightState.ON})
        time.sleep(LED_SECONDS)
    peripherals.lights.off()
    peripherals.show(["BUZZER CHECK", "one beep, GPIO27"])
    peripherals.beep(1, 0.3)

    pressed = threading.Lock()
    for switch, name, pin in ((peripherals.run_switch, "run", RUN_SWITCH_PIN),
                              (peripherals.page_switch, "page", PAGE_SWITCH_PIN)):
        if switch is not None:
            switch.on_press = _reporter(peripherals, pressed, name, pin, "short")
            switch.on_hold = _reporter(peripherals, pressed, name, pin, "long")
    peripherals.show(["SWITCH CHECK", f"press each, {SWITCH_SECONDS:.0f} s", "short and long (2 s)"])
    time.sleep(SWITCH_SECONDS)
    peripherals.reset()
    log("wiring_check_done")


def _reporter(peripherals: Peripherals, lock: threading.Lock, name: str, pin: int, kind: str):
    def report() -> None:
        with lock:
            log("wiring_check_switch", switch=name, pin=pin, press=kind)
            peripherals.show(["SWITCH CHECK", f"{name} GPIO{pin}", f"{kind} press"])
            peripherals.beep(1 if kind == "short" else 2, 0.1)
    return report


if __name__ == "__main__":
    main()
