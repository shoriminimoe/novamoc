/**
 * Unit tests for ``probeOpfs`` — the startup feature probe that gates
 * the SPA on browsers capable of running SQLite-WASM over OPFS with
 * ``FileSystemSyncAccessHandle`` (ADR-003). The probe MUST fail closed
 * — if any of OPFS / sync-access-handle / cross-origin isolation is
 * unavailable, the layout routes to a blocking error page rather than
 * silently falling back to an in-memory DB.
 *
 * The tests stub the relevant globals (``navigator.storage``,
 * ``crossOriginIsolated``) directly on ``globalThis`` because the probe
 * reads them by name; jsdom ships none of them.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { probeOpfs } from '../../src/lib/db/probe'

type MutableGlobal = typeof globalThis & {
  navigator: Navigator
  crossOriginIsolated?: boolean
}

const g = globalThis as MutableGlobal

// We mutate ``navigator`` and ``crossOriginIsolated`` per-test, so capture
// the originals up front and restore them after each test rather than
// relying on jsdom's default reset.
const originalNavigator = g.navigator
const originalCrossOriginIsolated = Object.getOwnPropertyDescriptor(
  g,
  'crossOriginIsolated',
)

function setNavigator(nav: Partial<Navigator>): void {
  Object.defineProperty(g, 'navigator', {
    value: nav,
    configurable: true,
    writable: true,
  })
}

function setCrossOriginIsolated(value: boolean): void {
  Object.defineProperty(g, 'crossOriginIsolated', {
    value,
    configurable: true,
    writable: true,
  })
}

/**
 * Build a fake ``navigator.storage`` whose root directory's prototype
 * has (or lacks) ``FileSystemSyncAccessHandle``. The probe inspects the
 * directory handle's constructor prototype to decide whether the sync
 * variant is supported.
 */
function fakeStorage(syncHandleSupported: boolean): { getDirectory: () => Promise<unknown> } {
  // Build a prototype with or without the sync-handle marker. The probe
  // checks ``'FileSystemSyncAccessHandle' in <root>.constructor.prototype``;
  // wiring the marker onto the constructor's prototype mirrors how a real
  // ``FileSystemDirectoryHandle`` would expose ``createSyncAccessHandle``.
  function Dir(this: unknown): void {}
  if (syncHandleSupported) {
    ;(Dir.prototype as Record<string, unknown>).FileSystemSyncAccessHandle =
      function () {}
  }
  const root = Object.create(Dir.prototype as object) as object
  return {
    getDirectory: () => Promise.resolve(root),
  }
}

afterEach(() => {
  Object.defineProperty(g, 'navigator', {
    value: originalNavigator,
    configurable: true,
    writable: true,
  })
  if (originalCrossOriginIsolated) {
    Object.defineProperty(g, 'crossOriginIsolated', originalCrossOriginIsolated)
  } else {
    delete (g as Record<string, unknown>).crossOriginIsolated
  }
})

describe('probeOpfs', () => {
  describe('OPFS missing', () => {
    it('fails with missing="opfs" when navigator has no storage', async () => {
      setNavigator({} as Navigator)
      setCrossOriginIsolated(true)

      const result = await probeOpfs()
      expect(result).toEqual({ ok: false, missing: 'opfs' })
    })

    it('fails with missing="opfs" when navigator.storage lacks getDirectory', async () => {
      setNavigator({ storage: {} as StorageManager } as Navigator)
      setCrossOriginIsolated(true)

      const result = await probeOpfs()
      expect(result).toEqual({ ok: false, missing: 'opfs' })
    })
  })

  describe('sync access handle missing', () => {
    it('fails with missing="sync_handle" when the directory prototype lacks FileSystemSyncAccessHandle', async () => {
      setNavigator({
        storage: fakeStorage(false) as unknown as StorageManager,
      } as Navigator)
      setCrossOriginIsolated(true)

      const result = await probeOpfs()
      expect(result).toEqual({ ok: false, missing: 'sync_handle' })
    })
  })

  describe('cross-origin isolation missing', () => {
    it('fails with missing="cross_origin_isolation" when crossOriginIsolated is false', async () => {
      setNavigator({
        storage: fakeStorage(true) as unknown as StorageManager,
      } as Navigator)
      setCrossOriginIsolated(false)

      const result = await probeOpfs()
      expect(result).toEqual({ ok: false, missing: 'cross_origin_isolation' })
    })

    it('fails with missing="cross_origin_isolation" when crossOriginIsolated is undefined', async () => {
      setNavigator({
        storage: fakeStorage(true) as unknown as StorageManager,
      } as Navigator)
      // Explicitly delete the global so the probe sees ``undefined``.
      delete (g as Record<string, unknown>).crossOriginIsolated

      const result = await probeOpfs()
      expect(result).toEqual({ ok: false, missing: 'cross_origin_isolation' })
    })
  })

  describe('success', () => {
    it('returns ok=true when all three preconditions are met', async () => {
      setNavigator({
        storage: fakeStorage(true) as unknown as StorageManager,
      } as Navigator)
      setCrossOriginIsolated(true)

      const result = await probeOpfs()
      expect(result).toEqual({ ok: true })
    })
  })
})
