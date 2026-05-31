/**
 * Unit tests for the main-thread worker driver `checkSyncAccessHandle`.
 *
 * The worker itself does real OPFS I/O and only runs in a browser (covered
 * by the Playwright e2e). Here we stub the `Worker` global to drive the
 * driver's message/error/timeout handling deterministically.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { checkSyncAccessHandle } from '../../src/lib/db/probe.sync-handle'

type Behavior = 'ok' | 'fail' | 'error' | 'silent' | 'nodata'

// The driver constructs the worker internally, so the test can't pass
// per-instance config — behavior is set externally before each call and
// reset in beforeEach. Safe because vitest runs a file's tests serially.
class FakeWorker {
  onmessage: ((e: { data: unknown }) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  static behavior: Behavior = 'ok'
  static terminated = 0
  postMessage(): void {
    queueMicrotask(() => {
      if (FakeWorker.behavior === 'ok') this.onmessage?.({ data: { ok: true } })
      else if (FakeWorker.behavior === 'fail') this.onmessage?.({ data: { ok: false } })
      else if (FakeWorker.behavior === 'nodata') this.onmessage?.({ data: undefined })
      else if (FakeWorker.behavior === 'error') this.onerror?.(new Error('boom'))
      // 'silent': never responds — exercises the timeout path.
    })
  }
  terminate(): void {
    FakeWorker.terminated += 1
  }
}

const g = globalThis as typeof globalThis & { Worker?: unknown }
const originalWorker = Object.getOwnPropertyDescriptor(g, 'Worker')

beforeEach(() => {
  FakeWorker.behavior = 'ok'
  FakeWorker.terminated = 0
  Object.defineProperty(g, 'Worker', { value: FakeWorker, configurable: true, writable: true })
})

afterEach(() => {
  if (originalWorker) Object.defineProperty(g, 'Worker', originalWorker)
  else delete (g as Record<string, unknown>).Worker
  vi.useRealTimers()
})

describe('checkSyncAccessHandle', () => {
  it('returns false when Worker is unavailable', async () => {
    delete (g as Record<string, unknown>).Worker
    expect(await checkSyncAccessHandle()).toBe(false)
  })

  it('returns false when the Worker constructor throws', async () => {
    Object.defineProperty(g, 'Worker', {
      value: class {
        constructor() {
          throw new Error('worker construction failed')
        }
      },
      configurable: true,
      writable: true,
    })
    expect(await checkSyncAccessHandle()).toBe(false)
  })

  it('returns true when the worker reports ok', async () => {
    FakeWorker.behavior = 'ok'
    expect(await checkSyncAccessHandle()).toBe(true)
    expect(FakeWorker.terminated).toBe(1)
  })

  it('returns false when the worker reports failure', async () => {
    FakeWorker.behavior = 'fail'
    expect(await checkSyncAccessHandle()).toBe(false)
    expect(FakeWorker.terminated).toBe(1)
  })

  it('returns false when the worker posts a message without a payload', async () => {
    FakeWorker.behavior = 'nodata'
    expect(await checkSyncAccessHandle()).toBe(false)
  })

  it('returns false when the worker errors', async () => {
    FakeWorker.behavior = 'error'
    expect(await checkSyncAccessHandle()).toBe(false)
    expect(FakeWorker.terminated).toBe(1)
  })

  it('returns false (and terminates) when the worker never responds', async () => {
    vi.useFakeTimers()
    FakeWorker.behavior = 'silent'
    const pending = checkSyncAccessHandle()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(await pending).toBe(false)
    expect(FakeWorker.terminated).toBe(1)
  })
})
