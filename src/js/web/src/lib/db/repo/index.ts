/**
 * Typed repository façade over the local SQLite-WASM DB (ADR-003).
 *
 * E3/E4 read and write local data exclusively through this layer — never raw
 * SQL. The implementation is hand-rolled inline SQL with typed mappers, the
 * approach chosen by the E1.4 spike (query builders cost too much bundle weight
 * for a local-first client).
 *
 * {@link withTenant} is the single entry point: it binds a tenant id once and
 * returns the full set of repos, every one of which pins that tenant into every
 * statement. The repo set (and the rows it yields) is branded with a phantom
 * tenant type `B`, so a row read under one brand cannot be passed to another
 * brand's `upsert` — a cross-tenant write is a compile error, not just a
 * runtime guard. See `_tenant.ts` for the brand machinery.
 */

import type { DbHandle } from '../bootstrap'
import type { TenantContext } from './_tenant'
import { makeAssetRepo } from './asset'
import type { AssetRepo } from './asset'
import { makeAssetFieldValueRepo } from './asset_field_value'
import type { AssetFieldValueRepo } from './asset_field_value'
import { makeMaintenanceRecordRepo } from './maintenance_record'
import type { MaintenanceRecordRepo } from './maintenance_record'
import { makeMaintenanceRecordFieldValueRepo } from './maintenance_record_field_value'
import type { MaintenanceRecordFieldValueRepo } from './maintenance_record_field_value'
import { makeSchemaProjectionRepo } from './schema_projection'
import type { SchemaProjectionRepo } from './schema_projection'
import { makeEventLogRepo } from './event_log'
import type { EventLogRepo } from './event_log'
import { makePendingQueueRepo } from './pending_queue'
import type { PendingQueueRepo } from './pending_queue'

export type { TenantContext, TenantScoped, Writable } from './_tenant'
export type {
  AssetDraft,
  AssetRow,
  MaintenanceRecordDraft,
  MaintenanceRecordRow,
  AssetFieldValueRow,
  MaintenanceRecordFieldValueRow,
  TypeRow,
  TypeFieldRow,
  EventLogRow,
  PendingEventRow,
} from './_rows'
export type { AssetRepo } from './asset'
export type {
  AssetFieldValueRepo,
  AssetFieldValueUpsert,
} from './asset_field_value'
export type { MaintenanceRecordRepo } from './maintenance_record'
export type {
  MaintenanceRecordFieldValueRepo,
  MaintenanceRecordFieldValueUpsert,
} from './maintenance_record_field_value'
export type { SchemaProjectionRepo } from './schema_projection'
export type { EventLogRepo } from './event_log'
export type { PendingQueueRepo } from './pending_queue'

/** The full set of repositories, all pinned to one branded tenant. */
export interface RepoSet<B> {
  assets: AssetRepo<B>
  assetFieldValues: AssetFieldValueRepo<B>
  maintenanceRecords: MaintenanceRecordRepo<B>
  maintenanceRecordFieldValues: MaintenanceRecordFieldValueRepo<B>
  schema: SchemaProjectionRepo<B>
  events: EventLogRepo<B>
  pending: PendingQueueRepo<B>
}

/**
 * Bind `db` to `tenantId` and return the full repository set for that tenant.
 *
 * The phantom brand `B` defaults to `unknown` so single-tenant call sites need
 * no type argument. Code that juggles two tenants (and must not mix their rows)
 * passes a distinct brand per tenant — `withTenant<'a'>(...)` vs
 * `withTenant<'b'>(...)` — which makes a cross-tenant row a type error.
 */
export function withTenant<B = unknown>(
  db: DbHandle,
  tenantId: string,
): RepoSet<B> {
  const ctx: TenantContext<B> = { db, tenantId }
  return {
    assets: makeAssetRepo(ctx),
    assetFieldValues: makeAssetFieldValueRepo(ctx),
    maintenanceRecords: makeMaintenanceRecordRepo(ctx),
    maintenanceRecordFieldValues: makeMaintenanceRecordFieldValueRepo(ctx),
    schema: makeSchemaProjectionRepo(ctx),
    events: makeEventLogRepo(ctx),
    pending: makePendingQueueRepo(ctx),
  }
}
