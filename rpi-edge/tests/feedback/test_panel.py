"""The panel of the detection mode with fakes in place of the LCD, the LEDs, the buzzer and the switches."""
from collections import Counter
from datetime import UTC, datetime

import numpy as np
from samples import configuration, detection_event

from common.faults import FAULT_TONE_SECONDS, FaultBoard
from common.peripherals import Light, Lights, LightState, Peripherals, TactSwitch
from detection.cloud.api import CloudHealth
from detection.contract.alerts import Alert, AlertList
from detection.contract.configuration import ModelVersions
from detection.delivery.queues import Queues
from detection.feedback.panel import ALERT_BEEPS, ALERT_SCREEN_SECONDS, Feedback, FeedbackSources, FrameRate
from detection.gps.source import FixedLocationSource
from detection.loop import Hold
from detection.pipeline import FrameResult
from detection.rules.alerts import AlertWatch
from detection.vision.frame import Frame
from detection.vision.models import LoadedModels, ModelSlot

ALERT = Alert("0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c", "WA12345", "Kradziony")
FRAME = Frame(np.zeros((2, 2, 3), np.uint8), datetime(2026, 11, 13, tzinfo=UTC))


class FakeButton:
    when_pressed = when_held = when_released = None


class FakeLcd:
    def __init__(self):
        self.lines = []

    def show(self, lines):
        self.lines = lines

    def clear(self):
        self.lines = []


class FakeBeeper:
    def __init__(self):
        self.beeps = []

    def beep(self, count, length):
        self.beeps.append((count, length))


class FakeLed:
    def on(self):
        pass

    def off(self):
        pass

    def blink(self, on_time, off_time):
        pass


class InstantPeripherals(Peripherals):
    def beep_later(self, count=1, length=0.12):  # in the caller's thread: the test sees it at once
        self.beep(count, length)


class FakeConfiguration:
    current = configuration()


def panel(tmp_path, clock):
    slot, watch, faults = ModelSlot(), AlertWatch(), FaultBoard()
    slot.put(LoadedModels(ModelVersions("v3", "v3"), None, None))
    watch.replace(AlertList((ALERT,)), '"1"')
    peripherals = InstantPeripherals(FakeLcd(), FakeBeeper(), Lights(**{n: Light(FakeLed()) for n in (
        "run", "net", "gps", "queue", "alert", "fault")}), TactSwitch(FakeButton()), TactSwitch(FakeButton()))
    sources = FeedbackSources(FakeConfiguration(), slot, Queues.open(tmp_path / "outbox"),
                              FixedLocationSource(52.2, 21.0), CloudHealth(last_answer_at=1.0), watch, faults, Hold(),
                              tmp_path)
    return Feedback(sources, peripherals, clock=lambda: clock[0]), peripherals


def test_an_alert_shows_blinks_and_then_keeps_its_light_on_until_the_analysis_stops(tmp_path):
    clock = [100.0]
    fb, p = panel(tmp_path, clock)
    fb.on_frame(FRAME, FrameResult(events=[detection_event(1)], rejected=Counter()))  # reads WA12345
    assert p.beeper.beeps == [(1, 0.12), ALERT_BEEPS]  # ready, then the alert
    fb.refresh()
    assert p.lcd.lines[:2] == ["*** ALERT ***", "WA12345"] and p.lights.alert.state is LightState.BLINK

    clock[0] += ALERT_SCREEN_SECONDS + 1
    fb.refresh()
    assert p.lcd.lines[0].startswith("DETECTING") and p.lights.alert.state is LightState.ON

    p.run_switch.on_press()  # stop
    fb.refresh()
    assert p.lcd.lines[0] == "DETECTION STOPPED" and p.beeper.beeps[-1] == (2, 0.12)
    assert p.lights.alert.state is LightState.OFF and p.lights.run.state is LightState.OFF
    assert fb.sources.hold.held
    p.run_switch.on_press()  # start again
    assert not fb.sources.hold.held and p.beeper.beeps[-1] == (1, 0.12)


def test_the_page_switch_moves_through_the_pages(tmp_path):
    fb, p = panel(tmp_path, [0.0])
    p.page_switch.on_press()
    fb.refresh()
    assert p.lcd.lines[0] == "GPS              2/6"
    for _ in range(4):
        p.page_switch.on_press()
    fb.on_frame(FRAME, FrameResult(events=[detection_event(1, plate="KR9876A")], rejected=Counter()))
    fb.refresh()
    assert p.lcd.lines == ["LAST PLATES      6/6", "KR9876A       0s ago", "", "alert list  1 plates"]
    p.page_switch.on_hold()
    fb.refresh()
    assert p.lcd.lines[0].startswith("DETECTING")


def test_a_fault_lights_its_led_and_sounds_once(tmp_path):
    fb, p = panel(tmp_path, [0.0])
    fb.sources.faults.report("frame_loop", "frame loop error")
    fb.refresh()
    fb.refresh()
    assert p.lights.fault.state is LightState.ON and p.beeper.beeps == [(1, FAULT_TONE_SECONDS)]
    fb.sources.faults.clear("frame_loop")
    fb.refresh()
    assert p.lights.fault.state is LightState.OFF


def test_other_plates_raise_nothing(tmp_path):
    fb, p = panel(tmp_path, [0.0])
    fb.on_frame(FRAME, FrameResult(events=[], rejected=Counter(cooldown=1)))
    assert p.beeper.beeps == [(1, 0.12)]


def test_the_frame_rate_counts_the_last_seconds_only():
    clock = [0.0]
    rate = FrameRate(lambda: clock[0])
    for _ in range(15):
        rate.tick()
        clock[0] += 1.0
    assert rate.per_second() == 1.0  # 10 ticks in the 10 s window
