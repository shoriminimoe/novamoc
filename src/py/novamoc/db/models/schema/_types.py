from __future__ import annotations

from enum import StrEnum


class FieldDataType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
