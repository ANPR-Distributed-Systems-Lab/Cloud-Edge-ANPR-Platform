"""The screen and the buzzer, with fakes in place of the LCD, the GPIO and the queue (no hardware)."""
from collections import Counter
from datetime import UTC, datetime

import numpy as np
from samples import configuration, detection_event

from common.peripherals import LCD_COLS
from detection.cloud.api import CloudHealth
from detection.contract.alerts import Alert, AlertList
from detection.contract.configuration import ModelVersions
from detection.contract.metrics import FixType
from detection.feedback import (
    ALERT_BEEPS,
    ALERT_SCREEN_SECONDS,
    Feedback,
    FrameRate,
    StatusSources,
    StatusView,
    alert_lines,
    gps_text,
    status_lines,
)
from detection.gps.source import FixedLocationSource
from detection.gps.tracker import GpsStatus
from detection.pipeline import FrameResult
from detection.rules.alerts import AlertWatch
from detection.vision.frame import Frame
from detection.vision.models import LoadedModels, ModelSlot

ALERT = Alert("0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c", "WA12345", "Kradziony, zgłoś na 112 – Łódź")
FRAME = Frame(np.zeros((2, 2, 3), np.uint8), datetime(2026, 11, 13, tzinfo=UTC))
FIX_3D = GpsStatus(receiving=True, fix=FixType.FIX_3D, satellites_used=13, satellites_in_view=18)


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


class FakeQueue:
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
    sources = StatusSources(FakeConfiguration(), slot, FakeQueue(), FixedLocationSource(52.2, 21.0), health, watch)
    fb = Feedback(sources, lcd, beeper, led, clock=lambda: clock[0])
    fb._beep = lambda count, length: beeper.beep(count, length)  # synchronous in tests
    return fb, lcd, beeper, led


def view(**override):
    values = dict(stage="running", fps=1.53, models="D2 O3", online=False, pending=12345, gps=FIX_3D, alerts=5,
                  ip="192.168.100.200", temp_c=61.4)
    return StatusView(**(values | override))


def test_the_status_screen_fits_the_lcd():
    lines = status_lines(view())
    assert lines == ["DET 1.5fps D2 O3", "NET offline Q 9999+", "GPS 3D 13   AL 5", "192.168.100.200 61C"]
    assert all(len(line) <= LCD_COLS for line in lines)
    waiting = status_lines(view(stage="config", online=None, pending=0, alerts=None, ip="no network", temp_c=None,
                                gps=GpsStatus(False, FixType.NONE, 0, 0)))
    assert waiting == ["WAIT CONFIG", "NET --      Q 0", "GPS --      AL ?", "no network"]


def test_the_gnss_state_in_few_characters():
    assert gps_text(GpsStatus(False, FixType.NONE, 0, 0)) == "GPS --"
    assert gps_text(GpsStatus(True, FixType.NONE, 0, 7)) == "GPS nofix 7"
    assert gps_text(GpsStatus(True, FixType.FIX_2D, 4, 9)) == "GPS 2D 4"
    assert gps_text(FIX_3D) == "GPS 3D 13"


def test_the_alert_screen_shows_the_plate_and_the_text_without_polish_letters():
    assert alert_lines(ALERT) == ["*** ALERT ***", "WA12345", "Kradziony, zglos na ", "112  Lodz"]


def test_a_sent_detection_of_an_alerted_plate_raises_the_alert_for_a_while():
    clock = [100.0]
    fb, lcd, beeper, led = feedback(clock)
    fb.on_frame(FRAME, FrameResult(events=[detection_event(1)], rejected=Counter()))  # reads WA12345
    assert beeper.beeps == [(1, 0.12), ALERT_BEEPS]  # ready, then the alert
    fb.refresh()
    assert lcd.lines[1] == "WA12345" and led.value == 1

    clock[0] += ALERT_SCREEN_SECONDS + 1
    fb.refresh()
    assert lcd.lines[0].startswith("DET ") and lcd.lines[0].endswith("D2 O3")
    assert lcd.lines[1] == "NET ok      Q 3"
    assert lcd.lines[2].startswith("GPS 3D")


def test_other_plates_raise_nothing():
    clock = [0.0]
    fb, lcd, beeper, _ = feedback(clock)
    fb.on_frame(FRAME, FrameResult(events=[], rejected=Counter(cooldown=1)))
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
