/**
 * Candidate 3 — DRIZZLE ORM repo.
 *
 * Uses drizzle's query builder against the schema. There is no official
 * @sqlite.org/sqlite-wasm driver, so we wire a thin custom async/sync proxy.
 * For a fair bundle comparison we pull in `drizzle-orm` and build the same
 * queries; the SQLite-proxy driver is part of drizzle-orm itself.
 */
import { drizzle } from 'drizzle-orm/sqlite-proxy'
import { eq, and } from 'drizzle-orm'
import { assets, assetFieldValues } from './drizzle_schema'
import type { WasmDB } from './driver'
import type { Asset, AssetFieldValue, AssetWithField } from './domain'

export function makeDrizzle(wasm: WasmDB) {
  return drizzle(
    async (sql, params, method) => {
      const rows = wasm.exec({
        sql,
        bind: params,
        rowMode: method === 'all' ? 'object' : 'array',
        returnValue: 'resultRows',
      })
      return { rows: rows as unknown[] }
    },
    { schema: { assets, assetFieldValues } },
  )
}

type DB = ReturnType<typeof makeDrizzle>

export async function upsertAsset(db: DB, a: Asset): Promise<void> {
  await db
    .insert(assets)
    .values({
      tenantId: a.tenantId,
      id: a.id,
      typeId: a.typeId,
      name: a.name,
      properties: a.properties,
      deleted: a.deleted,
      rowStateHlc: a.rowStateHlc,
    })
    .onConflictDoUpdate({
      target: [assets.tenantId, assets.id],
      set: {
        typeId: a.typeId,
        name: a.name,
        properties: a.properties,
        deleted: a.deleted,
        rowStateHlc: a.rowStateHlc,
      },
    })
}

export async function listAssetsByType(db: DB, tenantId: string, typeId: string): Promise<Asset[]> {
  const rows = await db
    .select()
    .from(assets)
    .where(and(eq(assets.tenantId, tenantId), eq(assets.typeId, typeId), eq(assets.deleted, false)))
  return rows.map(toAsset)
}

export async function getAssetById(db: DB, tenantId: string, id: string): Promise<Asset | null> {
  const rows = await db
    .select()
    .from(assets)
    .where(and(eq(assets.tenantId, tenantId), eq(assets.id, id)))
  return rows.length ? toAsset(rows[0]) : null
}

export async function upsertFieldValue(db: DB, v: AssetFieldValue): Promise<void> {
  await db
    .insert(assetFieldValues)
    .values({
      tenantId: v.tenantId,
      assetId: v.assetId,
      fieldId: v.fieldId,
      valueJson: v.valueJson,
      hlc: v.hlc,
    })
    .onConflictDoUpdate({
      target: [assetFieldValues.tenantId, assetFieldValues.assetId, assetFieldValues.fieldId],
      set: { valueJson: v.valueJson, hlc: v.hlc },
    })
}

export async function listFieldValuesByEntity(
  db: DB,
  tenantId: string,
  assetId: string,
): Promise<AssetFieldValue[]> {
  const rows = await db
    .select()
    .from(assetFieldValues)
    .where(and(eq(assetFieldValues.tenantId, tenantId), eq(assetFieldValues.assetId, assetId)))
  return rows.map((r) => ({
    tenantId: r.tenantId,
    assetId: r.assetId,
    fieldId: r.fieldId,
    valueJson: r.valueJson,
    hlc: r.hlc,
  }))
}

export async function listAssetFields(
  db: DB,
  tenantId: string,
  typeId: string,
): Promise<AssetWithField[]> {
  const rows = await db
    .select({
      assetId: assets.id,
      assetName: assets.name,
      fieldId: assetFieldValues.fieldId,
      valueJson: assetFieldValues.valueJson,
      hlc: assetFieldValues.hlc,
    })
    .from(assets)
    .innerJoin(
      assetFieldValues,
      and(eq(assetFieldValues.tenantId, assets.tenantId), eq(assetFieldValues.assetId, assets.id)),
    )
    .where(and(eq(assets.tenantId, tenantId), eq(assets.typeId, typeId)))
  return rows
}

function toAsset(r: typeof assets.$inferSelect): Asset {
  return {
    tenantId: r.tenantId,
    id: r.id,
    typeId: r.typeId,
    name: r.name,
    properties: r.properties,
    deleted: r.deleted,
    rowStateHlc: r.rowStateHlc,
  }
}
