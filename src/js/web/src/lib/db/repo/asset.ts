/**
 * Repository over the `assets` projection (ADR-012 / ADR-019).
 *
 * Hand-rolled inline SQL per the E1.4 spike. Every statement carries the
 * pinned `tenant_id` (from {@link TenantContext}) in its WHERE / VALUES, so a
 * repo bound to tenant A cannot read or write tenant B's rows. Reads funnel
 * through {@link rowToAsset} — the typed mapper is where SQL-column drift is
 * caught (the spike's type-safety chokepoint) and where INTEGER/JSON columns
 * become their JS-native shapes.
 */

import type { TenantContext, TenantScoped, Writable } from './_tenant'
import type { AssetDraft, AssetRow } from './_rows'
import { fromBool, parseJson, stringifyJson, toBool } from './_sql'

// Explicit column list (not SELECT *) so the positional `rowMode: 'array'`
// result lines up with the mapper regardless of on-disk column order.
const COLUMNS =
  'id, type_id, properties, deleted, row_state_hlc, created_at, updated_at'

function rowToAsset<B>(row: unknown[]): TenantScoped<AssetRow, B> {
  return {
    id: row[0] as string,
    type_id: row[1] as string,
    // Invariant: assets.properties is always a JSON object (ADR-012 fold).
    properties: parseJson(row[2]) as Record<string, unknown>,
    deleted: toBool(row[3]),
    row_state_hlc: row[4] as string,
    created_at: (row[5] as string | null) ?? null,
    updated_at: (row[6] as string | null) ?? null,
  } as TenantScoped<AssetRow, B>
}

export interface AssetRepo<B> {
  listByType(typeId: string): Promise<TenantScoped<AssetRow, B>[]>
  getById(id: string): Promise<TenantScoped<AssetRow, B> | null>
  upsert(draft: Writable<AssetDraft, B>): Promise<void>
  archive(id: string, hlc: string): Promise<void>
  restore(id: string, hlc: string): Promise<void>
  delete(id: string): Promise<void>
}

export function makeAssetRepo<B>(ctx: TenantContext<B>): AssetRepo<B> {
  const { db, tenantId } = ctx

  return {
    async listByType(typeId) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM assets WHERE tenant_id = ? AND type_id = ? ORDER BY id`,
        [tenantId, typeId],
      )
      return rows.map((row) => rowToAsset<B>(row))
    },

    async getById(id) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM assets WHERE tenant_id = ? AND id = ?`,
        [tenantId, id],
      )
      return rows.length ? rowToAsset<B>(rows[0]) : null
    },

    async upsert(draft) {
      await db.exec(
        `INSERT INTO assets (tenant_id, id, type_id, properties, deleted, row_state_hlc)
         VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT (tenant_id, id) DO UPDATE SET
           type_id = excluded.type_id,
           properties = excluded.properties,
           deleted = excluded.deleted,
           row_state_hlc = excluded.row_state_hlc`,
        [
          tenantId,
          draft.id,
          draft.type_id,
          stringifyJson(draft.properties),
          fromBool(draft.deleted),
          draft.row_state_hlc,
        ],
      )
    },

    async archive(id, hlc) {
      await db.exec(
        'UPDATE assets SET deleted = 1, row_state_hlc = ? WHERE tenant_id = ? AND id = ?',
        [hlc, tenantId, id],
      )
    },

    async restore(id, hlc) {
      await db.exec(
        'UPDATE assets SET deleted = 0, row_state_hlc = ? WHERE tenant_id = ? AND id = ?',
        [hlc, tenantId, id],
      )
    },

    async delete(id) {
      await db.exec('DELETE FROM assets WHERE tenant_id = ? AND id = ?', [
        tenantId,
        id,
      ])
    },
  }
}
