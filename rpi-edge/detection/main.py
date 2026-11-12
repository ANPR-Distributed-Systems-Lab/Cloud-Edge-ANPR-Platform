"""Detection mode: camera -> detector -> send rule -> OCR -> outbox -> batches to the cloud. See DETECTION.md.

This module only assembles the parts. Threads: the frame loop (loop.py, this thread), the configuration poller,
the model updater and the sender. The loop starts once there is a configuration (from the cloud or the copy on
the device) and a set of models (the cache or a download).
"""
import signal
import threading

from common.jsonlog import log
from detection.cloud.api import Api
from detection.cloud.cognito import CognitoAuth
from detection.cloud.config_poll import ConfigPoller
from detection.cloud.model_store import ModelStore
from detection.cloud.model_updater import ModelUpdater
from detection.cloud.transport import Http
from detection.config.environment import Environment, EnvironmentIncomplete
from detection.config.store import ConfigurationStore
from detection.delivery.outbox import Outbox
from detection.delivery.sender import Sender
from detection.loop import run_loop
from detection.pipeline import Pipeline
from detection.vision.camera import Camera
from detection.vision.models import ModelSlot
from detection.vision.replay import ReplayCamera

WORKER_JOIN_SECONDS = 20  # a request in flight finishes or times out; the outbox keeps the rest


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
    models = ModelSlot()
    outbox = Outbox(env.state_dir / "outbox.sqlite3")
    log("detection_starting", cloud=env.api_base_url, authenticated=auth is not None, pending=outbox.pending())

    workers = _start_workers({
        "config-poll": ConfigPoller(api, env.config_url, configuration).run,
        "model-updater": ModelUpdater(ModelStore(env.state_dir / "models", api, http, env.models_url),
                                      configuration, models).run,
        "sender": Sender(outbox, api, env.ingest_url, configuration).run,
    }, stop)
    if configuration.wait_until_configured(stop) and models.wait(stop):
        camera = ReplayCamera(env.replay_dir) if env.replay_dir else Camera()
        run_loop(camera, Pipeline(), configuration, models, outbox, stop)

    log("shutting_down")
    for worker in workers:
        worker.join(timeout=WORKER_JOIN_SECONDS)
    outbox.close()


def _stop_on_signals() -> threading.Event:
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    return stop


def _start_workers(targets: dict, stop: threading.Event) -> list[threading.Thread]:
    workers = [threading.Thread(target=target, args=(stop,), name=name, daemon=True)
               for name, target in targets.items()]
    for worker in workers:
        worker.start()
    return workers
