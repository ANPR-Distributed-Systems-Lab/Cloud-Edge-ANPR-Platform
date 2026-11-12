"""Turns a JSON document into a frozen dataclass and checks it against the contract on the way.

A field `ocr_min_confidence` reads the key `ocrMinConfidence`. What a field accepts is declared next to it:

    exposure_us: int = bounded(20, 1_000_000)     a number in the range (int fields get an int)
    mode: str = one_of("MANUAL", "AUTO")          one of the listed strings
    version: str = matching(r"[A-Za-z0-9]+")       a string matching the whole pattern
    hflip: bool                                   true or false
    camera: CameraConfiguration                   a nested object
    files: tuple[ModelFile, ...]                  a non-empty array of nested objects
    items: tuple[Alert, ...] = array(min_items=0) an array that may also be empty
    alert_text: str | None = matching(".*")       null, or a value of the other type

Every problem of a document is collected, not only the first one.
"""
import re
from dataclasses import field, fields, is_dataclass
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints


class ContractError(ValueError):
    """A document that breaks its contract; `problems` names each field ("ml.ocrMinConfidence must be ...")."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def bounded(low: float, high: float):
    return field(metadata={"range": (low, high)})


def one_of(*choices: str):
    return field(metadata={"choices": choices})


def matching(pattern: str):
    return field(metadata={"pattern": re.compile(pattern)})


def array(min_items: int):
    """An array field; without it an array needs at least one item."""
    return field(metadata={"min_items": min_items})


def parse(cls, document, path: str = ""):
    """document -> cls; path names the document in messages ("" for the root, then e.g. "camera.exposure")."""
    if not isinstance(document, dict):
        raise ContractError([f"{path or 'the document'} must be an object"])
    values, problems = {}, []
    types = get_type_hints(cls)
    for f in fields(cls):
        key = camel(f.name)
        where = f"{path}.{key}" if path else key
        try:
            values[f.name] = _value(document.get(key), types[f.name], f.metadata, where)
        except ContractError as e:
            problems += e.problems
    if problems:
        raise ContractError(problems)
    return cls(**values)


def camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _value(raw, kind, metadata, where: str):
    if get_origin(kind) in (Union, UnionType):  # X | None
        if raw is None:
            return None
        kind = next(k for k in get_args(kind) if k is not type(None))
    if is_dataclass(kind):
        return parse(kind, raw, where)
    if get_origin(kind) is tuple:
        return _items(raw, get_args(kind)[0], metadata.get("min_items", 1), where)
    # bool is checked before numbers: in Python True is also an int, and 1 is not a boolean here.
    if kind is bool:
        if not isinstance(raw, bool):
            raise ContractError([f"{where} must be true or false"])
        return raw
    if kind is str:
        return _text(raw, metadata, where)
    low, high = metadata["range"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not low <= raw <= high:
        raise ContractError([f"{where} must be a number from {low} to {high}"])
    return kind(raw)


def _items(raw, kind, min_items: int, where: str) -> tuple:
    if not isinstance(raw, list) or len(raw) < min_items:
        raise ContractError([f"{where} must be a non-empty array" if min_items else f"{where} must be an array"])
    items, problems = [], []
    for i, item in enumerate(raw):
        try:
            items.append(parse(kind, item, f"{where}[{i}]"))
        except ContractError as e:
            problems += e.problems
    if problems:
        raise ContractError(problems)
    return tuple(items)


def _text(raw, metadata, where: str) -> str:
    if "choices" in metadata:
        if raw not in metadata["choices"]:
            raise ContractError([f"{where} must be one of {', '.join(metadata['choices'])}"])
        return raw
    if not isinstance(raw, str) or not metadata["pattern"].fullmatch(raw):
        raise ContractError([f"{where} must match {metadata['pattern'].pattern}"])
    return raw
