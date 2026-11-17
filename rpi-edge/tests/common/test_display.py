"""The LCD rows always fit, label left and value right, and the page switch moves through the pages."""
from common.display import Pages, ascii_text, count, duration, fault_lines, row, title
from common.faults import Fault
from common.peripherals import LCD_COLS


class FakeSwitch:
    on_press = on_hold = None


def test_a_row_puts_the_value_on_the_right_and_cuts_the_label_when_both_do_not_fit():
    assert row("plates", "12") == "plates" + " " * 12 + "12"
    assert row("a very long label of a row", "123") == "a very long labe 123"
    assert len(row("a very long label of a row", "123")) == LCD_COLS
    assert row("only a label") == "only a label"


def test_counts_and_durations_stay_short():
    assert count(12) == "12" and count(123_456) == "9999+"
    assert [duration(s) for s in (5, 125, 3 * 3600 + 720, 2 * 86400 + 4 * 3600)] == ["5s", "2m", "3h12m", "2d4h"]


def test_the_page_switch_shows_the_next_page_and_a_long_press_the_home_page():
    switch = FakeSwitch()
    pages = Pages(3, switch)
    switch.on_press()
    switch.on_press()
    assert pages.index == 2 and title("GPS", pages) == "GPS" + " " * 14 + "3/3"
    switch.on_press()
    assert pages.index == 0
    switch.on_press()
    switch.on_hold()
    assert pages.index == 0


def test_the_faults_page_lists_what_fits_and_counts_the_rest():
    pages = Pages(2, None)
    pages.next()
    faults = [Fault(str(i), f"fault {i}") for i in range(5)]
    assert fault_lines(faults, pages) == [row("FAULTS 5", "2/2"), "fault 0", "fault 1", "+3 more"]
    assert fault_lines(faults[:3], pages)[1:] == ["fault 0", "fault 1", "fault 2"]
    assert fault_lines([], pages)[1:] == ["none"]


def test_polish_letters_become_ascii():
    assert ascii_text("Zgłoś, Łódź") == "Zglos, Lodz"
