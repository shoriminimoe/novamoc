/**
 * Repository over the `maintenance_record_field_values` EAV/LWW table
 * (ADR-007 / ADR-011).
 *
 * Same shape as {@link makeAssetFieldValueRepo}, keyed on
 * `(tenant_id, maintenance_record_id, field_id)`.
 */

import type { TenantContext, TenantScoped, Writable } from './_tenant'
import type { Json, MaintenanceRecordFieldValueRow } from './_rows'
import { parseJson, stringifyJson } from './_sql'

const COLUMNS = 'maintenance_record_id, field_id, value_json, hlc'

function rowToFieldValue<B>(
  row: unknown[],
): TenantScoped<MaintenanceRecordFieldValueRow, B> {
  return {
    maintenance_record_id: row[0] as string,
    field_id: row[1] as string,
    value_json: parseJson(row[2]),
    hlc: row[3] as string,
  } as TenantScoped<MaintenanceRecordFieldValueRow, B>
}

export interface MaintenanceRecordFieldValueUpsert {
  maintenance_record_id: string
  field_id: string
  value_json: Json
  hlc: string
}

export interface MaintenanceRecordFieldValueRepo<B> {
  listByRecord(
    recordId: string,
  ): Promise<TenantScoped<MaintenanceRecordFieldValueRow, B>[]>
  upsert(value: Writable<MaintenanceRecordFieldValueUpsert, B>): Promise<void>
  clear(recordId: string, fieldId: string, hlc: string): Promise<void>
}

export function makeMaintenanceRecordFieldValueRepo<B>(
  ctx: TenantContext<B>,
): MaintenanceRecordFieldValueRepo<B> {
  const { db, tenantId } = ctx

  return {
    async listByRecord(recordId) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM maintenance_record_field_values
         WHERE tenant_id = ? AND maintenance_record_id = ? ORDER BY field_id`,
        [tenantId, recordId],
      )
      return rows.map((row) => rowToFieldValue<B>(row))
    },

    async upsert(value) {
      await db.exec(
        `INSERT INTO maintenance_record_field_values
           (tenant_id, maintenance_record_id, field_id, value_json, hlc)
         VALUES (?, ?, ?, ?, ?)
         ON CONFLICT (tenant_id, maintenance_record_id, field_id) DO UPDATE SET
           value_json = excluded.value_json,
           hlc = excluded.hlc`,
        [
          tenantId,
          value.maintenance_record_id,
          value.field_id,
          stringifyJson(value.value_json),
          value.hlc,
        ],
      )
    },

    async clear(recordId, fieldId, hlc) {
      await db.exec(
        `INSERT INTO maintenance_record_field_values
           (tenant_id, maintenance_record_id, field_id, value_json, hlc)
         VALUES (?, ?, ?, NULL, ?)
         ON CONFLICT (tenant_id, maintenance_record_id, field_id) DO UPDATE SET
           value_json = NULL,
           hlc = excluded.hlc`,
        [tenantId, recordId, fieldId, hlc],
      )
    },
  }
}
