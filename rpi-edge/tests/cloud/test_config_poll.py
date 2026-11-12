from fakes import FakeApi, response
from samples import configuration_document

from detection.cloud.config_poll import ConfigPoller
from detection.cloud.transport import NetworkError
from detection.config.store import ConfigurationStore

URL = "https://abc.execute-api.eu-central-1.amazonaws.com/api/v1/device/config"


def test_the_poller_sends_the_etag_and_applies_a_new_configuration(tmp_path):
    store = ConfigurationStore(tmp_path)
    api = FakeApi(response(200, configuration_document(plateCooldownSeconds=5), {"ETag": '"2"'}), response(304))
    poller = ConfigPoller(api, URL, store)
    poller.poll_once()
    assert store.current.plate_cooldown_seconds == 5
    poller.poll_once()
    assert "If-None-Match" not in api.requests[0]["headers"]
    assert api.requests[1]["headers"]["If-None-Match"] == '"2"'
    assert store.version == 1


def test_failed_polls_and_refused_configurations_keep_the_current_one(tmp_path):
    store = ConfigurationStore(tmp_path)
    store.apply(configuration_document(), '"1"')
    before = store.current
    api = FakeApi(response(500), response(404, {"code": "DEVICE_NOT_FOUND"}), NetworkError("offline"),
                  response(200, configuration_document(ml={"minPlateWidthPx": 5}), {"ETag": '"2"'}))
    poller = ConfigPoller(api, URL, store)
    for _ in range(4):
        poller.poll_once()
    assert store.current == before and store.version == 1 and store.etag == '"1"'
