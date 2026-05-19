"""Opaque cursor for the initial-sync transfer.

Encodes ``(start_seq, table, last_id)`` as URL-safe base64 of compact JSON.
The cursor is *not* signed: see the design spec §"Cursor encoding" for
the threat model — a client that tampers only hurts itself, and Layer 1
of the tenant-scoping listeners scopes every read regardless.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from novamoc.domain._errors import ErrorCode, PayloadShapeError


class InitialSyncTable(StrEnum):
    """The four projection tables an initial sync walks, in order.

    The string values double as the discriminator tags on the response
    body union (see ``_payloads._SyncBody``).
    """

    ASSETS = "assets"
    ASSET_FIELD_VALUES = "asset_field_values"
    MAINTENANCE_RECORDS = "maintenance_records"
    MAINTENANCE_RECORD_FIELD_VALUES = "maintenance_record_field_values"


@dataclass(frozen=True, slots=True)
class CursorState:
    """State threaded across one client's initial-sync requests.

    Attributes:
        start_seq: ``MAX(event_log.seq)`` observed on the first
            request; emitted as ``event_log_cursor`` on the terminal
            batch. Threaded so that mid-transfer event arrivals don't
            shift the cursor (design spec §"Why ``start_seq`` on the
            first request").
        table: Next projection table to read from.
        last_id: Last-seen primary key in ``table``, or ``None`` to
            start at the beginning. Entity tables: the UUID as a string.
            Field-value tables: ``"<entity_uuid>:<field_id>"`` (split on
            the first colon, so a ``col:name`` field id parses cleanly).
    """

    start_seq: int
    table: InitialSyncTable
    last_id: str | None


def encode_cursor(state: CursorState) -> str:
    """URL-safe base64 of compact JSON. Trailing ``=`` padding stripped."""
    payload = {
        "start_seq": state.start_seq,
        "table": state.table.value,
        "last_id": state.last_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(token: str) -> CursorState:
    """Inverse of :func:`encode_cursor`.

    Raises:
        PayloadShapeError: token isn't valid base64-JSON, the decoded
            object is missing required fields, has the wrong field
            types, or names an unknown ``table``.
    """
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor is not valid base64",
            field="cursor",
        ) from exc

    try:
        parsed: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor is not valid JSON",
            field="cursor",
        ) from exc

    if not isinstance(parsed, dict):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor must decode to a JSON object",
            field="cursor",
        )

    try:
        start_seq = parsed["start_seq"]
        table_value = parsed["table"]
        last_id = parsed["last_id"]
    except KeyError as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"cursor missing field {exc.args[0]!r}",
            field="cursor",
        ) from exc

    if not isinstance(start_seq, int) or isinstance(start_seq, bool):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor.start_seq must be an integer",
            field="cursor",
        )
    if not isinstance(table_value, str):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor.table must be a string",
            field="cursor",
        )
    if last_id is not None and not isinstance(last_id, str):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor.last_id must be a string or null",
            field="cursor",
        )

    try:
        table = InitialSyncTable(table_value)
    except ValueError as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"cursor.table {table_value!r} is not a known table",
            field="cursor",
        ) from exc

    return CursorState(start_seq=start_seq, table=table, last_id=last_id)


__all__ = ("CursorState", "InitialSyncTable", "decode_cursor", "encode_cursor")
