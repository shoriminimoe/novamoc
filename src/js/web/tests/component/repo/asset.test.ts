import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { DbHandle } from '../../../src/lib/db/bootstrap'
import {
  HLC_1,
  HLC_2,
  TENANT_A,
  freshDb,
  resetDbs,
  seedAssetType,
  withTenant,
} from './_fixtures'

const TYPE_PUMP = '00000000-0000-0000-0000-0000000000a1'
const ASSET_1 = '00000000-0000-0000-0000-0000000000b1'
const ASSET_2 = '00000000-0000-0000-0000-0000000000b2'

function draft(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    type_id: TYPE_PUMP,
    properties: { name: 'Pump 1' },
    deleted: false,
    row_state_hlc: HLC_1,
    ...overrides,
  }
}

describe('assetRepo', () => {
  let db: DbHandle
  let repo: ReturnType<typeof withTenant>['assets']

  beforeEach(async () => {
    db = await freshDb(TENANT_A)
    await seedAssetType(db, TENANT_A, TYPE_PUMP)
    repo = withTenant(db, TENANT_A).assets
  })

  afterEach(resetDbs)

  it('upserts a new asset and reads it back via getById', async () => {
    await repo.upsert(draft(ASSET_1))

    const row = await repo.getById(ASSET_1)
    expect(row).toMatchObject({
      id: ASSET_1,
      type_id: TYPE_PUMP,
      properties: { name: 'Pump 1' },
      deleted: false,
      row_state_hlc: HLC_1,
    })
  })

  it('returns null from getById for an unknown id', async () => {
    expect(await repo.getById(ASSET_1)).toBeNull()
  })

  it('upsert is idempotent on the primary key (overwrites)', async () => {
    await repo.upsert(draft(ASSET_1))
    await repo.upsert(
      draft(ASSET_1, { properties: { name: 'Renamed' }, row_state_hlc: HLC_2 }),
    )

    const row = await repo.getById(ASSET_1)
    expect(row?.properties).toEqual({ name: 'Renamed' })
    expect(row?.row_state_hlc).toBe(HLC_2)
  })

  it('listByType returns only assets of the given type, in id order', async () => {
    await repo.upsert(draft(ASSET_2))
    await repo.upsert(draft(ASSET_1))

    const rows = await repo.listByType(TYPE_PUMP)
    expect(rows.map((r) => r.id)).toEqual([ASSET_1, ASSET_2])
  })

  it('archive sets deleted and restore clears it', async () => {
    await repo.upsert(draft(ASSET_1))

    await repo.archive(ASSET_1, HLC_2)
    expect((await repo.getById(ASSET_1))?.deleted).toBe(true)
    expect((await repo.getById(ASSET_1))?.row_state_hlc).toBe(HLC_2)

    await repo.restore(ASSET_1, HLC_2)
    expect((await repo.getById(ASSET_1))?.deleted).toBe(false)
  })

  it('delete removes the row', async () => {
    await repo.upsert(draft(ASSET_1))
    await repo.delete(ASSET_1)

    expect(await repo.getById(ASSET_1)).toBeNull()
  })
})
