"""Server side of the shared LWW-fold parity harness (ADR-007 / ADR-012).

Drives the *production* server fold — ``EventServiceBundle.append_event``,
which orchestrates ``apply_row_state`` → ``apply_field_value`` →
``apply_entity_projection`` — over each JSON scenario in this directory
and asserts the resulting projection equals the scenario's
``expected_projection``. The vitest twin
(``src/js/web/tests/fold-parity/fold-parity.test.ts``) drives the client
fold over the *same* JSON files, so a fold that diverges between the two
implementations fails in one suite or the other.

The harness is self-contained: it seeds ``schema_state`` directly via the
ORM (so projection-table foreign keys resolve) and reads the projection
back through the ORM. The comparison is over the *structural* entity-row
columns plus the full field-value tables — the derived ``name`` /
``properties`` JSON is reconstructed from field-value rows at read time
(ADR-015) and is not part of the fold's parity contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import msgspec
import pytest
from sqlalchemy import select

from novamoc.db.models.data import (
    Asset,
    AssetFieldValue,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)
from novamoc.db.models.schema import (
    AssetType,
    AssetTypeField,
    MaintenanceRecordType,
    MaintenanceRecordTypeField,
)
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._payloads import EntityFamily, EventBody, EventEnvelope
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

_SCENARIO_DIR = Path(__file__).parent
# E1.3 (HLC) ships its own self-contained parity runner; skip its scenario
# here so the two harnesses stay independent and don't fight over loading.
_NOT_OURS = frozenset({"hlc_basic.json"})
_SCENARIO_FILES = sorted(
    p for p in _SCENARIO_DIR.glob("*.json") if p.name not in _NOT_OURS
)
# Schema-version tag on every folded event. The fold itself doesn't gate on
# it (ADR-009 gating lives upstream); any constant works for parity.
_SCHEMA_VERSION = 1


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def _seed_schema(session: AsyncSession, schema_state: Mapping[str, Any]) -> None:
    """Insert the scenario's schema rows so projection FKs resolve.

    The autouse ``tenant`` fixture's contextvar makes the tenant-scoping
    listeners stamp ``tenant_id`` on flush, so these rows need no explicit
    tenant.
    """
    for row in schema_state.get("asset_types", []):
        session.add(AssetType(id=UUID(row["id"]), name=row["name"]))
    for row in schema_state.get("maintenance_record_types", []):
        session.add(MaintenanceRecordType(id=UUID(row["id"]), name=row["name"]))
    await session.flush()
    for row in schema_state.get("asset_type_fields", []):
        session.add(
            AssetTypeField(
                id=UUID(row["id"]),
                parent_id=UUID(row["parent_id"]),
                name=row["name"],
                data_type=row["data_type"],
            )
        )
    for row in schema_state.get("maintenance_record_type_fields", []):
        session.add(
            MaintenanceRecordTypeField(
                id=UUID(row["id"]),
                parent_id=UUID(row["parent_id"]),
                name=row["name"],
                data_type=row["data_type"],
            )
        )
    await session.flush()


def _envelope(raw: Mapping[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        hlc=raw["hlc"],
        family=EntityFamily(raw["family"]),
        type_id=UUID(raw["type_id"]),
        instance_id=UUID(raw["instance_id"]),
        body=msgspec.convert(raw["body"], type=EventBody),
    )


def _entity_rows(rows: list[Any], *, with_parent: bool) -> list[dict[str, Any]]:
    """Project entity ORM rows to the structural columns the parity
    contract compares. ``name`` / ``properties`` are excluded — those are
    read-time-derived (ADR-015), not fold output."""
    projected: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "id": str(row.id),
            "type_id": str(row.type_id),
            "deleted": bool(row.deleted),
            "row_state_hlc": row.row_state_hlc,
        }
        if with_parent:
            entry["asset_id"] = str(row.asset_id)
        projected.append(entry)
    return sorted(projected, key=lambda r: r["id"])


def _field_rows(rows: list[Any], id_attr: str) -> list[dict[str, Any]]:
    projected = [
        {
            "entity_id": str(getattr(row, id_attr)),
            "field_id": row.field_id,
            "value_json": row.value_json,
            "hlc": row.hlc,
        }
        for row in rows
    ]
    return sorted(projected, key=lambda r: (r["entity_id"], r["field_id"]))


def _normalise_expected(expected: Mapping[str, Any]) -> dict[str, Any]:
    """Sort the expected tables the same way the actual ones are sorted."""
    return {
        "assets": sorted(expected["assets"], key=lambda r: r["id"]),
        "asset_field_values": sorted(
            expected["asset_field_values"],
            key=lambda r: (r["entity_id"], r["field_id"]),
        ),
        "maintenance_records": sorted(
            expected["maintenance_records"], key=lambda r: r["id"]
        ),
        "maintenance_record_field_values": sorted(
            expected["maintenance_record_field_values"],
            key=lambda r: (r["entity_id"], r["field_id"]),
        ),
    }


async def _read_projection(session: AsyncSession) -> dict[str, Any]:
    assets = (await session.execute(select(Asset))).scalars().all()
    asset_fvs = (await session.execute(select(AssetFieldValue))).scalars().all()
    mrs = (await session.execute(select(MaintenanceRecord))).scalars().all()
    mr_fvs = (
        (await session.execute(select(MaintenanceRecordFieldValue))).scalars().all()
    )
    return {
        "assets": _entity_rows(list(assets), with_parent=False),
        "asset_field_values": _field_rows(list(asset_fvs), "asset_id"),
        "maintenance_records": _entity_rows(list(mrs), with_parent=True),
        "maintenance_record_field_values": _field_rows(
            list(mr_fvs), "maintenance_record_id"
        ),
    }


@pytest.mark.parametrize("scenario_path", _SCENARIO_FILES, ids=lambda p: p.stem)
async def test_server_fold_matches_expected(
    scenario_path: Path, session: AsyncSession
) -> None:
    scenario = _load(scenario_path)
    await _seed_schema(session, scenario["schema_state"])

    bundle = EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=_SCHEMA_VERSION,
    )
    for raw in scenario["events"]:
        await bundle.append_event(_envelope(raw))
    await session.flush()

    actual = await _read_projection(session)
    expected = _normalise_expected(scenario["expected_projection"])
    assert actual == expected
