/**
 * Repository over the `asset_field_values` EAV/LWW table (ADR-007 / ADR-011).
 *
 * Field values are keyed `(tenant_id, asset_id, field_id)` and ordered by
 * `hlc`. `clear` writes a JSON `null` value (a tombstoned-but-present field,
 * ADR-019) rather than deleting the row — the row stays so its `hlc` keeps
 * guarding later writes.
 */

import type { TenantContext, TenantScoped, Writable } from './_tenant'
import type { AssetFieldValueRow, Json } from './_rows'
import { parseJson, stringifyJson } from './_sql'

const COLUMNS = 'asset_id, field_id, value_json, hlc'

function rowToFieldValue<B>(
  row: unknown[],
): TenantScoped<AssetFieldValueRow, B> {
  return {
    asset_id: row[0] as string,
    field_id: row[1] as string,
    value_json: parseJson(row[2]),
    hlc: row[3] as string,
  } as TenantScoped<AssetFieldValueRow, B>
}

export interface AssetFieldValueUpsert {
  asset_id: string
  field_id: string
  value_json: Json
  hlc: string
}

export interface AssetFieldValueRepo<B> {
  listByAsset(assetId: string): Promise<TenantScoped<AssetFieldValueRow, B>[]>
  upsert(value: Writable<AssetFieldValueUpsert, B>): Promise<void>
  clear(assetId: string, fieldId: string, hlc: string): Promise<void>
}

export function makeAssetFieldValueRepo<B>(
  ctx: TenantContext<B>,
): AssetFieldValueRepo<B> {
  const { db, tenantId } = ctx

  return {
    async listByAsset(assetId) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM asset_field_values
         WHERE tenant_id = ? AND asset_id = ? ORDER BY field_id`,
        [tenantId, assetId],
      )
      return rows.map((row) => rowToFieldValue<B>(row))
    },

    async upsert(value) {
      await db.exec(
        `INSERT INTO asset_field_values (tenant_id, asset_id, field_id, value_json, hlc)
         VALUES (?, ?, ?, ?, ?)
         ON CONFLICT (tenant_id, asset_id, field_id) DO UPDATE SET
           value_json = excluded.value_json,
           hlc = excluded.hlc`,
        [
          tenantId,
          value.asset_id,
          value.field_id,
          stringifyJson(value.value_json),
          value.hlc,
        ],
      )
    },

    async clear(assetId, fieldId, hlc) {
      await db.exec(
        `INSERT INTO asset_field_values (tenant_id, asset_id, field_id, value_json, hlc)
         VALUES (?, ?, ?, NULL, ?)
         ON CONFLICT (tenant_id, asset_id, field_id) DO UPDATE SET
           value_json = NULL,
           hlc = excluded.hlc`,
        [tenantId, assetId, fieldId, hlc],
      )
    },
  }
}
