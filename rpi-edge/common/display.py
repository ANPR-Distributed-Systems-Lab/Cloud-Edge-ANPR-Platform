"""The pages of the LCD and the text helpers both modes build them with.

Each mode has a home page (its status) and pages with a title row naming the page and its number, e.g.
"GPS              2/6". A short press of the page switch shows the next page, a long one the home page. Every row
is a label and its value, the value right-aligned, so a number on the screen always says what it counts.
"""
import threading
import unicodedata

from common.faults import Fault
from common.peripherals import LCD_COLS, LCD_ROWS, TactSwitch

MAX_SHOWN_COUNT = 9999  # larger counts show as 9999+


class Pages:
    def __init__(self, count: int, switch: TactSwitch | None) -> None:
        self.count = count
        self.index = 0  # 0 is the home page
        self._changed = threading.Event()
        if switch is not None:
            switch.on_press, switch.on_hold = self.next, self.home

    def next(self) -> None:
        self.index = (self.index + 1) % self.count
        self._changed.set()

    def home(self) -> None:
        self.index = 0
        self._changed.set()

    def wait(self, seconds: float) -> None:
        """Waits for the next refresh: `seconds`, or less when the page changes, so a press shows at once."""
        self._changed.wait(seconds)
        self._changed.clear()


def row(label: str, value: str = "") -> str:
    """The label left, the value right-aligned. When both do not fit, the label is cut: the value is the news."""
    if not value:
        return label[:LCD_COLS]
    room = LCD_COLS - len(value) - 1
    return f"{label[:max(room, 0)]:<{max(room, 0)}} {value}"[-LCD_COLS:]


def title(name: str, pages: Pages) -> str:
    return row(name, f"{pages.index + 1}/{pages.count}")


def count(n: int) -> str:
    return f"{MAX_SHOWN_COUNT}+" if n > MAX_SHOWN_COUNT else str(n)


def duration(seconds: float) -> str:
    """45s, 12m, 3h12m, 2d4h: the two largest units."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{s % 3600 // 60}m"
    return f"{s // 86400}d{s % 86400 // 3600}h"


def ascii_text(text: str) -> str:
    """The LCD has no Polish letters: ą -> a, ł -> l, and so on."""
    text = text.replace("ł", "l").replace("Ł", "L")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def fault_lines(faults: list[Fault], pages: Pages) -> list[str]:
    """The FAULTS page: what lights the fault LED, one per row; the log has the details."""
    shown = LCD_ROWS - 1
    lines = [title(f"FAULTS {len(faults)}", pages)]
    if not faults:
        return [*lines, "none"]
    texts = [f.text[:LCD_COLS] for f in faults]
    if len(texts) > shown:
        return [*lines, *texts[:shown - 1], f"+{len(texts) - shown + 1} more"]
    return [*lines, *texts]
