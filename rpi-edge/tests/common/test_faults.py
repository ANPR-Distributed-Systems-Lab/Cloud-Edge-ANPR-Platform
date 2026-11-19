"""Faults: reported and cleared by code, read from the Pi's flags, and sounded once when they appear."""
from common.faults import (
    CPU_HOT_C,
    FAULT_QUIET_SECONDS,
    FAULT_TONE_SECONDS,
    Fault,
    FaultAlarm,
    FaultBoard,
    system_faults,
)


def test_the_board_keeps_one_fault_per_code_until_cleared():
    board = FaultBoard()
    board.report("models", "no models")
    board.report("models", "model load failed")
    board.report("frame_loop", "frame loop error")
    board.clear("models", "unknown")
    assert board.active() == [Fault("frame_loop", "frame loop error")]


def test_the_faults_of_the_pi():
    assert system_faults(None, None) == []
    faults = system_faults({"undervoltage_now": True, "throttled_now": True, "undervoltage_occurred": True},
                           CPU_HOT_C + 2)
    assert [f.text for f in faults] == ["power too low", "CPU throttled", "CPU hot 82C"]
    assert system_faults({"undervoltage_occurred": True}, CPU_HOT_C - 1) == []  # the past does not count


def test_a_fault_sounds_when_it_appears_and_not_again_on_a_flap():
    clock, beeps = [0.0], []
    alarm = FaultAlarm(lambda count, length: beeps.append((count, length)), lambda: clock[0])
    hot, camera = Fault("cpu_hot", "CPU hot 81C"), Fault("camera", "camera error")
    alarm.check([hot])
    alarm.check([hot])  # still there
    alarm.check([])
    alarm.check([hot])  # back within the quiet time
    assert beeps == [(1, FAULT_TONE_SECONDS)]
    alarm.check([hot, camera])  # another one
    assert len(beeps) == 2
    alarm.check([])
    clock[0] += FAULT_QUIET_SECONDS
    alarm.check([hot])
    assert len(beeps) == 3
