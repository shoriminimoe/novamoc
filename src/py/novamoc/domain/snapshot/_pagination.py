"""Walks the four projection tables in fixed order.

Captures ``start_seq`` on the first request (when ``page is None``),
pages within the current table, advances to the next non-empty table
when the current one runs out, and emits the terminal batch (with
``cursor=start_seq``) once every table is exhausted.

Tenant scoping is structural: every ``.list(...)`` and every
``current_version`` / ``current_seq`` aggregate routes through Layer 1
of ``db._listeners``. The paginator carries no tenant predicate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from advanced_alchemy.filters import LimitOffset, OrderBy
from sqlalchemy import and_, or_

from novamoc.db.models.data import (
    Asset,
    AssetFieldValue,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)
from novamoc.domain.snapshot._page import (
    PageState,
    SnapshotTable,
    decode_page,
    encode_page,
)
from novamoc.domain.snapshot._payloads import (
    AssetFieldValuesBatchBody,
    AssetFieldValueView,
    AssetsBatchBody,
    AssetView,
    MaintenanceRecordFieldValuesBatchBody,
    MaintenanceRecordFieldValueView,
    MaintenanceRecordsBatchBody,
    MaintenanceRecordView,
    SnapshotBatch,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from advanced_alchemy.filters import StatementFilter
    from sqlalchemy import ColumnElement

    from novamoc.domain.events.services import EventLogService
    from novamoc.domain.schema.services import SchemaChangeLogService
    from novamoc.domain.snapshot._payloads import SnapshotBody
    from novamoc.domain.snapshot.services import (
        AssetFieldValueService,
        AssetService,
        MaintenanceRecordFieldValueService,
        MaintenanceRecordService,
    )


# Fixed order. ``maintenance_record_field_values`` is always last because
# its terminal batch is what carries ``cursor`` (the replication seq).
_TABLES: Final[tuple[SnapshotTable, ...]] = (
    SnapshotTable.ASSETS,
    SnapshotTable.ASSET_FIELD_VALUES,
    SnapshotTable.MAINTENANCE_RECORDS,
    SnapshotTable.MAINTENANCE_RECORD_FIELD_VALUES,
)


def _tables_from(start: SnapshotTable) -> tuple[SnapshotTable, ...]:
    """Suffix of ``_TABLES`` starting at ``start``."""
    idx = _TABLES.index(start)
    return _TABLES[idx:]


def _split_field_value_last_id(last_id: str) -> tuple[UUID, str]:
    """Decode the ``"<entity_uuid>:<field_id>"`` last-id for field-value tables.

    Splits on the first ``:`` so a ``col:name`` field id (which itself
    contains a colon) survives intact.
    """
    entity_str, _, field_id = last_id.partition(":")
    return UUID(entity_str), field_id


class SnapshotPaginator:
    """Page through the four projection tables in fixed order."""

    def __init__(  # noqa: PLR0913  # one parameter per injected service; aggregator class
        self,
        *,
        change_log_service: SchemaChangeLogService,
        event_log_service: EventLogService,
        asset_service: AssetService,
        asset_field_value_service: AssetFieldValueService,
        maintenance_record_service: MaintenanceRecordService,
        maintenance_record_field_value_service: MaintenanceRecordFieldValueService,
    ) -> None:
        self._change_log = change_log_service
        self._event_log = event_log_service
        self._asset = asset_service
        self._asset_field_value = asset_field_value_service
        self._maintenance_record = maintenance_record_service
        self._maintenance_record_field_value = maintenance_record_field_value_service

    async def __call__(
        self, *, page: str | None, results_per_page: int
    ) -> SnapshotBatch:
        if page is None:
            start_seq = await self._event_log.current_seq()
            current_table = _TABLES[0]
            last_id: str | None = None
        else:
            state = decode_page(page)
            start_seq = state.start_seq
            current_table = state.table
            last_id = state.last_id

        schema_version = await self._change_log.current_version()

        for table in _tables_from(current_table):
            page_last_id = last_id if table is current_table else None
            rows = await self._read_page(table, page_last_id, results_per_page + 1)
            has_more_in_table = len(rows) > results_per_page
            page_rows = rows[:results_per_page]
            if page_rows or table is _TABLES[-1]:
                body = _body_for(table, page_rows)
                next_page, cursor = self._compute_continuation(
                    table=table,
                    page_rows=page_rows,
                    has_more_in_table=has_more_in_table,
                    start_seq=start_seq,
                )
                return SnapshotBatch(
                    schema_version=schema_version,
                    page=next_page,
                    cursor=cursor,
                    body=body,
                )
        # Unreachable: the last-table branch above always returns.
        msg = "SnapshotPaginator exited the walk without emitting a batch"
        raise RuntimeError(msg)

    async def _read_page(
        self,
        table: SnapshotTable,
        last_id: str | None,
        limit: int,
    ) -> Sequence[Any]:
        if table is SnapshotTable.ASSETS:
            filters: list[StatementFilter | ColumnElement[bool]] = [
                OrderBy(field_name="id"),
                LimitOffset(limit=limit, offset=0),
            ]
            if last_id is not None:
                filters.insert(0, Asset.id > UUID(last_id))
            return await self._asset.list(*filters)
        if table is SnapshotTable.ASSET_FIELD_VALUES:
            filters: list[StatementFilter | ColumnElement[bool]] = [
                OrderBy(field_name="asset_id"),
                OrderBy(field_name="field_id"),
                LimitOffset(limit=limit, offset=0),
            ]
            if last_id is not None:
                entity_uuid, field_id = _split_field_value_last_id(last_id)
                # Row-value `>` expanded as portable OR-form. The spec
                # ("Tuple comparison") documents this as the fallback when
                # the sqlalchemy.tuple_ form misbehaves at the typed layer.
                filters.insert(
                    0,
                    or_(
                        AssetFieldValue.asset_id > entity_uuid,
                        and_(
                            AssetFieldValue.asset_id == entity_uuid,
                            AssetFieldValue.field_id > field_id,
                        ),
                    ),
                )
            return await self._asset_field_value.list(*filters)
        if table is SnapshotTable.MAINTENANCE_RECORDS:
            filters: list[StatementFilter | ColumnElement[bool]] = [
                OrderBy(field_name="id"),
                LimitOffset(limit=limit, offset=0),
            ]
            if last_id is not None:
                filters.insert(0, MaintenanceRecord.id > UUID(last_id))
            return await self._maintenance_record.list(*filters)
        # MAINTENANCE_RECORD_FIELD_VALUES
        filters: list[StatementFilter | ColumnElement[bool]] = [
            OrderBy(field_name="maintenance_record_id"),
            OrderBy(field_name="field_id"),
            LimitOffset(limit=limit, offset=0),
        ]
        if last_id is not None:
            entity_uuid, field_id = _split_field_value_last_id(last_id)
            filters.insert(
                0,
                or_(
                    MaintenanceRecordFieldValue.maintenance_record_id > entity_uuid,
                    and_(
                        MaintenanceRecordFieldValue.maintenance_record_id
                        == entity_uuid,
                        MaintenanceRecordFieldValue.field_id > field_id,
                    ),
                ),
            )
        return await self._maintenance_record_field_value.list(*filters)

    @staticmethod
    def _compute_continuation(
        *,
        table: SnapshotTable,
        page_rows: Sequence[Any],
        has_more_in_table: bool,
        start_seq: int,
    ) -> tuple[str | None, int | None]:
        """Return ``(next_page, cursor)`` for this batch.

        ``next_page`` is the opaque pagination continuation (or ``None``
        on the terminal batch). ``cursor`` is the replication
        ``event_log.seq`` (only present on the terminal batch; ``None``
        on intermediate batches).
        """
        if has_more_in_table:
            next_state = PageState(
                start_seq=start_seq,
                table=table,
                last_id=_last_id_of(table, page_rows[-1]),
            )
            return encode_page(next_state), None
        if table is _TABLES[-1]:
            return None, start_seq
        next_table = _TABLES[_TABLES.index(table) + 1]
        next_state = PageState(start_seq=start_seq, table=next_table, last_id=None)
        return encode_page(next_state), None


def _last_id_of(table: SnapshotTable, row: Any) -> str:
    """Return the encoded last-id string for ``row`` in ``table``.

    ``row`` is the appropriate ORM model for ``table``; typed as ``Any``
    because the four branches handle four model classes without
    over-engineering an overload set.
    """
    if table is SnapshotTable.ASSETS:
        return str(row.id)
    if table is SnapshotTable.ASSET_FIELD_VALUES:
        return f"{row.asset_id}:{row.field_id}"
    if table is SnapshotTable.MAINTENANCE_RECORDS:
        return str(row.id)
    return f"{row.maintenance_record_id}:{row.field_id}"


def _body_for(table: SnapshotTable, rows: Sequence[Any]) -> SnapshotBody:
    """Wrap ``rows`` in the discriminated body variant for ``table``."""
    if table is SnapshotTable.ASSETS:
        return AssetsBatchBody(
            items=tuple(
                AssetView(
                    id=r.id,
                    type_id=r.type_id,
                    deleted=r.deleted,
                    row_state_hlc=r.row_state_hlc,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in rows
            )
        )
    if table is SnapshotTable.ASSET_FIELD_VALUES:
        return AssetFieldValuesBatchBody(
            items=tuple(
                AssetFieldValueView(
                    asset_id=r.asset_id,
                    field_id=r.field_id,
                    value_json=r.value_json,
                    hlc=r.hlc,
                )
                for r in rows
            )
        )
    if table is SnapshotTable.MAINTENANCE_RECORDS:
        return MaintenanceRecordsBatchBody(
            items=tuple(
                MaintenanceRecordView(
                    id=r.id,
                    type_id=r.type_id,
                    asset_id=r.asset_id,
                    deleted=r.deleted,
                    row_state_hlc=r.row_state_hlc,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in rows
            )
        )
    return MaintenanceRecordFieldValuesBatchBody(
        items=tuple(
            MaintenanceRecordFieldValueView(
                maintenance_record_id=r.maintenance_record_id,
                field_id=r.field_id,
                value_json=r.value_json,
                hlc=r.hlc,
            )
            for r in rows
        )
    )


__all__ = ("SnapshotPaginator",)
