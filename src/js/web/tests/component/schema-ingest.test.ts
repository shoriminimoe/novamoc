/**
 * Schema-projection ingest + version-gating tests (ADR-008 / ADR-009).
 *
 * Runs against the real in-memory SQLite-WASM DB from `openLocalDb` — no DB
 * mocks, matching the project's db-test discipline — so reconcile, the
 * monotonic version write, and the buffer release exercise actual SQL. Only
 * the HTTP boundary is mocked: a fake `ApiClient` returns canned
 * `GET /schema` responses.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { _resetLocalDbsForTest, openLocalDb } from '../../src/lib/db/bootstrap'
import type { ApiClient } from '../../src/lib/api'
import type { SchemaSnapshot } from '../../src/lib/schema'
import {
  type BufferableEvent,
  activeSchemaVersion,
  bufferEvent,
  bufferedEventCount,
  gateEvent,
  refreshSchema,
} from '../../src/lib/sync/schema'

const TENANT = '00000000-0000-0000-0000-0000000005ce'

const TRUCK = '11111111-1111-1111-1111-111111111111'
const VIN = '22222222-2222-2222-2222-222222222222'
const COLOR = '33333333-3333-3333-3333-333333333333'
const INSPECTION = '44444444-4444-4444-4444-444444444444'
const NOTES = '55555555-5555-5555-5555-555555555555'

/** A canned `ApiClient` that returns a fixed `GET /schema` snapshot. */
function fakeClient(snapshot: SchemaSnapshot): ApiClient {
  return {
    get: <T>() => Promise.resolve(snapshot as T),
    post: <T>() => Promise.resolve(undefined as T),
  }
}

function snapshotV1(): SchemaSnapshot {
  return {
    schema_version: 1,
    asset_types: [
      {
        id: TRUCK,
        name: 'Truck',
        active: true,
        fields: [
          {
            id: VIN,
            name: 'VIN',
            data_type: 'text',
            validation: { max_length: 17 },
            active: true,
          },
        ],
      },
    ],
    maintenance_record_types: [],
  }
}

function snapshotV2(): SchemaSnapshot {
  return {
    schema_version: 2,
    asset_types: [
      {
        id: TRUCK,
        name: 'Truck',
        active: true,
        fields: [
          {
            id: VIN,
            name: 'VIN',
            data_type: 'text',
            validation: { max_length: 17 },
            active: true,
          },
          // The new field that v2 introduces — an event referencing it must
          // wait for this refresh before it can be applied.
          {
            id: COLOR,
            name: 'Color',
            data_type: 'text',
            validation: null,
            active: true,
          },
        ],
      },
    ],
    maintenance_record_types: [
      {
        id: INSPECTION,
        name: 'Inspection',
        active: true,
        fields: [
          {
            id: NOTES,
            name: 'Notes',
            data_type: 'text',
            validation: null,
            active: false,
          },
        ],
      },
    ],
  }
}

interface Store {
  exec(sql: string, bind?: unknown[]): Promise<unknown[][]>
}

async function rows(store: Store, sql: string, bind?: unknown[]) {
  return (await store.exec(sql, bind)) as unknown[][]
}

afterEach(async () => {
  await _resetLocalDbsForTest()
})

describe('gateEvent', () => {
  it("returns 'apply' when the event is at or below the active version", () => {
    expect(gateEvent({ schema_version: 1 }, 1)).toBe('apply')
    expect(gateEvent({ schema_version: 1 }, 2)).toBe('apply')
  })

  it("returns 'buffer' when the event is ahead of the active version", () => {
    expect(gateEvent({ schema_version: 2 }, 1)).toBe('buffer')
  })
})

describe('refreshSchema', () => {
  it('mirrors the wire response into the local schema tables', async () => {
    const db = await openLocalDb(TENANT, { memory: true })

    await refreshSchema({ store: db, tenantId: TENANT, client: fakeClient(snapshotV2()) })

    const types = await rows(db, 'SELECT id, name, active FROM asset_types ORDER BY id')
    expect(types).toEqual([[TRUCK, 'Truck', 1]])

    const fields = await rows(
      db,
      'SELECT id, parent_id, name, data_type, validation, active FROM asset_type_fields ORDER BY id',
    )
    expect(fields).toEqual([
      [VIN, TRUCK, 'VIN', 'text', JSON.stringify({ max_length: 17 }), 1],
      [COLOR, TRUCK, 'Color', 'text', null, 1],
    ])

    const mrTypes = await rows(
      db,
      'SELECT id, name, active FROM maintenance_record_types ORDER BY id',
    )
    expect(mrTypes).toEqual([[INSPECTION, 'Inspection', 1]])

    const mrFields = await rows(
      db,
      'SELECT id, parent_id, active FROM maintenance_record_type_fields ORDER BY id',
    )
    // Tombstoned fields are kept (active=0), per ADR-008/ADR-009.
    expect(mrFields).toEqual([[NOTES, INSPECTION, 0]])
  })

  it('sets the active schema version from the response', async () => {
    const db = await openLocalDb(TENANT, { memory: true })

    const result = await refreshSchema({
      store: db,
      tenantId: TENANT,
      client: fakeClient(snapshotV2()),
    })

    expect(result.activeVersion).toBe(2)
    expect(await activeSchemaVersion(db)).toBe(2)
  })

  it('is idempotent — a repeat refresh reproduces the same tables', async () => {
    const db = await openLocalDb(TENANT, { memory: true })

    await refreshSchema({ store: db, tenantId: TENANT, client: fakeClient(snapshotV2()) })
    const first = await rows(
      db,
      'SELECT id, parent_id, name, data_type, validation, active FROM asset_type_fields ORDER BY id',
    )

    await refreshSchema({ store: db, tenantId: TENANT, client: fakeClient(snapshotV2()) })
    const second = await rows(
      db,
      'SELECT id, parent_id, name, data_type, validation, active FROM asset_type_fields ORDER BY id',
    )

    expect(second).toEqual(first)
    const count = await rows(db, 'SELECT count(*) FROM asset_type_fields')
    expect(count[0][0]).toBe(2)
  })

  it('advances the active version monotonically — never backward', async () => {
    const db = await openLocalDb(TENANT, { memory: true })

    await refreshSchema({ store: db, tenantId: TENANT, client: fakeClient(snapshotV2()) })
    expect(await activeSchemaVersion(db)).toBe(2)

    // A stale read reporting v1 must not lower the gate threshold.
    const result = await refreshSchema({
      store: db,
      tenantId: TENANT,
      client: fakeClient(snapshotV1()),
    })

    expect(result.activeVersion).toBe(2)
    expect(await activeSchemaVersion(db)).toBe(2)
  })
})

describe('schema-version gating', () => {
  const futureEvent: BufferableEvent = {
    seq: 42,
    hlc: '0000000000000005-00000-client-a',
    schema_version: 2,
    family: 'asset',
    type_id: TRUCK,
    instance_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    body: { event: 'updated', values: { [COLOR]: 'red' } },
  }

  it('buffers an event ahead of the active version instead of applying it', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    await refreshSchema({ store: db, tenantId: TENANT, client: fakeClient(snapshotV1()) })

    const active = await activeSchemaVersion(db)
    expect(gateEvent(futureEvent, active)).toBe('buffer')

    await bufferEvent(db, TENANT, futureEvent)
    expect(await bufferedEventCount(db, TENANT)).toBe(1)
  })

  it('releases a buffered event once a refresh raises the version past it', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    await refreshSchema({ store: db, tenantId: TENANT, client: fakeClient(snapshotV1()) })
    await bufferEvent(db, TENANT, futureEvent)

    // v2 ingest knows the Color field and unblocks the parked event.
    const result = await refreshSchema({
      store: db,
      tenantId: TENANT,
      client: fakeClient(snapshotV2()),
    })

    expect(result.activeVersion).toBe(2)
    expect(result.released).toHaveLength(1)
    expect(result.released[0].seq).toBe(42)
    expect(result.released[0].body).toEqual({
      event: 'updated',
      values: { [COLOR]: 'red' },
    })
    // The buffer is drained — the handoff to the fold is complete.
    expect(await bufferedEventCount(db, TENANT)).toBe(0)
  })

  it('keeps an event buffered when the refresh still does not reach its version', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    await refreshSchema({ store: db, tenantId: TENANT, client: fakeClient(snapshotV1()) })

    const farFuture: BufferableEvent = { ...futureEvent, seq: 99, schema_version: 5 }
    await bufferEvent(db, TENANT, farFuture)

    // A v2 refresh does not reach schema_version 5 — the event stays parked.
    const result = await refreshSchema({
      store: db,
      tenantId: TENANT,
      client: fakeClient(snapshotV2()),
    })

    expect(result.released).toHaveLength(0)
    expect(await bufferedEventCount(db, TENANT)).toBe(1)
  })
})
