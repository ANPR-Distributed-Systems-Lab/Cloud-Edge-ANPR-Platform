import json

import pytest

from detection.config.schema import EdgeSettings, SettingsError
from detection.config.settings import DEFAULTS, Settings, default_settings, merge


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_documents_map_onto_typed_settings():
    settings = default_settings()
    assert settings.ml.ocr_min_confidence == 0.80
    assert settings.ml.min_plate_width_px == 70 and isinstance(settings.ml.min_plate_width_px, int)
    assert settings.camera.white_balance.mode == "DAYLIGHT"
    assert settings.camera.exposure.max_exposure_us == 540
    assert settings.intervals.config_poll_seconds == 60


@pytest.mark.parametrize("patch, problem", [
    ({"ml": {"ocrMinConfidence": 1.5}}, "ml.ocrMinConfidence must be a number from 0 to 1"),
    ({"ml": {"minPlateWidthPx": "70"}}, "ml.minPlateWidthPx"),
    ({"camera": {"exposure": {"mode": "auto"}}}, "camera.exposure.mode must be one of"),  # the enums are upper case
    ({"camera": {"hflip": 1}}, "camera.hflip must be true or false"),
    ({"batching": {"detectionsBatchSize": True}}, "batching.detectionsBatchSize"),
    ({"camera": {"whiteBalance": None}}, "camera.whiteBalance must be an object"),
])
def test_out_of_contract_values_are_named(patch, problem):
    with pytest.raises(SettingsError) as e:
        EdgeSettings.from_document(merge(DEFAULTS, patch))
    assert any(p.startswith(problem) for p in e.value.problems)


def test_every_problem_is_reported_at_once():
    with pytest.raises(SettingsError) as e:
        EdgeSettings.from_document(merge(DEFAULTS, {"ml": {"ocrMinConfidence": 2, "minEdgeMarginPx": -1}}))
    assert len(e.value.problems) == 2


def test_the_local_file_overrides_the_defaults(tmp_path):
    write(tmp_path / "detection.json", {"ml": {"ocrMinConfidence": 0.9}, "camera": {"hflip": True, "vflip": True}})
    settings = Settings(tmp_path).current
    assert settings.ml.ocr_min_confidence == 0.9
    assert settings.ml.detector_min_confidence == default_settings().ml.detector_min_confidence
    assert settings.camera.hflip is True


def test_a_local_file_with_a_byte_order_mark_is_read(tmp_path):
    (tmp_path / "detection.json").write_bytes(b'\xef\xbb\xbf{"camera": {"hflip": true}}')
    assert Settings(tmp_path).current.camera.hflip is True


def test_an_invalid_local_file_is_ignored_as_a_whole(tmp_path):
    write(tmp_path / "detection.json", {"ml": {"ocrMinConfidence": 0.9, "minPlateWidthPx": -1}})
    assert Settings(tmp_path).current == default_settings()


def test_the_cloud_overrides_the_local_file_and_is_cached(tmp_path):
    write(tmp_path / "detection.json", {"ml": {"ocrMinConfidence": 0.9}, "camera": {"hflip": True}})
    settings = Settings(tmp_path)
    cloud = {"deviceId": "d", "version": 4, "plateCooldownSeconds": 30,
             "ml": {"detectorMinConfidence": 0.5, "ocrMinConfidence": 0.6, "minPlateWidthPx": 60},
             "camera": {"fps": 2.0, "exposure": DEFAULTS["camera"]["exposure"] | {"mode": "MANUAL"},
                        "whiteBalance": DEFAULTS["camera"]["whiteBalance"]}}
    assert settings.apply_cloud(cloud, '"4"') is True
    assert settings.version == 1
    current = settings.current
    assert current.ml.ocr_min_confidence == 0.6 and current.plate_cooldown_seconds == 30
    assert current.ml.readable_min_probability == 0.80  # not in the cloud contract: the default stays
    assert current.camera.hflip is True  # local only

    restarted = Settings(tmp_path)
    assert restarted.current == current and restarted.cloud_etag == '"4"'
    assert restarted.apply_cloud(cloud, '"4"') is False
