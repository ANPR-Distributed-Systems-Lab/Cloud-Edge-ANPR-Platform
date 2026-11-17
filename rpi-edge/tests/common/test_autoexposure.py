from common.autoexposure import metered_rows


def test_the_metered_rows_are_the_band_in_rows_of_the_image():
    assert metered_rows(3040, 0.337, 0.795) == (1024, 2417)
    assert metered_rows(100, 0.0, 1.0) == (0, 100)


def test_a_band_thinner_than_a_row_still_measures_one():
    assert metered_rows(100, 0.5, 0.501) == (50, 51)
    assert metered_rows(100, 0.999, 1.0) == (99, 100)
