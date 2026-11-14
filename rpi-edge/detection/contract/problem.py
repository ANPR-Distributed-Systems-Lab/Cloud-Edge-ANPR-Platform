"""Error answers of the platform: RFC 9457 problem details with a stable `code` and per-field errors.

Lenient on purpose: an error answer is read to decide what to do and what to log, so a body that is not a problem
document (a gateway error page, an empty 503) gives a Problem with no code and no fields instead of an error.
"""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldError:
    index: int | None  # position of the item in a batch; None for an error about the request itself
    field: str
    code: str  # names the rule broken, never the value, so it is safe to log


@dataclass(frozen=True)
class Problem:
    status: int
    code: str | None  # e.g. VALIDATION_FAILED, MODEL_NOT_PUBLISHED, DEVICE_NOT_FOUND
    fields: tuple[FieldError, ...] = ()

    @property
    def indexes(self) -> set[int]:
        return {f.index for f in self.fields if f.index is not None}

    @classmethod
    def of(cls, status: int, body: bytes) -> "Problem":
        try:
            document = json.loads(body) if body else {}
        except ValueError:
            document = {}
        if not isinstance(document, dict):
            document = {}
        code = document.get("code")
        return cls(status, code if isinstance(code, str) else None, tuple(
            FieldError(f["index"] if isinstance(f.get("index"), int) else None, str(f.get("field", "")),
                       str(f.get("code", "")))
            for f in document.get("fields") or [] if isinstance(f, dict)))
