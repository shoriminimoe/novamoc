/**
 * Schema-projection ingest and the schema-version gate (ADR-008 / ADR-009).
 *
 * The schema is server-authoritative: the client refetches `GET /schema` and
 * reconciles its local projection against the response (the design rejects
 * delta-event ingest — see the epic spec Q6). Reconcile is upsert + delete of
 * rows the wire no longer carries, not delete-then-insert: `assets` /
 * `maintenance_records` reference the type tables without `ON DELETE CASCADE`,
 * so a wholesale delete would raise a FK constraint the moment any data has
 * been folded. After a refresh the local schema tables mirror the wire
 * response and `sync_state.active_schema_version` holds the server's version.
 *
 * The gate is the load-bearing ADR-009 invariant: an inbound catch-up event
 * tagged with a `schema_version` ahead of the local `active_schema_version`
 * must NOT be applied — a server schema change the client hasn't ingested
 * could corrupt the projection (e.g. an event referencing a field the local
 * schema doesn't yet know). Such events are buffered verbatim in
 * `pending_schema_buffer` and surfaced once a later refresh raises the active
 * version to or past the event's. Release is non-lossy: the buffer rows stay
 * put until the consumer has folded them and explicitly discarded them in its
 * own transaction (fold-then-discard), so a crash mid-handoff re-releases
 * rather than dropping events that never reached `event_log`. This module owns
 * the gate and the buffer; the fold and the catch-up loop live elsewhere.
 *
 * `active_schema_version` only ever advances, and only a strictly-newer
 * response triggers a reconcile: a stale read reporting an older (or equal)
 * version is a no-op, so the projection can't revert while the gate stays high.
 */

import { applySchemaProjection } from '../db/fold'
import { fetchSchema } from '../schema'
import type { DbHandle } from '../db/bootstrap'
import type { ApiClient } from '../api'
import type {
  EntityFamily,
  EventBody,
  SchemaField,
  SchemaProjection,
  SchemaType,
} from '../db/types'

/** The minimal persistence surface the ingest needs — satisfied by {@link DbHandle}. */
export type SchemaStore = Pick<DbHandle, 'exec'>

const KNOWN_FAMILIES: ReadonlySet<EntityFamily> = new Set<EntityFamily>([
  'asset',
  'maintenance_record',
])

const KNOWN_EVENT_TAGS: ReadonlySet<string> = new Set([
  'created',
  'updated',
  'deactivated',
  'activated',
])

/** Raised when a buffered event's `family` or `body` discriminator is invalid. */
export class InvalidBufferableEventError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'InvalidBufferableEventError'
  }
}

/**
 * A gated inbound event: the catch-up envelope plus its replication cursor.
 * `family` and `body` are typed against the fold's vocabulary so a released
 * event is a valid {@link import('../db/types').EventEnvelope} without a cast —
 * a typo'd discriminator is rejected at the buffer boundary, not deep in the
 * fold.
 */
export interface BufferableEvent {
  seq: number
  hlc: string
  schema_version: number
  family: EntityFamily
  type_id: string
  instance_id: string
  /** The event body; stored verbatim and replayed on release. */
  body: EventBody
  received_at?: string | null
}

/**
 * Reject an event whose `family` isn't a known projection family or whose
 * `body` lacks a valid `event` discriminator tag. Cheap structural checks —
 * the fold trusts the discriminator, so a bad tag must never reach it. Run at
 * both the buffer boundary and the release read.
 */
function assertBufferableEvent(event: BufferableEvent): void {
  if (!KNOWN_FAMILIES.has(event.family)) {
    throw new InvalidBufferableEventError(
      `unknown event family: ${String(event.family)}`,
    )
  }
  const tag = (event.body as { event?: unknown } | null)?.event
  if (typeof tag !== 'string' || !KNOWN_EVENT_TAGS.has(tag)) {
    throw new InvalidBufferableEventError(
      `event body missing a valid discriminator tag: ${String(tag)}`,
    )
  }
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

/**
 * Delete the tenant's rows in `table` whose `id` is absent from `ids`. The
 * server response is the whole truth, so any local row the wire no longer
 * carries is gone server-side — but tombstoned types stay in the wire
 * (`active=false`), so this never drops a type that still has dependent
 * assets. Parameterised `NOT IN`; an empty wire deletes the lot.
 */
async function deleteAbsent(
  store: SchemaStore,
  table: string,
  tenantId: string,
  ids: string[],
): Promise<void> {
  if (ids.length === 0) {
    await store.exec(`DELETE FROM ${table} WHERE tenant_id = ?`, [tenantId])
    return
  }
  const placeholders = ids.map(() => '?').join(', ')
  await store.exec(
    `DELETE FROM ${table} WHERE tenant_id = ? AND id NOT IN (${placeholders})`,
    [tenantId, ...ids],
  )
}

async function upsertTypes(
  store: SchemaStore,
  table: string,
  tenantId: string,
  types: SchemaType[],
  now: string,
): Promise<void> {
  for (const type of types) {
    await store.exec(
      `INSERT INTO ${table} (tenant_id, id, name, active, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(tenant_id, id) DO UPDATE SET
         name = excluded.name,
         active = excluded.active,
         updated_at = excluded.updated_at`,
      [tenantId, type.id, type.name, type.active ? 1 : 0, now, now],
    )
  }
}

async function upsertFields(
  store: SchemaStore,
  table: string,
  tenantId: string,
  fields: SchemaField[],
  now: string,
): Promise<void> {
  for (const field of fields) {
    await store.exec(
      `INSERT INTO ${table}
         (tenant_id, id, parent_id, name, data_type, validation, active, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(tenant_id, id) DO UPDATE SET
         parent_id = excluded.parent_id,
         name = excluded.name,
         data_type = excluded.data_type,
         validation = excluded.validation,
         active = excluded.active,
         updated_at = excluded.updated_at`,
      [
        tenantId,
        field.id,
        field.parent_id,
        field.name,
        field.data_type,
        jsonOrNull(field.validation),
        field.active ? 1 : 0,
        now,
        now,
      ],
    )
  }
}

/**
 * Reconcile the tenant's schema-projection rows with `projection`. The server
 * is authoritative, so the response is the whole truth — but a wholesale
 * delete-then-insert violates the no-CASCADE FK from `assets`/
 * `maintenance_records` onto their type tables the moment any data has been
 * folded. So each table is upserted (`ON CONFLICT DO UPDATE`, preserving
 * `created_at`) and then rows whose `id` is absent from the wire are deleted.
 * `now` is the first-seen-locally timestamp, supplied by the I/O layer so the
 * fold stays pure. Runs inside the caller's transaction.
 */
async function reconcileTables(
  store: SchemaStore,
  tenantId: string,
  projection: SchemaProjection,
  now: string,
): Promise<void> {
  await upsertTypes(store, 'asset_types', tenantId, projection.asset_types, now)
  await upsertTypes(
    store,
    'maintenance_record_types',
    tenantId,
    projection.maintenance_record_types,
    now,
  )
  await upsertFields(
    store,
    'asset_type_fields',
    tenantId,
    projection.asset_type_fields,
    now,
  )
  await upsertFields(
    store,
    'maintenance_record_type_fields',
    tenantId,
    projection.maintenance_record_type_fields,
    now,
  )
  // Delete-absent after the upserts, child tables first so a removed field
  // goes before its (possibly also-removed) parent type.
  await deleteAbsent(
    store,
    'asset_type_fields',
    tenantId,
    projection.asset_type_fields.map((f) => f.id),
  )
  await deleteAbsent(
    store,
    'maintenance_record_type_fields',
    tenantId,
    projection.maintenance_record_type_fields.map((f) => f.id),
  )
  await deleteAbsent(
    store,
    'asset_types',
    tenantId,
    projection.asset_types.map((t) => t.id),
  )
  await deleteAbsent(
    store,
    'maintenance_record_types',
    tenantId,
    projection.maintenance_record_types.map((t) => t.id),
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
  /**
   * Buffered events the version bump just unblocked, in cursor order. These
   * stay in the buffer — the consumer must fold them then call
   * {@link discardBufferedEvents} with their seqs, all inside its own
   * transaction. See the fold-then-discard contract on this function.
   */
  releasable: BufferableEvent[]
}

/**
 * Buffer an inbound event whose schema version is ahead of the local one.
 * `INSERT OR REPLACE` keyed on `(tenant_id, seq)` makes a re-delivered batch
 * idempotent. Caller is responsible for gating before calling. The event is
 * validated first — a bad `family` / discriminator never reaches the buffer,
 * so the release read can hand back fold envelopes without re-checking shape.
 */
export async function bufferEvent(
  store: SchemaStore,
  tenantId: string,
  event: BufferableEvent,
): Promise<void> {
  assertBufferableEvent(event)
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
      // `?? null` so a missing body can never serialise to the string
      // `"undefined"` or to JS `undefined` (a NOT NULL violation on `body`);
      // typed callers can't hit this, but the buffer's invariant is its own.
      JSON.stringify(event.body ?? null),
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
 * Read (do NOT delete) every buffered event now applicable under
 * `activeVersion` (`schema_version <= activeVersion`), in ascending `seq`
 * order. Read-only by design: the events stay in the buffer so a caller that
 * crashes after receiving them but before folding loses nothing — they're
 * re-released on the next refresh (the fold is idempotent under HLC-LWW and
 * `event_log` has a `(tenant_id, hlc)` unique constraint). The caller folds
 * the returned events then calls {@link discardBufferedEvents} with their
 * seqs, inside its own transaction, to complete the handoff.
 */
async function releasableBufferedEvents(
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
  return rows.map((row) => {
    const event: BufferableEvent = {
      seq: row[0] as number,
      hlc: row[1] as string,
      schema_version: row[2] as number,
      family: row[3] as EntityFamily,
      type_id: row[4] as string,
      instance_id: row[5] as string,
      body: JSON.parse(row[6] as string) as EventBody,
      received_at: row[7] as string | null,
    }
    // Defence in depth: a row that somehow stored a bad shape must not flow
    // into the fold as a valid-looking envelope.
    assertBufferableEvent(event)
    return event
  })
}

/**
 * Delete the named buffered events by seq. The catch-up consumer calls this
 * after folding the events {@link refreshSchema} (or
 * {@link releasableBufferedEvents}) returned, inside the SAME transaction it
 * folded them in, so the fold-then-discard handoff is atomic: a crash before
 * discard re-releases the events next refresh rather than losing them.
 */
export async function discardBufferedEvents(
  store: SchemaStore,
  tenantId: string,
  seqs: number[],
): Promise<void> {
  if (seqs.length === 0) {
    return
  }
  const placeholders = seqs.map(() => '?').join(', ')
  await store.exec(
    `DELETE FROM pending_schema_buffer
      WHERE tenant_id = ? AND seq IN (${placeholders})`,
    [tenantId, ...seqs],
  )
}

/**
 * Fetch `GET /schema`, and — only when the response reports a strictly newer
 * schema version than the local one — reconcile the local schema projection,
 * advance the active schema version, and surface the buffered events the bump
 * unblocks.
 *
 * A response at or below the stored version is a no-op: schema version =
 * MAX(seq) of the change log, so the same version means the same schema, and a
 * stale read reporting an older version must not revert the projection while
 * the gate stays high (that would let events apply against rows the schema no
 * longer has). Either way the result is idempotent.
 *
 * The reconcile + version write run inside a `SAVEPOINT` so this composes both
 * standalone and nested under an outer transaction — a raw `BEGIN` would throw
 * when nested and its `ROLLBACK` would abort the outer transaction. The buffer
 * is NOT drained here; see {@link RefreshSchemaResult.releasable}.
 */
export async function refreshSchema(
  options: RefreshSchemaOptions,
): Promise<RefreshSchemaResult> {
  const { store, tenantId, client } = options
  const wire = await fetchSchema(client)

  const stored = await readActiveVersion(store)
  if (wire.schema_version <= stored) {
    return { activeVersion: stored, releasable: [] }
  }

  const projection = applySchemaProjection(wire)
  const now = new Date().toISOString()

  await store.exec('SAVEPOINT refresh_schema')
  try {
    await reconcileTables(store, tenantId, projection, now)
    await store.exec(
      'UPDATE sync_state SET active_schema_version = ? WHERE id = 1',
      [projection.schema_version],
    )
    await store.exec('RELEASE refresh_schema')
  } catch (error) {
    await store.exec('ROLLBACK TO refresh_schema')
    await store.exec('RELEASE refresh_schema')
    throw error
  }

  const activeVersion = projection.schema_version
  const releasable = await releasableBufferedEvents(store, tenantId, activeVersion)
  return { activeVersion, releasable }
}
