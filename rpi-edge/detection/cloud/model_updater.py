"""Keeps the models of the device at the versions its configuration names (models.detector, models.ocr).

Runs in its own thread. At startup it hands the cached set to the frame loop at once, whatever its versions, so
the device detects without network. Whenever the loaded versions differ from the configuration it fetches the
download URLs, installs the files and loads the new set, while the loop goes on with the old one; then it swaps
them (vision/models.py). A failure keeps the old set and is retried with a growing delay.
"""
import threading
from collections.abc import Callable
from dataclasses import asdict

from common.jsonlog import log
from detection.cloud.model_store import ModelStore, ModelsUnavailable
from detection.config.store import ConfigurationStore
from detection.vision.models import LoadedModels, ModelSet, ModelSlot

CHECK_SECONDS = 5.0  # how soon a changed configuration is noticed
RETRY_FIRST_SECONDS = 5.0
RETRY_MAX_SECONDS = 300.0


class ModelUpdater:
    def __init__(self, store: ModelStore, configuration: ConfigurationStore, slot: ModelSlot,
                 load: Callable[[ModelSet], LoadedModels] = LoadedModels.load) -> None:
        self.store = store
        self.configuration = configuration
        self.slot = slot
        self.load = load
        self.failures = 0

    def run(self, stop: threading.Event) -> None:
        self.load_cached()
        while not stop.is_set():
            try:
                wait = self.update_once()
            except Exception as e:  # never let the updater thread die; a model that fails to load lands here
                log("models_update_error", level="error", error=repr(e))
                wait = self._retry_delay()
            stop.wait(wait)

    def load_cached(self) -> None:
        cached = self.store.cached()
        if cached is not None:
            self.slot.put(self.load(cached))
            log("models_loaded", source="cache", detector=cached.versions.detector, ocr=cached.versions.ocr)

    def update_once(self) -> float:
        """One step. Returns the seconds to wait before the next one."""
        configuration = self.configuration.current
        loaded = self.slot.get()
        if configuration is None or (loaded is not None and loaded.versions == configuration.models):
            self.failures = 0
            return CHECK_SECONDS
        wanted = configuration.models
        try:
            model_set = self.store.install(self.store.fetch())
        except ModelsUnavailable as e:
            log("models_update_failed", level="warning", detector=wanted.detector, ocr=wanted.ocr, error=str(e),
                running=None if loaded is None else asdict(loaded.versions))
            return self._retry_delay()
        self.slot.put(self.load(model_set))
        log("models_loaded", source="cloud", detector=model_set.versions.detector, ocr=model_set.versions.ocr)
        if model_set.versions != wanted:  # the configuration changed again meanwhile
            return self._retry_delay()
        self.failures = 0
        return CHECK_SECONDS

    def _retry_delay(self) -> float:
        self.failures += 1
        return min(RETRY_FIRST_SECONDS * 2 ** (self.failures - 1), RETRY_MAX_SECONDS)
