import threading

from samples import configuration

from detection.cloud.model_store import ModelsUnavailable
from detection.cloud.model_updater import CHECK_SECONDS, RETRY_FIRST_SECONDS, ModelUpdater
from detection.contract.configuration import ModelVersions
from detection.vision.models import LoadedModels, ModelSet, ModelSlot


class FakeConfiguration:
    def __init__(self, detector="v2", ocr="v3"):
        self.current = configuration(models={"detector": detector, "ocr": ocr})


def model_set(detector, ocr="v3"):
    return ModelSet(ModelVersions(detector, ocr), None, None, None)


class FakeStore:
    """install() gives the set of the last fetch(); fetch() fails while `offline`."""

    def __init__(self, cached=None, serves=("v2", "v3"), offline=False):
        self._cached, self.serves, self.offline = cached, serves, offline
        self.fetches = 0

    def cached(self):
        return self._cached

    def fetch(self):
        self.fetches += 1
        if self.offline:
            raise ModelsUnavailable("offline")
        return self.serves

    def install(self, served):
        return model_set(*served)


def load(model_set):
    return LoadedModels(model_set.versions, detector=None, reader=None)


def updater(store, config=None):
    slot = ModelSlot()
    return ModelUpdater(store, config or FakeConfiguration(), slot, load=load), slot


def test_the_cached_set_is_used_at_once_even_offline():
    store = FakeStore(cached=model_set("v1"), offline=True)
    up, slot = updater(store)
    up.load_cached()
    assert slot.get().versions.detector == "v1"
    assert up.update_once() == RETRY_FIRST_SECONDS  # the configuration wants v2: keeps trying
    assert slot.get().versions.detector == "v1"  # and keeps detecting with what it has


def test_a_new_version_in_the_configuration_is_downloaded_and_swapped_in():
    store = FakeStore(cached=model_set("v1"))
    up, slot = updater(store)
    up.load_cached()
    assert up.update_once() == CHECK_SECONDS
    assert slot.get().versions == ModelVersions("v2", "v3")
    assert up.update_once() == CHECK_SECONDS and store.fetches == 1  # nothing to do any more


def test_failures_back_off():
    up, slot = updater(FakeStore(offline=True))
    waits = [up.update_once() for _ in range(4)]
    assert waits == sorted(waits) and waits[-1] > waits[0]
    assert slot.get() is None


def test_nothing_happens_before_the_first_configuration():
    config = FakeConfiguration()
    config.current = None
    up, slot = updater(FakeStore(), config)
    assert up.update_once() == CHECK_SECONDS and slot.get() is None


def test_the_slot_hands_over_the_loaded_set():
    slot, stop = ModelSlot(), threading.Event()
    slot.put(load(model_set("v2")))
    assert slot.wait(stop).versions.detector == "v2"
