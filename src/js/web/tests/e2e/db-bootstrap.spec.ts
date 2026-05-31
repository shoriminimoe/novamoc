/**
 * Real-browser e2e for the SQLite-WASM OPFS bootstrap (ADR-003).
 *
 * Persistent OPFS storage can only run in a worker:
 * ``FileSystemSyncAccessHandle`` is ``[Exposed=DedicatedWorker]`` (absent
 * on the main thread in every supporting browser) and the "opfs" VFS uses
 * ``Atomics.wait`` (illegal on the main thread). Neither exists under
 * vitest/jsdom, so this spec is the only place the OPFS path runs. It opens
 * the worker-backed DB through the real ``openLocalDb``, asserts every
 * table exists, foreign keys are on, the schema is stamped, and a second
 * ``openLocalDb`` for the same tenant returns the same handle.
 *
 * No WAL assertion: no OPFS VFS in sqlite-wasm supports WAL — the "opfs"
 * VFS reports ``journal_mode = delete``. Durability comes from the
 * synchronous access handles, not WAL (see ``src/lib/db/worker.ts``). We
 * assert the actual rollback-journal mode instead.
 *
 * The harness serves the SPA cross-origin-isolated over loopback HTTP (see
 * ``playwright.config.ts``), so the OPFS preconditions hold. We drive
 * ``openLocalDb`` by importing it through Vite's dev server in the page
 * context.
 */

import { expect, test } from '@playwright/test'

import { SCHEMA_VERSION } from '../../src/lib/db/migrations'

const EXPECTED_TABLES = [
  'asset_field_values',
  'asset_type_fields',
  'asset_types',
  'assets',
  'event_log',
  'local_pending_events',
  'maintenance_record_field_values',
  'maintenance_record_type_fields',
  'maintenance_record_types',
  'maintenance_records',
  'schema_change_log',
  'sync_state',
]

test('opens an OPFS-backed DB, applies the DDL, and is idempotent', async ({
  page,
}) => {
  // Land on a real app route so the page is in the SPA's module graph and
  // cross-origin isolation is in effect before we import the module.
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  expect(await page.evaluate(() => globalThis.crossOriginIsolated)).toBe(true)

  const result = await page.evaluate(async (modulePath: string) => {
    // The module is loaded through Vite's dev server in the page context;
    // the path is a runtime URL, not a build-time import, so it's passed in
    // rather than written as an import literal tsc would try to resolve.
    const { openLocalDb } = (await import(/* @vite-ignore */ modulePath)) as {
      openLocalDb: (
        tenantId: string,
      ) => Promise<{ exec: (sql: string) => Promise<unknown[][]> }>
    }

    // Unique per run so a re-run doesn't collide with a prior OPFS file.
    const tenantId = `e2e-${crypto.randomUUID()}`
    const db = await openLocalDb(tenantId)

    const scalar = async (sql: string): Promise<unknown> =>
      (await db.exec(sql))[0][0]

    const tables = (
      await db.exec(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
      )
    ).map((row) => row[0])

    const again = await openLocalDb(tenantId)

    return {
      tables,
      journalMode: await scalar('PRAGMA journal_mode'),
      foreignKeys: await scalar('PRAGMA foreign_keys'),
      userVersion: await scalar('PRAGMA user_version'),
      syncStateRows: await scalar('SELECT count(*) FROM sync_state'),
      idempotent: again === db,
    }
  }, '/src/lib/db/bootstrap.ts')

  expect(result.tables).toEqual(EXPECTED_TABLES)
  expect(result.journalMode).toBe('delete')
  expect(result.foreignKeys).toBe(1)
  expect(result.userVersion).toBe(SCHEMA_VERSION)
  expect(result.syncStateRows).toBe(1)
  expect(result.idempotent).toBe(true)
})
