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


def test_equal_documents_give_equal_configurations():
    assert configuration() == configuration()
    assert configuration() != configuration(ml={"ocrMinConfidence": 0.9})


@pytest.mark.parametrize("patch, problem", [
    ({"ml": {"ocrMinConfidence": 1.5}}, "ml.ocrMinConfidence must be a number from 0 to 1"),
    ({"ml": {"minPlateWidthPx": "70"}}, "ml.minPlateWidthPx"),
    ({"camera": {"exposure": {"mode": "auto"}}}, "camera.exposure.mode must be one of"),  # the enums are upper case
    ({"camera": {"hflip": 1}}, "camera.hflip must be true or false"),
    ({"batching": {"detectionsBatchSize": True}}, "batching.detectionsBatchSize"),
    ({"camera": {"whiteBalance": None}}, "camera.whiteBalance must be an object"),
    ({"models": {"ocr": "../v3"}}, "models.ocr must match"),  # a version becomes a directory name
    ({"deviceId": "rpi-01"}, "deviceId must match"),
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
