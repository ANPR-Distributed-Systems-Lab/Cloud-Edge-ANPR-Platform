from pathlib import Path

import pytest

from detection.config.environment import Environment, EnvironmentIncomplete

BASE = "https://abc.execute-api.eu-central-1.amazonaws.com"


def test_the_endpoints_derive_from_the_api_base_url():
    env = Environment.from_env({"API_BASE_URL": BASE + "/", "COGNITO_REGION": "eu-central-1",
                                "COGNITO_CLIENT_ID": "abc"})
    assert env.config_url == BASE + "/api/v1/device/config"
    assert env.models_url == BASE + "/api/v1/device/models"
    assert env.alerts_url == BASE + "/api/v1/alerts"
    assert env.ingest_url == BASE + "/api/v1/ingest/detections"
    assert env.locations_url == BASE + "/api/v1/ingest/device-locations"
    assert env.metrics_url == BASE + "/api/v1/device/metrics"
    assert env.image_urls_url == BASE + "/api/v1/images/presigned-urls"
    assert env.signs_in
    assert env.credentials_file == Path("/config/device-credentials.json")


def test_the_development_cloud_needs_no_sign_in():
    env = Environment.from_env({"API_BASE_URL": "http://localhost:8100", "REPLAY_DIR": "/mnt/usb/session"})
    assert not env.signs_in
    assert env.replay_dir == Path("/mnt/usb/session")


def test_without_the_platform_the_mode_cannot_start():
    with pytest.raises(EnvironmentIncomplete):
        Environment.from_env({"EDGE_MODE": "detection"})


def test_the_gnss_module_comes_from_a_serial_port_or_a_fixed_position():
    base = {"API_BASE_URL": "http://localhost:8100"}
    module = Environment.from_env(base | {"GPS_DEVICE": "/dev/ttyAMA0"})
    assert module.gps_device == "/dev/ttyAMA0" and module.gps_baud == 115200 and module.gps_fixed_location is None
    assert Environment.from_env(base | {"GPS_DEVICE": "/dev/ttyS0", "GPS_BAUD": "9600"}).gps_baud == 9600
    assert Environment.from_env(base | {"GPS_FIXED_LOCATION": "52.229676,21.012229"}).gps_fixed_location == (
        52.229676, 21.012229)
    assert Environment.from_env(base).gps_device is None


@pytest.mark.parametrize("value", ["52.2", "a,b", "0,0", "91,10", "10,181"])
def test_a_wrong_fixed_position_stops_the_mode_with_a_message(value):
    with pytest.raises(EnvironmentIncomplete, match="GPS_FIXED_LOCATION"):
        Environment.from_env({"API_BASE_URL": BASE, "GPS_FIXED_LOCATION": value})
