"""What the LCD and the LEDs show in collection mode, from the status of the camera service."""
import copy

from collection.indicators import USB_LOW_FREE_BYTES, collection_faults, home_lines, light_states
from common.peripherals import LCD_COLS, LightState

STATUS = {
    "camera": {"running": True, "error": None, "actual": {"exposure_us": 4000, "gain": 2.0}},
    "recording": {"saved": 1234, "dropped": 0},
    "storage": {"usage": {"free": 12_300_000_000}, "error": None, "device": "/dev/sda1"},
    "system": {"temp_c": 52.4, "power": {"undervoltage_now": False}},
}


def status(**change):
    s = copy.deepcopy(STATUS)
    for path, value in change.items():
        section, key = path.split("__")
        s[section] = value if key == "" else {**s[section], key: value}
    return s


def test_the_home_page_while_recording_and_idle():
    lines = home_lines(STATUS, 2.0)
    assert lines[:3] == ["REC frames      1234", "USB free     12.3 GB", "1/250s       ISO 200"]
    assert lines[3].endswith(" 52C") and all(len(line) <= LCD_COLS for line in lines)
    idle = status(recording__=None, storage__usage=None, storage__device=None)
    assert home_lines(idle, 11.7)[:2] == ["IDLE rec at 11.7 fps", "USB             none"]


def test_the_faults_of_the_collection_mode():
    assert collection_faults(STATUS) == []
    broken = status(camera__error="no camera", recording__dropped=3, system__temp_c=85.0)
    assert [f.text for f in collection_faults(broken)] == ["camera error", "dropped frames 3", "CPU hot 85C"]


def test_the_leds_show_the_camera_the_recording_and_a_nearly_full_stick():
    assert light_states(STATUS, []) == {"run": LightState.BLINK, "queue": LightState.OFF, "alert": LightState.ON,
                                        "fault": LightState.OFF}
    nearly_full = status(storage__usage={"free": USB_LOW_FREE_BYTES - 1}, recording__=None)
    states = light_states(nearly_full, [])
    assert states["queue"] is LightState.BLINK and states["alert"] is LightState.OFF
