/**
 * Deterministic per-field LWW fold (ADR-007 / ADR-012 / ADR-019).
 *
 * This is the client half of the parity contract: the server folds the
 * same event log into its projection tables via
 * `domain/events/_bundle.py::append_event` (which orchestrates
 * `apply_row_state` → `apply_field_value` → `apply_entity_projection`),
 * and this module must produce byte-identical projection state from the
 * same events. The shared scenarios under repo-root `tests/fold-parity/`
 * pin both implementations to the same truth.
 *
 * The fold is pure: no I/O, no clock, no randomness. It takes the current
 * projection plus a batch of events and returns the next projection. The
 * SQL bridge that persists the result into SQLite-WASM lives in the issues
 * that consume the fold (snapshot ingest, catch-up, write path) — never
 * here.
 *
 * Two rules drive the implementation, each mirroring a server step:
 *
 * 1. Row-state runs first (server `apply_row_state`). `created` inserts the
 *    entity row if missing, else restores it under the HLC guard;
 *    `activated`/`deactivated` toggle `deleted` on an existing row under the
 *    guard; `updated` has no row-state component. The guard is
 *    strict-greater on `row_state_hlc`.
 * 2. Per-`(entity, field)` LWW fold (server `apply_field_value`). A field
 *    value is written only when its HLC is strictly greater than the stored
 *    one — late arrivals lose silently, equal HLCs are idempotent no-ops.
 *    A cleared cell carries value `null` and is recorded like any other
 *    value (ADR-019: it is not removed).
 *
 * The server's third step (`apply_entity_projection`, mirroring values into
 * the entity row's `name` / `properties`) has no client analog: the client
 * `assets`/`maintenance_records` tables have no `name` or `properties`
 * column that the fold writes — derived entity JSON is reconstructed from
 * the per-field rows at read time (ADR-015). The field-value tables carry
 * the full LWW truth, including `col:`-prefixed reserved fields.
 */

import type {
  EntityFamily,
  EntityRow,
  EventBody,
  EventEnvelope,
  FieldValueRow,
  Projection,
  SchemaField,
  SchemaProjection,
  SchemaSnapshotWire,
  SchemaType,
  SchemaWireType,
  SnapshotRow,
} from './types'

function flattenTypes(types: SchemaWireType[]): {
  types: SchemaType[]
  fields: SchemaField[]
} {
  const flatTypes: SchemaType[] = []
  const flatFields: SchemaField[] = []
  for (const type of types) {
    flatTypes.push({ id: type.id, name: type.name, active: type.active })
    for (const field of type.fields) {
      flatFields.push({
        id: field.id,
        parent_id: type.id,
        name: field.name,
        data_type: field.data_type,
        validation: field.validation,
        active: field.active,
      })
    }
  }
  return { types: flatTypes, fields: flatFields }
}

/**
 * Flatten the nested `GET /schema` response into the flat
 * {@link SchemaProjection} the local schema tables hold. The server is
 * authoritative for the schema (ADR-008): the response is the whole truth,
 * so this is a wholesale flatten, not an HLC-guarded merge like the data
 * fold — the SQL ingest replaces the local rows with what this returns.
 */
export function applySchemaProjection(
  wire: SchemaSnapshotWire,
): SchemaProjection {
  const assets = flattenTypes(wire.asset_types)
  const records = flattenTypes(wire.maintenance_record_types)
  return {
    schema_version: wire.schema_version,
    asset_types: assets.types,
    asset_type_fields: assets.fields,
    maintenance_record_types: records.types,
    maintenance_record_type_fields: records.fields,
  }
}

/** Per-family handles into the projection. Keeps the fold generic. */
interface FamilyTables {
  entities: Map<string, EntityRow>
  fieldValues: Map<string, FieldValueRow>
}

function tablesFor(projection: Projection, family: EntityFamily): FamilyTables {
  if (family === 'asset') {
    return {
      entities: projection.assets,
      fieldValues: projection.asset_field_values,
    }
  }
  return {
    entities: projection.maintenance_records,
    fieldValues: projection.maintenance_record_field_values,
  }
}

function fieldKey(entityId: string, fieldId: string): string {
  // Field ids are UUID strings or `col:<name>` — neither contains a space,
  // so a space delimiter cannot collide.
  return `${entityId} ${fieldId}`
}

/**
 * Shallow-clone the projection so the fold never mutates its input. Each
 * map is copied; the row objects inside are replaced wholesale on write
 * (never mutated in place), so a shallow map copy is enough to isolate the
 * caller's projection.
 */
function cloneProjection(projection: Projection): Projection {
  return {
    assets: new Map(projection.assets),
    asset_field_values: new Map(projection.asset_field_values),
    maintenance_records: new Map(projection.maintenance_records),
    maintenance_record_field_values: new Map(
      projection.maintenance_record_field_values,
    ),
  }
}

function bodyValues(body: EventBody): Record<string, unknown> {
  if (body.event === 'created' || body.event === 'updated') {
    return body.values ?? {}
  }
  return {}
}

/** Server `apply_row_state`: insert-or-restore for `created`, toggle for
 * `activated`/`deactivated`, no-op for `updated`. */
function applyRowState(tables: FamilyTables, event: EventEnvelope): void {
  const { entities } = tables
  const existing = entities.get(event.instance_id)
  const body = event.body

  if (body.event === 'created') {
    if (existing === undefined) {
      const row: EntityRow = {
        id: event.instance_id,
        type_id: event.type_id,
        deleted: false,
        row_state_hlc: event.hlc,
      }
      if (event.family === 'maintenance_record') {
        // A Created MR references its parent asset (server raises an
        // invalid_payload_shape DomainError when absent; parity scenarios
        // never carry a malformed MR create, so we read the parent directly).
        row.asset_id = body.parent?.instance_id
      }
      entities.set(event.instance_id, row)
    } else if (event.hlc > existing.row_state_hlc) {
      entities.set(event.instance_id, {
        ...existing,
        deleted: false,
        row_state_hlc: event.hlc,
      })
    }
    return
  }

  if (body.event === 'activated' || body.event === 'deactivated') {
    // UPDATE-only: a missing row is a no-op (restoration requires a row that
    // has been seen). Strict-greater HLC guard.
    if (existing !== undefined && event.hlc > existing.row_state_hlc) {
      entities.set(event.instance_id, {
        ...existing,
        deleted: body.event === 'deactivated',
        row_state_hlc: event.hlc,
      })
    }
  }
  // `updated`: no row-state component.
}

/**
 * Server `apply_field_value`: conditional upsert under the strict-greater
 * HLC guard. A stored cell with an HLC >= the new event's loses nothing —
 * late arrivals and equal-HLC re-delivery are silent no-ops.
 */
function applyFieldValue(
  tables: FamilyTables,
  entityId: string,
  fieldId: string,
  value: unknown,
  hlc: string,
): void {
  const key = fieldKey(entityId, fieldId)
  const existing = tables.fieldValues.get(key)
  if (existing !== undefined && hlc <= existing.hlc) {
    return
  }
  tables.fieldValues.set(key, {
    entity_id: entityId,
    field_id: fieldId,
    value_json: value,
    hlc,
  })
}

/**
 * Fold `events` into `projection`, returning a new projection. The input is
 * left untouched. Events are applied in array order; the per-field HLC guard
 * makes the field-value result order-independent, but row-state writes
 * observe array order.
 */
export function fold(
  projection: Projection,
  events: readonly EventEnvelope[],
): Projection {
  const next = cloneProjection(projection)
  for (const event of events) {
    const tables = tablesFor(next, event.family)
    // Row-state first so a `created` row exists before its values fold in.
    applyRowState(tables, event)
    for (const [fieldId, value] of Object.entries(bodyValues(event.body))) {
      applyFieldValue(tables, event.instance_id, fieldId, value, event.hlc)
    }
  }
  return next
}

/**
 * Apply one `GET /snapshot` row to `projection`, returning a new projection.
 * The input is left untouched.
 *
 * Snapshot rows are *already-committed* projection state — the server resolved
 * LWW before serving them — so this is an unconditional write, not the
 * HLC-guarded merge {@link fold} runs on events. It still honours the fold's
 * materialization contract: entity rows carry only structural columns (`id`,
 * `type_id`, `asset_id`, `deleted`, `row_state_hlc`); `name`/`properties` are
 * never materialized (reconstructed from per-field rows at read time, ADR-015).
 * The field-value rows carry their `hlc` so a subsequent event fold against
 * this state stays LWW-correct (ADR-007). The four snapshot tables map onto the
 * same four projection maps the fold writes, so applying every snapshot row
 * yields the same projection as folding the events that produced them.
 */
export function applySnapshotRow(
  projection: Projection,
  snapshot: SnapshotRow,
): Projection {
  const next = cloneProjection(projection)
  switch (snapshot.table) {
    case 'assets': {
      const { row } = snapshot
      next.assets.set(row.id, {
        id: row.id,
        type_id: row.type_id,
        deleted: row.deleted,
        row_state_hlc: row.row_state_hlc,
      })
      break
    }
    case 'maintenance_records': {
      const { row } = snapshot
      next.maintenance_records.set(row.id, {
        id: row.id,
        type_id: row.type_id,
        asset_id: row.asset_id,
        deleted: row.deleted,
        row_state_hlc: row.row_state_hlc,
      })
      break
    }
    case 'asset_field_values': {
      const { row } = snapshot
      next.asset_field_values.set(fieldKey(row.entity_id, row.field_id), {
        entity_id: row.entity_id,
        field_id: row.field_id,
        value_json: row.value_json,
        hlc: row.hlc,
      })
      break
    }
    case 'maintenance_record_field_values': {
      const { row } = snapshot
      next.maintenance_record_field_values.set(
        fieldKey(row.entity_id, row.field_id),
        {
          entity_id: row.entity_id,
          field_id: row.field_id,
          value_json: row.value_json,
          hlc: row.hlc,
        },
      )
      break
    }
  }
  return next
}

/** An empty projection — the starting point for a from-scratch fold. */
export function emptyProjection(): Projection {
  return {
    assets: new Map(),
    asset_field_values: new Map(),
    maintenance_records: new Map(),
    maintenance_record_field_values: new Map(),
  }
}
