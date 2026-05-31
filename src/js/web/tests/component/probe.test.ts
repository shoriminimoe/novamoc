/**
 * Unit tests for `probeOpfs` orchestration (ADR-003). The probe must fail
 * closed — if OPFS, cross-origin isolation, or the sync access handle is
 * unavailable, the layout routes to a blocking error page rather than
 * silently falling back to an in-memory DB.
 *
 * The sync-handle check is genuinely only observable in a DedicatedWorker
 * (the interface is `[Exposed=DedicatedWorker]`), so it can't be exercised
 * in jsdom. Here we mock that boundary (`./probe.sync-handle`) to drive the
 * orchestration deterministically; the real worker path is covered by the
 * Playwright e2e (api-smoke proves the happy path in a real browser).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { checkSyncAccessHandle } = vi.hoisted(() => ({
  checkSyncAccessHandle: vi.fn<() => Promise<boolean>>(),
}))
vi.mock('../../src/lib/db/probe.sync-handle', () => ({ checkSyncAccessHandle }))

import { probeOpfs } from '../../src/lib/db/probe'

type MutableGlobal = typeof globalThis & {
  navigator: Navigator
  crossOriginIsolated?: boolean
}

const g = globalThis as MutableGlobal

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

/** A navigator whose OPFS root is reachable (getDirectory is callable). */
function navigatorWithOpfs(): Navigator {
  return {
    storage: { getDirectory: () => Promise.resolve({}) } as unknown as StorageManager,
  } as Navigator
}

beforeEach(() => {
  checkSyncAccessHandle.mockReset()
})

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
    it('fails with missing="opfs" when navigator is undefined', async () => {
      delete (g as Record<string, unknown>).navigator
      setCrossOriginIsolated(true)

      expect(await probeOpfs()).toEqual({ ok: false, missing: 'opfs' })
      expect(checkSyncAccessHandle).not.toHaveBeenCalled()
    })

    it('fails with missing="opfs" when navigator has no storage', async () => {
      setNavigator({} as Navigator)
      setCrossOriginIsolated(true)

      expect(await probeOpfs()).toEqual({ ok: false, missing: 'opfs' })
      expect(checkSyncAccessHandle).not.toHaveBeenCalled()
    })

    it('fails with missing="opfs" when navigator.storage lacks getDirectory', async () => {
      setNavigator({ storage: {} as StorageManager } as Navigator)
      setCrossOriginIsolated(true)

      expect(await probeOpfs()).toEqual({ ok: false, missing: 'opfs' })
      expect(checkSyncAccessHandle).not.toHaveBeenCalled()
    })
  })

  describe('cross-origin isolation missing', () => {
    it('fails with missing="cross_origin_isolation" when crossOriginIsolated is false', async () => {
      setNavigator(navigatorWithOpfs())
      setCrossOriginIsolated(false)

      expect(await probeOpfs()).toEqual({
        ok: false,
        missing: 'cross_origin_isolation',
      })
      // No point spawning the worker if SharedArrayBuffer is unavailable.
      expect(checkSyncAccessHandle).not.toHaveBeenCalled()
    })

    it('fails with missing="cross_origin_isolation" when crossOriginIsolated is undefined', async () => {
      setNavigator(navigatorWithOpfs())
      delete (g as Record<string, unknown>).crossOriginIsolated

      expect(await probeOpfs()).toEqual({
        ok: false,
        missing: 'cross_origin_isolation',
      })
      expect(checkSyncAccessHandle).not.toHaveBeenCalled()
    })
  })

  describe('sync access handle missing', () => {
    it('fails with missing="sync_handle" when the worker cannot acquire one', async () => {
      setNavigator(navigatorWithOpfs())
      setCrossOriginIsolated(true)
      checkSyncAccessHandle.mockResolvedValue(false)

      expect(await probeOpfs()).toEqual({ ok: false, missing: 'sync_handle' })
      expect(checkSyncAccessHandle).toHaveBeenCalledOnce()
    })
  })

  describe('success', () => {
    it('returns ok=true when all three preconditions are met', async () => {
      setNavigator(navigatorWithOpfs())
      setCrossOriginIsolated(true)
      checkSyncAccessHandle.mockResolvedValue(true)

      expect(await probeOpfs()).toEqual({ ok: true })
    })
  })
})
