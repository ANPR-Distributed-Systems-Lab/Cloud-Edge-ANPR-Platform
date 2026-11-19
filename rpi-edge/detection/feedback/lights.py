"""What each LED shows in the detection mode, from the Snapshot of one refresh (screens.py).

  run    blinks while frames are analysed; off when stopped, waiting or failing
  net    on: the platform answers; blinks: no answer (the queues keep the data); off: no request yet, or no sign-in
  gps    on: a fix young enough for the frames (gps.maxFixAgeSeconds); blinks: no such fix; off: no data from a module
  queue  on: plates or track points wait to be sent; blinks: only photos wait (they go when the link is free)
  alert  blinks while an alert is on the screen, then stays on until the analysis is stopped or the mode switched
  fault  on while there is a fault (feedback/faults.py)
"""
from common.peripherals import LightState
from detection.feedback.screens import Snapshot, Stage

OFF, ON, BLINK = LightState.OFF, LightState.ON, LightState.BLINK


def light_states(s: Snapshot, alert_showing: bool, alert_seen: bool) -> dict[str, LightState]:
    return {
        "run": BLINK if s.stage is Stage.RUNNING and s.fps > 0 else OFF,
        "net": _net(s),
        "gps": OFF if not s.gps.receiving else ON if s.fix_fresh else BLINK,
        "queue": _queue(s),
        "alert": BLINK if alert_showing else ON if alert_seen else OFF,
        "fault": ON if s.faults else OFF,
    }


def _net(s: Snapshot) -> LightState:
    if s.online is None or s.sign_in_failed:
        return OFF
    return ON if s.online else BLINK


def _queue(s: Snapshot) -> LightState:
    if s.waiting.plates or s.waiting.track_points:
        return ON
    return BLINK if s.waiting.photos else OFF
