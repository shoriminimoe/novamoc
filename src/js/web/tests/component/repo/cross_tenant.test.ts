/**
 * Paired cross-tenant isolation, mirroring the server's
 * `tests/schema/test_cross_tenant_isolation.py` discipline: seed equivalent
 * rows under two tenant ids in the *same* DB and assert each tenant's repo
 * sees only its own.
 *
 * The local app opens one tenant's DB file at a time, but the `tenant_id`
 * column is carried on every row for wire/fold parity (see `ddl.ts`); these
 * tests prove the repo's WHERE/VALUES pinning is correct regardless, which is
 * the property E3/E4 rely on.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { DbHandle } from '../../../src/lib/db/bootstrap'
import {
  HLC_1,
  TENANT_A,
  TENANT_B,
  freshDb,
  resetDbs,
  seedAssetType,
  withTenant,
} from './_fixtures'

const TYPE_PUMP = '00000000-0000-0000-0000-0000000000a1'
const ASSET_A = '00000000-0000-0000-0000-0000000000aa'
const ASSET_B = '00000000-0000-0000-0000-0000000000bb'
const FIELD_NAME = '00000000-0000-0000-0000-0000000000d1'

describe('cross-tenant isolation', () => {
  let db: DbHandle

  beforeEach(async () => {
    // One physical DB, two tenants seeded with equivalent rows.
    db = await freshDb(TENANT_A)
    await seedAssetType(db, TENANT_A, TYPE_PUMP)
    await seedAssetType(db, TENANT_B, TYPE_PUMP)

    const a = withTenant(db, TENANT_A)
    const b = withTenant(db, TENANT_B)
    await a.assets.upsert({
      id: ASSET_A,
      type_id: TYPE_PUMP,
      properties: { name: 'A' },
      deleted: false,
      row_state_hlc: HLC_1,
    })
    await b.assets.upsert({
      id: ASSET_B,
      type_id: TYPE_PUMP,
      properties: { name: 'B' },
      deleted: false,
      row_state_hlc: HLC_1,
    })
    await a.assetFieldValues.upsert({
      asset_id: ASSET_A,
      field_id: FIELD_NAME,
      value_json: 'A',
      hlc: HLC_1,
    })
    await b.assetFieldValues.upsert({
      asset_id: ASSET_B,
      field_id: FIELD_NAME,
      value_json: 'B',
      hlc: HLC_1,
    })
  })

  afterEach(resetDbs)

  it('listByType returns only the calling tenant rows', async () => {
    const a = withTenant(db, TENANT_A)
    const b = withTenant(db, TENANT_B)

    expect((await a.assets.listByType(TYPE_PUMP)).map((r) => r.id)).toEqual([
      ASSET_A,
    ])
    expect((await b.assets.listByType(TYPE_PUMP)).map((r) => r.id)).toEqual([
      ASSET_B,
    ])
  })

  it('getById cannot reach across tenants', async () => {
    const a = withTenant(db, TENANT_A)
    const b = withTenant(db, TENANT_B)

    expect(await a.assets.getById(ASSET_B)).toBeNull()
    expect(await b.assets.getById(ASSET_A)).toBeNull()
  })

  it('field-value reads are tenant-scoped', async () => {
    const a = withTenant(db, TENANT_A)
    const b = withTenant(db, TENANT_B)

    expect(await a.assetFieldValues.listByAsset(ASSET_B)).toEqual([])
    expect((await b.assetFieldValues.listByAsset(ASSET_B))[0].value_json).toBe(
      'B',
    )
  })

  it('a write under tenant A does not appear under tenant B', async () => {
    const a = withTenant(db, TENANT_A)
    const b = withTenant(db, TENANT_B)

    await a.assets.archive(ASSET_A, HLC_1)
    // B's equivalent row is untouched.
    expect((await b.assets.getById(ASSET_B))?.deleted).toBe(false)
  })
})
