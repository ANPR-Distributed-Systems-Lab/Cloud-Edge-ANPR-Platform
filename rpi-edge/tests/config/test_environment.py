from pathlib import Path

from detection.config.environment import Environment

BASE = "https://abc.execute-api.eu-central-1.amazonaws.com"


def test_the_platform_endpoints_derive_from_the_api_base_url():
    env = Environment.from_env({"API_BASE_URL": BASE + "/", "COGNITO_REGION": "eu-central-1",
                                "COGNITO_CLIENT_ID": "abc"})
    assert env.ingest_url == BASE + "/api/v1/ingest/detections"
    assert env.models_manifest_url == BASE + "/api/v1/device/models"
    assert env.config_url == BASE + "/api/v1/device/config"
    assert env.signs_in


def test_development_overrides_win_and_no_cloud_means_no_polling():
    env = Environment.from_env({"INGEST_URL": "http://localhost:8200/ingest",
                                "MODELS_MANIFEST_URL": "http://localhost:8100/manifest.json",
                                "REPLAY_DIR": "/mnt/usb/session"})
    assert env.ingest_url == "http://localhost:8200/ingest"
    assert env.models_manifest_url == "http://localhost:8100/manifest.json"
    assert env.config_url is None and env.api_base_url is None and not env.signs_in
    assert env.replay_dir == Path("/mnt/usb/session")
    assert env.credentials_file == Path("/config/device-credentials.json")
