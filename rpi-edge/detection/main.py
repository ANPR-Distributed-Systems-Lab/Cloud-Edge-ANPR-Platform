"""Detection mode: camera -> detector -> send rule -> OCR -> outbox -> batches to the cloud. See DETECTION.md.

This module only assembles the parts. Threads: the frame loop (loop.py), the sender, and the configuration poller
when the cloud is set up.
"""
import signal
import threading

from common.jsonlog import log
from detection.cloud.api import Api
from detection.cloud.cognito import CognitoAuth
from detection.cloud.config_poll import ConfigPoller
from detection.cloud.model_store import ModelSet, ModelStore
from detection.cloud.transport import Http
from detection.config.environment import Environment
from detection.config.settings import Settings
from detection.delivery.outbox import Outbox
from detection.delivery.sender import Sender
from detection.loop import run_loop
from detection.pipeline import Pipeline
from detection.vision.camera import Camera
from detection.vision.detector import Detector
from detection.vision.ocr import Reader
from detection.vision.replay import ReplayCamera

WORKER_JOIN_SECONDS = 20  # a request in flight finishes or times out; the outbox keeps the rest


def main() -> None:
    env = Environment.from_env()
    settings = Settings(env.config_dir)
    stop = _stop_on_signals()
    http = Http()
    auth = CognitoAuth(env.cognito_region, env.cognito_client_id, env.credentials_file, http) if env.signs_in else None
    api = Api(http, auth, env.api_base_url)
    outbox = Outbox(env.state_dir / "outbox.sqlite3")
    log("detection_starting", cloud=env.api_base_url, ingest=env.ingest_url, models=env.models_manifest_url,
        authenticated=auth is not None, pending=outbox.pending())

    workers = _start_workers(env, api, settings, outbox, stop)
    models = ModelStore(env.state_dir / "models", api, http, env.models_manifest_url).wait_for_models(stop)
    if models is not None:
        camera = ReplayCamera(env.replay_dir) if env.replay_dir else Camera()
        run_loop(camera, _pipeline(models), settings, outbox, stop)

    log("shutting_down")
    for worker in workers:
        worker.join(timeout=WORKER_JOIN_SECONDS)
    outbox.close()


def _stop_on_signals() -> threading.Event:
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    return stop


def _start_workers(env: Environment, api: Api, settings: Settings, outbox: Outbox,
                   stop: threading.Event) -> list[threading.Thread]:
    targets = {}
    if env.ingest_url:
        targets["sender"] = Sender(outbox, api, env.ingest_url, settings).run
    else:
        log("sender_disabled", level="warning", hint="set API_BASE_URL or INGEST_URL in rpi-edge/.env")
    if env.config_url:
        targets["config-poll"] = ConfigPoller(api, env.config_url, settings).run
    workers = [threading.Thread(target=target, args=(stop,), name=name, daemon=True)
               for name, target in targets.items()]
    for worker in workers:
        worker.start()
    return workers


def _pipeline(models: ModelSet) -> Pipeline:
    pipeline = Pipeline(Detector(str(models.detector)), Reader(str(models.ocr), str(models.ocr_config)))
    log("models_loaded", versions=models.versions, detector_input=list(pipeline.detector.input_size))
    return pipeline
