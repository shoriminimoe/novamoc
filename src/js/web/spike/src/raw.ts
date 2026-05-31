/**
 * Candidate 4 — RAW db.exec + type assertions at the boundary.
 *
 * No mapping helpers, no schema declaration. SQL is literal, results are
 * cast with `as` at the call boundary. JSON columns are hand-parsed. This is
 * the absolute floor on weight and the absolute floor on safety.
 */
import type { WasmDB } from './driver'
import type { Asset, AssetFieldValue, AssetWithField } from './domain'

export function upsertAsset(db: WasmDB, a: Asset): void {
  db.exec({
    sql: `INSERT INTO assets (tenant_id, id, type_id, name, properties, deleted, row_state_hlc)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(tenant_id, id) DO UPDATE SET
            type_id=excluded.type_id, name=excluded.name, properties=excluded.properties,
            deleted=excluded.deleted, row_state_hlc=excluded.row_state_hlc`,
    bind: [a.tenantId, a.id, a.typeId, a.name, JSON.stringify(a.properties), a.deleted ? 1 : 0, a.rowStateHlc],
  })
}

export function listAssetsByType(db: WasmDB, tenantId: string, typeId: string): Asset[] {
  const rows = db.exec({
    sql: `SELECT * FROM assets WHERE tenant_id=? AND type_id=? AND deleted=0`,
    bind: [tenantId, typeId],
    rowMode: 'object',
    returnValue: 'resultRows',
  })
  // The shape is asserted, not checked. A wrong column name in the SQL above
  // produces `undefined` at runtime with zero compile-time warning.
  return rows as unknown as Asset[]
}

export function getAssetById(db: WasmDB, tenantId: string, id: string): Asset | null {
  const rows = db.exec({
    sql: `SELECT * FROM assets WHERE tenant_id=? AND id=?`,
    bind: [tenantId, id],
    rowMode: 'object',
    returnValue: 'resultRows',
  })
  return (rows[0] as unknown as Asset) ?? null
}

export function upsertFieldValue(db: WasmDB, v: AssetFieldValue): void {
  db.exec({
    sql: `INSERT INTO asset_field_values (tenant_id, asset_id, field_id, value_json, hlc)
          VALUES (?, ?, ?, ?, ?)
          ON CONFLICT(tenant_id, asset_id, field_id) DO UPDATE SET
            value_json=excluded.value_json, hlc=excluded.hlc`,
    bind: [v.tenantId, v.assetId, v.fieldId, JSON.stringify(v.valueJson), v.hlc],
  })
}

export function listFieldValuesByEntity(
  db: WasmDB,
  tenantId: string,
  assetId: string,
): AssetFieldValue[] {
  const rows = db.exec({
    sql: `SELECT * FROM asset_field_values WHERE tenant_id=? AND asset_id=?`,
    bind: [tenantId, assetId],
    rowMode: 'object',
    returnValue: 'resultRows',
  })
  return rows as unknown as AssetFieldValue[]
}

export function listAssetFields(db: WasmDB, tenantId: string, typeId: string): AssetWithField[] {
  const rows = db.exec({
    sql: `SELECT a.id AS assetId, a.name AS assetName, v.field_id AS fieldId,
                 v.value_json AS valueJson, v.hlc AS hlc
          FROM assets a JOIN asset_field_values v
            ON v.tenant_id=a.tenant_id AND v.asset_id=a.id
          WHERE a.tenant_id=? AND a.type_id=?`,
    bind: [tenantId, typeId],
    rowMode: 'object',
    returnValue: 'resultRows',
  })
  return rows as unknown as AssetWithField[]
}
