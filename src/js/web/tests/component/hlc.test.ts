/**
 * HLC tests (ADR-006). Runs against the real in-memory SQLite-WASM DB from
 * ``openLocalDb`` — no mocks, matching the project's db-test discipline — so
 * persistence (and the across-reload guarantees) exercise actual SQL rather
 * than a stub. Wall time is driven with vitest fake timers so the
 * physical-collision and advance branches are deterministic.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { _resetLocalDbsForTest, openLocalDb } from '../../src/lib/db/bootstrap'
import { Hlc, HlcParseError, createHlc } from '../../src/lib/db/hlc'

const TENANT = '00000000-0000-0000-0000-0000000000c1'

const PHYSICAL_WIDTH = 16
const LOGICAL_WIDTH = 5

function physicalOf(hlc: string): number {
  return Number(hlc.slice(0, PHYSICAL_WIDTH))
}

function logicalOf(hlc: string): number {
  return Number(hlc.slice(PHYSICAL_WIDTH + 1, PHYSICAL_WIDTH + 1 + LOGICAL_WIDTH))
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(1_700_000_000_000)
})

afterEach(async () => {
  vi.useRealTimers()
  await _resetLocalDbsForTest()
})

describe('Hlc', () => {
  it('produces the fixed-width, zero-padded ADR-006 string format', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const hlc = await createHlc(db)

    const stamp = await hlc.now()

    // {physical:016}-{logical:05}-{node_id}; node_id is a UUID (has dashes).
    expect(stamp).toMatch(/^\d{16}-\d{5}-[0-9a-f-]+$/)
    expect(physicalOf(stamp)).toBe(1_700_000_000_000)
    expect(logicalOf(stamp)).toBe(0)
  })

  it('is monotonic within a session', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const hlc = await createHlc(db)

    const stamps: string[] = []
    for (let i = 0; i < 5; i++) {
      stamps.push(await hlc.now())
      vi.advanceTimersByTime(1)
    }

    const sorted = [...stamps].sort()
    expect(stamps).toEqual(sorted)
    // Strictly increasing — no two equal.
    expect(new Set(stamps).size).toBe(stamps.length)
  })

  it('cascades the logical counter on a same-physical-ms collision', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const hlc = await createHlc(db)

    // Wall time frozen: every now() lands on the same physical ms.
    const a = await hlc.now()
    const b = await hlc.now()
    const c = await hlc.now()

    expect(physicalOf(a)).toBe(physicalOf(b))
    expect(physicalOf(b)).toBe(physicalOf(c))
    expect(logicalOf(a)).toBe(0)
    expect(logicalOf(b)).toBe(1)
    expect(logicalOf(c)).toBe(2)
  })

  it('lexicographic ordering matches numeric ordering', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const hlc = await createHlc(db)

    const stamps: string[] = []
    // Mix same-ms cascades with wall-clock advances.
    stamps.push(await hlc.now())
    stamps.push(await hlc.now())
    vi.advanceTimersByTime(7)
    stamps.push(await hlc.now())
    vi.advanceTimersByTime(1000)
    stamps.push(await hlc.now())

    const numeric = [...stamps].sort((x, y) => {
      const dp = physicalOf(x) - physicalOf(y)
      return dp !== 0 ? dp : logicalOf(x) - logicalOf(y)
    })
    const lexicographic = [...stamps].sort()
    expect(lexicographic).toEqual(numeric)
  })

  it('keeps node_id stable across reloads', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const first = await createHlc(db)
    const nodeId = first.nodeId
    expect(nodeId).toBeTruthy()

    // Simulated reload: a new clock instance over the same persisted DB.
    const second = await createHlc(db)
    expect(second.nodeId).toBe(nodeId)
  })

  it('is monotonic across a simulated reload', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const first = await createHlc(db)

    // Burn the logical counter at a frozen wall time.
    let last = ''
    for (let i = 0; i < 3; i++) {
      last = await first.now()
    }

    // Reload (new instance, same DB) at the SAME wall time — the persisted
    // HLC must still force a strictly greater stamp.
    const reloaded = await createHlc(db)
    const afterReload = await reloaded.now()

    expect(afterReload > last).toBe(true)
    expect(physicalOf(afterReload)).toBe(physicalOf(last))
    expect(logicalOf(afterReload)).toBe(logicalOf(last) + 1)
  })

  it('persists the node_id into sync_state on first launch', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const hlc = await createHlc(db)

    const rows = await db.exec('SELECT node_id, last_hlc FROM sync_state WHERE id = 1')
    expect(rows[0][0]).toBe(hlc.nodeId)
    // last_hlc is only written once an HLC is issued.
    expect(rows[0][1]).toBeNull()

    const stamp = await hlc.now()
    const after = await db.exec('SELECT last_hlc FROM sync_state WHERE id = 1')
    expect(after[0][0]).toBe(stamp)
  })

  it('throws when the logical counter would overflow within one ms', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    // Resume at the frozen wall ms with the logical field already maxed.
    await db.exec(
      "UPDATE sync_state SET node_id = 'n', last_hlc = '0001700000000000-99999-n' WHERE id = 1",
    )
    const hlc = await createHlc(db)

    // Wall is frozen at the same ms, so now() must tick logical past 99999.
    await expect(hlc.now()).rejects.toThrow(/overflow/)
  })

  it('rejects a malformed remote HLC rather than poisoning local state', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const hlc = await createHlc(db)

    await expect(hlc.receive('not-an-hlc')).rejects.toThrow(HlcParseError)

    // State is untouched: a subsequent stamp is still well-formed.
    const stamp = await hlc.now()
    expect(stamp).toMatch(/^\d{16}-\d{5}-[0-9a-f-]+$/)
  })

  it('refuses to open with a persisted HLC but no node_id', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    await db.exec(
      "UPDATE sync_state SET node_id = NULL, last_hlc = '0001700000000000-00000-orphan' WHERE id = 1",
    )

    await expect(createHlc(db)).rejects.toThrow(/no node_id/)
  })

  describe('receive', () => {
    it('adopts a further-ahead remote physical and zeros logical', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
      const hlc = await createHlc(db)

      const remotePhysical = 1_700_000_000_000 + 5000
      await hlc.receive(`${String(remotePhysical).padStart(16, '0')}-00042-other-node`)

      // Wall time (frozen) and local are both behind the remote physical.
      const next = await hlc.now()
      expect(physicalOf(next)).toBe(remotePhysical)
      // receive set logical = remote.logical + 1 = 43; now() collides on the
      // same physical (wall is behind) and ticks to 44.
      expect(logicalOf(next)).toBe(44)
    })

    it('ticks logical when wall advances past both local and remote', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
      const hlc = await createHlc(db)

      const past = 1_700_000_000_000 - 1000
      await hlc.receive(`${String(past).padStart(16, '0')}-00009-other-node`)

      // New physical came from wall (ahead of both) -> logical zeroed.
      const next = await hlc.now()
      expect(physicalOf(next)).toBe(1_700_000_000_000)
      // receive zeroed logical (wall branch); now() collides -> ticks to 1.
      expect(logicalOf(next)).toBe(1)
    })

    it('breaks an exact physical tie by max-ing both logicals + 1', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
      const hlc = await createHlc(db)

      // Push local logical up to 3 at the frozen wall ms.
      await hlc.now()
      await hlc.now()
      await hlc.now()
      await hlc.now() // logical 3

      // Remote at the exact same physical with a higher logical.
      await hlc.receive(`${String(1_700_000_000_000).padStart(16, '0')}-00010-other`)

      const next = await hlc.now()
      expect(physicalOf(next)).toBe(1_700_000_000_000)
      // receive: max(3, 10) + 1 = 11; now() collides -> 12.
      expect(logicalOf(next)).toBe(12)
    })

    it('persists across a reload after receive', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
      const first = await createHlc(db)

      const remotePhysical = 1_700_000_000_000 + 9000
      await first.receive(`${String(remotePhysical).padStart(16, '0')}-00000-other`)

      const reloaded = await createHlc(db)
      const next = await reloaded.now()
      expect(physicalOf(next)).toBe(remotePhysical)
    })
  })

  describe('drift detection', () => {
    it('warns when persisted physical lags wall time by over a minute', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
      const first = await createHlc(db)
      await first.now()

      // Jump wall clock forward by > 1 minute, then reload so the persisted
      // (stale) physical is what the new clock compares against.
      vi.setSystemTime(1_700_000_000_000 + 61_000)
      const reloaded = await createHlc(db)
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

      const stamp = await reloaded.now()

      expect(warn).toHaveBeenCalledWith('clock_drift_detected', expect.anything())
      // Drift is observed, not enforced — the (ahead) wall time is still adopted.
      expect(physicalOf(stamp)).toBe(1_700_000_000_000 + 61_000)
      warn.mockRestore()
    })

    it('does not warn within the drift bound', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
      const first = await createHlc(db)
      await first.now()

      // Reload so the resumed clock has a persisted baseline to compare
      // against; 30s of lag is under the bound.
      vi.setSystemTime(1_700_000_000_000 + 30_000)
      const reloaded = await createHlc(db)
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

      await reloaded.now()

      expect(warn).not.toHaveBeenCalled()
      warn.mockRestore()
    })

    it('does not warn at exactly the drift bound (strict >)', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
      const first = await createHlc(db)
      await first.now()

      // Exactly DRIFT_WARN_MS of lag: the comparison is strict ``>``.
      vi.setSystemTime(1_700_000_000_000 + 60_000)
      const reloaded = await createHlc(db)
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

      await reloaded.now()

      expect(warn).not.toHaveBeenCalled()
      warn.mockRestore()
    })

    it('does not warn on a fresh clock with no persisted baseline', async () => {
      const db = await openLocalDb(TENANT, { memory: true })
      const hlc = await createHlc(db)
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

      // No prior HLC was persisted at open — there's nothing to drift from.
      await hlc.now()
      vi.advanceTimersByTime(120_000)
      await hlc.now()

      expect(warn).not.toHaveBeenCalled()
      warn.mockRestore()
    })
  })

  it('createHlc and Hlc.open are equivalent entry points', async () => {
    const db = await openLocalDb(TENANT, { memory: true })
    const viaFactory = await createHlc(db)
    const viaStatic = await Hlc.open(db)
    expect(viaStatic.nodeId).toBe(viaFactory.nodeId)
  })
})
