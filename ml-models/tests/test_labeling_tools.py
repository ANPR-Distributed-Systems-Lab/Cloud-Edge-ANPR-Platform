import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from anpr_ml.frames import dhash, hamming
from anpr_ml.make_splits import make_splits
from anpr_ml.select_frames import allocate, dedupe, evenly
from anpr_ml.validate_export import validate_xml


def test_dhash_same_image_matches_and_different_differs(tmp_path):
    rng = np.random.default_rng(0)
    a = Image.fromarray(rng.integers(0, 255, (300, 400), dtype=np.uint8))
    b = Image.fromarray(rng.integers(0, 255, (300, 400), dtype=np.uint8))
    a.save(tmp_path / "a.jpg")
    b.save(tmp_path / "b.jpg")
    assert dhash(tmp_path / "a.jpg") == dhash(tmp_path / "a.jpg")
    assert hamming(dhash(tmp_path / "a.jpg"), dhash(tmp_path / "b.jpg")) > 10


def test_dedupe_compares_with_last_kept_frame():
    hashes = [0b0, 0b1, 0b11, 0b1111, 0b11111111]
    assert dedupe(hashes, threshold=4) == [0, 3, 4]
    assert dedupe([5, 5, 5], threshold=1) == [0]


def test_allocate_and_evenly():
    assert allocate([10, 30, 60], 10) == [1, 3, 6]
    assert sum(allocate([3, 3, 3], 7)) == 7
    assert allocate([2, 100], 50)[0] <= 2
    assert evenly(list(range(10)), 3) == [0, 4, 9]
    assert evenly([1, 2], 5) == [1, 2]


def test_splits_are_deterministic_disjoint_and_mix_days():
    sessions = [f"session_2026100{d}_{h:02d}0000" for d in (4, 5, 6) for h in range(6)]
    one = make_splits(sessions, 3, 3, seed=1)
    assert one == make_splits(sessions, 3, 3, seed=1)
    groups = [set(one[k]) for k in ("train", "val", "test")]
    assert sum(len(g) for g in groups) == len(sessions) and not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    assert len({s.split("_")[1] for s in one["test"]}) == 3  # one test session per day


def _xml(shapes: str) -> ET.Element:
    return ET.fromstring(f'<annotations><image id="0" name="a.jpg" width="4056" height="3040">{shapes}</image></annotations>')


def _plate(points: str, text="WA12345", readable="yes", label="plate") -> str:
    return (
        f'<polygon label="{label}" source="manual" occluded="0" points="{points}">'
        f'<attribute name="text">{text}</attribute><attribute name="readable">{readable}</attribute>'
        '<attribute name="occlusion">none</attribute><attribute name="type">standard</attribute></polygon>'
    )


GOOD = "1000,1000;1200,1010;1200,1050;1000,1040"  # TL, TR, BR, BL


def test_valid_plate_passes_and_is_normalized():
    report, records = validate_xml(_xml(_plate(GOOD)))
    assert not report.errors and report.plates == 1
    assert records[0]["plates"][0]["corners"][0] == [round(1000 / 4056, 6), round(1000 / 3040, 6)]
    assert 199 < report.widths[0] < 201


def test_wrong_corner_order_point_count_and_text_are_errors():
    counter_clockwise = "1000,1000;1000,1040;1200,1050;1200,1010"
    assert validate_xml(_xml(_plate(counter_clockwise)))[0].errors
    assert validate_xml(_xml(_plate("1000,1000;1200,1010;1200,1050")))[0].errors
    assert validate_xml(_xml(_plate(GOOD, text="")))[0].errors
    assert not validate_xml(_xml(_plate(GOOD, text="", readable="no")))[0].errors
    assert validate_xml(_xml(_plate("-50,1000;150,1010;150,1050;-50,1040")))[0].errors  # outside the frame


def test_small_plate_warns_and_ignore_region_needs_no_text():
    small = "1000,1000;1050,1002;1050,1012;1000,1010"
    assert validate_xml(_xml(_plate(small)))[0].warnings
    report, records = validate_xml(_xml(f'<polygon label="plate_ignore" source="manual" occluded="0" points="{small}"></polygon>'))
    assert not report.errors and report.ignored == 1 and records[0]["ignore"]
