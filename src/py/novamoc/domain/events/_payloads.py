"""Wire-format structs for ``POST /events``.

Events are past-tense facts. :class:`Created`, :class:`Updated`,
:class:`Deactivated`, and :class:`Activated` form the
:data:`EventBody` discriminated union; new event types extend it
without changing the envelope.

Three data-model layers map to the wire as ``family`` (meta-schema),
``type_id`` (user-defined type), and ``instance_id`` plus ``values``
(user data). The envelope addresses the entity; the body describes
the event. ``values`` keys are bare UUIDs (user fields) or
``col:<column>`` (projection columns); ``col:type_id``,
``col:asset_id``, and ``col:deleted`` are reserved and rejected.

The envelope's ``hlc`` stamps two LWW tracks: row-state (visibility,
ADR-007) and per-``(instance, field_id)`` cell-state. Re-authored
events preserve their original ``hlc`` for idempotency via
``UNIQUE(tenant_id, hlc)`` (ADR-011).

``tenant_id`` is resolved from the bearer (ADR-014/017); ``seq`` and
``received_at`` are server-assigned; ``schema_version`` lives on the
batch (ADR-008/009). ``forbid_unknown_fields=True`` rejects unknown
keys.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

import msgspec


class EntityFamily(StrEnum):
    """Projection-table family targeted by an event."""

    ASSET = "asset"
    MAINTENANCE_RECORD = "maintenance_record"


class Parent(msgspec.Struct, forbid_unknown_fields=True):
    """Reference to a parent entity.

    Attributes:
        type_id: Parent's user-schema type FK.
        instance_id: Parent's user-data instance id.
    """

    type_id: UUID
    instance_id: UUID


class _Body(msgspec.Struct, tag_field="event", forbid_unknown_fields=True):
    """Discriminator base for :data:`EventBody`.

    Subclasses set ``tag`` to a past-tense event name. The discriminator
    field is ``event`` to avoid collision with the envelope's ``type_id``.
    """


class Created(_Body, tag="created"):
    """Entity was created with this initial definition.

    Stamps both LWW tracks (row-state and per-field). ``parent`` is
    write-once; re-parenting is structurally forbidden by
    :class:`Updated` having no ``parent`` field.

    Attributes:
        parent: Parent reference. Per-family rules (handler-enforced)
            determine when it's required.
        values: Initial field values keyed by ``field_id``. Empty is
            legal.
    """

    parent: Parent | None = None
    values: dict[str, Any] = msgspec.field(default_factory=dict)


class Updated(_Body, tag="updated"):
    """Entity's field values changed.

    Stamps the per-field HLC track only; row-state untouched. ADR-009:
    events may target a deactivated user-schema field (only deleted
    fields are invalid targets).

    Attributes:
        values: Partial update keyed by ``field_id``; ``null`` clears
            a cell. Empty is rejected.
    """

    values: dict[str, Any]


class Deactivated(_Body, tag="deactivated"):
    """Entity was tombstoned.

    Stamps the row-state HLC track only; cell values retained for
    later restoration.
    """


class Activated(_Body, tag="activated"):
    """Entity was restored from tombstoned state.

    Stamps the row-state HLC track only. No-op if no prior
    :class:`Deactivated` exists at a lower HLC.
    """


EventBody = Created | Updated | Deactivated | Activated


class EventEnvelope(msgspec.Struct, forbid_unknown_fields=True):
    """One event addressed by entity tuple, ordered by HLC.

    Attributes:
        hlc: LWW key and idempotency key
            (``UNIQUE(tenant_id, hlc)``, ADR-011).
        family: Meta-schema family.
        type_id: User-schema type FK.
        instance_id: User-data instance id.
        body: Discriminated event payload.
    """

    hlc: str
    family: EntityFamily
    type_id: UUID
    instance_id: UUID
    body: EventBody


class EventBatch(msgspec.Struct, forbid_unknown_fields=True):
    """Batch posted to ``POST /events``.

    Per-event outcomes (see :class:`EventOutcome`) are atomic at the
    event grain, not the batch grain (M1.5): one rejected or duplicate
    event does not poison its neighbours. Batch-level failures
    (``schema_version_stale``, malformed body) still reject the
    whole submission via the ``application/problem+json`` envelope.

    Attributes:
        schema_version: Client's loaded schema state (ADR-008/009).
        events: Ordered tuple. Order is preserved in the response.
    """

    schema_version: int
    events: tuple[EventEnvelope, ...]


class EventOutcome(msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True):
    """Per-event outcome in the ``POST /events`` response.

    ``outcome`` is one of:

    - ``accepted`` — appended to ``event_log``.
    - ``duplicate`` — a row with the same ``(tenant_id, hlc)`` already
      exists (idempotent re-delivery, ADR-011).
    - ``rejected:<code>`` — per-event validation failed; ``<code>`` is
      the corresponding :class:`ErrorCode` value (``hlc_drift_exceeded``,
      ``unknown_field``, ``value_type_mismatch``, or
      ``invalid_payload_shape``).

    Rejected outcomes also carry ``problem``, a dict shaped like the
    ``application/problem+json`` body the same error would produce at
    batch level — standard RFC 9457 slots (``type``, ``title``,
    ``status``, ``detail``, ``instance``) plus per-code extension
    members at top level (e.g. ``drift_seconds``, ``field``,
    ``expected``). The docs page pointed to by ``problem.type``
    documents the per-code extras. Omitted for ``accepted`` and
    ``duplicate``.
    """

    hlc: str
    outcome: str
    problem: dict[str, Any] | None = None


class EventBatchResponse(msgspec.Struct, forbid_unknown_fields=True):
    """Response body for ``POST /events``.

    ``outcomes`` is ordered to match the input ``events`` tuple, so a
    client can correlate by index in addition to by ``hlc``.
    """

    outcomes: tuple[EventOutcome, ...]
