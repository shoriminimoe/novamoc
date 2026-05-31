/**
 * SQLite-WASM bootstrap for the local-first store (ADR-003).
 *
 * Opens (or creates) the per-tenant database, applies the connection
 * pragmas, and runs the DDL/migration to bring a fresh file up to the
 * current schema version. Hands back a {@link DbHandle} — the repository
 * façade (E1.9) builds typed methods on top of it; this issue just hands
 * back the open connection.
 *
 * The WASM module and OPFS VFS are static-imported (Epic 1 decision Q1):
 * no dynamic ``import()``, no UX-gated loading. Persistent OPFS storage can
 * only run in a worker — ``FileSystemSyncAccessHandle`` is
 * ``[Exposed=DedicatedWorker]`` and the "opfs" VFS uses ``Atomics.wait``,
 * both illegal on the main thread — so the OPFS database lives in
 * ``./worker`` and the handle proxies ``exec`` to it. Operations are
 * therefore async. The startup probe (``./probe``) gates unsupported
 * browsers before we get here, so a failed OPFS open is an unexpected
 * error, not a fallback path.
 *
 * Tests use the in-memory mode, which runs on the main thread (no worker,
 * no OPFS) but behind the same async {@link DbHandle} interface.
 *
 * Tenant isolation is by file: the OPFS path is keyed by ``tenantId`` so a
 * future multi-tenant-on-same-browser case is naturally separated. v1 keeps
 * one tenant open at a time. Calling ``openLocalDb`` twice for the same
 * tenant is idempotent — it returns the cached handle.
 */

import sqlite3InitModule from '@sqlite.org/sqlite-wasm'
import type { Database } from '@sqlite.org/sqlite-wasm'

import { migrate } from './migrations'
import { openWorkerDb } from './worker-handle'

/** A row of column values, in declared column order. */
export type Row = unknown[]

/**
 * The open local database. ``exec`` runs a single statement and returns its
 * result rows (empty for non-SELECT statements). Async because the OPFS
 * backend lives in a worker.
 */
export interface DbHandle {
  exec(sql: string, bind?: unknown[]): Promise<Row[]>
  close(): Promise<void>
}

export interface OpenLocalDbOptions {
  /**
   * Open an in-memory DB on the main thread instead of the OPFS-backed
   * worker. For tests only: OPFS needs a worker, and the in-memory DB drops
   * on close.
   */
  memory?: boolean
}

/**
 * OPFS file path for a tenant's DB. Slashes make the OPFS VFS create a
 * directory tree, keeping each tenant's file separate. The tenant id is a
 * UUID, so no escaping is needed.
 */
function dbPathFor(tenantId: string): string {
  return `/novamoc/${tenantId}/local.sqlite`
}

/** Main-thread in-memory handle, used by tests. Runs the DDL in-process. */
async function openMemory(): Promise<DbHandle> {
  const sqlite3 = await sqlite3InitModule()
  const db: Database = new sqlite3.oo1.DB(':memory:', 'c')
  db.exec('PRAGMA foreign_keys = ON')
  migrate(db)

  return {
    exec(sql, bind) {
      const rows = db.exec({
        sql,
        bind: bind as never,
        returnValue: 'resultRows',
        rowMode: 'array',
      }) as Row[]
      return Promise.resolve(rows)
    },
    close() {
      db.close()
      return Promise.resolve()
    },
  }
}

// Cache keyed by file path. The promise is cached, not the resolved handle,
// so concurrent first-opens share one in-flight init.
const handles = new Map<string, Promise<DbHandle>>()

/**
 * Open (or create) the local DB for ``tenantId`` and return its handle.
 *
 * Idempotent: repeated calls for the same tenant (and mode) resolve to the
 * same handle.
 */
export function openLocalDb(
  tenantId: string,
  options: OpenLocalDbOptions = {},
): Promise<DbHandle> {
  const memory = options.memory ?? false
  const path = memory ? `:memory:/${tenantId}` : dbPathFor(tenantId)

  const existing = handles.get(path)
  if (existing) {
    return existing
  }

  const opening = memory ? openMemory() : openWorkerDb(path)
  handles.set(path, opening)
  return opening
}

/**
 * Close all cached handles and clear the cache. Test-only — production has
 * no teardown path in v1 (the tab owns the connection for its lifetime).
 */
export async function _resetLocalDbsForTest(): Promise<void> {
  for (const opening of handles.values()) {
    try {
      await (await opening).close()
    } catch {
      // A handle that failed to open has nothing to close.
    }
  }
  handles.clear()
}
