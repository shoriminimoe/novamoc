import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { DbHandle } from '../../../src/lib/db/bootstrap'
import { HLC_1, HLC_2, TENANT_A, freshDb, resetDbs, withTenant } from './_fixtures'

const TYPE_PUMP = '00000000-0000-0000-0000-0000000000a1'
const FIELD_NAME = '00000000-0000-0000-0000-0000000000d1'
const ASSET_1 = '00000000-0000-0000-0000-0000000000b1'

describe('schemaProjectionRepo', () => {
  let db: DbHandle
  let repos: ReturnType<typeof withTenant>

  beforeEach(async () => {
    db = await freshDb(TENANT_A)
    await db.exec(
      'INSERT INTO asset_types (tenant_id, id, name, active) VALUES (?, ?, ?, 0)',
      [TENANT_A, TYPE_PUMP, 'Pump'],
    )
    await db.exec(
      `INSERT INTO asset_type_fields
         (tenant_id, id, parent_id, name, data_type, validation, active)
       VALUES (?, ?, ?, ?, ?, ?, 1)`,
      [TENANT_A, FIELD_NAME, TYPE_PUMP, 'name', 'text', '{"required":true}'],
    )
    repos = withTenant(db, TENANT_A)
  })

  afterEach(resetDbs)

  it('lists asset types including tombstoned (active=false) rows', async () => {
    const types = await repos.schema.listAssetTypes()
    expect(types).toEqual([{ id: TYPE_PUMP, name: 'Pump', active: false }])
  })

  it('lists fields for a type with parsed validation JSON', async () => {
    const fields = await repos.schema.listAssetTypeFields(TYPE_PUMP)
    expect(fields).toEqual([
      {
        id: FIELD_NAME,
        parent_id: TYPE_PUMP,
        name: 'name',
        data_type: 'text',
        validation: { required: true },
        active: true,
      },
    ])
  })

  it('returns empty arrays for record types with no rows', async () => {
    expect(await repos.schema.listRecordTypes()).toEqual([])
    expect(await repos.schema.listRecordTypeFields(TYPE_PUMP)).toEqual([])
  })
})

describe('eventLogRepo', () => {
  let db: DbHandle
  let repos: ReturnType<typeof withTenant>

  beforeEach(async () => {
    db = await freshDb(TENANT_A)
    for (const [seq, hlc] of [
      [1, HLC_1],
      [2, HLC_2],
    ] as const) {
      await db.exec(
        `INSERT INTO event_log
           (seq, tenant_id, hlc, schema_version, table_name, type_id, entity_id, op, value_json)
         VALUES (?, ?, ?, 1, 'assets', ?, ?, 'CREATE', ?)`,
        [seq, TENANT_A, hlc, TYPE_PUMP, ASSET_1, '{"k":1}'],
      )
    }
    repos = withTenant(db, TENANT_A)
  })

  afterEach(resetDbs)

  it('lists events after a cursor in seq order with parsed value_json', async () => {
    const events = await repos.events.listSince(0)
    expect(events.map((e) => e.seq)).toEqual([1, 2])
    expect(events[0].value_json).toEqual({ k: 1 })
  })

  it('honours the exclusive cursor', async () => {
    const events = await repos.events.listSince(1)
    expect(events.map((e) => e.seq)).toEqual([2])
  })

  it('getBySeq returns one row or null', async () => {
    expect((await repos.events.getBySeq(2))?.hlc).toBe(HLC_2)
    expect(await repos.events.getBySeq(99)).toBeNull()
  })
})

describe('pendingQueueRepo', () => {
  let db: DbHandle
  let repos: ReturnType<typeof withTenant>

  async function enqueue(hlc: string): Promise<number> {
    const rows = await db.exec(
      `INSERT INTO local_pending_events
         (tenant_id, hlc, schema_version, table_name, type_id, entity_id, op, value_json)
       VALUES (?, ?, 1, 'assets', ?, ?, 'CREATE', '{}')
       RETURNING client_seq`,
      [TENANT_A, hlc, TYPE_PUMP, ASSET_1],
    )
    return rows[0][0] as number
  }

  beforeEach(async () => {
    db = await freshDb(TENANT_A)
    repos = withTenant(db, TENANT_A)
  })

  afterEach(resetDbs)

  it('lists pending rows in hlc (send) order', async () => {
    await enqueue(HLC_2)
    await enqueue(HLC_1)

    const pending = await repos.pending.listPending()
    expect(pending.map((p) => p.hlc)).toEqual([HLC_1, HLC_2])
  })

  it('markSent removes the row from the queue', async () => {
    const seq = await enqueue(HLC_1)
    await repos.pending.markSent(seq)

    expect(await repos.pending.listPending()).toEqual([])
  })

  it('recordFailure leaves the row queued for retry', async () => {
    const seq = await enqueue(HLC_1)
    await repos.pending.recordFailure(seq, 'network down')

    const pending = await repos.pending.listPending()
    expect(pending.map((p) => p.client_seq)).toEqual([seq])
  })
})
