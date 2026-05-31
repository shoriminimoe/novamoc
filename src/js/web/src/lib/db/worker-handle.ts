/**
 * Main-thread client for the SQLite-WASM DB worker (ADR-003).
 *
 * Spawns ``./worker`` (which owns the OPFS-backed database — see that file
 * for why OPFS must live in a worker) and exposes it as an async
 * {@link DbHandle}: each ``exec`` is a request/response round-trip over
 * ``postMessage``. The ``ready`` reply resolves the open; per-call ids
 * correlate ``result`` / ``error`` replies back to their callers.
 *
 * Browser-worker-only: not reachable under jsdom, so it's excluded from
 * unit coverage and exercised by ``tests/e2e/db-bootstrap.spec.ts`` instead.
 */

import type { DbHandle, Row } from './bootstrap'
import type { DbWorkerMessage, DbWorkerRequest } from './worker'

/** Spawn the DB worker for ``path`` and resolve once its DDL has applied. */
export function openWorkerDb(path: string): Promise<DbHandle> {
  const worker = new Worker(new URL('./worker.ts', import.meta.url), {
    type: 'module',
  })

  let nextId = 0
  const pending = new Map<
    number,
    { resolve: (rows: Row[]) => void; reject: (error: Error) => void }
  >()

  return new Promise<DbHandle>((resolveReady, rejectReady) => {
    const handle: DbHandle = {
      exec(sql, bind) {
        return new Promise<Row[]>((resolve, reject) => {
          const id = nextId++
          pending.set(id, { resolve, reject })
          const request: DbWorkerRequest = { kind: 'exec', id, sql, bind }
          worker.postMessage(request)
        })
      },
      close() {
        worker.terminate()
        return Promise.resolve()
      },
    }

    worker.onmessage = (event: MessageEvent<DbWorkerMessage>): void => {
      const message = event.data

      if (message.kind === 'ready') {
        resolveReady(handle)
        return
      }
      if (message.kind === 'result') {
        pending.get(message.id)?.resolve(message.rows as Row[])
        pending.delete(message.id)
        return
      }
      // kind === 'error'
      const error = new Error(message.message)
      if (message.id === undefined) {
        rejectReady(error)
        return
      }
      pending.get(message.id)?.reject(error)
      pending.delete(message.id)
    }

    worker.onerror = (event): void => {
      rejectReady(new Error(event.message))
    }

    const open: DbWorkerRequest = { kind: 'open', path }
    worker.postMessage(open)
  })
}
