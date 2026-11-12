from pathlib import Path

import pytest

from detection.config.environment import Environment, EnvironmentIncomplete

BASE = "https://abc.execute-api.eu-central-1.amazonaws.com"


def test_the_endpoints_derive_from_the_api_base_url():
    env = Environment.from_env({"API_BASE_URL": BASE + "/", "COGNITO_REGION": "eu-central-1",
                                "COGNITO_CLIENT_ID": "abc"})
    assert env.config_url == BASE + "/api/v1/device/config"
    assert env.models_url == BASE + "/api/v1/device/models"
    assert env.ingest_url == BASE + "/api/v1/ingest/detections"
    assert env.signs_in
    assert env.credentials_file == Path("/config/device-credentials.json")


def test_the_development_cloud_needs_no_sign_in():
    env = Environment.from_env({"API_BASE_URL": "http://localhost:8100", "REPLAY_DIR": "/mnt/usb/session"})
    assert not env.signs_in
    assert env.replay_dir == Path("/mnt/usb/session")


def test_without_the_platform_the_mode_cannot_start():
    with pytest.raises(EnvironmentIncomplete):
        Environment.from_env({"EDGE_MODE": "detection"})
