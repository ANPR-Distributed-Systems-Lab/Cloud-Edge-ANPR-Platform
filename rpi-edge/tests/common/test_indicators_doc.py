"""INDICATORS.md and common/fault_catalog.py name the same faults, with the same text on the LCD, per mode."""
import re
from pathlib import Path

import pytest

from common import fault_catalog as kinds

DOC = Path(__file__).parents[2] / "INDICATORS.md"
ROW = re.compile(r"^\| ([^|]+) \| `([a-z_]+)` \|")


def documented(section: str) -> dict[str, str]:
    """Code -> LCD text of the fault tables in the section of the document."""
    text = DOC.read_text(encoding="utf-8").split(f"## {section}", 1)[1].split("\n## ", 1)[0]
    return {m[2]: m[1] for m in map(ROW.match, text.splitlines()) if m}


@pytest.mark.skipif(not DOC.exists(), reason="only in the repository")
@pytest.mark.parametrize(("section", "catalogued"), [("2. Detection mode", kinds.DETECTION + kinds.SYSTEM),
                                                     ("3. Collection mode", kinds.COLLECTION + kinds.SYSTEM)])
def test_the_document_lists_every_fault_of_the_mode_and_no_other(section, catalogued):
    rows = documented(section)
    assert set(rows) == {k.code for k in catalogued}
    for kind in catalogued:  # the text as on the LCD; a detail (a count, a value) shows as N
        assert rows[kind.code].removesuffix(" N").removesuffix(" Ns").removesuffix(" NMB").removesuffix(" NC") \
            == kind.text, kind.code
