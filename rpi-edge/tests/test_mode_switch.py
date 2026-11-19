"""main.py: one mode at a time; a long press stops the running mode before the other one starts."""
import threading

from common.peripherals import Peripherals, TactSwitch
from main import ModeSwitcher, other


class FakeButton:
    when_pressed = when_held = when_released = None


class Modes:
    """Fake modes that record what runs, and let the test act while one is running."""

    def __init__(self):
        self.log, self.running, self.started = [], None, threading.Event()

    def mode(self, name, ends_by_itself=False):
        def run(stop, peripherals):
            assert self.running is None  # never two at once
            self.running = name
            self.log.append(f"start {name}")
            self.started.set()
            if not ends_by_itself:
                stop.wait()
            self.log.append(f"stop {name}")
            self.running = None
        return run


def start(switcher, mode):
    thread = threading.Thread(target=switcher.run, args=(mode,), daemon=True)
    thread.start()
    return thread


def wait_started(modes):
    assert modes.started.wait(2)
    modes.started.clear()


def switcher_with(modes, ending=()):
    peripherals = Peripherals(run_switch=TactSwitch(FakeButton()))
    runs = {name: modes.mode(name, name in ending) for name in ("collection", "detection")}
    return ModeSwitcher(runs, peripherals), peripherals


def test_a_long_press_switches_to_the_other_mode_after_the_first_has_stopped():
    modes = Modes()
    switcher, peripherals = switcher_with(modes)
    thread = start(switcher, "detection")
    wait_started(modes)
    peripherals.run_switch.held()  # the long press, as gpiozero reports it
    wait_started(modes)
    switcher.request_switch()
    wait_started(modes)
    switcher.shutdown()
    thread.join(2)
    assert not thread.is_alive()
    assert modes.log == ["start detection", "stop detection", "start collection", "stop collection",
                         "start detection", "stop detection"]


def test_a_mode_that_ends_by_itself_waits_for_a_switch():
    modes = Modes()
    switcher, _ = switcher_with(modes, ending=("detection",))
    thread = start(switcher, "detection")
    wait_started(modes)
    assert thread.is_alive()
    switcher.request_switch()
    wait_started(modes)
    switcher.shutdown()
    thread.join(2)
    assert modes.log == ["start detection", "stop detection", "start collection", "stop collection"]


def test_a_failing_mode_does_not_stop_the_switcher(capsys):
    failed, ran = threading.Event(), threading.Event()

    def broken(stop, peripherals):
        failed.set()
        raise RuntimeError("camera missing")

    def working(stop, peripherals):
        ran.set()
        stop.wait()

    switcher = ModeSwitcher({"detection": broken, "collection": working}, Peripherals())
    thread = start(switcher, "detection")
    assert failed.wait(2)
    switcher.request_switch()
    assert ran.wait(2)
    switcher.shutdown()
    thread.join(2)
    assert "mode_failed" in capsys.readouterr().out


def test_the_other_mode():
    assert other("collection") == "detection" and other("detection") == "collection"
