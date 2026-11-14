"""Data collection mode: tune the camera from a browser, take test shots, record frames to a USB stick.

Open http://<pi-address>:8000/ . See DATA_COLLECTION.md.
"""
import os
import signal
import threading

from collection.camera_service import CameraService
from collection.hardware import Hardware
from collection.settings import SettingsStore
from collection.storage import Storage
from collection.web import App, make_server
from common.jsonlog import log

PORT = int(os.environ.get("PORT", 8000))


def main() -> None:
    store = SettingsStore()
    storage = Storage()
    camera = CameraService(store, storage)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    camera.start()
    http = make_server(App(store, storage, camera), PORT)
    threading.Thread(target=http.serve_forever, name="http", daemon=True).start()
    hardware = Hardware(camera)
    log("started", port=PORT)

    stop.wait()

    log("shutting_down")
    hardware.close()
    camera.close()  # stops recording first, so the last frames are flushed
    storage.eject()
    http.shutdown()


if __name__ == "__main__":
    main()
