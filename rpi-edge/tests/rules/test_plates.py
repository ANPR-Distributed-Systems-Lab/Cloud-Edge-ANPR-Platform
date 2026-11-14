import pytest

from detection.rules.plates import COUNTY_CODES, is_polish_plate

# Made-up numbers in the layouts of ml-models/PLATE_FORMAT.md; WA = Warszawa (1-letter county code A),
# WPI = piaseczyński (2-letter county code PI).


@pytest.mark.parametrize("text", [
    "WA12345", "WA1234A", "WA123AC", "WA1A234", "WA1AC23",  # 1-letter county code, 5 characters
    "WPIA123", "WPI12AC", "WPI1A23", "WPI12A3", "WPI1AC2", "WPIAC12",  # 2-letter county code, 4 characters
    "WPI12345", "WPI1234A", "WPI123AC",  # 2-letter county code, 5 characters
    "VW12345", "AA12345", "MZ12345",  # second voivodeship letters (dolnośląskie, mazowieckie, wielkopolskie)
])
def test_ordinary_plates_pass(text):
    assert is_polish_plate(text)


@pytest.mark.parametrize("text", [
    "W0ABC", "W0ABCDE", "W0ABCD1", "W0AB12", "V1KOT", "W0BIOZ",  # individual: owner's letters may be B, D, I, O, Z
])
def test_individual_plates_pass(text):
    assert is_polish_plate(text)


@pytest.mark.parametrize("text", [
    "",
    "WA1234",  # too short after a 1-letter county code
    "WA123456",  # too long
    "WA12A45",  # DDLDD is no layout
    "WPIA12C", "WPIA1CE",  # motorcycle layouts, not car ones
    "WA00000", "WA0000A", "WPIA000", "WA0A123", "WPI12A0",  # a run of digits outside its range
    "WA1234B", "WA123DO", "WPIZ123",  # B, D, I, O, Z are never in the vehicle part
    "WQ12345", "HA12345", "UA12345",  # no such county / voivodeship
    "WAQ1234",
    "W0AB", "W0ABCDEF", "W0A123", "W01ABC",  # individual: 3 to 5 characters, at most the last two digits
    "W12345",  # temporary plate, out of scope
    "wa12345", "WA 12345",
])
def test_other_texts_fail(text):
    assert not is_polish_plate(text)


def test_annex_13_has_every_county_code():
    assert len(COUNTY_CODES) == 16
    assert sum(len(codes.split()) for codes in COUNTY_CODES.values()) == 421
