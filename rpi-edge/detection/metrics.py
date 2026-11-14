"""Measures the health of the device every intervals.metricsSeconds and queues it for POST /api/v1/device/metrics.

View 5 charts these for the owner and View 4 shows the device online while the latest measurement is young, so a
device that analyses frames but sends no metrics looks offline. Measurements taken while there is no network wait in
the queue (store-and-forward) and go out together afterwards.
"""
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from common import system_info
from common.jsonlog import log
from detection.config.store import ConfigurationStore
from detection.contract.metrics import DeviceMetric, GpsState, QueueLengths
from detection.delivery.queues import Queues
from detection.gps.source import LocationSource
from detection.throughput import FrameCounter

FIRST_MEASUREMENT_SECONDS = 5.0  # soon after the start, so the device shows online without waiting a whole interval
UNCONFIGURED_WAIT_SECONDS = 5.0


class MetricsSampler:
    def __init__(self, queues: Queues, gps: LocationSource, frames: FrameCounter, configuration: ConfigurationStore,
                 state_dir: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.queues = queues
        self.gps = gps
        self.frames = frames
        self.configuration = configuration
        self.state_dir = state_dir
        self.clock = clock
        self._previous_frames = frames.total
        self._previous_at = clock()
        system_info.cpu_usage_percent()  # the first call has no earlier call to measure against

    def run(self, stop: threading.Event) -> None:
        stop.wait(FIRST_MEASUREMENT_SECONDS)
        while not stop.is_set():
            wait = UNCONFIGURED_WAIT_SECONDS
            try:
                if self.configuration.current is not None:
                    self.measure_once()
                    wait = self.configuration.current.intervals.metrics_seconds
            except Exception as e:  # never let the sampler thread die
                log("metrics_error", level="error", error=repr(e))
            stop.wait(wait)

    def measure_once(self) -> DeviceMetric | None:
        """Takes one measurement and queues it. None when the CPU temperature cannot be read (the contract requires
        it, and a made-up value would chart as a fact)."""
        now = self.clock()
        temperature = system_info.cpu_temp_c()
        if temperature is None:
            log("metrics_skipped", level="warning", reason="no CPU temperature")
            return None
        gps = self.gps.status(now)
        metric = DeviceMetric(
            recorded_at=now,
            cpu_temperature_c=temperature,
            cpu_usage_percent=system_info.cpu_usage_percent(),
            ram_usage_percent=system_info.ram_usage_percent(),
            processing_fps=self._frames_per_second(now),
            queues=QueueLengths(self.queues.detections.pending(), self.queues.locations.pending(),
                                self.queues.images.pending()),
            disk_free_mb=system_info.disk_free_mb(self.state_dir),
            uptime_seconds=system_info.uptime_seconds(),
            gps=GpsState(gps.fix, gps.satellites_used),
        )
        self.queues.metrics.add([metric])
        return metric

    def _frames_per_second(self, now: datetime) -> float:
        """Frames analysed per second since the previous measurement."""
        total, elapsed = self.frames.total, (now - self._previous_at).total_seconds()
        frames, self._previous_frames, self._previous_at = total - self._previous_frames, total, now
        return frames / elapsed if elapsed > 0 else 0.0
