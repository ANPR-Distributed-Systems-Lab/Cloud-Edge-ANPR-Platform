"""Feedback: the LCD, the LEDs, the buzzer and the two tact switches in the detection mode.

Refreshes the screen and the LEDs every REFRESH_SECONDS (at once after a press of the page switch). A short press
of the run switch stops or starts the analysis (one beep: started, two: stopped). Buzzer: one short beep when the
first frame is analysed, three long ones for an alert, one tone of 3 s when a fault appears (common/faults.py).

The last plates for the LCD are kept in memory only, like the alert list: never written to disk or logged.
"""
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from common import system_info
from common.display import Pages
from common.faults import FaultAlarm, FaultBoard
from common.jsonlog import log
from common.peripherals import Peripherals
from detection.cloud.api import CloudHealth
from detection.config.store import ConfigurationStore
from detection.contract.alerts import Alert
from detection.contract.ingest import DetectionEvent
from detection.delivery.queues import Queues
from detection.feedback.faults import detection_faults, quarantined
from detection.feedback.lights import light_states
from detection.feedback.screens import PAGES, LastPlate, Snapshot, Stage, Waiting, alert_lines
from detection.gps.source import LocationSource
from detection.loop import Hold
from detection.pipeline import FrameResult
from detection.rules.alerts import AlertWatch
from detection.vision.frame import Frame
from detection.vision.models import ModelSlot

REFRESH_SECONDS = 1.0
FPS_WINDOW_SECONDS = 10.0
ALERT_SCREEN_SECONDS = 15.0
ALERT_BEEPS = (3, 0.4)  # count, seconds each
READY_BEEPS = (1, 0.12)
STARTED_BEEPS, STOPPED_BEEPS = (1, 0.12), (2, 0.12)
LAST_PLATES = 2


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
class FeedbackSources:
    """Where the screen and the LEDs read from; each part is updated by its own thread."""
    configuration: ConfigurationStore
    models: ModelSlot
    queues: Queues
    gps: LocationSource
    health: CloudHealth
    alerts: AlertWatch
    faults: FaultBoard
    hold: Hold
    state_dir: Path  # on the SD card: its free space


class Feedback:
    def __init__(self, sources: FeedbackSources, peripherals: Peripherals, clock=time.monotonic) -> None:
        self.sources = sources
        self.peripherals = peripherals
        self.clock = clock
        self.frame_rate = FrameRate(clock)
        self.pages = Pages(len(PAGES), peripherals.page_switch)
        self.alarm = FaultAlarm(peripherals.beep_later, clock)
        self._last_plates: deque[tuple[str, float, bool]] = deque(maxlen=LAST_PLATES)  # plate, read at, alert
        self._alert: Alert | None = None
        self._alert_until = 0.0
        self._alert_seen = False  # an alert since the analysis started: the alert LED stays on
        self._ready = False
        self._quarantined_at_start = quarantined(sources.queues)  # the fault counts only new refusals
        if peripherals.run_switch is not None:
            peripherals.run_switch.on_press = self.toggle_hold

    def on_frame(self, frame: Frame, result: FrameResult) -> None:
        """A frame observer of the loop (loop.py)."""
        self.frame_rate.tick()
        if not self._ready:
            self._ready = True
            self.peripherals.beep_later(*READY_BEEPS)
        for event in result.events:
            alert = self.sources.alerts.match(event.plate)
            self._last_plates.appendleft((event.plate, self.clock(), alert is not None))
            if alert is not None:
                self._raise(alert, event)

    def toggle_hold(self) -> None:
        """The short press of the run switch: stops or starts the analysis."""
        held = self.sources.hold.toggle()
        self._alert, self._alert_seen = None, False
        log("detection_stopped_by_driver" if held else "detection_started_by_driver")
        self.peripherals.beep(*(STOPPED_BEEPS if held else STARTED_BEEPS))

    def run(self, stop: threading.Event) -> None:
        """Refreshes until `stop`; main.py clears the screen and the LEDs afterwards (Peripherals.reset)."""
        while not stop.is_set():
            self.pages.wait(REFRESH_SECONDS)
            if stop.is_set():
                break
            try:
                self.refresh()
            except Exception as e:  # the next refresh tries again
                log("feedback_error", level="error", error=repr(e))

    def refresh(self) -> None:
        snapshot = self.snapshot()
        self.alarm.check(list(snapshot.faults))
        alert_showing = self._alert is not None and self.clock() < self._alert_until
        self.peripherals.lights.show(**light_states(snapshot, alert_showing, self._alert_seen))
        page = PAGES[self.pages.index]
        self.peripherals.show(alert_lines(self._alert) if alert_showing else page(snapshot, self.pages))

    def snapshot(self) -> Snapshot:
        src, now = self.sources, datetime.now(UTC)
        configuration, loaded = src.configuration.current, src.models.get()
        if src.hold.held:
            stage = Stage.STOPPED
        elif configuration is None:
            stage = Stage.WAIT_CONFIG
        else:
            stage = Stage.WAIT_MODELS if loaded is None else Stage.RUNNING
        gps, fix = src.gps.status(now), src.gps.latest_fix()
        fix_age = None if fix is None else max(0.0, (now - fix.received_at).total_seconds())
        if configuration is None or fix_age is None:
            fresh = fix_age is not None
        else:
            fresh = fix_age <= configuration.gps.max_fix_age_seconds
        sd_free_mb = _sd_free_mb(src.state_dir)
        temp_c = system_info.cpu_temp_c()
        now_quarantined = quarantined(src.queues)
        # The retention prunes old rows: the count from the start goes down with them, so new ones still count.
        self._quarantined_at_start = min(self._quarantined_at_start, now_quarantined)
        refused = now_quarantined - self._quarantined_at_start
        faults = detection_faults(src.faults, src.health, refused, sd_free_mb, system_info.power_flags(), temp_c)
        clock = self.clock()
        return Snapshot(
            stage=stage,
            fps=self.frame_rate.per_second(),
            online=src.health.online,
            sign_in_failed=src.health.sign_in_failed,
            forbidden=src.health.forbidden,
            gps=gps,
            fix_seconds_ago=fix_age,
            fix_fresh=fresh,
            accuracy_m=None if fix is None else fix.accuracy_m,
            speed_mps=None if fix is None else fix.speed_mps,
            waiting=Waiting(src.queues.detections.pending(), src.queues.locations.pending(),
                            src.queues.images.pending()),
            faults=tuple(faults),
            ip=system_info.local_ip(),
            temp_c=temp_c,
            config_version=None if configuration is None else configuration.version,
            models=None if loaded is None else loaded.versions,
            sd_free_mb=sd_free_mb,
            last_plates=tuple(LastPlate(plate, clock - at, alert) for plate, at, alert in self._last_plates),
            alert_list=len(src.alerts) if src.alerts.loaded else None,
        )

    def _raise(self, alert: Alert, event: DetectionEvent) -> None:
        # The plate is on the screen for the driver, never in the log: the ids link the alert and the detection.
        log("alert_matched", traceId=event.detection_id, alertId=alert.alert_id)
        self._alert, self._alert_until, self._alert_seen = alert, self.clock() + ALERT_SCREEN_SECONDS, True
        self.peripherals.beep_later(*ALERT_BEEPS)


def _sd_free_mb(path: Path) -> int | None:
    try:
        return system_info.disk_free_mb(path)
    except OSError:
        return None
