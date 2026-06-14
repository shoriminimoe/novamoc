/**
 * Row shapes the repository layer reads and writes.
 *
 * These mirror the client DDL (`ddl.ts`) projection and log tables, modulo the
 * conventions the repo enforces:
 *
 *   - `tenant_id` never appears. The pinned tenant (see `_tenant.ts`) supplies
 *     it; exposing it on the row type would invite a call site to set it, which
 *     is exactly the cross-tenant footgun the brand exists to prevent.
 *   - SQLite affinities are surfaced as their JS-native types: INTEGER booleans
 *     (`deleted`, `active`) become `boolean`, and `properties` / `value_json`
 *     TEXT columns become parsed JSON. The mapper in each repo owns the
 *     (de)serialisation, per the spike (single chokepoint per table).
 *   - Entity rows carry no `name` column (ADR-015): the name is reconstructed
 *     from the `col:name` field value, not stored on the projection row.
 *
 * Defined here rather than in the shared `db/types.ts` so the repo build-out
 * does not collide with the parallel fold/ingest work on that file.
 */

/** A parsed JSON object, as held in `properties` / `value_json` columns. */
export type Json = unknown

// --- Data projections -------------------------------------------------------

/** An `assets` projection row (sans `tenant_id`). */
export interface AssetRow {
  id: string
  type_id: string
  properties: Record<string, Json>
  deleted: boolean
  row_state_hlc: string
  created_at: string | null
  updated_at: string | null
}

/** What an `assets` upsert writes; audit timestamps are server/fold-owned. */
export interface AssetDraft {
  id: string
  type_id: string
  properties: Record<string, Json>
  deleted: boolean
  row_state_hlc: string
}

/** A `maintenance_records` projection row (sans `tenant_id`). */
export interface MaintenanceRecordRow {
  id: string
  type_id: string
  asset_id: string
  properties: Record<string, Json>
  deleted: boolean
  row_state_hlc: string
  created_at: string | null
  updated_at: string | null
}

/** What a `maintenance_records` upsert writes. */
export interface MaintenanceRecordDraft {
  id: string
  type_id: string
  asset_id: string
  properties: Record<string, Json>
  deleted: boolean
  row_state_hlc: string
}

/** An `asset_field_values` EAV/LWW row (sans `tenant_id`). */
export interface AssetFieldValueRow {
  asset_id: string
  field_id: string
  value_json: Json
  hlc: string
}

/** A `maintenance_record_field_values` EAV/LWW row (sans `tenant_id`). */
export interface MaintenanceRecordFieldValueRow {
  maintenance_record_id: string
  field_id: string
  value_json: Json
  hlc: string
}

// --- Schema projections (read-only) -----------------------------------------

/** An `asset_types` / `maintenance_record_types` row. */
export interface TypeRow {
  id: string
  name: string
  active: boolean
}

/** An `asset_type_fields` / `maintenance_record_type_fields` row. */
export interface TypeFieldRow {
  id: string
  parent_id: string
  name: string
  data_type: string
  validation: Json | null
  active: boolean
}

// --- Event log (read-only) --------------------------------------------------

/** An `event_log` row — the local copy of the catch-up stream (ADR-011). */
export interface EventLogRow {
  seq: number
  hlc: string
  schema_version: number
  table_name: string
  type_id: string
  entity_id: string
  field_id: string | null
  op: string
  value_json: Json | null
  received_at: string | null
}

// --- Pending queue (read + status writes) -----------------------------------

/** A `local_pending_events` row — a write generated offline (ADR-013). */
export interface PendingEventRow {
  client_seq: number
  hlc: string
  schema_version: number
  table_name: string
  type_id: string
  entity_id: string
  field_id: string | null
  op: string
  value_json: Json | null
  created_at: string | null
}
