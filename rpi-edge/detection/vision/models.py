"""The models the frame loop runs, and the hand-over of a new set from the model updater without a restart.

The updater (cloud/model_updater.py) downloads and loads a new set in its own thread while the loop keeps
detecting with the old one; ModelSlot.put() then swaps the reference, and the next frame uses the new set.
"""
import threading
from dataclasses import dataclass
from pathlib import Path

from detection.contract.configuration import ModelVersions
from detection.vision.detector import Detector
from detection.vision.ocr import Reader


@dataclass(frozen=True)
class ModelSet:
    """The files of one installed set, checked against their SHA-256 (cloud/model_store.py)."""
    versions: ModelVersions
    detector: Path
    ocr: Path
    ocr_config: Path


@dataclass(frozen=True)
class LoadedModels:
    versions: ModelVersions
    detector: Detector
    reader: Reader

    @classmethod
    def load(cls, model_set: ModelSet) -> "LoadedModels":
        """Creates the ONNX Runtime sessions; takes a few seconds on the Pi."""
        return cls(model_set.versions, Detector(str(model_set.detector)),
                   Reader(str(model_set.ocr), str(model_set.ocr_config)))


class ModelSlot:
    """The current models, shared by the updater (writes) and the frame loop (reads)."""

    def __init__(self) -> None:
        self._models: LoadedModels | None = None
        self._ready = threading.Event()

    def put(self, models: LoadedModels) -> None:
        self._models = models  # one reference assignment: a reader gets the old or the new set, never a mix
        self._ready.set()

    def get(self) -> LoadedModels | None:
        return self._models

    def wait(self, stop: threading.Event) -> LoadedModels | None:
        """Blocks until a set is loaded (None if stopped first)."""
        while not stop.is_set():
            if self._ready.wait(timeout=1.0):
                return self._models
        return None
