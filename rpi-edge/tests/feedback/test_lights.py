"""What each LED shows in the detection mode."""
import pytest
from snapshots import FIX_3D, snapshot

from common.faults import Fault
from common.peripherals import LightState
from detection.contract.metrics import FixType
from detection.feedback.lights import light_states
from detection.feedback.screens import Stage, Waiting
from detection.gps.tracker import GpsStatus

OFF, ON, BLINK = LightState.OFF, LightState.ON, LightState.BLINK


def lights(alert_showing=False, alert_seen=False, **change):
    return light_states(snapshot(**change), alert_showing, alert_seen)


def test_a_running_device_with_everything_working():
    assert lights() == {"run": BLINK, "net": ON, "gps": ON, "queue": ON, "alert": OFF, "fault": OFF}


@pytest.mark.parametrize("change", [{"stage": Stage.STOPPED}, {"stage": Stage.WAIT_MODELS}, {"fps": 0.0}])
def test_the_run_light_is_off_without_frames(change):
    assert lights(**change)["run"] is OFF


@pytest.mark.parametrize(("change", "state"), [
    ({"online": False}, BLINK), ({"online": None}, OFF), ({"online": False, "sign_in_failed": True}, OFF)])
def test_the_network_light(change, state):
    assert lights(**change)["net"] is state


@pytest.mark.parametrize(("change", "state"), [
    ({"fix_fresh": False}, BLINK), ({"gps": GpsStatus(True, FixType.NONE, 0, 5), "fix_fresh": False}, BLINK),
    ({"gps": GpsStatus(False, FixType.NONE, 0, 0)}, OFF), ({"gps": FIX_3D}, ON)])
def test_the_gps_light(change, state):
    assert lights(**change)["gps"] is state


@pytest.mark.parametrize(("waiting", "state"), [
    (Waiting(0, 1, 0), ON), (Waiting(0, 0, 4), BLINK), (Waiting(0, 0, 0), OFF)])
def test_the_queue_light_blinks_when_only_photos_wait(waiting, state):
    assert lights(waiting=waiting)["queue"] is state


def test_the_alert_light_blinks_with_the_alert_and_then_stays_on():
    assert lights(alert_showing=True, alert_seen=True)["alert"] is BLINK
    assert lights(alert_seen=True)["alert"] is ON


def test_the_fault_light():
    assert lights(faults=(Fault("camera", "camera error"),))["fault"] is ON
