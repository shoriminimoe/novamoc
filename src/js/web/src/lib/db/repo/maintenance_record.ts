/**
 * Repository over the `maintenance_records` projection (ADR-012 / ADR-019).
 *
 * Same shape as {@link makeAssetRepo}, plus the parent `asset_id` a maintenance
 * record carries. Tenant-pinned and mapper-chokepointed for the same reasons.
 */

import type { TenantContext, TenantScoped, Writable } from './_tenant'
import type { MaintenanceRecordDraft, MaintenanceRecordRow } from './_rows'
import { fromBool, parseJson, stringifyJson, toBool } from './_sql'

const COLUMNS =
  'id, type_id, asset_id, properties, deleted, row_state_hlc, created_at, updated_at'

function rowToRecord<B>(row: unknown[]): TenantScoped<MaintenanceRecordRow, B> {
  return {
    id: row[0] as string,
    type_id: row[1] as string,
    asset_id: row[2] as string,
    // Invariant: maintenance_records.properties is always a JSON object (ADR-012 fold).
    properties: parseJson(row[3]) as Record<string, unknown>,
    deleted: toBool(row[4]),
    row_state_hlc: row[5] as string,
    created_at: (row[6] as string | null) ?? null,
    updated_at: (row[7] as string | null) ?? null,
  } as TenantScoped<MaintenanceRecordRow, B>
}

export interface MaintenanceRecordRepo<B> {
  listByType(typeId: string): Promise<TenantScoped<MaintenanceRecordRow, B>[]>
  getById(id: string): Promise<TenantScoped<MaintenanceRecordRow, B> | null>
  upsert(draft: Writable<MaintenanceRecordDraft, B>): Promise<void>
  archive(id: string, hlc: string): Promise<void>
  restore(id: string, hlc: string): Promise<void>
  delete(id: string): Promise<void>
}

export function makeMaintenanceRecordRepo<B>(
  ctx: TenantContext<B>,
): MaintenanceRecordRepo<B> {
  const { db, tenantId } = ctx

  return {
    async listByType(typeId) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM maintenance_records WHERE tenant_id = ? AND type_id = ? ORDER BY id`,
        [tenantId, typeId],
      )
      return rows.map((row) => rowToRecord<B>(row))
    },

    async getById(id) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM maintenance_records WHERE tenant_id = ? AND id = ?`,
        [tenantId, id],
      )
      return rows.length ? rowToRecord<B>(rows[0]) : null
    },

    async upsert(draft) {
      await db.exec(
        `INSERT INTO maintenance_records
           (tenant_id, id, type_id, asset_id, properties, deleted, row_state_hlc)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (tenant_id, id) DO UPDATE SET
           type_id = excluded.type_id,
           asset_id = excluded.asset_id,
           properties = excluded.properties,
           deleted = excluded.deleted,
           row_state_hlc = excluded.row_state_hlc`,
        [
          tenantId,
          draft.id,
          draft.type_id,
          draft.asset_id,
          stringifyJson(draft.properties),
          fromBool(draft.deleted),
          draft.row_state_hlc,
        ],
      )
    },

    async archive(id, hlc) {
      await db.exec(
        'UPDATE maintenance_records SET deleted = 1, row_state_hlc = ? WHERE tenant_id = ? AND id = ?',
        [hlc, tenantId, id],
      )
    },

    async restore(id, hlc) {
      await db.exec(
        'UPDATE maintenance_records SET deleted = 0, row_state_hlc = ? WHERE tenant_id = ? AND id = ?',
        [hlc, tenantId, id],
      )
    },

    async delete(id) {
      await db.exec(
        'DELETE FROM maintenance_records WHERE tenant_id = ? AND id = ?',
        [tenantId, id],
      )
    },
  }
}
