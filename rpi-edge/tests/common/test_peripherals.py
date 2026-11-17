"""The tact switch tells a short press from a long one, and the peripherals are cleared between the modes."""
import threading

from common.peripherals import Peripherals, TactSwitch


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
        self.value = 1

    def off(self):
        self.value = 0


class FakeLcd:
    def __init__(self):
        self.cleared = False

    def show(self, lines):
        pass

    def clear(self):
        self.cleared = True


def test_a_reset_leaves_nothing_of_the_previous_mode():
    switch = TactSwitch(FakeButton())
    switch.on_press = lambda: None
    peripherals = Peripherals(FakeLcd(), None, FakeLed(), switch)
    peripherals.reset()
    assert switch.on_press is None and peripherals.led.value == 0 and peripherals.lcd.cleared


def test_missing_parts_are_skipped():
    peripherals = Peripherals(None, None, None, None)
    peripherals.show(["x"])
    peripherals.beep()
    peripherals.reset()
