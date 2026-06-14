/**
 * Shared fixtures for the repository component tests.
 *
 * Every test runs against a real in-memory SQLite-WASM DB (no mocks), matching
 * the server-side discipline. `openLocalDb(..., { memory: true })` gives a
 * fully-migrated schema on the main thread; the repo set is bound to it via
 * `withTenant`. Schema-projection and event-log tables have no repo write path,
 * so tests seed them with direct `exec` against the same handle.
 */
import { _resetLocalDbsForTest, openLocalDb } from '../../../src/lib/db/bootstrap'
import type { DbHandle } from '../../../src/lib/db/bootstrap'
import { withTenant } from '../../../src/lib/db/repo'

export const TENANT_A = '00000000-0000-0000-0000-00000000000a'
export const TENANT_B = '00000000-0000-0000-0000-00000000000b'

export const HLC_1 = '2026-06-01T00:00:00.000Z-0000-node'
export const HLC_2 = '2026-06-01T00:00:01.000Z-0000-node'

export async function freshDb(tenantId: string): Promise<DbHandle> {
  return openLocalDb(tenantId, { memory: true })
}

export function resetDbs(): Promise<void> {
  return _resetLocalDbsForTest()
}

export { withTenant }

/**
 * Seed the schema projection rows a data-projection FK needs. The DDL turns on
 * `PRAGMA foreign_keys`, so an asset insert fails without its `asset_types`
 * parent row present.
 */
export async function seedAssetType(
  db: DbHandle,
  tenantId: string,
  typeId: string,
  name = 'Pump',
): Promise<void> {
  await db.exec(
    'INSERT INTO asset_types (tenant_id, id, name, active) VALUES (?, ?, ?, 1)',
    [tenantId, typeId, name],
  )
}

export async function seedRecordType(
  db: DbHandle,
  tenantId: string,
  typeId: string,
  name = 'Inspection',
): Promise<void> {
  await db.exec(
    'INSERT INTO maintenance_record_types (tenant_id, id, name, active) VALUES (?, ?, ?, 1)',
    [tenantId, typeId, name],
  )
}
