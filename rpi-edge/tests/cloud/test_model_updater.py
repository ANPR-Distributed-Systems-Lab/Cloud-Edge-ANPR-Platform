import threading

from samples import configuration

from common.faults import FaultBoard
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


def updater(store, config=None, faults=None):
    slot = ModelSlot()
    return ModelUpdater(store, config or FakeConfiguration(), slot, faults or FaultBoard(), load=load), slot


def test_the_cached_set_is_used_at_once_even_offline():
    store, faults = FakeStore(cached=model_set("v1"), offline=True), FaultBoard()
    up, slot = updater(store, faults=faults)
    up.load_cached()
    assert slot.get().versions.detector == "v1"
    assert up.update_once() == RETRY_FIRST_SECONDS  # the configuration wants v2: keeps trying
    assert slot.get().versions.detector == "v1"  # and keeps detecting with what it has
    assert faults.active() == []  # no answer while a set runs: the network LED shows it
    store.offline = False
    assert up.update_once() == CHECK_SECONDS and faults.active() == []


def test_a_new_version_in_the_configuration_is_downloaded_and_swapped_in():
    store = FakeStore(cached=model_set("v1"))
    up, slot = updater(store)
    up.load_cached()
    assert up.update_once() == CHECK_SECONDS
    assert slot.get().versions == ModelVersions("v2", "v3")
    assert up.update_once() == CHECK_SECONDS and store.fetches == 1  # nothing to do any more


def test_failures_back_off():
    faults = FaultBoard()
    up, slot = updater(FakeStore(offline=True), faults=faults)
    waits = [up.update_once() for _ in range(4)]
    assert waits == sorted(waits) and waits[-1] > waits[0]
    assert slot.get() is None and [f.text for f in faults.active()] == ["no models"]


def test_nothing_happens_before_the_first_configuration():
    config = FakeConfiguration()
    config.current = None
    up, slot = updater(FakeStore(), config)
    assert up.update_once() == CHECK_SECONDS and slot.get() is None


def test_the_slot_hands_over_the_loaded_set():
    slot, stop = ModelSlot(), threading.Event()
    slot.put(load(model_set("v2")))
    assert slot.wait(stop).versions.detector == "v2"


class AnsweringStore(FakeStore):
    """fetch() fails with the given error answer."""

    def __init__(self, error, **kwargs):
        super().__init__(**kwargs)
        self.error = error

    def fetch(self):
        self.fetches += 1
        raise self.error


def test_a_version_that_is_not_published_is_its_own_fault():
    faults = FaultBoard()
    up, _ = updater(AnsweringStore(ModelsUnavailable("HTTP 409", answered=True, code="MODEL_NOT_PUBLISHED"),
                                   cached=model_set("v1")), faults=faults)
    up.load_cached()
    up.update_once()
    assert [f.code for f in faults.active()] == ["model_not_published"]


def test_error_answers_in_a_row_while_an_older_set_runs():
    faults = FaultBoard()
    up, _ = updater(AnsweringStore(ModelsUnavailable("HTTP 503", answered=True), cached=model_set("v1")),
                    faults=faults)
    up.load_cached()
    states = []
    for _ in range(3):
        up.update_once()
        states.append([f.code for f in faults.active()])
    assert states == [[], [], ["models_not_updated"]]


def test_a_cached_set_that_does_not_load_is_a_fault_and_the_updater_goes_on():
    faults, stop = FaultBoard(), threading.Event()

    def broken(model_set):
        stop.set()
        raise RuntimeError("onnx refuses it")

    up = ModelUpdater(FakeStore(cached=model_set("v2")), FakeConfiguration(), ModelSlot(), faults, load=broken)
    up.run(stop)
    assert [f.code for f in faults.active()] == ["model_load_failed"]
