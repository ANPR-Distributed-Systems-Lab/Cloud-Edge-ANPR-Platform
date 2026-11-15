"""Keeps the photos of the frames that produced detections: JPEG on the SD card, then a row for the uploader.

The photo is the frame at photos.widthPx (a narrower setting downscales it, keeping the aspect ratio) and
photos.jpegQuality, both as configured when the frame was analysed. The corners of a detection are relative to the
frame, so they fit the photo at any size.

The frame loop must not wait for the encoder, so a frame is handed over here and encoded by a background thread. When
the encoder is behind (a few frames queued), further photos are not saved and counted: a detection without a photo is
better than a slower detection. The photo is written to a .part file first, so a power cut never leaves half a JPEG
under its final name.
"""
import queue
import threading
from collections.abc import Callable
from pathlib import Path

import cv2

from common.jsonlog import log
from detection.config.store import ConfigurationStore
from detection.contract.configuration import PhotosConfiguration
from detection.delivery.queue import PersistentQueue
from detection.delivery.uploads import ImageJob
from detection.pipeline import FrameResult
from detection.vision.frame import Frame

MAX_WAITING_FRAMES = 3  # each holds a 37 MB BGR frame
WAIT_SECONDS = 1.0


class FrameSaver:
    def __init__(self, directory: Path, images: PersistentQueue[ImageJob], configuration: ConfigurationStore,
                 encode: Callable[[Frame, PhotosConfiguration], bytes] | None = None) -> None:
        self.directory = directory
        self.images = images
        self.configuration = configuration
        self.encode = encode or encode_jpeg
        self._waiting: queue.Queue[tuple[Frame, str, PhotosConfiguration]] = queue.Queue(maxsize=MAX_WAITING_FRAMES)
        self.not_saved = 0
        directory.mkdir(parents=True, exist_ok=True)
        for leftover in directory.glob("*.part"):  # a power cut during a write
            leftover.unlink(missing_ok=True)

    def submit(self, frame: Frame, result: FrameResult) -> None:
        """A frame observer of the loop: keeps the photo of a frame that produced detections."""
        if not result.events:
            return
        try:
            self._waiting.put_nowait((frame, result.frame_id, self.configuration.current.photos))
        except queue.Full:
            self.not_saved += 1
            log("photo_not_saved", level="warning", frameId=result.frame_id, reason="encoder busy",
                not_saved=self.not_saved)

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                frame, frame_id, photos = self._waiting.get(timeout=WAIT_SECONDS)
            except queue.Empty:
                continue
            try:
                self.save(frame, frame_id, photos)
            except Exception as e:  # never let the encoder thread die
                log("photo_error", level="error", frameId=frame_id, error=repr(e))

    def save(self, frame: Frame, frame_id: str, photos: PhotosConfiguration) -> None:
        path = self.directory / f"{frame_id}.jpg"
        part = path.with_name(path.name + ".part")
        part.write_bytes(self.encode(frame, photos))
        part.replace(path)
        self.images.add([ImageJob(frame_id, frame.captured_at, path)])


def encode_jpeg(frame: Frame, photos: PhotosConfiguration) -> bytes:
    """A full frame at quality 90 is 1.5-5 MB, depending on the scene; half the width is about a quarter of that."""
    image = frame.image
    height, width = image.shape[:2]
    if photos.width_px < width:  # INTER_AREA: the filter for shrinking, no aliasing on the plate characters
        size = (photos.width_px, round(height * photos.width_px / width))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, photos.jpeg_quality])
    if not ok:
        raise ValueError("the frame could not be encoded as JPEG")
    return encoded.tobytes()
