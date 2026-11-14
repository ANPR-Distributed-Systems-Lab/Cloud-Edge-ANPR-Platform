"""Recorded frames instead of the camera (REPLAY_DIR), for developing and testing the mode without a car.

Reads the JPEGs of a directory (e.g. a session of the collection mode, subfolders included) in name order and
starts again after the last one, as if the camera kept running. A frame's capture time is the time it is read.
"""
from datetime import UTC, datetime
from pathlib import Path

import cv2

from common.jsonlog import log
from detection.contract.configuration import CameraConfiguration
from detection.vision.frame import Frame


class ReplayCamera:
    def __init__(self, directory: Path) -> None:
        # Names starting with a dot are the half-written files of the collection mode.
        self.files = sorted(p for p in directory.rglob("*.jpg") if not p.name.startswith("."))
        if not self.files:
            raise ValueError(f"no JPEG frames in {directory}")
        self.index = 0
        self.is_open = False

    def open(self, camera: CameraConfiguration) -> None:
        self.is_open = True
        log("replay_started", frames=len(self.files))

    def apply(self, camera: CameraConfiguration) -> None:
        pass

    def capture(self) -> Frame:
        path = self.files[self.index % len(self.files)]
        self.index += 1
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"cannot decode {path.name}")
        return Frame(image, datetime.now(UTC))

    def close(self) -> None:
        self.is_open = False
