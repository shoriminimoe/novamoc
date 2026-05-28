"""Shared fixtures for ``tests/events/``.

The ``event_services`` fixture wires an ``EventServiceBundle`` against
the function-scoped ``session`` from the top-level conftest. The bundle
shape is fixed by the production wiring (``domain.events._bundle``);
the only knob worth varying per test is ``schema_version``, which
defaults to ``0`` here — handler-level tests don't exercise the
schema-version gate (that's the controller's job), so ``0`` matches
what every consumer in this directory wants.

``tests/events/test_bundle.py`` keeps its own fixture because it
substitutes a counting spy for ``AssetTypeFieldService``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def event_services(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=0,
    )
