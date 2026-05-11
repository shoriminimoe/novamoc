"""Shared validation helpers for the events endpoint (M1.4).

Public surface:

* :func:`validate_values` — sync. Iterates a values dict, classifies each
  key (UUID user field vs ``col:<name>`` projection column), and validates
  the value's JSON shape against the field's declared ``FieldDataType``.
  Raises one of the M1.4 error types on the first offending key.
* :func:`matches_data_type` / :func:`json_type_name` — pure predicates,
  exposed for handler-level tests and future callers.

The handler is responsible for loading the type's field set and passing
it via ``fields_by_id``. The validator does no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID

from novamoc.db.models.schema._types import FieldDataType
from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.events._errors import (
    UnknownFieldError,
    ValueTypeMismatchError,
)
from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from novamoc.domain.events._payloads import EventEnvelope


__all__ = ("json_type_name", "matches_data_type", "validate_values")


class _FieldLike(Protocol):
    """Minimal shape the validator reads from a field row.

    Both ``AssetTypeField`` and ``MaintenanceRecordTypeField`` satisfy
    this; unit tests build a structurally-compatible dataclass without
    the SQLAlchemy / advanced-alchemy machinery.
    """

    @property
    def data_type(self) -> FieldDataType: ...


_COL_PREFIX: Final = "col:"

_RESERVED_COLS: Final[frozenset[str]] = frozenset(
    {"type_id", "asset_id", "deleted", "row_state_hlc"}
)

_USER_WRITABLE_COLS: Final[dict[EntityFamily, dict[str, FieldDataType]]] = {
    EntityFamily.ASSET: {"name": FieldDataType.TEXT},
    EntityFamily.MAINTENANCE_RECORD: {"name": FieldDataType.TEXT},
}

# bool comes first — ``bool`` is an ``int`` subclass and would otherwise
# resolve to "integer".
_JSON_TYPE_LABELS: Final[tuple[tuple[type, str], ...]] = (
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (list, "array"),
    (dict, "object"),
)


def json_type_name(value: Any) -> str:
    """Human-readable JSON type label for problem-details ``received``."""
    if value is None:
        return "null"
    for cls, label in _JSON_TYPE_LABELS:
        if isinstance(value, cls):
            return label
    return type(value).__name__


def _is_text(v: Any) -> bool:
    return isinstance(v, str)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_integer(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_boolean(v: Any) -> bool:
    return isinstance(v, bool)


_DATA_TYPE_PREDICATES: Final[dict[FieldDataType, Callable[[Any], bool]]] = {
    FieldDataType.TEXT: _is_text,
    FieldDataType.NUMBER: _is_number,
    FieldDataType.INTEGER: _is_integer,
    FieldDataType.BOOLEAN: _is_boolean,
    FieldDataType.DATE: _is_text,
    FieldDataType.DATETIME: _is_text,
}


def matches_data_type(value: Any, data_type: FieldDataType) -> bool:
    """Whether ``value``'s JSON shape matches ``data_type``.

    ``None`` is always a match — it is the cell-clearing sentinel.
    """
    if value is None:
        return True
    return _DATA_TYPE_PREDICATES[data_type](value)


def _check_value(*, field: str, value: Any, data_type: FieldDataType) -> None:
    if not matches_data_type(value, data_type):
        raise ValueTypeMismatchError(
            field=field,
            expected=data_type.value,
            received=json_type_name(value),
        )


def _validate_col(
    *,
    event: EventEnvelope,
    key: str,
    value: Any,
) -> None:
    col_name = key[len(_COL_PREFIX) :]
    if col_name in _RESERVED_COLS:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"Field {key!r} is server-managed and cannot be set on the wire.",
            field=key,
        )
    family_cols = _USER_WRITABLE_COLS.get(event.family, {})
    data_type = family_cols.get(col_name)
    if data_type is None:
        raise UnknownFieldError(
            family=event.family.value,
            type_id=str(event.type_id),
            field=key,
        )
    _check_value(field=key, value=value, data_type=data_type)


def _validate_user_field(
    *,
    event: EventEnvelope,
    key: str,
    value: Any,
    fields_by_id: Mapping[UUID, _FieldLike],
) -> None:
    try:
        field_id = UUID(key)
    except ValueError as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"Field key {key!r} is neither a UUID nor a 'col:' column.",
            field=key,
        ) from exc
    field = fields_by_id.get(field_id)
    if field is None:
        raise UnknownFieldError(
            family=event.family.value,
            type_id=str(event.type_id),
            field=key,
        )
    _check_value(field=key, value=value, data_type=field.data_type)


def validate_values(
    *,
    event: EventEnvelope,
    values: Mapping[str, Any],
    fields_by_id: Mapping[UUID, _FieldLike],
) -> None:
    """Validate every (key, value) pair against the preloaded field set.

    Iterates ``values``; classifies each key as a UUID (looked up in
    ``fields_by_id``) or ``col:<name>`` (matched against the static
    reserved / user-writable tables). Raises on the first offending key:

    Raises:
        PayloadShapeError: key is malformed (not a UUID, not ``col:<known>``)
            or addresses a reserved server-managed column.
        UnknownFieldError: a UUID field id is not in ``fields_by_id`` (so it
            does not belong to ``event.type_id``), or a ``col:`` column is
            not in :data:`_USER_WRITABLE_COLS`.
        ValueTypeMismatchError: a value's JSON shape does not match the
            field's declared ``FieldDataType``.
    """
    for key, value in values.items():
        if key.startswith(_COL_PREFIX):
            _validate_col(event=event, key=key, value=value)
        else:
            _validate_user_field(
                event=event, key=key, value=value, fields_by_id=fields_by_id
            )
