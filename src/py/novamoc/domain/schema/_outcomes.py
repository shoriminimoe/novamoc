"""Outcome of a single accepted ``POST /schema`` command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Outcome(StrEnum):
    CREATED = "created"
    ACTIVATED = "activated"
    NOOP = "noop"
    UPDATED = "updated"
    DEACTIVATED = "deactivated"
    CLEARED = "cleared"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class SchemaCommitOutcome:
    schema_version: int
    entity_id: UUID
    outcome: Outcome
    committed_at: datetime
