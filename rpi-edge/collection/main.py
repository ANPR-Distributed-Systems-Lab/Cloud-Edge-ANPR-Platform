"""Data collection mode: tune the camera from a browser, take test shots, record frames to a USB stick.

Open http://<pi-address>:8000/ . See DATA_COLLECTION.md. main.py runs it until the mode is switched or the
container stops.
"""
import os
import threading

from collection.camera_service import CameraService
from collection.hardware import Hardware
from collection.settings import SettingsStore
from collection.storage import Storage
from collection.web import App, make_server
from common.jsonlog import log
from common.peripherals import Peripherals

PORT = int(os.environ.get("PORT", 8000))


def run(stop: threading.Event, peripherals: Peripherals) -> None:
    """Runs until `stop`, then releases the camera, the USB stick and the port, so the detection mode can take over."""
    store = SettingsStore()
    storage = Storage()
    camera = CameraService(store, storage)
    camera.start()
    http = make_server(App(store, storage, camera), PORT)
    threading.Thread(target=http.serve_forever, name="http", daemon=True).start()
    hardware = Hardware(camera, peripherals)
    log("collection_started", port=PORT)

    stop.wait()

    log("collection_stopping")
    hardware.close()
    camera.close()  # stops recording first, so the last frames are flushed
    storage.eject()
    http.shutdown()
    http.server_close()  # frees the port for the next start of this mode
