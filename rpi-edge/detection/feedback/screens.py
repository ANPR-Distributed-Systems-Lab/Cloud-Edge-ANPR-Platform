"""The LCD pages of the detection mode, built from one Snapshot per refresh (panel.py).

  home         DETECTING    2.9 fps     what runs: DETECTING, DETECTION STOPPED, WAITING FOR CONFIG / MODELS
               network           ok     ok, offline, connecting, no sign-in, denied (the token is refused)
               GPS           3D fix     3D fix, 2D fix, no fix, no data (the module says nothing)
               unsent plates     12     detections waiting to be sent
  GPS          fix 3D        1s ago     the latest fix and its age
               satellites  13 of 18     used in the fix, of those in view
               accuracy 5m  45 km/h     estimated from the HDOP, speed over ground
  WAITING      plates / track points / photos waiting to be sent
  FAULTS       what lights the fault LED (common/display.py)
  SYSTEM       title with the configuration version; IP and CPU temperature; the model versions; free SD space
  LAST PLATES  the last two plates accepted for sending, ALERT when on the alert list, and how long ago; the
               plates on the alert list (loading before the first poll)

An alert replaces whichever page shows (alert_lines).
"""
from dataclasses import dataclass
from enum import Enum

from common.display import Pages, ascii_text, count, duration, fault_lines, row, title
from common.faults import Fault
from common.peripherals import LCD_COLS
from detection.contract.alerts import Alert
from detection.contract.configuration import ModelVersions
from detection.contract.metrics import FixType
from detection.gps.tracker import GpsStatus

MPS_TO_KMH = 3.6
MEGABYTES_PER_GIGABYTE = 1000


class Stage(Enum):
    STOPPED = "stopped"  # the driver stopped the analysis
    WAIT_CONFIG = "config"
    WAIT_MODELS = "models"
    RUNNING = "running"


@dataclass(frozen=True)
class Waiting:
    """Items waiting to be sent."""
    plates: int
    track_points: int
    photos: int


@dataclass(frozen=True)
class LastPlate:
    plate: str
    seconds_ago: float
    alert: bool


@dataclass(frozen=True)
class Snapshot:
    """What the screen and the LEDs show at one refresh, read once from the sources."""
    stage: Stage
    fps: float
    online: bool | None  # None before the first request
    sign_in_failed: bool
    denied: bool  # the platform refuses the token
    gps: GpsStatus
    fix_seconds_ago: float | None  # None: no fix since the start
    fix_fresh: bool  # young enough to go with a frame (gps.maxFixAgeSeconds)
    accuracy_m: float | None
    speed_mps: float | None
    waiting: Waiting
    faults: tuple[Fault, ...]
    ip: str
    temp_c: float | None
    config_version: int | None
    models: ModelVersions | None
    sd_free_mb: int | None
    last_plates: tuple[LastPlate, ...]
    alert_list: int | None  # plates on the alert list, None before the first list


def home_lines(s: Snapshot, pages: Pages) -> list[str]:
    first = {Stage.STOPPED: "DETECTION STOPPED", Stage.WAIT_CONFIG: "WAITING FOR CONFIG",
             Stage.WAIT_MODELS: "WAITING FOR MODELS"}.get(s.stage) or row("DETECTING", f"{s.fps:.1f} fps")
    return [first, row("network", network_text(s)), row("GPS", gps_text(s.gps)),
            row("unsent plates", count(s.waiting.plates))]


def network_text(s: Snapshot) -> str:
    if s.sign_in_failed:
        return "no sign-in"
    if s.denied:
        return "denied"
    return {None: "connecting", True: "ok", False: "offline"}[s.online]


def gps_text(status: GpsStatus) -> str:
    if not status.receiving:
        return "no data"
    if status.fix is FixType.NONE:
        return "no fix"
    return f"{status.fix.value[-2:]} fix"


def gps_lines(s: Snapshot, pages: Pages) -> list[str]:
    lines = [title("GPS", pages)]
    if not s.gps.receiving:
        return [*lines, "no data from module"]
    ago = "" if s.fix_seconds_ago is None else f"{duration(s.fix_seconds_ago)} ago"
    if s.gps.fix is FixType.NONE:
        lines.append(row("no fix", f"last {ago}" if ago else "yet"))
    else:
        lines.append(row(f"fix {s.gps.fix.value[-2:]}", ago))
    lines.append(row("satellites", f"{s.gps.satellites_used} of {s.gps.satellites_in_view}"))
    accuracy = "accuracy --" if s.accuracy_m is None else f"accuracy {s.accuracy_m:.0f}m"
    speed = "" if s.speed_mps is None else f"{s.speed_mps * MPS_TO_KMH:.0f} km/h"
    return [*lines, row(accuracy, speed)]


def waiting_lines(s: Snapshot, pages: Pages) -> list[str]:
    return [title("WAITING TO SEND", pages), row("plates", count(s.waiting.plates)),
            row("track points", count(s.waiting.track_points)), row("photos", count(s.waiting.photos))]


def faults_lines(s: Snapshot, pages: Pages) -> list[str]:
    return fault_lines(list(s.faults), pages)


def system_lines(s: Snapshot, pages: Pages) -> list[str]:
    name = "SYSTEM" if s.config_version is None else f"SYSTEM config {s.config_version}"
    temp = "" if s.temp_c is None else f"{s.temp_c:.0f}C"
    models = "models --" if s.models is None else row(f"detector {s.models.detector}", f"ocr {s.models.ocr}")
    sd = "--" if s.sd_free_mb is None else f"{s.sd_free_mb / MEGABYTES_PER_GIGABYTE:.1f} GB"
    return [title(name, pages), row(s.ip, temp), models, row("SD card free", sd)]


def last_plates_lines(s: Snapshot, pages: Pages) -> list[str]:
    plates = [row(f"{p.plate} ALERT" if p.alert else p.plate, f"{duration(p.seconds_ago)} ago")
              for p in s.last_plates] or ["none yet"]
    alert_list = "loading" if s.alert_list is None else f"{count(s.alert_list)} plates"
    return [title("LAST PLATES", pages), *plates, *[""] * (2 - len(plates)), row("alert list", alert_list)]


PAGES = (home_lines, gps_lines, waiting_lines, faults_lines, system_lines, last_plates_lines)


def alert_lines(alert: Alert) -> list[str]:
    text = ascii_text(alert.alert_text or "")
    return ["*** ALERT ***", alert.plate, text[:LCD_COLS], text[LCD_COLS:2 * LCD_COLS]]
