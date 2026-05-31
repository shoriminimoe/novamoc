/**
 * Candidate 2 — KYSELY typed query builder.
 *
 * Schema is declared ONCE as a `Database` interface; query builder methods are
 * fully typed off it. JSON columns are declared with the row type so reads come
 * back typed; SQLite stores them as TEXT so we serialize at the boundary.
 *
 * We use the query *compiler* only (CompiledQuery -> { sql, parameters }) and
 * hand the SQL to our WasmDB driver, since there is no official kysely dialect
 * for @sqlite.org/sqlite-wasm. This is exactly how the real layer would work.
 */
import { Kysely, DummyDriver, SqliteAdapter, SqliteIntrospector, SqliteQueryCompiler } from 'kysely'
import type { Generated } from 'kysely'
import type { WasmDB } from './driver'
import type { Asset, AssetFieldValue, AssetWithField } from './domain'

interface AssetsTable {
  tenant_id: string
  id: string
  type_id: string
  name: string | null
  properties: string // JSON serialized at boundary
  deleted: Generated<number>
  row_state_hlc: string
}

interface AssetFieldValuesTable {
  tenant_id: string
  asset_id: string
  field_id: string
  value_json: string | null
  hlc: string
}

interface Database {
  assets: AssetsTable
  asset_field_values: AssetFieldValuesTable
}

// Compile-only Kysely: no live connection, we extract SQL + params.
const qb = new Kysely<Database>({
  dialect: {
    createAdapter: () => new SqliteAdapter(),
    createDriver: () => new DummyDriver(),
    createIntrospector: (db) => new SqliteIntrospector(db),
    createQueryCompiler: () => new SqliteQueryCompiler(),
  },
})

function run<T>(db: WasmDB, sql: string, parameters: readonly unknown[]): T[] {
  return db.exec({
    sql,
    bind: parameters as unknown[],
    rowMode: 'object',
    returnValue: 'resultRows',
  }) as T[]
}

export function upsertAsset(db: WasmDB, a: Asset): void {
  const c = qb
    .insertInto('assets')
    .values({
      tenant_id: a.tenantId,
      id: a.id,
      type_id: a.typeId,
      name: a.name,
      properties: JSON.stringify(a.properties),
      deleted: a.deleted ? 1 : 0,
      row_state_hlc: a.rowStateHlc,
    })
    .onConflict((oc) =>
      oc.columns(['tenant_id', 'id']).doUpdateSet({
        type_id: a.typeId,
        name: a.name,
        properties: JSON.stringify(a.properties),
        deleted: a.deleted ? 1 : 0,
        row_state_hlc: a.rowStateHlc,
      }),
    )
    .compile()
  run(db, c.sql, c.parameters)
}

export function listAssetsByType(db: WasmDB, tenantId: string, typeId: string): Asset[] {
  const c = qb
    .selectFrom('assets')
    .selectAll()
    .where('tenant_id', '=', tenantId)
    .where('type_id', '=', typeId)
    .where('deleted', '=', 0)
    .compile()
  return run<AssetsTable>(db, c.sql, c.parameters).map(deserializeAsset)
}

export function getAssetById(db: WasmDB, tenantId: string, id: string): Asset | null {
  const c = qb
    .selectFrom('assets')
    .selectAll()
    .where('tenant_id', '=', tenantId)
    .where('id', '=', id)
    .compile()
  const rows = run<AssetsTable>(db, c.sql, c.parameters)
  return rows.length ? deserializeAsset(rows[0]) : null
}

export function upsertFieldValue(db: WasmDB, v: AssetFieldValue): void {
  const c = qb
    .insertInto('asset_field_values')
    .values({
      tenant_id: v.tenantId,
      asset_id: v.assetId,
      field_id: v.fieldId,
      value_json: JSON.stringify(v.valueJson),
      hlc: v.hlc,
    })
    .onConflict((oc) =>
      oc
        .columns(['tenant_id', 'asset_id', 'field_id'])
        .doUpdateSet({ value_json: JSON.stringify(v.valueJson), hlc: v.hlc }),
    )
    .compile()
  run(db, c.sql, c.parameters)
}

export function listFieldValuesByEntity(
  db: WasmDB,
  tenantId: string,
  assetId: string,
): AssetFieldValue[] {
  const c = qb
    .selectFrom('asset_field_values')
    .selectAll()
    .where('tenant_id', '=', tenantId)
    .where('asset_id', '=', assetId)
    .compile()
  return run<AssetFieldValuesTable>(db, c.sql, c.parameters).map((r) => ({
    tenantId: r.tenant_id,
    assetId: r.asset_id,
    fieldId: r.field_id,
    valueJson: JSON.parse(r.value_json ?? 'null'),
    hlc: r.hlc,
  }))
}

export function listAssetFields(db: WasmDB, tenantId: string, typeId: string): AssetWithField[] {
  const c = qb
    .selectFrom('assets as a')
    .innerJoin('asset_field_values as v', (j) =>
      j.onRef('v.tenant_id', '=', 'a.tenant_id').onRef('v.asset_id', '=', 'a.id'),
    )
    .select(['a.id as asset_id', 'a.name as asset_name', 'v.field_id', 'v.value_json', 'v.hlc'])
    .where('a.tenant_id', '=', tenantId)
    .where('a.type_id', '=', typeId)
    .compile()
  return run<{
    asset_id: string
    asset_name: string | null
    field_id: string
    value_json: string | null
    hlc: string
  }>(db, c.sql, c.parameters).map((r) => ({
    assetId: r.asset_id,
    assetName: r.asset_name,
    fieldId: r.field_id,
    valueJson: JSON.parse(r.value_json ?? 'null'),
    hlc: r.hlc,
  }))
}

function deserializeAsset(r: AssetsTable): Asset {
  return {
    tenantId: r.tenant_id,
    id: r.id,
    typeId: r.type_id,
    name: r.name,
    properties: JSON.parse(r.properties ?? '{}'),
    deleted: Boolean(r.deleted),
    rowStateHlc: r.row_state_hlc,
  }
}
