from detection.cloud.config_poll import ConfigPoller
from detection.config.settings import Settings
from fakes import FakeApi, response

URL = "https://abc.execute-api.eu-central-1.amazonaws.com/api/v1/device/config"


def test_the_poller_sends_the_etag_and_applies_a_new_configuration(tmp_path):
    settings = Settings(tmp_path)
    api = FakeApi(response(200, {"version": 2, "plateCooldownSeconds": 5}, {"ETag": '"2"'}), response(304))
    poller = ConfigPoller(api, URL, settings)
    poller.poll_once()
    assert settings.current.plate_cooldown_seconds == 5
    poller.poll_once()
    assert "If-None-Match" not in api.requests[0]["headers"]
    assert api.requests[1]["headers"]["If-None-Match"] == '"2"'
    assert settings.version == 1


def test_a_failed_poll_keeps_the_settings(tmp_path):
    settings = Settings(tmp_path)
    before = settings.current
    ConfigPoller(FakeApi(response(500), response(404)), URL, settings).poll_once()
    assert settings.current == before and settings.version == 0
