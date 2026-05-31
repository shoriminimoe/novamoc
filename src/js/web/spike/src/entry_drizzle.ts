import { makeDb } from './driver'
import { makeDrizzle } from './drizzle_repo'
import * as repo from './drizzle_repo'
import type { Asset, AssetFieldValue } from './domain'

const db = makeDrizzle(makeDb())
const a: Asset = {
  tenantId: 't', id: 'a', typeId: 'ty', name: 'n', properties: { k: 1 }, deleted: false, rowStateHlc: 'h',
}
const v: AssetFieldValue = { tenantId: 't', assetId: 'a', fieldId: 'f', valueJson: { x: 1 }, hlc: 'h' }
async function main() {
  await repo.upsertAsset(db, a)
  await repo.upsertFieldValue(db, v)
  ;(globalThis as Record<string, unknown>).out = [
    await repo.listAssetsByType(db, 't', 'ty'),
    await repo.getAssetById(db, 't', 'a'),
    await repo.listFieldValuesByEntity(db, 't', 'a'),
    await repo.listAssetFields(db, 't', 'ty'),
  ]
}
void main()
