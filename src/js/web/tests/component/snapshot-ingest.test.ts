/**
 * Snapshot-ingest tests (ADR-013 / ADR-015).
 *
 * Runs against the real in-memory SQLite-WASM DB from `openLocalDb` — no DB
 * mocks, matching the project's db-test discipline — so the four projection
 * tables, the resumable in-flight token, and the terminal `sync_state` write
 * exercise actual SQL. Only the HTTP boundary is mocked: a scripted
 * `ApiClient` hands back canned `GET /snapshot` batches in sequence, and can
 * be made to throw mid-pagination to drive the resume/restart paths.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { _resetLocalDbsForTest, openLocalDb } from '../../src/lib/db/bootstrap'
import { SnapshotProgressStore } from '../../src/lib/sync/_progress'
import { ingestSnapshot } from '../../src/lib/sync/snapshot'
import type { ApiClient } from '../../src/lib/api'

const TENANT = '00000000-0000-0000-0000-0000000005ce'
const TRUCK = '11111111-1111-1111-1111-111111111111'
const OIL = '44444444-4444-4444-4444-444444444444'
const ASSET_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const ASSET_B = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaab'
const MR_A = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'

interface Store {
  exec(sql: string, bind?: unknown[]): Promise<unknown[][]>
}

async function rows(store: Store, sql: string, bind?: unknown[]) {
  return (await store.exec(sql, bind)) as unknown[][]
}

/**
 * Seed the schema type rows the snapshot's projection rows reference. In
 * production `refreshSchema` (E1.6) populates these before the snapshot runs;
 * the projection FKs (assets→asset_types, MRs→mr_types) require them present.
 */
async function seedSchema(store: Store): Promise<void> {
  await store.exec(
    'INSERT INTO asset_types (tenant_id, id, name) VALUES (?, ?, ?)',
    [TENANT, TRUCK, 'Truck'],
  )
  await store.exec(
    'INSERT INTO maintenance_record_types (tenant_id, id, name) VALUES (?, ?, ?)',
    [TENANT, OIL, 'Oil Change'],
  )
}

/**
 * An `ApiClient` whose `GET /snapshot` returns scripted batches in order. A
 * batch may be a function that throws (to simulate a transport error). The
 * client records every requested path so a test can assert resume behaviour.
 */
function scriptedClient(batches: (object | (() => never))[]): {
  client: ApiClient
  paths: string[]
} {
  const paths: string[] = []
  let i = 0
  const client: ApiClient = {
    get: <T>(path: string) => {
      paths.push(path)
      const next = batches[i]
      i += 1
      if (typeof next === 'function') {
        next()
      }
      return Promise.resolve(next as T)
    },
    post: <T>() => Promise.resolve(undefined as T),
  }
  return { client, paths }
}

// A full multi-batch transfer: assets (2 batches), one asset field value,
// one maintenance record, one MR field value, terminal carries the cursor.
function fullTransfer(schemaVersion = 7): object[] {
  return [
    {
      schema_version: schemaVersion,
      page: 'PAGE-1',
      cursor: null,
      body: {
        table: 'assets',
        items: [
          { id: ASSET_A, type_id: TRUCK, deleted: false, row_state_hlc: 'h1' },
        ],
      },
    },
    {
      schema_version: schemaVersion,
      page: 'PAGE-2',
      cursor: null,
      body: {
        table: 'assets',
        items: [
          { id: ASSET_B, type_id: TRUCK, deleted: true, row_state_hlc: 'h2' },
        ],
      },
    },
    {
      schema_version: schemaVersion,
      page: 'PAGE-3',
      cursor: null,
      body: {
        table: 'asset_field_values',
        items: [
          { asset_id: ASSET_A, field_id: 'col:name', value_json: 'Truck A', hlc: 'h1' },
        ],
      },
    },
    {
      schema_version: schemaVersion,
      page: 'PAGE-4',
      cursor: null,
      body: {
        table: 'maintenance_records',
        items: [
          {
            id: MR_A,
            type_id: OIL,
            asset_id: ASSET_A,
            deleted: false,
            row_state_hlc: 'h3',
          },
        ],
      },
    },
    {
      schema_version: schemaVersion,
      page: null,
      cursor: 42,
      body: {
        table: 'maintenance_record_field_values',
        items: [
          {
            maintenance_record_id: MR_A,
            field_id: 'col:name',
            value_json: 'Oil change',
            hlc: 'h3',
          },
        ],
      },
    },
  ]
}

afterEach(async () => {
  await _resetLocalDbsForTest()
})

describe('ingestSnapshot', () => {
  it('populates all four projection tables and returns the terminal cursor', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    await seedSchema(db)
    const { client } = scriptedClient(fullTransfer(7))

    const result = await ingestSnapshot({ store: db, tenantId: TENANT, client })

    expect(result).toEqual({ cursor: 42, schema_version: 7 })

    const assets = await rows(
      db,
      'SELECT id, type_id, deleted, row_state_hlc FROM assets ORDER BY id',
    )
    expect(assets).toEqual([
      [ASSET_A, TRUCK, 0, 'h1'],
      [ASSET_B, TRUCK, 1, 'h2'],
    ])

    const afvs = await rows(
      db,
      'SELECT asset_id, field_id, value_json, hlc FROM asset_field_values ORDER BY asset_id, field_id',
    )
    expect(afvs).toEqual([[ASSET_A, 'col:name', JSON.stringify('Truck A'), 'h1']])

    const mrs = await rows(
      db,
      'SELECT id, type_id, asset_id, deleted, row_state_hlc FROM maintenance_records',
    )
    expect(mrs).toEqual([[MR_A, OIL, ASSET_A, 0, 'h3']])

    const mrfvs = await rows(
      db,
      'SELECT maintenance_record_id, field_id, value_json, hlc FROM maintenance_record_field_values',
    )
    expect(mrfvs).toEqual([[MR_A, 'col:name', JSON.stringify('Oil change'), 'h3']])
  })

  it('persists cursor and schema_version into sync_state and clears the in-flight token', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    await seedSchema(db)
    const { client } = scriptedClient(fullTransfer(7))

    await ingestSnapshot({ store: db, tenantId: TENANT, client })

    const [[lastSeen, activeVersion, page, snapVersion]] = await rows(
      db,
      `SELECT last_seen_seq, active_schema_version, snapshot_page, snapshot_schema_version
         FROM sync_state WHERE id = 1`,
    )
    expect(lastSeen).toBe(42)
    expect(activeVersion).toBe(7)
    expect(page).toBeNull()
    expect(snapVersion).toBeNull()
  })

  it('handles an empty tenant (single terminal batch, cursor 0)', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    await seedSchema(db)
    const { client } = scriptedClient([
      {
        schema_version: 3,
        page: null,
        cursor: 0,
        body: { table: 'maintenance_record_field_values', items: [] },
      },
    ])

    const result = await ingestSnapshot({ store: db, tenantId: TENANT, client })

    expect(result).toEqual({ cursor: 0, schema_version: 3 })
    const [[count]] = await rows(db, 'SELECT count(*) FROM assets')
    expect(count).toBe(0)
  })

  it('reports per-table progress to the observable', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    await seedSchema(db)
    const { client } = scriptedClient(fullTransfer(7))
    const progress = new SnapshotProgressStore()

    await ingestSnapshot({ store: db, tenantId: TENANT, client, progress })

    const snap = progress.snapshot()
    expect(snap.phase).toBe('done')
    expect(snap.totalRows).toBe(5)
    expect(snap.tables.assets).toEqual({ rows: 2, batches: 2 })
    expect(snap.tables.maintenance_record_field_values).toEqual({
      rows: 1,
      batches: 1,
    })
  })

  describe('resumable failure', () => {
    it('leaves partial state and a resumable token after a transport error', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
    await seedSchema(db)
      const transfer = fullTransfer(7)
      // Deliver the first two batches, then fail on the third fetch.
      const { client, paths } = scriptedClient([
        transfer[0],
        transfer[1],
        () => {
          throw new Error('network down')
        },
      ])
      const progress = new SnapshotProgressStore()

      await expect(
        ingestSnapshot({ store: db, tenantId: TENANT, client, progress }),
      ).rejects.toThrow('network down')

      // Partial assets persisted.
      const [[assetCount]] = await rows(db, 'SELECT count(*) FROM assets')
      expect(assetCount).toBe(2)

      // The continuation token from batch 2 is checkpointed.
      const [[page, snapVersion]] = await rows(
        db,
        'SELECT snapshot_page, snapshot_schema_version FROM sync_state WHERE id = 1',
      )
      expect(page).toBe('PAGE-2')
      expect(snapVersion).toBe(7)
      expect(progress.snapshot().phase).toBe('error')
      // The failing fetch used PAGE-2 (batch 2's continuation).
      expect(paths.at(-1)).toBe('/snapshot?page=PAGE-2')
    })

    it('resumes from the persisted token on the next call', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
    await seedSchema(db)
      const transfer = fullTransfer(7)

      // First attempt: batches 1-2 then error.
      const first = scriptedClient([
        transfer[0],
        transfer[1],
        () => {
          throw new Error('network down')
        },
      ])
      await expect(
        ingestSnapshot({ store: db, tenantId: TENANT, client: first.client }),
      ).rejects.toThrow('network down')

      // Second attempt: the remaining batches (3,4,terminal). Resume must NOT
      // re-fetch from the start — the first request carries the persisted page.
      const second = scriptedClient([transfer[2], transfer[3], transfer[4]])
      const result = await ingestSnapshot({
        store: db,
        tenantId: TENANT,
        client: second.client,
      })

      expect(result).toEqual({ cursor: 42, schema_version: 7 })
      expect(second.paths[0]).toBe('/snapshot?page=PAGE-2')

      // All four tables fully populated — no rows lost, none duplicated.
      const [[assets]] = await rows(db, 'SELECT count(*) FROM assets')
      const [[afv]] = await rows(db, 'SELECT count(*) FROM asset_field_values')
      const [[mr]] = await rows(db, 'SELECT count(*) FROM maintenance_records')
      const [[mrfv]] = await rows(
        db,
        'SELECT count(*) FROM maintenance_record_field_values',
      )
      expect([assets, afv, mr, mrfv]).toEqual([2, 1, 1, 1])
    })
  })

  describe('invalidated snapshot', () => {
    it('restarts from scratch when a batch reports a new schema_version', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
    await seedSchema(db)

      // Batch 1 at v7 seeds ASSET_A. Batch 2 reports v8 — the snapshot the
      // client started under is invalidated, so the partial ASSET_A is
      // discarded and the transfer restarts (page null). The restarted
      // transfer is a clean v8 run that ends on a terminal batch.
      const batchV7 = fullTransfer(7)[0]
      const restartedV8 = fullTransfer(8)
      const { client, paths } = scriptedClient([
        batchV7, // page PAGE-1, v7 — seeds ASSET_A
        {
          schema_version: 8,
          page: 'PAGE-X',
          cursor: null,
          body: { table: 'assets', items: [] },
        },
        ...restartedV8, // the from-scratch v8 transfer
      ])

      const result = await ingestSnapshot({ store: db, tenantId: TENANT, client })

      expect(result).toEqual({ cursor: 42, schema_version: 8 })
      // After restart the projection holds exactly the v8 transfer's rows.
      const [[assetCount]] = await rows(db, 'SELECT count(*) FROM assets')
      expect(assetCount).toBe(2)
      // The restart re-fetched from the start (no page) after the v8 batch.
      expect(paths).toEqual([
        '/snapshot',
        '/snapshot?page=PAGE-1',
        '/snapshot',
        '/snapshot?page=PAGE-1',
        '/snapshot?page=PAGE-2',
        '/snapshot?page=PAGE-3',
        '/snapshot?page=PAGE-4',
      ])
    })

    it('detects invalidation across a reload (persisted token version mismatch)', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
    await seedSchema(db)
      const transfer = fullTransfer(7)

      // First attempt under v7: batch 1 then error, leaving PAGE-1 + v7.
      const first = scriptedClient([
        transfer[0],
        () => {
          throw new Error('network down')
        },
      ])
      await expect(
        ingestSnapshot({ store: db, tenantId: TENANT, client: first.client }),
      ).rejects.toThrow('network down')

      // Resume after a "reload": the server has advanced to v8. The resumed
      // fetch (with the persisted PAGE-1) reports v8 ≠ persisted v7, so the
      // ingest restarts from scratch under v8.
      const second = scriptedClient([
        {
          schema_version: 8,
          page: 'PAGE-1',
          cursor: null,
          body: { table: 'assets', items: [] },
        },
        ...fullTransfer(8),
      ])
      const result = await ingestSnapshot({
        store: db,
        tenantId: TENANT,
        client: second.client,
      })

      expect(result).toEqual({ cursor: 42, schema_version: 8 })
      // First fetch of the resume used the persisted token; restart then
      // re-requested from the start.
      expect(second.paths[0]).toBe('/snapshot?page=PAGE-1')
      expect(second.paths[1]).toBe('/snapshot')
    })
  })
})
