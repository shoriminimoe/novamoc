/**
 * Candidate 1 — HAND-ROLLED typed functions with inline SQL.
 *
 * SQL strings are literal; row<->object mapping is by hand; types come from
 * the domain interfaces. Zero dependency weight on top of the driver.
 */
import type { WasmDB } from './driver'
import type { Asset, AssetFieldValue, AssetWithField } from './domain'

function rowToAsset(r: Record<string, unknown>): Asset {
  return {
    tenantId: r.tenant_id as string,
    id: r.id as string,
    typeId: r.type_id as string,
    name: (r.name as string | null) ?? null,
    properties: JSON.parse((r.properties as string) ?? '{}'),
    deleted: Boolean(r.deleted),
    rowStateHlc: r.row_state_hlc as string,
  }
}

export function upsertAsset(db: WasmDB, a: Asset): void {
  db.exec({
    sql: `INSERT INTO assets (tenant_id, id, type_id, name, properties, deleted, row_state_hlc)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(tenant_id, id) DO UPDATE SET
            type_id = excluded.type_id,
            name = excluded.name,
            properties = excluded.properties,
            deleted = excluded.deleted,
            row_state_hlc = excluded.row_state_hlc`,
    bind: [
      a.tenantId,
      a.id,
      a.typeId,
      a.name,
      JSON.stringify(a.properties),
      a.deleted ? 1 : 0,
      a.rowStateHlc,
    ],
  })
}

export function listAssetsByType(db: WasmDB, tenantId: string, typeId: string): Asset[] {
  const rows = db.exec({
    sql: `SELECT tenant_id, id, type_id, name, properties, deleted, row_state_hlc
          FROM assets WHERE tenant_id = ? AND type_id = ? AND deleted = 0`,
    bind: [tenantId, typeId],
    rowMode: 'object',
    returnValue: 'resultRows',
  })
  return rows.map(rowToAsset)
}

export function getAssetById(db: WasmDB, tenantId: string, id: string): Asset | null {
  const rows = db.exec({
    sql: `SELECT tenant_id, id, type_id, name, properties, deleted, row_state_hlc
          FROM assets WHERE tenant_id = ? AND id = ?`,
    bind: [tenantId, id],
    rowMode: 'object',
    returnValue: 'resultRows',
  })
  return rows.length ? rowToAsset(rows[0]) : null
}

export function upsertFieldValue(db: WasmDB, v: AssetFieldValue): void {
  db.exec({
    sql: `INSERT INTO asset_field_values (tenant_id, asset_id, field_id, value_json, hlc)
          VALUES (?, ?, ?, ?, ?)
          ON CONFLICT(tenant_id, asset_id, field_id) DO UPDATE SET
            value_json = excluded.value_json, hlc = excluded.hlc`,
    bind: [v.tenantId, v.assetId, v.fieldId, JSON.stringify(v.valueJson), v.hlc],
  })
}

export function listFieldValuesByEntity(
  db: WasmDB,
  tenantId: string,
  assetId: string,
): AssetFieldValue[] {
  const rows = db.exec({
    sql: `SELECT tenant_id, asset_id, field_id, value_json, hlc
          FROM asset_field_values WHERE tenant_id = ? AND asset_id = ?`,
    bind: [tenantId, assetId],
    rowMode: 'object',
    returnValue: 'resultRows',
  })
  return rows.map((r) => ({
    tenantId: r.tenant_id as string,
    assetId: r.asset_id as string,
    fieldId: r.field_id as string,
    valueJson: JSON.parse((r.value_json as string) ?? 'null'),
    hlc: r.hlc as string,
  }))
}

/** Join: assets × asset_field_values. */
export function listAssetFields(db: WasmDB, tenantId: string, typeId: string): AssetWithField[] {
  const rows = db.exec({
    sql: `SELECT a.id AS asset_id, a.name AS asset_name,
                 v.field_id, v.value_json, v.hlc
          FROM assets a
          JOIN asset_field_values v
            ON v.tenant_id = a.tenant_id AND v.asset_id = a.id
          WHERE a.tenant_id = ? AND a.type_id = ?`,
    bind: [tenantId, typeId],
    rowMode: 'object',
    returnValue: 'resultRows',
  })
  return rows.map((r) => ({
    assetId: r.asset_id as string,
    assetName: (r.asset_name as string | null) ?? null,
    fieldId: r.field_id as string,
    valueJson: JSON.parse((r.value_json as string) ?? 'null'),
    hlc: r.hlc as string,
  }))
}
