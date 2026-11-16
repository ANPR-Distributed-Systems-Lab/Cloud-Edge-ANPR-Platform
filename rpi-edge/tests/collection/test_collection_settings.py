"""The collection settings: the ranges of the device configuration, and its defaults, so values carry over by hand."""
from pathlib import Path

import pytest
import yaml

from collection.settings import DEFAULTS, sanitize
from common.sensor import MAX_EXPOSURE_US, MAX_FPS

SERVICE_DEFAULTS = Path(__file__).parents[3] / "device-management-service/src/main/resources/application.yaml"


def test_missing_and_unknown_values_fall_back_to_the_defaults():
    assert sanitize({}) == DEFAULTS
    assert "resolution" not in sanitize({"recording": {"resolution": "2028x1520"}})["recording"]  # fixed: 4056x3040


@pytest.mark.parametrize("key", ["exposure_us", "max_exposure_us"])
def test_an_exposure_is_at_most_80_ms(key):
    assert sanitize({"exposure": {key: 1_000_000}})["exposure"][key] == MAX_EXPOSURE_US


def test_the_frame_rate_is_limited_to_what_the_full_sensor_delivers():
    assert sanitize({"recording": {"fps": 30}})["recording"]["fps"] == MAX_FPS


def test_the_metered_band_keeps_the_ranges_of_the_device_configuration():
    exposure = sanitize({"exposure": {"metering_top": 0.2, "metering_bottom": 0.9}})["exposure"]
    assert (exposure["metering_top"], exposure["metering_bottom"]) == (0.2, 0.9)
    assert sanitize({"exposure": {"metering_top": 0.99, "metering_bottom": 1.0}})["exposure"]["metering_top"] == 0.95
    assert sanitize({"exposure": {"metering_top": 0.0, "metering_bottom": 0.0}})["exposure"]["metering_bottom"] == 0.05


def test_a_bottom_above_the_top_becomes_the_thinnest_band_below_it():
    exposure = sanitize({"exposure": {"metering_top": 0.6, "metering_bottom": 0.3}})["exposure"]
    assert exposure["metering_top"] == 0.6 and exposure["metering_bottom"] == 0.601


@pytest.mark.skipif(not SERVICE_DEFAULTS.exists(), reason="only in the repository, not in the device image")
def test_the_camera_defaults_are_those_of_a_new_device_in_device_management():
    camera = yaml.safe_load(SERVICE_DEFAULTS.read_text(encoding="utf-8"))["app"]["configuration"]["defaults"]["camera"]
    service, wb = camera["exposure"], camera["white-balance"]
    assert DEFAULTS["exposure"] == {
        "mode": service["mode"].lower(), "exposure_us": service["exposure-us"], "gain": service["gain"],
        "max_exposure_us": service["max-exposure-us"], "max_gain": service["max-gain"],
        "target_brightness": service["target-brightness"], "metering_top": service["metering-top"],
        "metering_bottom": service["metering-bottom"]}
    assert DEFAULTS["white_balance"] == {"mode": wb["mode"].lower(), "red_gain": wb["red-gain"],
                                         "blue_gain": wb["blue-gain"]}
    assert DEFAULTS["camera"] == {"hflip": camera["hflip"], "vflip": camera["vflip"]}
