"""Faults: reported and cleared by kind, lit after failures in a row, counted, read from the Pi's flags, logged and
sounded once when they appear."""
import pytest

from common import fault_catalog as kinds
from common.fault_catalog import CPU_HOT_C, system_faults
from common.faults import FAULT_QUIET_SECONDS, FAULT_TONE_SECONDS, Fault, FaultBoard, FaultKind, FaultMonitor
from common.peripherals import LCD_COLS

RETRIED = FaultKind("retried", "retried thing", raise_after=3)


def test_the_board_keeps_one_fault_per_kind_until_cleared():
    board = FaultBoard()
    board.report(kinds.NO_MODELS)
    board.report(kinds.MODEL_LOAD_FAILED)
    board.report(kinds.NO_MODELS)
    board.clear(kinds.NO_MODELS, kinds.CONFIG_REFUSED)
    assert board.active() == [Fault("model_load_failed", "model load failed")]


def test_a_retried_fault_lights_after_failures_in_a_row_and_clears_with_a_success():
    board = FaultBoard()
    board.failed(RETRIED)
    board.failed(RETRIED)
    board.succeeded(RETRIED)  # the streak starts again
    board.failed(RETRIED)
    board.failed(RETRIED)
    assert board.active() == []
    board.failed(RETRIED)
    assert board.active() == [Fault("retried", "retried thing")]
    board.succeeded(RETRIED)
    assert board.active() == []


def test_lost_items_add_up_for_the_run():
    board = FaultBoard()
    board.add(kinds.DATA_DROPPED, 3)
    board.add(kinds.DATA_DROPPED, 4)
    assert board.active() == [Fault("data_dropped", "data dropped 7")]


def test_the_faults_of_the_pi():
    assert system_faults(None, None) == []
    faults = system_faults({"undervoltage_now": True, "throttled_now": True, "undervoltage_occurred": True},
                           CPU_HOT_C + 2)
    assert [f.text for f in faults] == ["power too low", "CPU throttled", "CPU hot 82C"]
    assert system_faults({"undervoltage_occurred": True}, CPU_HOT_C - 1) == []  # the past does not count


def test_a_fault_sounds_when_it_appears_and_not_again_on_a_flap(capsys):
    clock, beeps = [0.0], []
    monitor = FaultMonitor(lambda count, length: beeps.append((count, length)), lambda: clock[0])
    hot, camera = Fault("cpu_hot", "CPU hot 81C"), Fault("camera_error", "camera error")
    monitor.check([hot])
    monitor.check([hot])  # still there
    monitor.check([])
    monitor.check([hot])  # back within the quiet time
    assert beeps == [(1, FAULT_TONE_SECONDS)]
    monitor.check([hot, camera])  # another one
    assert len(beeps) == 2
    monitor.check([])
    clock[0] += FAULT_QUIET_SECONDS
    monitor.check([hot])
    assert len(beeps) == 3
    events = capsys.readouterr().out
    assert events.count('"fault_raised"') == 4 and events.count('"fault_cleared"') == 3


@pytest.mark.parametrize("kind", kinds.ALL, ids=lambda k: k.code)
def test_every_fault_fits_the_lcd_with_its_detail(kind):
    detail = {"cpu_hot": "104C", "refused_items": "20000", "data_dropped": "300000", "clock_wrong": "9999s",
              "sd_low": "999MB", "dropped_frames": "99999"}.get(kind.code, "")
    assert len(kind.fault(detail).text) <= LCD_COLS


def test_every_code_is_unique():
    assert len({k.code for k in kinds.ALL}) == len(kinds.ALL)
