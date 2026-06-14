/**
 * Bulk snapshot ingest from `GET /snapshot` (ADR-013 / ADR-015).
 *
 * On first login (or after a "drop local DB and resync") the client hydrates
 * its four data-projection tables from the server's bulk snapshot before
 * incremental catch-up (E1.8) can begin. The transfer is paginated: each batch
 * carries one projection table's rows plus an opaque `page` continuation, and
 * the terminal batch carries the replication `cursor` (`event_log.seq`) the
 * client feeds to catch-up.
 *
 * Snapshot rows are *committed* projection state, not events — the server
 * resolved LWW before serving them, so each row is applied unconditionally
 * (mirroring {@link applySnapshotRow}): structural entity columns plus the
 * field-value tables with their `hlc` preserved, no `name`/`properties`
 * materialization (ADR-015). A subsequent event fold against this state stays
 * LWW-correct because the `hlc`s ride along.
 *
 * Two failure-recovery invariants (ADR-015 §"Consistency"):
 *
 * 1. **Resume.** On a transport error mid-pagination the partial rows stay in
 *    the DB and the in-flight `page` token is persisted in `sync_state`, so the
 *    next `ingestSnapshot()` (even after a reload) resumes from it rather than
 *    re-downloading from the start.
 * 2. **Restart on invalidation.** The server captures `start_seq` on the first
 *    request and threads it through the token; it does *not* reject a token
 *    whose snapshot the server has since advanced past. The signal the protocol
 *    gives is `schema_version`: every batch echoes the server's current version,
 *    and an advance across batches means a schema change committed mid-transfer
 *    and the partial state is inconsistent. When a batch reports a version
 *    different from the one this transfer started under, the ingest discards the
 *    partial projection and restarts from scratch (page = null).
 */

import { applySnapshotRow } from '../db/fold'
import { createApiClient } from '../api'
import type { ApiClient } from '../api'
import type { DbHandle } from '../db/bootstrap'
import type {
  SnapshotAssetView,
  SnapshotFieldValueView,
  SnapshotMaintenanceRecordView,
} from '../db/types'
import type { SnapshotProgressStore } from './_progress'

/** The persistence surface the ingest needs — satisfied by {@link DbHandle}. */
export type SnapshotStore = Pick<DbHandle, 'exec'>

/** One discriminated `GET /snapshot` body, mirroring the server's union. */
type SnapshotBody =
  | { table: 'assets'; items: SnapshotAssetView[] }
  | { table: 'asset_field_values'; items: SnapshotFieldValueWire[] }
  | { table: 'maintenance_records'; items: SnapshotMaintenanceRecordView[] }
  | {
      table: 'maintenance_record_field_values'
      items: SnapshotFieldValueWire[]
    }

/**
 * Field-value row as it rides the wire. The asset table names the entity FK
 * `asset_id`, the MR table names it `maintenance_record_id`; both decode to the
 * fold's neutral `entity_id`. Both keys are optional here so one wire type
 * covers both tables.
 */
interface SnapshotFieldValueWire {
  asset_id?: string
  maintenance_record_id?: string
  field_id: string
  value_json: unknown
  hlc: string
}

/** One batch of the snapshot transfer (mirrors the server's `SnapshotBatch`). */
interface SnapshotBatch {
  schema_version: number
  /** Opaque pagination continuation; `null` ⇒ terminal batch. */
  page: string | null
  /** Replication `event_log.seq`; present only on the terminal batch. */
  cursor: number | null
  body: SnapshotBody
}

export interface IngestSnapshotOptions {
  store: SnapshotStore
  tenantId: string
  /** API client for `GET /snapshot`. Defaults to the shared session-cookie client. */
  client?: ApiClient
  /** Optional progress sink for the debug surface. */
  progress?: SnapshotProgressStore
}

export interface IngestSnapshotResult {
  /** Replication cursor (`event_log.seq`) to begin catch-up from (E1.8). */
  cursor: number
  /** The schema version the snapshot was projected under. */
  schema_version: number
}

interface InFlight {
  page: string | null
  schema_version: number | null
}

async function readInFlight(store: SnapshotStore): Promise<InFlight> {
  const rows = await store.exec(
    'SELECT snapshot_page, snapshot_schema_version FROM sync_state WHERE id = 1',
  )
  const row = rows[0]
  return {
    page: (row?.[0] as string | null | undefined) ?? null,
    schema_version: (row?.[1] as number | null | undefined) ?? null,
  }
}

async function persistInFlight(
  store: SnapshotStore,
  inFlight: InFlight,
): Promise<void> {
  await store.exec(
    'UPDATE sync_state SET snapshot_page = ?, snapshot_schema_version = ? WHERE id = 1',
    [inFlight.page, inFlight.schema_version],
  )
}

/**
 * Delete every data-projection row for the tenant — the from-scratch reset run
 * before a restart (or as the first step of a fresh ingest with no resumable
 * token). Children before parents so the no-CASCADE FKs from `*_field_values`
 * and `maintenance_records` onto `assets` don't trip.
 */
async function clearProjection(
  store: SnapshotStore,
  tenantId: string,
): Promise<void> {
  for (const table of [
    'maintenance_record_field_values',
    'maintenance_records',
    'asset_field_values',
    'assets',
  ]) {
    await store.exec(`DELETE FROM ${table} WHERE tenant_id = ?`, [tenantId])
  }
}

function fieldValueEntityId(item: SnapshotFieldValueWire): string {
  const id = item.asset_id ?? item.maintenance_record_id
  if (id === undefined) {
    throw new Error('snapshot field-value row missing its entity id')
  }
  return id
}

/** Persist one batch's rows. `applySnapshotRow` defines the materialization
 * contract; this is its SQL bridge — an unconditional upsert keyed on the
 * projection PK (snapshot rows are committed state, so a resumed overlap is an
 * idempotent rewrite of the same row). */
async function writeBatch(
  store: SnapshotStore,
  tenantId: string,
  body: SnapshotBody,
): Promise<number> {
  switch (body.table) {
    case 'assets': {
      for (const item of body.items) {
        await store.exec(
          `INSERT INTO assets (tenant_id, id, type_id, deleted, row_state_hlc)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, id) DO UPDATE SET
             type_id = excluded.type_id,
             deleted = excluded.deleted,
             row_state_hlc = excluded.row_state_hlc`,
          [tenantId, item.id, item.type_id, item.deleted ? 1 : 0, item.row_state_hlc],
        )
      }
      return body.items.length
    }
    case 'maintenance_records': {
      for (const item of body.items) {
        await store.exec(
          `INSERT INTO maintenance_records
             (tenant_id, id, type_id, asset_id, deleted, row_state_hlc)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, id) DO UPDATE SET
             type_id = excluded.type_id,
             asset_id = excluded.asset_id,
             deleted = excluded.deleted,
             row_state_hlc = excluded.row_state_hlc`,
          [
            tenantId,
            item.id,
            item.type_id,
            item.asset_id,
            item.deleted ? 1 : 0,
            item.row_state_hlc,
          ],
        )
      }
      return body.items.length
    }
    case 'asset_field_values': {
      for (const item of body.items) {
        await store.exec(
          `INSERT INTO asset_field_values
             (tenant_id, asset_id, field_id, value_json, hlc)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, asset_id, field_id) DO UPDATE SET
             value_json = excluded.value_json,
             hlc = excluded.hlc`,
          [
            tenantId,
            fieldValueEntityId(item),
            item.field_id,
            serializeValue(item.value_json),
            item.hlc,
          ],
        )
      }
      return body.items.length
    }
    case 'maintenance_record_field_values': {
      for (const item of body.items) {
        await store.exec(
          `INSERT INTO maintenance_record_field_values
             (tenant_id, maintenance_record_id, field_id, value_json, hlc)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, maintenance_record_id, field_id) DO UPDATE SET
             value_json = excluded.value_json,
             hlc = excluded.hlc`,
          [
            tenantId,
            fieldValueEntityId(item),
            item.field_id,
            serializeValue(item.value_json),
            item.hlc,
          ],
        )
      }
      return body.items.length
    }
  }
}

/**
 * Serialize a field value to the `value_json` TEXT column. A cleared cell is
 * JSON `null` (ADR-019), distinct from a wholly absent value — but the wire
 * always carries `value_json`, so `undefined` only arises from a malformed row
 * and is treated as SQL NULL.
 */
function serializeValue(value: unknown): string | null {
  return value === undefined ? null : JSON.stringify(value)
}

/**
 * Ingest the active tenant's bulk snapshot into the local projection.
 *
 * Resumes from a persisted in-flight `page` token when one exists and the
 * transfer's `schema_version` still holds; restarts from scratch when a batch
 * reports a different version (the snapshot is invalidated). On the terminal
 * batch, persists the replication `cursor` → `sync_state.last_seen_seq` and the
 * `schema_version` → `sync_state.active_schema_version`, clears the in-flight
 * token, and returns both.
 */
export async function ingestSnapshot(
  options: IngestSnapshotOptions,
): Promise<IngestSnapshotResult> {
  const { store, tenantId, progress } = options
  const client = options.client ?? createApiClient()

  let { page, schema_version: snapshotVersion } = await readInFlight(store)
  // No resumable token ⇒ a fresh transfer. Clear any stale partial rows so a
  // restart and a first run share one code path.
  if (page === null) {
    await clearProjection(store, tenantId)
    snapshotVersion = null
  }

  progress?.setPhase('running')

  try {
    for (;;) {
      const batch = await fetchBatch(client, page)

      // Invalidation: a version different from the one this transfer began under
      // means a schema change committed mid-transfer (ADR-015). The partial
      // projection and the checkpoint are both invalid. Null the checkpoint
      // BEFORE wiping rows so an interruption in this window leaves
      // `snapshot_page = NULL` — the next run re-clears and restarts from
      // scratch rather than resuming the invalidated token.
      if (snapshotVersion !== null && batch.schema_version !== snapshotVersion) {
        await persistInFlight(store, { page: null, schema_version: null })
        await clearProjection(store, tenantId)
        page = null
        snapshotVersion = null
        progress?.reset()
        continue
      }
      snapshotVersion = batch.schema_version

      const written = await writeBatch(store, tenantId, batch.body)
      progress?.recordBatch(batch.body.table, written)

      if (batch.page === null) {
        const cursor = batch.cursor ?? 0
        await store.exec(
          `UPDATE sync_state
              SET last_seen_seq = ?,
                  active_schema_version = ?,
                  snapshot_page = NULL,
                  snapshot_schema_version = NULL
            WHERE id = 1`,
          [cursor, batch.schema_version],
        )
        progress?.setPhase('done')
        return { cursor, schema_version: batch.schema_version }
      }

      // Checkpoint the continuation so a transport error on the next fetch
      // leaves a resumable token in the DB.
      page = batch.page
      await persistInFlight(store, { page, schema_version: batch.schema_version })
    }
  } catch (error) {
    // Partial state and the persisted token stay put; the next call resumes.
    progress?.setPhase('error')
    throw error
  }
}

/** Fetch one batch. Errors propagate so the caller can mark progress `error`
 * and leave the persisted token for the next resume. */
async function fetchBatch(
  client: ApiClient,
  page: string | null,
): Promise<SnapshotBatch> {
  const path =
    page === null ? '/snapshot' : `/snapshot?page=${encodeURIComponent(page)}`
  return client.get<SnapshotBatch>(path)
}
