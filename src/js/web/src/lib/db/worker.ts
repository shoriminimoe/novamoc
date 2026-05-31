/**
 * Dedicated SQLite-WASM worker for the OPFS-backed local store (ADR-003).
 *
 * The OPFS VFS can only run in a worker: ``FileSystemSyncAccessHandle`` is
 * ``[Exposed=DedicatedWorker]`` (absent on the main thread in every
 * supporting browser) and the "opfs" VFS uses ``Atomics.wait`` (illegal on
 * the main thread). So the database lives here and the main thread talks to
 * it over a request/response protocol (``./bootstrap`` is the client).
 *
 * The library's ``Worker1Promiser`` would give us this for free but was
 * deprecated 2026-04-15, so we run the OO1 ``OpfsDb`` directly and keep a
 * tiny protocol of our own.
 *
 * One worker owns one DB for one tenant's file. Pragmas, DDL, and the
 * ``user_version`` migration all run synchronously here on open (the OO1
 * ``exec`` is synchronous inside the worker), before the ``ready`` reply.
 *
 * Note on WAL: no OPFS VFS in sqlite-wasm supports WAL — both the "opfs"
 * VFS and the SAH-pool VFS report ``journal_mode = delete``. Durability
 * comes from the synchronous access handles, not WAL. ADR-003's "enable
 * WAL" line predates this constraint; we apply the default rollback
 * journal and surface the real mode rather than a no-op pragma.
 */

import sqlite3InitModule from '@sqlite.org/sqlite-wasm'
import type { Database, Sqlite3Static } from '@sqlite.org/sqlite-wasm'

import { migrate } from './migrations'

export interface DbWorkerOpenRequest {
  kind: 'open'
  path: string
}

export interface DbWorkerExecRequest {
  kind: 'exec'
  id: number
  sql: string
  bind?: unknown[]
}

export type DbWorkerRequest = DbWorkerOpenRequest | DbWorkerExecRequest

export interface DbWorkerReadyMessage {
  kind: 'ready'
}

export interface DbWorkerErrorMessage {
  kind: 'error'
  id?: number
  message: string
}

export interface DbWorkerResultMessage {
  kind: 'result'
  id: number
  rows: unknown[][]
}

export type DbWorkerMessage =
  | DbWorkerReadyMessage
  | DbWorkerErrorMessage
  | DbWorkerResultMessage

let sqlite3: Sqlite3Static | undefined
let db: Database | undefined

async function openDb(path: string): Promise<void> {
  sqlite3 ??= await sqlite3InitModule()

  // file: URI with an explicit vfs so the "opfs" VFS is used regardless of
  // the default. The OPFS VFS creates the directory parts of the path, so
  // the per-tenant directory keys each tenant's file apart.
  db = new sqlite3.oo1.DB(`file:${path}?vfs=opfs`, 'c')
  db.exec('PRAGMA foreign_keys = ON')
  migrate(db)
}

function exec(sql: string, bind?: unknown[]): unknown[][] {
  if (!db) {
    throw new Error('exec before open')
  }
  return db.exec({
    sql,
    bind: bind as never,
    returnValue: 'resultRows',
    rowMode: 'array',
  }) as unknown[][]
}

function post(message: DbWorkerMessage): void {
  ;(self as unknown as Worker).postMessage(message)
}

self.onmessage = (event: MessageEvent<DbWorkerRequest>): void => {
  const request = event.data

  if (request.kind === 'open') {
    openDb(request.path).then(
      () => post({ kind: 'ready' }),
      (error: unknown) => post({ kind: 'error', message: String(error) }),
    )
    return
  }

  try {
    post({ kind: 'result', id: request.id, rows: exec(request.sql, request.bind) })
  } catch (error) {
    post({ kind: 'error', id: request.id, message: String(error) })
  }
}
