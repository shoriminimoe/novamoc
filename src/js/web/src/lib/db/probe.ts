/**
 * Startup feature probe for SQLite-WASM over OPFS (ADR-003).
 *
 * novaMOC is local-first: the client stores its full tenant dataset in
 * SQLite-WASM persisted to the Origin Private File System. The OPFS VFS
 * shipped by `@sqlite.org/sqlite-wasm` requires `FileSystemSyncAccessHandle`
 * (Chrome 109+, Safari 17+, Firefox best-effort) AND cross-origin isolation
 * (for SharedArrayBuffer).
 *
 * Per ADR-003 §Consequences, browsers missing any precondition MUST get a
 * blocking error rather than a silent in-memory fallback (which would lose
 * data on tab close). This module exposes the probe; the layout consumes it
 * and routes to the blocking error page on failure.
 *
 * It's a feature test, not UA sniffing — capability is what matters and UA
 * strings are unreliable.
 */

import { checkSyncAccessHandle } from './probe.sync-handle'

/** The three failure modes the probe can report. */
export type MissingFeature = 'opfs' | 'sync_handle' | 'cross_origin_isolation'

/** Result of one probe run. */
export type ProbeResult = { ok: true } | { ok: false; missing: MissingFeature }

/**
 * Probe the runtime for SQLite-WASM-over-OPFS support.
 *
 * Checks, in order:
 * 1. `navigator.storage.getDirectory` exists (OPFS root accessible).
 * 2. `crossOriginIsolated === true` (SharedArrayBuffer prerequisite, served
 *    via COOP/COEP — see `vite.config.ts`).
 * 3. A worker can actually acquire a sync access handle. The interface is
 *    `[Exposed=DedicatedWorker]`, so this is the only reliable detection —
 *    inspecting prototypes on the main thread false-negatives in every
 *    supporting browser. See `./probe.sync-handle`.
 *
 * Returns on the first failure; the caller branches on `missing` to tell the
 * user what they're missing. The worker probe runs last because it's the
 * only async/expensive check.
 */
export async function probeOpfs(): Promise<ProbeResult> {
  if (
    typeof navigator === 'undefined' ||
    !('storage' in navigator) ||
    !navigator.storage ||
    typeof navigator.storage.getDirectory !== 'function'
  ) {
    return { ok: false, missing: 'opfs' }
  }

  if (globalThis.crossOriginIsolated !== true) {
    return { ok: false, missing: 'cross_origin_isolation' }
  }

  if (!(await checkSyncAccessHandle())) {
    return { ok: false, missing: 'sync_handle' }
  }

  return { ok: true }
}
