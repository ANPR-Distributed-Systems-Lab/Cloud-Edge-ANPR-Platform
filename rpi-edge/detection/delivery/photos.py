"""Keeps the photos of the frames that produced detections: JPEG on the SD card, then a row for the uploader.

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
from detection.delivery.queue import PersistentQueue
from detection.delivery.uploads import ImageJob
from detection.pipeline import FrameResult
from detection.vision.frame import Frame

JPEG_QUALITY = 90  # a full frame is 3-5 MB at this quality
MAX_WAITING_FRAMES = 3  # each holds a 37 MB BGR frame
WAIT_SECONDS = 1.0


class FrameSaver:
    def __init__(self, directory: Path, images: PersistentQueue[ImageJob],
                 encode: Callable[[Frame], bytes] | None = None) -> None:
        self.directory = directory
        self.images = images
        self.encode = encode or encode_jpeg
        self._waiting: queue.Queue[tuple[Frame, str]] = queue.Queue(maxsize=MAX_WAITING_FRAMES)
        self.not_saved = 0
        directory.mkdir(parents=True, exist_ok=True)
        for leftover in directory.glob("*.part"):  # a power cut during a write
            leftover.unlink(missing_ok=True)

    def submit(self, frame: Frame, result: FrameResult) -> None:
        """A frame observer of the loop: keeps the photo of a frame that produced detections."""
        if not result.events:
            return
        try:
            self._waiting.put_nowait((frame, result.frame_id))
        except queue.Full:
            self.not_saved += 1
            log("photo_not_saved", level="warning", frameId=result.frame_id, reason="encoder busy",
                not_saved=self.not_saved)

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                frame, frame_id = self._waiting.get(timeout=WAIT_SECONDS)
            except queue.Empty:
                continue
            try:
                self.save(frame, frame_id)
            except Exception as e:  # never let the encoder thread die
                log("photo_error", level="error", frameId=frame_id, error=repr(e))

    def save(self, frame: Frame, frame_id: str) -> None:
        path = self.directory / f"{frame_id}.jpg"
        part = path.with_name(path.name + ".part")
        part.write_bytes(self.encode(frame))
        part.replace(path)
        self.images.add([ImageJob(frame_id, frame.captured_at, path)])


def encode_jpeg(frame: Frame) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("the frame could not be encoded as JPEG")
    return encoded.tobytes()
