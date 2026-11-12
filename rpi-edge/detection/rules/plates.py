"""Polish plate format check: rejects OCR output that cannot be a standard Polish plate.

A standard plate is a county code of 2 or 3 letters, starting with the letter of a voivodeship, followed by
a vehicle part whose allowed digit/letter patterns depend on the length of the code. The patterns below
follow the registration regulation as summarised in the ML send-rule analysis (they pass 412 of the 415
labeled texts; custom and special plates fail). They are not yet verified against the official text:
a verified per-position rules document is an open item of ml-models (ML_ASSUMPTIONS.md, section 7).
"""
import re

VOIVODESHIPS = "BCDEFGKLNOPRSTWZ"

# D = digit, L = letter. Vehicle part after a 2-letter county code (5 characters).
AFTER_TWO_LETTERS = ("DDDDD", "DDDDL", "DDDLL", "DLDDD", "DLLDD")
# Vehicle part after a 3-letter county code (4 or 5 characters).
AFTER_THREE_LETTERS = ("LDDD", "DDLL", "DLDD", "DDLD", "DLLD", "LLDD", "LDDL", "LDLL", "DDDDD", "DDDDL", "DDDLL")


def _pattern(shape: str) -> str:
    return "".join("[0-9]" if c == "D" else "[A-Z]" for c in shape)


_STANDARD = re.compile(
    f"[{VOIVODESHIPS}][A-Z](?:{'|'.join(map(_pattern, AFTER_TWO_LETTERS))})"
    f"|[{VOIVODESHIPS}][A-Z]{{2}}(?:{'|'.join(map(_pattern, AFTER_THREE_LETTERS))})"
)


def is_polish_plate(text: str) -> bool:
    return _STANDARD.fullmatch(text) is not None
