"""Every page of the detection mode fits the 20 columns and names what each number counts."""
import pytest
from snapshots import snapshot

from common.display import Pages
from common.faults import Fault
from common.peripherals import LCD_COLS, LCD_ROWS
from detection.contract.alerts import Alert
from detection.contract.metrics import FixType
from detection.feedback.screens import (
    PAGES,
    Stage,
    Waiting,
    alert_lines,
    gps_lines,
    home_lines,
    last_plates_lines,
    system_lines,
    waiting_lines,
)
from detection.gps.tracker import GpsStatus


def on_page(n):
    pages = Pages(len(PAGES), None)
    pages.index = n - 1
    return pages


def test_the_home_page_says_what_runs():
    assert home_lines(snapshot(), on_page(1)) == [
        "DETECTING    2.9 fps",
        "network           ok",
        "GPS           3D fix",
        "unsent plates     12"]
    waiting = snapshot(stage=Stage.WAIT_CONFIG, online=None, gps=GpsStatus(False, FixType.NONE, 0, 0),
                       waiting=Waiting(0, 0, 0))
    assert home_lines(waiting, on_page(1)) == [
        "WAITING FOR CONFIG", "network   connecting", "GPS          no data", "unsent plates      0"]
    assert home_lines(snapshot(stage=Stage.STOPPED), on_page(1))[0] == "DETECTION STOPPED"


@pytest.mark.parametrize(("change", "text"), [
    ({"online": False}, "offline"), ({"sign_in_failed": True}, "no sign-in"), ({"denied": True}, "denied")])
def test_the_network_row(change, text):
    assert home_lines(snapshot(**change), on_page(1))[1] == f"{'network':<{LCD_COLS - len(text)}}{text}"


def test_the_gps_page():
    assert gps_lines(snapshot(), on_page(2)) == [
        "GPS              2/6",
        "fix 3D        0s ago",
        "satellites  13 of 18",
        "accuracy 4m  45 km/h"]
    no_fix = snapshot(gps=GpsStatus(True, FixType.NONE, 0, 7), fix_seconds_ago=95.0)
    assert gps_lines(no_fix, on_page(2))[1:3] == ["no fix   last 1m ago", "satellites    0 of 7"]
    assert gps_lines(snapshot(gps=GpsStatus(False, FixType.NONE, 0, 0)), on_page(2))[1] == "no data from module"


def test_the_waiting_and_system_pages():
    assert waiting_lines(snapshot(), on_page(3)) == [
        "WAITING TO SEND  3/6", "plates            12", "track points     340", "photos             5"]
    assert system_lines(snapshot(), on_page(5)) == [
        "SYSTEM config 12 5/6", "192.168.137.12   52C", "detector v3   ocr v3", "SD card free 25.3 GB"]


def test_the_last_plates_say_which_was_an_alert():
    assert last_plates_lines(snapshot(), on_page(6)) == [
        "LAST PLATES      6/6", "WA12345 ALERT 2m ago", "KR9876A      15s ago", "alert list  5 plates"]
    assert last_plates_lines(snapshot(last_plates=(), alert_list=None), on_page(6))[1:] == [
        "none yet", "", "alert list   loading"]


def test_every_page_fits_the_lcd_even_with_large_numbers():
    crowded = snapshot(waiting=Waiting(123_456, 200_000, 20_000), config_version=2**40, temp_c=104.0,
                       faults=tuple(Fault(str(i), "a fault with a long text") for i in range(6)))
    for n, page in enumerate(PAGES, start=1):
        lines = page(crowded, on_page(n))
        assert len(lines) <= LCD_ROWS and all(len(line) <= LCD_COLS for line in lines), (n, lines)


def test_the_alert_screen_shows_the_plate_and_the_text_without_polish_letters():
    alert = Alert("0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c", "WA12345", "Kradziony, zgłoś na 112 – Łódź")
    assert alert_lines(alert) == ["*** ALERT ***", "WA12345", "Kradziony, zglos na ", "112  Lodz"]
