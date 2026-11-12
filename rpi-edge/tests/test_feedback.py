"""The screen and the buzzer, with fakes in place of the LCD, the GPIO and the outbox (no hardware)."""
from collections import Counter

from samples import configuration
from test_outbox import event

from common.peripherals import LCD_COLS
from detection.cloud.api import CloudHealth
from detection.contract.alerts import Alert, AlertList
from detection.contract.configuration import ModelVersions
from detection.feedback import (ALERT_BEEPS, ALERT_SCREEN_SECONDS, Feedback, FrameRate, StatusSources, StatusView,
                                alert_lines, status_lines)
from detection.pipeline import FrameResult
from detection.rules.alerts import AlertWatch
from detection.vision.models import LoadedModels, ModelSlot

ALERT = Alert("0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c", "WA12345", "Kradziony, zgłoś na 112 – Łódź")


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
    value = 0

    def off(self):
        self.value = 0


class FakeOutbox:
    def pending(self):
        return 3


class FakeConfiguration:
    current = configuration()


def feedback(clock):
    slot, watch = ModelSlot(), AlertWatch()
    slot.put(LoadedModels(ModelVersions("v2", "v3"), None, None))
    watch.replace(AlertList((ALERT,)), '"1"')
    health = CloudHealth(last_answer_at=1.0)
    lcd, beeper, led = FakeLcd(), FakeBeeper(), FakeLed()
    fb = Feedback(StatusSources(FakeConfiguration(), slot, FakeOutbox(), health, watch), lcd, beeper, led,
                  clock=lambda: clock[0])
    fb._beep = lambda count, length: beeper.beep(count, length)  # synchronous in tests
    return fb, lcd, beeper, led


def test_the_status_screen_fits_the_lcd():
    lines = status_lines(StatusView("running", 1.53, "D2 O3", False, 12345, 5, "192.168.100.200", 61.4))
    assert lines == ["DET 1.5fps D2 O3", "NET offline Q 9999+", "GPS --      AL 5", "192.168.100.200 61C"]
    assert all(len(line) <= LCD_COLS for line in lines)
    assert status_lines(StatusView("config", 0, "", None, 0, None, "no network", None))[:3] == [
        "WAIT CONFIG", "NET --      Q 0", "GPS --      AL ?"]


def test_the_alert_screen_shows_the_plate_and_the_text_without_polish_letters():
    assert alert_lines(ALERT) == ["*** ALERT ***", "WA12345", "Kradziony, zglos na ", "112  Lodz"]


def test_a_sent_detection_of_an_alerted_plate_raises_the_alert_for_a_while():
    clock = [100.0]
    fb, lcd, beeper, led = feedback(clock)
    fb.frame_done(FrameResult(events=[event(1)], rejected=Counter()))  # event(1) reads WA12345
    assert beeper.beeps == [(1, 0.12), ALERT_BEEPS]  # ready, then the alert
    fb.refresh()
    assert lcd.lines[1] == "WA12345" and led.value == 1

    clock[0] += ALERT_SCREEN_SECONDS + 1
    fb.refresh()
    assert lcd.lines[0].startswith("DET ") and lcd.lines[0].endswith("D2 O3")
    assert lcd.lines[1] == "NET ok      Q 3"


def test_other_plates_raise_nothing():
    clock = [0.0]
    fb, lcd, beeper, _ = feedback(clock)
    fb.frame_done(FrameResult(events=[], rejected=Counter(cooldown=1)))
    assert beeper.beeps == [(1, 0.12)]


def test_the_frame_rate_counts_the_last_seconds_only():
    clock = [0.0]
    rate = FrameRate(lambda: clock[0])
    for _ in range(15):
        rate.tick()
        clock[0] += 1.0
    assert rate.per_second() == 1.0  # 10 ticks in the 10 s window


def test_cloud_health_follows_the_latest_request():
    assert CloudHealth().online is None
    assert CloudHealth(last_answer_at=5.0, last_failure_at=3.0).online is True
    assert CloudHealth(last_answer_at=5.0, last_failure_at=6.0).online is False
