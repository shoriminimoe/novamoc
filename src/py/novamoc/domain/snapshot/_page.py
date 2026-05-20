"""Opaque pagination token for ``GET /snapshot``.

Encodes ``(start_seq, table, last_id)`` as URL-safe base64 of compact
JSON. Distinct from the replication ``cursor`` (the ``event_log.seq``
returned on the terminal batch) — see the design spec §"Page vs cursor"
for the two-concept disambiguation.

The page token is *not* signed: a client that tampers only hurts itself,
and Layer 1 of the tenant-scoping listeners scopes every read regardless.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from novamoc.domain._errors import ErrorCode, PayloadShapeError


class SnapshotTable(StrEnum):
    """The four projection tables a snapshot walks, in order.

    The string values double as the discriminator tags on the response
    body union (see ``_payloads._SnapshotBody``).
    """

    ASSETS = "assets"
    ASSET_FIELD_VALUES = "asset_field_values"
    MAINTENANCE_RECORDS = "maintenance_records"
    MAINTENANCE_RECORD_FIELD_VALUES = "maintenance_record_field_values"


@dataclass(frozen=True, slots=True)
class PageState:
    """State threaded across one client's snapshot requests.

    Attributes:
        start_seq: ``MAX(event_log.seq)`` observed on the first
            request; emitted as the terminal-batch ``cursor`` on the
            final batch. Threaded so that mid-transfer event arrivals
            don't shift the cursor (design spec §"Why ``start_seq`` on
            the first request").
        table: Next projection table to read from.
        last_id: Last-seen primary key in ``table``, or ``None`` to
            start at the beginning. Entity tables: the UUID as a string.
            Field-value tables: ``"<entity_uuid>:<field_id>"`` (split on
            the first colon, so a ``col:name`` field id parses cleanly).
    """

    start_seq: int
    table: SnapshotTable
    last_id: str | None


def encode_page(state: PageState) -> str:
    """URL-safe base64 of compact JSON. Trailing ``=`` padding stripped."""
    payload = {
        "start_seq": state.start_seq,
        "table": state.table.value,
        "last_id": state.last_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_page(token: str) -> PageState:
    """Inverse of :func:`encode_page`.

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
            message="page is not valid base64",
            field="page",
        ) from exc

    try:
        parsed: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="page is not valid JSON",
            field="page",
        ) from exc

    if not isinstance(parsed, dict):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="page must decode to a JSON object",
            field="page",
        )

    try:
        start_seq = parsed["start_seq"]
        table_value = parsed["table"]
        last_id = parsed["last_id"]
    except KeyError as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"page missing field {exc.args[0]!r}",
            field="page",
        ) from exc

    if not isinstance(start_seq, int) or isinstance(start_seq, bool):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="page.start_seq must be an integer",
            field="page",
        )
    if not isinstance(table_value, str):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="page.table must be a string",
            field="page",
        )
    if last_id is not None and not isinstance(last_id, str):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="page.last_id must be a string or null",
            field="page",
        )

    try:
        table = SnapshotTable(table_value)
    except ValueError as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"page.table {table_value!r} is not a known table",
            field="page",
        ) from exc

    return PageState(start_seq=start_seq, table=table, last_id=last_id)


__all__ = ("PageState", "SnapshotTable", "decode_page", "encode_page")
