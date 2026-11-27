from fakes import FakeApi, response
from samples import configuration_document

from common import fault_catalog as kinds
from common.faults import FaultBoard
from detection.cloud.config_poll import ConfigPoller
from detection.cloud.transport import NetworkError
from detection.config.store import ConfigurationStore

URL = "https://abc.execute-api.eu-central-1.amazonaws.com/api/v1/device/config"


def test_the_poller_sends_the_etag_and_applies_a_new_configuration(tmp_path):
    store = ConfigurationStore(tmp_path)
    api = FakeApi(response(200, configuration_document(plateCooldownSeconds=5), {"ETag": '"2"'}), response(304))
    poller = ConfigPoller(api, URL, store, FaultBoard())
    poller.poll_once()
    assert store.current.plate_cooldown_seconds == 5
    applied = store.current
    poller.poll_once()
    assert "If-None-Match" not in api.requests[0]["headers"]
    assert api.requests[1]["headers"]["If-None-Match"] == '"2"'
    assert store.current is applied  # a 304 changes nothing


def test_failed_polls_and_refused_configurations_keep_the_current_one(tmp_path):
    store = ConfigurationStore(tmp_path)
    store.apply(configuration_document(), '"1"')
    before = store.current
    api = FakeApi(response(500), response(404, {"code": "DEVICE_NOT_FOUND"}), NetworkError("offline"),
                  response(200, configuration_document(ml={"minPlateWidthPx": 5}), {"ETag": '"2"'}))
    faults = FaultBoard()
    poller = ConfigPoller(api, URL, store, faults)
    for _ in range(4):
        poller.poll_once()
    assert store.current is before and store.etag == '"1"'
    # one 500 is no fault yet, the 404 DEVICE_NOT_FOUND is the account's (cloud/api.py), no answer is none
    assert {f.code for f in faults.active()} == {"config_refused"}


def test_error_answers_in_a_row_are_a_fault_until_a_poll_succeeds(tmp_path):
    store, faults = ConfigurationStore(tmp_path), FaultBoard()
    store.apply(configuration_document(), '"1"')
    poller = ConfigPoller(FakeApi(response(503), response(500), response(502), response(304)), URL, store, faults)
    states = []
    for _ in range(4):
        poller.poll_once()
        states.append([f.code for f in faults.active()])
    assert states == [[], [], ["config_poll_failed"], []]


def test_a_configuration_taken_clears_the_faults_of_the_poll(tmp_path):
    faults = FaultBoard()
    faults.report(kinds.CONFIG_REFUSED)
    faults.report(kinds.NO_CONFIG)
    ConfigPoller(FakeApi(response(200, configuration_document(), {"ETag": '"1"'})), URL, ConfigurationStore(tmp_path),
                 faults).poll_once()
    assert faults.active() == []
