import pytest
from samples import configuration, configuration_document

from detection.contract.configuration import DeviceConfiguration
from detection.contract.parsing import ContractError


def test_the_document_maps_onto_typed_fields():
    config = configuration()
    assert config.ml.ocr_min_confidence == 0.80
    assert config.ml.min_plate_width_px == 70 and isinstance(config.ml.min_plate_width_px, int)
    assert config.models.detector == "v2" and config.models.ocr == "v3"
    assert config.camera.white_balance.mode == "DAYLIGHT"
    assert config.camera.exposure.max_exposure_us == 540
    assert config.camera.hflip is True
    assert config.intervals.config_poll_seconds == 60
    assert config.batching.image_uploads_low_priority is True
    assert config.gps.max_fix_age_seconds == 30
    assert config.photos.width_px == 4056 and config.photos.jpeg_quality == 90


def test_the_track_may_be_sampled_up_to_once_an_hour():
    assert configuration(intervals={"locationSampleSeconds": 3600}).intervals.location_sample_seconds == 3600


def test_equal_documents_give_equal_configurations():
    assert configuration() == configuration()
    assert configuration() != configuration(ml={"ocrMinConfidence": 0.9})


@pytest.mark.parametrize("patch, problem", [
    ({"ml": {"ocrMinConfidence": 1.5}}, "ml.ocrMinConfidence must be a number from 0 to 1"),
    ({"ml": {"minPlateWidthPx": "70"}}, "ml.minPlateWidthPx"),
    ({"camera": {"exposure": {"mode": "auto"}}}, "camera.exposure.mode must be one of"),  # the enums are upper case
    ({"camera": {"hflip": 1}}, "camera.hflip must be true or false"),
    ({"batching": {"detectionsBatchSize": True}}, "batching.detectionsBatchSize"),
    ({"batching": {"imageUploadsLowPriority": "yes"}}, "batching.imageUploadsLowPriority must be true or false"),
    ({"camera": {"whiteBalance": None}}, "camera.whiteBalance must be an object"),
    ({"models": {"ocr": "../v3"}}, "models.ocr must match"),  # a version becomes a directory name
    ({"deviceId": "rpi-01"}, "deviceId must match"),
    ({"camera": {"exposure": {"exposureUs": 80_001}}}, "camera.exposure.exposureUs"),  # longer than a frame
    ({"camera": {"exposure": {"maxExposureUs": 1_000_000}}}, "camera.exposure.maxExposureUs"),
    ({"intervals": {"locationSampleSeconds": 3601}}, "intervals.locationSampleSeconds"),
    ({"gps": {"maxFixAgeSeconds": 0}}, "gps.maxFixAgeSeconds"),
    ({"photos": {"widthPx": 639}}, "photos.widthPx"),
    ({"photos": {"widthPx": 4057}}, "photos.widthPx"),  # never upscaled
    ({"photos": {"jpegQuality": 101}}, "photos.jpegQuality"),
    ({"photos": None}, "photos must be an object"),
])
def test_values_outside_the_contract_are_named(patch, problem):
    with pytest.raises(ContractError) as e:
        DeviceConfiguration.from_document(configuration_document(**patch))
    assert any(p.startswith(problem) for p in e.value.problems)


def test_every_problem_is_reported_at_once():
    document = configuration_document(ml={"ocrMinConfidence": 2, "minEdgeMarginPx": -1})
    del document["models"]
    with pytest.raises(ContractError) as e:
        DeviceConfiguration.from_document(document)
    assert len(e.value.problems) == 3


def test_a_document_that_is_no_object_is_refused():
    with pytest.raises(ContractError):
        DeviceConfiguration.from_document([1, 2])
