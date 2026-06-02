/**
 * Schema-projection ingest and the schema-version gate (ADR-008 / ADR-009).
 *
 * The schema is server-authoritative: the client refetches `GET /schema` and
 * reconciles its local projection wholesale (the design rejects delta-event
 * ingest — see the epic spec Q6). After a refresh the local schema tables
 * exactly mirror the wire response and `sync_state.active_schema_version`
 * holds the server's current version.
 *
 * The gate is the load-bearing ADR-009 invariant: an inbound catch-up event
 * tagged with a `schema_version` ahead of the local `active_schema_version`
 * must NOT be applied — a server schema change the client hasn't ingested
 * could corrupt the projection (e.g. an event referencing a field the local
 * schema doesn't yet know). Such events are buffered verbatim in
 * `pending_schema_buffer` and released — re-evaluated and handed back to the
 * caller for folding — once a later refresh raises the active version to or
 * past the event's. This module owns the gate and the buffer; the fold and
 * the catch-up loop that consume released events live elsewhere.
 *
 * `active_schema_version` only ever advances. A refresh that reports a
 * version below the stored one (a stale read racing a newer one) leaves the
 * stored version untouched — the gate must never loosen.
 */

import { applySchemaProjection } from '../db/fold'
import { fetchSchema } from '../schema'
import type { DbHandle } from '../db/bootstrap'
import type { ApiClient } from '../api'
import type { SchemaField, SchemaProjection, SchemaType } from '../db/types'

/** The minimal persistence surface the ingest needs — satisfied by {@link DbHandle}. */
export type SchemaStore = Pick<DbHandle, 'exec'>

/** A gated inbound event: the catch-up envelope plus its replication cursor. */
export interface BufferableEvent {
  seq: number
  hlc: string
  schema_version: number
  family: string
  type_id: string
  instance_id: string
  /** The event body, JSON-serialisable; stored verbatim and replayed on release. */
  body: unknown
  received_at?: string | null
}

/** Outcome of gating one event against the active schema version. */
export type GateDecision = 'apply' | 'buffer'

/**
 * Decide whether an event may be applied now (`'apply'`) or must wait for a
 * schema refresh (`'buffer'`). Pure — no I/O, no clock. ADR-009: an event is
 * applicable iff its `schema_version` is not ahead of what the client holds.
 */
export function gateEvent(
  event: { schema_version: number },
  activeVersion: number,
): GateDecision {
  return event.schema_version <= activeVersion ? 'apply' : 'buffer'
}

async function readActiveVersion(store: SchemaStore): Promise<number> {
  const rows = await store.exec(
    'SELECT active_schema_version FROM sync_state WHERE id = 1',
  )
  return (rows[0]?.[0] as number | undefined) ?? 0
}

/** Read the tenant's current `active_schema_version` (the gate threshold). */
export function activeSchemaVersion(store: SchemaStore): Promise<number> {
  return readActiveVersion(store)
}

function jsonOrNull(value: Record<string, unknown> | null): string | null {
  return value === null ? null : JSON.stringify(value)
}

async function upsertTypes(
  store: SchemaStore,
  table: string,
  tenantId: string,
  types: SchemaType[],
): Promise<void> {
  for (const type of types) {
    await store.exec(
      `INSERT INTO ${table} (tenant_id, id, name, active) VALUES (?, ?, ?, ?)`,
      [tenantId, type.id, type.name, type.active ? 1 : 0],
    )
  }
}

async function upsertFields(
  store: SchemaStore,
  table: string,
  tenantId: string,
  fields: SchemaField[],
): Promise<void> {
  for (const field of fields) {
    await store.exec(
      `INSERT INTO ${table}
         (tenant_id, id, parent_id, name, data_type, validation, active)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        tenantId,
        field.id,
        field.parent_id,
        field.name,
        field.data_type,
        jsonOrNull(field.validation),
        field.active ? 1 : 0,
      ],
    )
  }
}

/**
 * Replace the tenant's schema-projection rows with `projection`. Wholesale
 * delete-then-insert: the server is authoritative, so the response is the
 * entire truth and a diff merge would only risk drift. The four tables are
 * cleared parent-last/child-first to respect the FK, then repopulated. Runs
 * inside the caller's transaction.
 */
async function reconcileTables(
  store: SchemaStore,
  tenantId: string,
  projection: SchemaProjection,
): Promise<void> {
  // Child tables first: `*_type_fields` FK their parent type.
  for (const table of [
    'asset_type_fields',
    'maintenance_record_type_fields',
    'asset_types',
    'maintenance_record_types',
  ]) {
    await store.exec(`DELETE FROM ${table} WHERE tenant_id = ?`, [tenantId])
  }
  await upsertTypes(store, 'asset_types', tenantId, projection.asset_types)
  await upsertTypes(
    store,
    'maintenance_record_types',
    tenantId,
    projection.maintenance_record_types,
  )
  await upsertFields(
    store,
    'asset_type_fields',
    tenantId,
    projection.asset_type_fields,
  )
  await upsertFields(
    store,
    'maintenance_record_type_fields',
    tenantId,
    projection.maintenance_record_type_fields,
  )
}

export interface RefreshSchemaOptions {
  store: SchemaStore
  tenantId: string
  /** API client for `GET /schema`. Defaults to the shared session-cookie client. */
  client: ApiClient
}

export interface RefreshSchemaResult {
  /** The active schema version after the refresh (monotonic). */
  activeVersion: number
  /** Buffered events the version bump just unblocked, in cursor order. */
  released: BufferableEvent[]
}

/**
 * Buffer an inbound event whose schema version is ahead of the local one.
 * `INSERT OR REPLACE` keyed on `(tenant_id, seq)` makes a re-delivered batch
 * idempotent. Caller is responsible for gating before calling.
 */
export async function bufferEvent(
  store: SchemaStore,
  tenantId: string,
  event: BufferableEvent,
): Promise<void> {
  await store.exec(
    `INSERT OR REPLACE INTO pending_schema_buffer
       (tenant_id, seq, hlc, schema_version, family, type_id, instance_id, body, received_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      tenantId,
      event.seq,
      event.hlc,
      event.schema_version,
      event.family,
      event.type_id,
      event.instance_id,
      JSON.stringify(event.body),
      event.received_at ?? null,
    ],
  )
}

/** Number of events currently parked in the buffer (debug-surface input). */
export async function bufferedEventCount(
  store: SchemaStore,
  tenantId: string,
): Promise<number> {
  const rows = await store.exec(
    'SELECT count(*) FROM pending_schema_buffer WHERE tenant_id = ?',
    [tenantId],
  )
  return (rows[0]?.[0] as number | undefined) ?? 0
}

/**
 * Pull and delete every buffered event now applicable under `activeVersion`
 * (`schema_version <= activeVersion`), in ascending `seq` order. The rows are
 * removed in the same transaction they're read, so a caller that folds the
 * returned events completes the buffer-to-projection handoff atomically.
 */
async function releaseBufferedEvents(
  store: SchemaStore,
  tenantId: string,
  activeVersion: number,
): Promise<BufferableEvent[]> {
  const rows = await store.exec(
    `SELECT seq, hlc, schema_version, family, type_id, instance_id, body, received_at
       FROM pending_schema_buffer
      WHERE tenant_id = ? AND schema_version <= ?
      ORDER BY seq`,
    [tenantId, activeVersion],
  )
  if (rows.length === 0) {
    return []
  }
  await store.exec(
    'DELETE FROM pending_schema_buffer WHERE tenant_id = ? AND schema_version <= ?',
    [tenantId, activeVersion],
  )
  return rows.map((row) => ({
    seq: row[0] as number,
    hlc: row[1] as string,
    schema_version: row[2] as number,
    family: row[3] as string,
    type_id: row[4] as string,
    instance_id: row[5] as string,
    body: JSON.parse(row[6] as string),
    received_at: row[7] as string | null,
  }))
}

/**
 * Fetch `GET /schema`, reconcile the local schema projection, advance the
 * active schema version monotonically, and release any buffered events the
 * bump unblocks.
 *
 * Idempotent: re-running against an unchanged server reproduces the same
 * local tables and the same (already-advanced) version, and releases nothing.
 * The reconcile + version write + buffer release all run in one transaction so
 * a failed fetch or write leaves the prior state intact.
 */
export async function refreshSchema(
  options: RefreshSchemaOptions,
): Promise<RefreshSchemaResult> {
  const { store, tenantId, client } = options
  const wire = await fetchSchema(client)
  const projection = applySchemaProjection(wire)

  await store.exec('BEGIN')
  try {
    await reconcileTables(store, tenantId, projection)

    // Monotonic: never lower the active version, even if a stale read reports
    // an older one. `MAX` keeps the gate from loosening.
    await store.exec(
      `UPDATE sync_state
          SET active_schema_version = MAX(active_schema_version, ?)
        WHERE id = 1`,
      [projection.schema_version],
    )
    const activeVersion = await readActiveVersion(store)
    const released = await releaseBufferedEvents(store, tenantId, activeVersion)
    await store.exec('COMMIT')
    return { activeVersion, released }
  } catch (error) {
    await store.exec('ROLLBACK')
    throw error
  }
}
