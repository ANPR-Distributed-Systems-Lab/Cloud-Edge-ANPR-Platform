import json
import threading

import pytest
from samples import configuration_document

from detection.config.store import CACHE_FILE, ConfigurationStore
from detection.contract.parsing import ContractError


def test_a_device_without_a_configuration_has_none(tmp_path):
    store = ConfigurationStore(tmp_path)
    assert store.current is None and store.etag is None and store.version == 0
    stop = threading.Event()
    stop.set()
    assert store.wait_until_configured(stop) is None


def test_a_configuration_from_the_cloud_is_applied_and_kept_for_the_next_start(tmp_path):
    store = ConfigurationStore(tmp_path)
    assert store.apply(configuration_document(), '"3"') is True
    assert store.version == 1 and store.current.ml.ocr_min_confidence == 0.80
    assert store.wait_until_configured(threading.Event()) == store.current

    restarted = ConfigurationStore(tmp_path)
    assert restarted.current == store.current and restarted.etag == '"3"'
    assert restarted.apply(configuration_document(), '"3"') is False  # the same again: no change
    assert restarted.apply(configuration_document(ml={"ocrMinConfidence": 0.9}), '"4"') is True
    assert restarted.version == 2


def test_a_configuration_outside_the_contract_is_refused_and_the_current_one_stays(tmp_path):
    store = ConfigurationStore(tmp_path)
    store.apply(configuration_document(), '"3"')
    with pytest.raises(ContractError):
        store.apply(configuration_document(ml={"ocrMinConfidence": 7}), '"4"')
    assert store.current.ml.ocr_min_confidence == 0.80 and store.etag == '"3"'
    assert json.loads((tmp_path / CACHE_FILE).read_text())["etag"] == '"3"'


def test_an_unusable_copy_is_ignored(tmp_path):
    (tmp_path / CACHE_FILE).write_text(json.dumps({"etag": '"1"', "configuration": {"version": 1}}))
    assert ConfigurationStore(tmp_path).current is None
    (tmp_path / CACHE_FILE).write_text("{not json")
    assert ConfigurationStore(tmp_path).current is None
