"""Detection mode: camera -> detector -> send rule -> OCR -> queues -> batches to the cloud. See DETECTION.md.

This module only assembles the parts. The frame loop (loop.py) runs in this thread; everything else has a thread of its
own, started here:

  config-poll     the device configuration of device-management             cloud/config_poll.py
  model-updater   downloads and swaps in the model versions of the config   cloud/model_updater.py
  alert-poll      the alert list of the owner                               cloud/alert_poll.py
  gps             reads the NMEA stream of the GNSS module                  gps/serial_reader.py
  locations       records the track of the device                           gps/recorder.py
  metrics         measures the health of the device                         metrics.py
  photos          encodes the photos of the frames of detections            delivery/photos.py
  uploader        uploads the photos to S3                                  delivery/uploads.py
  send-<stream>   sends detections, locations and metrics in batches        delivery/sender.py
  feedback        the LCD, buzzer and LED in the car                        feedback.py

The loop starts once there is a configuration (from the cloud or the copy on the device) and a set of models (the
cache or a download).
"""
import signal
import threading
from collections.abc import Callable

from common.jsonlog import log
from detection.cloud.alert_poll import AlertPoller
from detection.cloud.api import Api
from detection.cloud.cognito import CognitoAuth
from detection.cloud.config_poll import ConfigPoller
from detection.cloud.model_store import ModelStore
from detection.cloud.model_updater import ModelUpdater
from detection.cloud.transport import Http
from detection.config.environment import Environment, EnvironmentIncomplete
from detection.config.store import ConfigurationStore
from detection.delivery.photos import FrameSaver
from detection.delivery.queues import Queues, streams
from detection.delivery.sender import Sender
from detection.delivery.uploads import ImageUploader
from detection.feedback import Feedback, StatusSources
from detection.gps.recorder import LocationRecorder
from detection.gps.serial_reader import SerialGpsReader
from detection.gps.source import FixedLocationSource, LocationSource, NoLocationSource
from detection.gps.tracker import GpsTracker
from detection.loop import FrameLoop
from detection.metrics import MetricsSampler
from detection.pipeline import Pipeline
from detection.rules.alerts import AlertWatch
from detection.throughput import FrameCounter
from detection.vision.camera import Camera
from detection.vision.models import ModelSlot
from detection.vision.replay import ReplayCamera

WORKER_JOIN_SECONDS = 20  # a request in flight finishes or times out; the queues keep the rest

Worker = Callable[[threading.Event], None]


def main() -> None:
    try:
        env = Environment.from_env()
    except EnvironmentIncomplete as e:
        log("detection_not_configured", level="error", error=str(e))
        raise SystemExit(1) from None
    stop = _stop_on_signals()
    http = Http()
    auth = CognitoAuth(env.cognito_region, env.cognito_client_id, env.credentials_file, http) if env.signs_in else None
    api = Api(http, auth, env.api_base_url)
    configuration = ConfigurationStore(env.config_dir)
    models, alerts, frames = ModelSlot(), AlertWatch(), FrameCounter()
    queues = Queues.open(env.state_dir / "outbox")
    gps, gps_workers = _gnss(env)
    feedback = Feedback.open(StatusSources(configuration, models, queues.detections, gps, api.health, alerts))
    photos = FrameSaver(env.state_dir / "frames", queues.images)
    log("detection_starting", cloud=env.api_base_url, authenticated=auth is not None, gps=_gps_kind(env),
        pending=queues.detections.pending())

    workers = _start_workers({
        "config-poll": ConfigPoller(api, env.config_url, configuration).run,
        "model-updater": ModelUpdater(ModelStore(env.state_dir / "models", api, http, env.models_url),
                                      configuration, models).run,
        "alert-poll": AlertPoller(api, env.alerts_url, alerts, configuration).run,
        **gps_workers,
        "locations": LocationRecorder(gps, queues.locations, configuration).run,
        "metrics": MetricsSampler(queues, gps, frames, configuration, env.state_dir).run,
        "photos": photos.run,
        "uploader": ImageUploader(queues.images, api, http, env.image_urls_url, configuration).run,
        **{f"send-{s.name}": Sender(s, api, configuration).run for s in streams(queues, env)},
        "feedback": feedback.run,
    }, stop)
    if configuration.wait_until_configured(stop) and models.wait(stop):
        camera = ReplayCamera(env.replay_dir) if env.replay_dir else Camera()
        FrameLoop(camera, Pipeline(), configuration, models, gps, queues.detections,
                  observers=(feedback.on_frame, photos.submit, lambda frame, result: frames.tick())).run(stop)

    log("shutting_down")
    for worker in workers:
        worker.join(timeout=WORKER_JOIN_SECONDS)
    queues.close()


def _gnss(env: Environment) -> tuple[LocationSource, dict[str, Worker]]:
    """Where the position comes from (the GNSS module, a fixed position for development, or nothing), and the thread
    that reads the module, if there is one."""
    if env.gps_device:
        tracker = GpsTracker()
        return tracker, {"gps": SerialGpsReader(tracker, env.gps_device, env.gps_baud).run}
    if env.gps_fixed_location:
        return FixedLocationSource(*env.gps_fixed_location), {}
    log("gps_not_configured", level="warning",
        hint="set GPS_DEVICE (or GPS_FIXED_LOCATION for development): without a position no plate is read")
    return NoLocationSource(), {}


def _gps_kind(env: Environment) -> str:
    return "module" if env.gps_device else "fixed" if env.gps_fixed_location else "none"


def _stop_on_signals() -> threading.Event:
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    return stop


def _start_workers(targets: dict[str, Worker], stop: threading.Event) -> list[threading.Thread]:
    workers = [threading.Thread(target=target, args=(stop,), name=name, daemon=True)
               for name, target in targets.items()]
    for worker in workers:
        worker.start()
    return workers
