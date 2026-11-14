import numpy as np
import pytest
from samples import configuration

from detection.rules.send_rule import Cooldown, geometry_rejection, is_clockwise_convex, plate_width, reading_rejection
from detection.vision.ocr import Reading

ML = configuration().ml
FRAME = (4056, 3040)


def quad(x, y, w, h=None):
    h = h or w / 4.5
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], float)


def test_plate_width_is_the_mean_of_top_and_bottom():
    corners = np.array([[0, 0], [100, 0], [90, 20], [10, 20]], float)
    assert plate_width(corners) == pytest.approx(90)


def test_geometry_accepts_a_plate_inside_the_frame():
    assert geometry_rejection(quad(1000, 1000, 120), FRAME, ML) is None


@pytest.mark.parametrize("corners, reason", [
    (quad(1000, 1000, 69), "too_small"),
    (quad(5, 1000, 120), "near_edge"),  # left edge
    (quad(4056 - 125, 1000, 120), "near_edge"),  # right edge: x reaches 4051, within 10 px of 4055
    (quad(1000, 3040 - 30, 120), "near_edge"),  # bottom edge
    (quad(1000, 1000, 120)[[1, 0, 3, 2]], "bad_corners"),  # mirrored: counter-clockwise
])
def test_geometry_rejections(corners, reason):
    assert geometry_rejection(corners, FRAME, ML) == reason


def test_self_intersecting_and_degenerate_quads_are_not_convex():
    assert is_clockwise_convex(quad(0, 0, 100))
    assert not is_clockwise_convex(np.array([[0, 0], [100, 20], [100, 0], [0, 20]], float))  # bow tie
    assert not is_clockwise_convex(np.array([[0, 0], [50, 0], [100, 0], [0, 20]], float))  # three in a line


@pytest.mark.parametrize("reading, reason", [
    (Reading("WA12345", 0.95, 0.97), None),
    (Reading("WA12345", 0.95, None), None),  # a model without the readability head
    (Reading("", 0.99, 0.99), "no_text"),
    (Reading("WA12345", 0.95, 0.79), "unreadable"),
    (Reading("XX12345", 0.95, 0.97), "bad_format"),
    (Reading("WA12345", 0.79, 0.97), "low_confidence"),
])
def test_reading_rejections(reading, reason):
    assert reading_rejection(reading, ML) == reason


def test_cooldown_suppresses_the_same_plate_until_it_expires():
    cooldown = Cooldown()
    assert cooldown.accept("WA12345", now=100.0, seconds=60)
    assert not cooldown.accept("WA12345", now=130.0, seconds=60)
    assert cooldown.accept("KR1AC23", now=130.0, seconds=60)  # another plate is independent
    assert not cooldown.accept("WA12345", now=159.9, seconds=60)  # sightings do not extend the window
    assert cooldown.accept("WA12345", now=160.0, seconds=60)


def test_zero_cooldown_sends_every_reading():
    cooldown = Cooldown()
    assert cooldown.accept("WA12345", now=1.0, seconds=0)
    assert cooldown.accept("WA12345", now=1.0, seconds=0)
