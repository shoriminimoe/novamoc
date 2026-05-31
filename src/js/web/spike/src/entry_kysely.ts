import { makeDb } from './driver'
import * as repo from './kysely_repo'
import type { Asset, AssetFieldValue } from './domain'

const db = makeDb()
const a: Asset = {
  tenantId: 't', id: 'a', typeId: 'ty', name: 'n', properties: { k: 1 }, deleted: false, rowStateHlc: 'h',
}
const v: AssetFieldValue = { tenantId: 't', assetId: 'a', fieldId: 'f', valueJson: { x: 1 }, hlc: 'h' }
repo.upsertAsset(db, a)
repo.upsertFieldValue(db, v)
;(globalThis as Record<string, unknown>).out = [
  repo.listAssetsByType(db, 't', 'ty'),
  repo.getAssetById(db, 't', 'a'),
  repo.listFieldValuesByEntity(db, 't', 'a'),
  repo.listAssetFields(db, 't', 'ty'),
]
