"""What the LCD and the LEDs show in collection mode, from CameraService.status() (no hardware or camera here).

LCD pages:
  home     REC frames        1234     frames saved; IDLE  rec at 2 fps when not recording
           USB free        12.3 GB    or USB none / not mounted / error
           1/250s          ISO 200    the exposure the camera runs with
           192.168.137.12      52C    the address of the web UI, CPU temperature
  FAULTS   what lights the fault LED (common/display.py)

LEDs: run blinks while the camera runs; queue blinks when the USB stick is nearly full; alert is on while
recording; fault is on with a fault (INDICATORS.md, collection). net and gps stay off: this mode uses neither.
"""
from common import fault_catalog as kinds
from common.display import row
from common.fault_catalog import system_faults
from common.faults import Fault
from common.peripherals import LightState
from common.system_info import local_ip

# Storage errors that are only about the stick being away; any other one (mount failed, read-only, unmount failed)
# with a stick in the port is a fault.
USB_ABSENT_ERRORS = ("No USB stick found", "USB stick was removed")
USB_LOW_FREE_BYTES = 5_000_000_000  # a few minutes of recording at 3 fps; recording stops at recording.min_free_mb
BYTES_PER_GIGABYTE = 1e9


def collection_faults(status: dict) -> list[Fault]:
    faults = []
    if status["camera"]["error"]:
        faults.append(kinds.CAMERA_ERROR.fault())
    rec = status["recording"]
    if rec is not None and rec["dropped"]:
        faults.append(kinds.DROPPED_FRAMES.fault(str(rec["dropped"])))
    usb = status["storage"]
    if usb["error"] and usb["device"] and usb["error"] not in USB_ABSENT_ERRORS:
        faults.append(kinds.USB_ERROR.fault())
    system = status["system"]
    return faults + system_faults(system["power"], system["temp_c"])


def light_states(status: dict, faults: list[Fault]) -> dict[str, LightState]:
    usage = status["storage"]["usage"]
    return {
        "run": LightState.BLINK if status["camera"]["running"] else LightState.OFF,
        "queue": LightState.BLINK if usage and usage["free"] < USB_LOW_FREE_BYTES else LightState.OFF,
        "alert": LightState.ON if status["recording"] is not None else LightState.OFF,
        "fault": LightState.ON if faults else LightState.OFF,
    }


def home_lines(status: dict, fps: float) -> list[str]:
    cam, rec, usb = status["camera"], status["recording"], status["storage"]
    first = row("REC frames", str(rec["saved"])) if rec is not None else row("IDLE", f"rec at {fps:g} fps")

    if usb["usage"]:
        second = row("USB free", f"{usb['usage']['free'] / BYTES_PER_GIGABYTE:.1f} GB")
    elif usb["error"]:
        second = row("USB", "error")
    else:
        second = row("USB", "not mounted" if usb["device"] else "none")

    actual = cam["actual"]
    if cam["error"]:
        third = "CAMERA ERROR"
    elif cam["running"] and actual["exposure_us"]:
        third = row(f"1/{round(1e6 / actual['exposure_us'])}s", f"ISO {round(actual['gain'] * 100)}")
    else:
        third = "camera starting"

    temp = status["system"]["temp_c"]
    return [first, second, third, row(local_ip(), "" if temp is None else f"{temp:.0f}C")]
