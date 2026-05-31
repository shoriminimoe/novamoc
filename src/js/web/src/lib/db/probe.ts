/**
 * Startup feature probe for SQLite-WASM over OPFS (ADR-003).
 *
 * novaMOC is local-first: the client stores its full tenant dataset in
 * SQLite-WASM persisted to the Origin Private File System. The OPFS
 * VFS shipped by ``@sqlite.org/sqlite-wasm`` requires
 * ``FileSystemSyncAccessHandle`` (Chrome 109+, Safari 17+, Firefox
 * best-effort) AND cross-origin isolation (for SharedArrayBuffer).
 *
 * Per ADR-003 §Consequences, browsers missing any of those
 * preconditions MUST get a blocking error rather than a silent
 * in-memory fallback (which would lose data on tab close). This
 * module exposes the probe; the layout consumes it and routes to the
 * blocking error page on failure.
 *
 * The probe is intentionally a feature test, not UA sniffing — capability
 * is what we actually care about, and UA strings are unreliable.
 */

/** The three failure modes the probe can report. */
export type MissingFeature = 'opfs' | 'sync_handle' | 'cross_origin_isolation'

/** Result of one probe run. */
export type ProbeResult = { ok: true } | { ok: false; missing: MissingFeature }

/**
 * Probe the runtime for SQLite-WASM-over-OPFS support.
 *
 * Checks, in order:
 * 1. ``navigator.storage.getDirectory`` exists (OPFS root accessible).
 * 2. The root directory's prototype exposes
 *    ``FileSystemSyncAccessHandle`` (sync access handle support).
 * 3. ``crossOriginIsolated === true`` (SharedArrayBuffer prerequisite,
 *    served via COOP/COEP headers — see ``vite.config.ts``).
 *
 * Returns on the first failure; the caller branches on ``missing`` to
 * tell the user *what* they're missing.
 */
export async function probeOpfs(): Promise<ProbeResult> {
  // 1. OPFS root accessible at all?
  if (
    typeof navigator === 'undefined' ||
    !('storage' in navigator) ||
    !navigator.storage ||
    typeof (navigator.storage as StorageManager).getDirectory !== 'function'
  ) {
    return { ok: false, missing: 'opfs' }
  }

  // 2. ``FileSystemSyncAccessHandle`` available? We probe the directory
  // handle's constructor prototype — that's where the sync-handle
  // creator lives. ``createSyncAccessHandle`` would be the real method
  // name, but the issue spec checks for the type name on the prototype;
  // we honour the spec and tolerate either.
  let root: FileSystemDirectoryHandle
  try {
    root = await navigator.storage.getDirectory()
  } catch {
    return { ok: false, missing: 'opfs' }
  }
  const proto = (root as unknown as { constructor: { prototype: object } })
    .constructor.prototype
  const hasSyncHandle =
    'FileSystemSyncAccessHandle' in proto ||
    'createSyncAccessHandle' in proto
  if (!hasSyncHandle) {
    return { ok: false, missing: 'sync_handle' }
  }

  // 3. Cross-origin isolated? Required for SharedArrayBuffer.
  if (
    typeof (globalThis as { crossOriginIsolated?: boolean })
      .crossOriginIsolated !== 'boolean' ||
    (globalThis as { crossOriginIsolated: boolean }).crossOriginIsolated !== true
  ) {
    return { ok: false, missing: 'cross_origin_isolation' }
  }

  return { ok: true }
}
