"""The tact switches tell a short press from a long one, the LEDs change only on a change, and the peripherals
are cleared between the modes."""
import threading

from common.peripherals import Lcd, Light, Lights, LightState, Peripherals, TactSwitch


class FakeButton:
    when_pressed = when_held = when_released = None


class Calls:
    def __init__(self):
        self.names, self.done = [], threading.Event()

    def recorder(self, name):
        def callback():
            self.names.append(name)
            self.done.set()
        return callback


def switch_recording(calls):
    switch = TactSwitch(FakeButton())
    switch.on_press, switch.on_hold = calls.recorder("press"), calls.recorder("hold")
    return switch


def test_a_short_press_counts_when_released():
    calls = Calls()
    switch = switch_recording(calls)
    switch.pressed()
    switch.released()
    assert calls.done.wait(1) and calls.names == ["press"]


def test_a_long_press_is_never_also_a_short_one():
    calls = Calls()
    switch = switch_recording(calls)
    switch.pressed()
    switch.held()
    assert calls.done.wait(1)
    switch.released()
    assert calls.names == ["hold"]


def test_the_button_events_are_wired_to_the_switch():
    button = FakeButton()
    switch = TactSwitch(button)
    assert (button.when_pressed, button.when_held, button.when_released) == (switch.pressed, switch.held,
                                                                              switch.released)


class FakeLed:
    def __init__(self):
        self.calls = []

    def on(self):
        self.calls.append("on")

    def off(self):
        self.calls.append("off")

    def blink(self, on_time, off_time):
        self.calls.append(("blink", on_time, off_time))


class FakeLcd:
    def __init__(self):
        self.cleared = False

    def show(self, lines):
        pass

    def clear(self):
        self.cleared = True


def test_a_light_acts_only_on_a_change_so_a_blink_keeps_going():
    led = FakeLed()
    light = Light(led)
    for state in (LightState.BLINK, LightState.BLINK, LightState.ON, LightState.ON, LightState.OFF):
        light.set(state)
    assert led.calls == [("blink", 0.5, 0.5), "on", "off"]


def test_the_lights_not_named_are_switched_off():
    run, fault = FakeLed(), FakeLed()
    lights = Lights(run=Light(run), fault=Light(fault))
    lights.show(run=LightState.ON, fault=LightState.ON)
    lights.show(run=LightState.ON)
    assert run.calls == ["on"] and fault.calls == ["on", "off"]


def test_a_reset_leaves_nothing_of_the_previous_mode():
    run_switch, page_switch = TactSwitch(FakeButton()), TactSwitch(FakeButton())
    run_switch.on_press = run_switch.on_hold = page_switch.on_press = page_switch.on_hold = lambda: None
    led = FakeLed()
    peripherals = Peripherals(lcd=FakeLcd(), lights=Lights(alert=Light(led)), run_switch=run_switch,
                              page_switch=page_switch)
    peripherals.lights.alert.set(LightState.ON)
    peripherals.reset()
    assert run_switch.on_press is None and page_switch.on_press is None and page_switch.on_hold is None
    assert run_switch.on_hold is not None  # the long press stays main.py's
    assert led.calls == ["on", "off"] and peripherals.lcd.cleared


def test_missing_parts_are_skipped():
    peripherals = Peripherals()
    peripherals.show(["x"])
    peripherals.beep()
    peripherals.beep_later()
    peripherals.lights.show(run=LightState.BLINK)
    peripherals.reset()


def test_the_lcd_writes_every_row_so_a_shorter_page_leaves_nothing_behind():
    class Device:
        def __init__(self):
            self.rows, self.cursor_pos = {}, (0, 0)

        def write_string(self, text):
            self.rows[self.cursor_pos[0]] = text

    device = Device()
    Lcd(device).show(["a" * 25, "b"])
    assert device.rows == {0: "a" * 20, 1: "b".ljust(20), 2: " " * 20, 3: " " * 20}
