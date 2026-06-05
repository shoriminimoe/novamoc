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
const RECORD_2 = '00000000-0000-0000-0000-0000000000c2'

describe('maintenanceRecordRepo', () => {
  let db: DbHandle
  let repos: ReturnType<typeof withTenant>

  function draft(id: string, overrides: Record<string, unknown> = {}) {
    return {
      id,
      type_id: TYPE_INSPECT,
      asset_id: ASSET_1,
      properties: { name: 'Q1 inspection' },
      deleted: false,
      row_state_hlc: HLC_1,
      ...overrides,
    }
  }

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
  })

  afterEach(resetDbs)

  it('upserts a record carrying its parent asset id and reads it back', async () => {
    await repos.maintenanceRecords.upsert(draft(RECORD_1))

    const row = await repos.maintenanceRecords.getById(RECORD_1)
    expect(row).toMatchObject({
      id: RECORD_1,
      type_id: TYPE_INSPECT,
      asset_id: ASSET_1,
      properties: { name: 'Q1 inspection' },
      deleted: false,
    })
  })

  it('getById returns null for an unknown id', async () => {
    expect(await repos.maintenanceRecords.getById(RECORD_1)).toBeNull()
  })

  it('listByType returns only records of the type, id-ordered', async () => {
    await repos.maintenanceRecords.upsert(draft(RECORD_2))
    await repos.maintenanceRecords.upsert(draft(RECORD_1))

    const rows = await repos.maintenanceRecords.listByType(TYPE_INSPECT)
    expect(rows.map((r) => r.id)).toEqual([RECORD_1, RECORD_2])
  })

  it('archive, restore and delete behave like the asset repo', async () => {
    await repos.maintenanceRecords.upsert(draft(RECORD_1))

    await repos.maintenanceRecords.archive(RECORD_1, HLC_2)
    expect((await repos.maintenanceRecords.getById(RECORD_1))?.deleted).toBe(
      true,
    )

    await repos.maintenanceRecords.restore(RECORD_1, HLC_2)
    expect((await repos.maintenanceRecords.getById(RECORD_1))?.deleted).toBe(
      false,
    )

    await repos.maintenanceRecords.delete(RECORD_1)
    expect(await repos.maintenanceRecords.getById(RECORD_1)).toBeNull()
  })
})
