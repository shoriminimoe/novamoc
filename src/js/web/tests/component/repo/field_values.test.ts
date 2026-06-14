import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { DbHandle } from '../../../src/lib/db/bootstrap'
import {
  HLC_1,
  HLC_2,
  TENANT_A,
  freshDb,
  resetDbs,
  seedAssetType,
  seedRecordType,
  withTenant,
} from './_fixtures'

const TYPE_PUMP = '00000000-0000-0000-0000-0000000000a1'
const TYPE_INSPECT = '00000000-0000-0000-0000-0000000000a2'
const ASSET_1 = '00000000-0000-0000-0000-0000000000b1'
const RECORD_1 = '00000000-0000-0000-0000-0000000000c1'
const FIELD_NAME = '00000000-0000-0000-0000-0000000000d1'
const FIELD_SERIAL = '00000000-0000-0000-0000-0000000000d2'

describe('assetFieldValueRepo', () => {
  let db: DbHandle
  let repos: ReturnType<typeof withTenant>

  beforeEach(async () => {
    db = await freshDb(TENANT_A)
    await seedAssetType(db, TENANT_A, TYPE_PUMP)
    repos = withTenant(db, TENANT_A)
    await repos.assets.upsert({
      id: ASSET_1,
      type_id: TYPE_PUMP,
      properties: {},
      deleted: false,
      row_state_hlc: HLC_1,
    })
  })

  afterEach(resetDbs)

  it('upserts and lists field values for an asset, ordered by field id', async () => {
    await repos.assetFieldValues.upsert({
      asset_id: ASSET_1,
      field_id: FIELD_SERIAL,
      value_json: 'SN-9',
      hlc: HLC_1,
    })
    await repos.assetFieldValues.upsert({
      asset_id: ASSET_1,
      field_id: FIELD_NAME,
      value_json: 'Pump 1',
      hlc: HLC_1,
    })

    const rows = await repos.assetFieldValues.listByAsset(ASSET_1)
    expect(rows.map((r) => r.field_id)).toEqual([FIELD_NAME, FIELD_SERIAL])
    expect(rows.map((r) => r.value_json)).toEqual(['Pump 1', 'SN-9'])
  })

  it('upsert overwrites an existing field value (LWW slot)', async () => {
    await repos.assetFieldValues.upsert({
      asset_id: ASSET_1,
      field_id: FIELD_NAME,
      value_json: 'Old',
      hlc: HLC_1,
    })
    await repos.assetFieldValues.upsert({
      asset_id: ASSET_1,
      field_id: FIELD_NAME,
      value_json: 'New',
      hlc: HLC_2,
    })

    const rows = await repos.assetFieldValues.listByAsset(ASSET_1)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ value_json: 'New', hlc: HLC_2 })
  })

  it('clear writes a JSON null, keeping the row present', async () => {
    await repos.assetFieldValues.upsert({
      asset_id: ASSET_1,
      field_id: FIELD_NAME,
      value_json: 'Pump 1',
      hlc: HLC_1,
    })
    await repos.assetFieldValues.clear(ASSET_1, FIELD_NAME, HLC_2)

    const rows = await repos.assetFieldValues.listByAsset(ASSET_1)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ value_json: null, hlc: HLC_2 })
  })

  it('preserves object value_json round-trip', async () => {
    await repos.assetFieldValues.upsert({
      asset_id: ASSET_1,
      field_id: FIELD_NAME,
      value_json: { nested: [1, 2, 3] },
      hlc: HLC_1,
    })
    const rows = await repos.assetFieldValues.listByAsset(ASSET_1)
    expect(rows[0].value_json).toEqual({ nested: [1, 2, 3] })
  })
})

describe('maintenanceRecordFieldValueRepo', () => {
  let db: DbHandle
  let repos: ReturnType<typeof withTenant>

  beforeEach(async () => {
    db = await freshDb(TENANT_A)
    await seedAssetType(db, TENANT_A, TYPE_PUMP)
    await seedRecordType(db, TENANT_A, TYPE_INSPECT)
    repos = withTenant(db, TENANT_A)
    await repos.assets.upsert({
      id: ASSET_1,
      type_id: TYPE_PUMP,
      properties: {},
      deleted: false,
      row_state_hlc: HLC_1,
    })
    await repos.maintenanceRecords.upsert({
      id: RECORD_1,
      type_id: TYPE_INSPECT,
      asset_id: ASSET_1,
      properties: {},
      deleted: false,
      row_state_hlc: HLC_1,
    })
  })

  afterEach(resetDbs)

  it('upserts, lists and clears record field values', async () => {
    await repos.maintenanceRecordFieldValues.upsert({
      maintenance_record_id: RECORD_1,
      field_id: FIELD_NAME,
      value_json: 'Quarterly',
      hlc: HLC_1,
    })

    let rows = await repos.maintenanceRecordFieldValues.listByRecord(RECORD_1)
    expect(rows[0]).toMatchObject({ value_json: 'Quarterly' })

    await repos.maintenanceRecordFieldValues.clear(RECORD_1, FIELD_NAME, HLC_2)
    rows = await repos.maintenanceRecordFieldValues.listByRecord(RECORD_1)
    expect(rows[0]).toMatchObject({ value_json: null, hlc: HLC_2 })
  })
})
