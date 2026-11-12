import pytest

from detection.rules.plates import is_polish_plate


@pytest.mark.parametrize("text", [
    "WA12345", "WA1234A", "WA123AC", "WA1A234", "WA1AC23",  # 2-letter county code + 5
    "WPIA123", "WPI12AC", "WPI1A23", "WPI12A3", "WPI1AC2", "WPIAC12", "WPIA12C", "WPIA1CE",  # 3-letter + 4
    "WPI12345", "WPI1234A", "WPI123AC",  # 3-letter + 5
])
def test_standard_patterns_pass(text):
    assert is_polish_plate(text)


@pytest.mark.parametrize("text", [
    "",
    "WA1234",  # too short after a 2-letter code
    "WA123456",  # too long
    "WAA1234",  # vehicle part starting with a letter after a 2-letter code, but "WAA" + "1234" has no 4-digit form
    "AA12345",  # A is no voivodeship
    "1A12345",
    "WA12A45",  # 2-letter code, pattern DDLDD does not exist
    "wa12345",
    "WA 12345",
])
def test_other_shapes_fail(text):
    assert not is_polish_plate(text)
