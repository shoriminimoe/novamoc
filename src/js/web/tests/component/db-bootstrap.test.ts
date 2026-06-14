/**
 * Bootstrap tests for the local SQLite-WASM DB (ADR-003).
 *
 * Runs against an in-memory (non-OPFS, main-thread) database. Persistent
 * OPFS storage can only run in a worker — ``FileSystemSyncAccessHandle`` is
 * ``[Exposed=DedicatedWorker]`` and the "opfs" VFS uses ``Atomics.wait``,
 * both illegal on the main thread — so the OPFS path is covered by
 * ``tests/e2e/db-bootstrap.spec.ts`` in a real browser. Here we prove the
 * DDL applies, foreign keys are on, the schema is stamped, and a second
 * ``openLocalDb`` for the same tenant returns the same handle.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { SCHEMA_VERSION } from '../../src/lib/db/migrations'
import { _resetLocalDbsForTest, openLocalDb } from '../../src/lib/db/bootstrap'

const TENANT_A = '00000000-0000-0000-0000-00000000000a'
const TENANT_B = '00000000-0000-0000-0000-00000000000b'

const EXPECTED_TABLES = [
  'assets',
  'asset_field_values',
  'maintenance_records',
  'maintenance_record_field_values',
  'asset_types',
  'asset_type_fields',
  'maintenance_record_types',
  'maintenance_record_type_fields',
  'schema_change_log',
  'event_log',
  'local_pending_events',
  'pending_schema_buffer',
  'sync_state',
].sort()

async function tableNames(
  db: Awaited<ReturnType<typeof openLocalDb>>,
): Promise<string[]> {
  const rows = await db.exec(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
  )
  return rows.map((row) => row[0] as string)
}

async function scalar(
  db: Awaited<ReturnType<typeof openLocalDb>>,
  sql: string,
): Promise<unknown> {
  const rows = await db.exec(sql)
  return rows[0][0]
}

afterEach(async () => {
  await _resetLocalDbsForTest()
})

describe('openLocalDb', () => {
  it('applies the full DDL on a fresh open', async () => {
    const db = await openLocalDb(TENANT_A, { memory: true })

    expect(await tableNames(db)).toEqual(EXPECTED_TABLES)
  })

  it('turns foreign keys on', async () => {
    const db = await openLocalDb(TENANT_A, { memory: true })

    expect(await scalar(db, 'PRAGMA foreign_keys')).toBe(1)
  })

  it('stamps the schema version via PRAGMA user_version', async () => {
    const db = await openLocalDb(TENANT_A, { memory: true })

    expect(await scalar(db, 'PRAGMA user_version')).toBe(SCHEMA_VERSION)
  })

  it('seeds a single sync_state row', async () => {
    const db = await openLocalDb(TENANT_A, { memory: true })

    expect(await scalar(db, 'SELECT count(*) FROM sync_state')).toBe(1)
  })

  it('returns the same handle on a repeat open for the same tenant', async () => {
    const first = await openLocalDb(TENANT_A, { memory: true })
    const second = await openLocalDb(TENANT_A, { memory: true })

    expect(second).toBe(first)
  })

  it('keeps separate handles per tenant', async () => {
    const a = await openLocalDb(TENANT_A, { memory: true })
    const b = await openLocalDb(TENANT_B, { memory: true })

    expect(b).not.toBe(a)
  })
})
