"""What the driver sees and hears in detection mode: the 4x20 LCD, the buzzer and the LED (common/peripherals.py).

Status screen, refreshed every second:

    DET 1.5fps D2 O3        frames analysed per second, model versions (WAIT CONFIG / WAIT MODELS before)
    NET ok      Q 3         whether the platform answers (ok / offline / --), detections waiting to be sent
    GPS 3D 13   AL 5        GNSS fix and satellites used (-- no module, nofix N: N satellites in view), alerts on
                            the list (? before the first list)
    192.168.1.20 52C        the IP to reach the Pi, CPU temperature

When an accepted detection is on the owner's alert list, the screen shows the plate and the alert text for
ALERT_SCREEN_SECONDS and the buzzer gives three long beeps. One short beep when the first frame is analysed. The
LED is on while frames are analysed. Every part is optional; without them only the log tells what happens.
"""
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from common import system_info
from common.jsonlog import log
from common.peripherals import LCD_COLS, Beeper, Lcd, open_led
from detection.cloud.api import CloudHealth
from detection.config.store import ConfigurationStore
from detection.contract.alerts import Alert
from detection.contract.ingest import DetectionEvent
from detection.contract.metrics import FixType
from detection.delivery.queue import PersistentQueue
from detection.gps.source import LocationSource
from detection.gps.tracker import GpsStatus
from detection.pipeline import FrameResult
from detection.rules.alerts import AlertWatch
from detection.vision.frame import Frame
from detection.vision.models import ModelSlot

REFRESH_SECONDS = 1.0
FPS_WINDOW_SECONDS = 10.0
ALERT_SCREEN_SECONDS = 15.0
ALERT_BEEPS = (3, 0.4)  # count, seconds each
READY_BEEPS = (1, 0.12)
LEFT_COLUMN = 12
MAX_SHOWN_COUNT = 9999


class FrameRate:
    """Frames analysed per second over the last FPS_WINDOW_SECONDS."""

    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self._ticks: deque[float] = deque()

    def tick(self) -> None:
        self._ticks.append(self.clock())

    def per_second(self) -> float:
        cutoff = self.clock() - FPS_WINDOW_SECONDS
        while self._ticks and self._ticks[0] < cutoff:
            self._ticks.popleft()
        return len(self._ticks) / FPS_WINDOW_SECONDS


@dataclass(frozen=True)
class StatusView:
    """One refresh of the status screen."""
    stage: str  # "config" (waiting for a configuration), "models" (waiting for models), "running"
    fps: float
    models: str  # e.g. "D2 O3"
    online: bool | None
    pending: int
    gps: GpsStatus
    alerts: int | None  # None before the first alert list
    ip: str
    temp_c: float | None


def status_lines(view: StatusView) -> list[str]:
    first = {"config": "WAIT CONFIG", "models": "WAIT MODELS"}.get(view.stage, f"DET {view.fps:.1f}fps {view.models}")
    network = {None: "--", True: "ok", False: "offline"}[view.online]
    alerts = "?" if view.alerts is None else _count(view.alerts)
    temp = "" if view.temp_c is None else f" {view.temp_c:.0f}C"
    return [first, f"{'NET ' + network:<{LEFT_COLUMN}}Q {_count(view.pending)}",
            f"{gps_text(view.gps):<{LEFT_COLUMN}}AL {alerts}", f"{view.ip}{temp}"]


def gps_text(status: GpsStatus) -> str:
    if not status.receiving:
        return "GPS --"
    if status.fix is FixType.NONE:
        return f"GPS nofix {status.satellites_in_view}"
    return f"GPS {status.fix.value[-2:]} {status.satellites_used}"


def alert_lines(alert: Alert) -> list[str]:
    text = _ascii(alert.alert_text or "")
    return ["*** ALERT ***", alert.plate, text[:LCD_COLS], text[LCD_COLS:2 * LCD_COLS]]


def _count(n: int) -> str:
    return f"{MAX_SHOWN_COUNT}+" if n > MAX_SHOWN_COUNT else str(n)


def _ascii(text: str) -> str:
    """The LCD has no Polish letters: ą -> a, ł -> l, and so on."""
    text = text.replace("ł", "l").replace("Ł", "L")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


@dataclass(frozen=True)
class StatusSources:
    """Where the status screen reads from; each part is updated by its own thread."""
    configuration: ConfigurationStore
    models: ModelSlot
    detections: PersistentQueue[DetectionEvent]
    gps: LocationSource
    health: CloudHealth
    alerts: AlertWatch


class Feedback:
    def __init__(self, sources: StatusSources, lcd: Lcd | None, beeper: Beeper | None, led,
                 clock=time.monotonic) -> None:
        self.sources = sources
        self.lcd = lcd
        self.beeper = beeper
        self.led = led
        self.clock = clock
        self.frame_rate = FrameRate(clock)
        self._alert: Alert | None = None
        self._alert_until = 0.0
        self._ready = False

    @classmethod
    def open(cls, sources: StatusSources) -> "Feedback":
        return cls(sources, Lcd.open(), Beeper.open(), open_led())

    def on_frame(self, frame: Frame, result: FrameResult) -> None:
        """A frame observer of the loop (loop.py)."""
        self.frame_rate.tick()
        if not self._ready:
            self._ready = True
            self._beep(*READY_BEEPS)
        for event in result.events:
            alert = self.sources.alerts.match(event.plate)
            if alert is not None:
                self._raise(alert, event)

    def run(self, stop: threading.Event) -> None:
        while not stop.wait(REFRESH_SECONDS):
            try:
                self.refresh()
            except OSError as e:  # I2C glitches happen, the next refresh tries again
                log("lcd_error", error=str(e))
            except Exception as e:
                log("feedback_error", level="error", error=repr(e))
        self.close()

    def refresh(self) -> None:
        fps = self.frame_rate.per_second()
        if self.led is not None:
            self.led.value = 1 if fps > 0 else 0
        if self.lcd is None:
            return
        showing_alert = self._alert is not None and self.clock() < self._alert_until
        self.lcd.show(alert_lines(self._alert) if showing_alert else status_lines(self.view(fps)))

    def view(self, fps: float) -> StatusView:
        configuration, loaded = self.sources.configuration.current, self.sources.models.get()
        stage = "config" if configuration is None else "models" if loaded is None else "running"
        models = "" if loaded is None else f"D{_short(loaded.versions.detector)} O{_short(loaded.versions.ocr)}"
        return StatusView(stage, fps, models, self.sources.health.online, self.sources.detections.pending(),
                          self.sources.gps.status(datetime.now(UTC)),
                          len(self.sources.alerts) if self.sources.alerts.loaded else None,
                          system_info.local_ip(), system_info.cpu_temp_c())

    def close(self) -> None:
        try:
            if self.led is not None:
                self.led.off()
            if self.lcd is not None:
                self.lcd.clear()
        except Exception as e:  # shutting down anyway
            log("feedback_close_error", level="warning", error=repr(e))

    def _raise(self, alert: Alert, event: DetectionEvent) -> None:
        # The plate is on the screen for the driver, never in the log: the ids link the alert and the detection.
        log("alert_matched", traceId=event.detection_id, alertId=alert.alert_id)
        self._alert, self._alert_until = alert, self.clock() + ALERT_SCREEN_SECONDS
        self._beep(*ALERT_BEEPS)

    def _beep(self, count: int, length: float) -> None:
        if self.beeper is not None:  # in its own thread: the frame loop never waits for the buzzer
            threading.Thread(target=self.beeper.beep, args=(count, length), daemon=True).start()


def _short(version: str) -> str:
    """'v3' -> '3', so both versions fit on the first line."""
    return version[1:] if version[:1] in "vV" and len(version) > 1 else version
