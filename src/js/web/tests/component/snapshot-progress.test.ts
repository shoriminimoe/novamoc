/**
 * Snapshot progress observable tests (E1.7).
 *
 * Pure value-type unit tests — no DB, no HTTP. Covers the subscribe contract
 * (immediate call + change notifications), per-table accumulation, the total
 * roll-up, lifecycle phases, and the restart reset the ingest uses when it
 * detects an invalidated snapshot.
 */
import { describe, expect, it, vi } from 'vitest'

import {
  SNAPSHOT_TABLES,
  SnapshotProgressStore,
} from '../../src/lib/sync/_progress'

describe('SnapshotProgressStore', () => {
  it('starts idle with zeroed per-table counters', () => {
    const snap = new SnapshotProgressStore().snapshot()
    expect(snap.phase).toBe('idle')
    expect(snap.totalRows).toBe(0)
    for (const table of SNAPSHOT_TABLES) {
      expect(snap.tables[table]).toEqual({ rows: 0, batches: 0 })
    }
  })

  it('calls a new subscriber immediately and on every change', () => {
    const store = new SnapshotProgressStore()
    const seen = vi.fn()
    const unsubscribe = store.subscribe(seen)
    expect(seen).toHaveBeenCalledTimes(1)

    store.recordBatch('assets', 3)
    expect(seen).toHaveBeenCalledTimes(2)
    expect(seen.mock.calls[1][0].tables.assets).toEqual({ rows: 3, batches: 1 })

    unsubscribe()
    store.recordBatch('assets', 1)
    expect(seen).toHaveBeenCalledTimes(2)
  })

  it('accumulates rows and batches per table and rolls up the total', () => {
    const store = new SnapshotProgressStore()
    store.recordBatch('assets', 2)
    store.recordBatch('assets', 5)
    store.recordBatch('maintenance_records', 4)

    const snap = store.snapshot()
    expect(snap.phase).toBe('running')
    expect(snap.tables.assets).toEqual({ rows: 7, batches: 2 })
    expect(snap.tables.maintenance_records).toEqual({ rows: 4, batches: 1 })
    expect(snap.totalRows).toBe(11)
  })

  it('moves to terminal phases via setPhase', () => {
    const store = new SnapshotProgressStore()
    store.setPhase('done')
    expect(store.snapshot().phase).toBe('done')
    store.setPhase('error')
    expect(store.snapshot().phase).toBe('error')
  })

  it('reset clears counters and marks the run restarted by default', () => {
    const store = new SnapshotProgressStore()
    store.recordBatch('assets', 5)
    store.reset()

    const snap = store.snapshot()
    expect(snap.phase).toBe('restarted')
    expect(snap.totalRows).toBe(0)
    expect(snap.tables.assets).toEqual({ rows: 0, batches: 0 })
  })

  it('reset accepts an explicit phase', () => {
    const store = new SnapshotProgressStore()
    store.recordBatch('assets', 5)
    store.reset('running')
    expect(store.snapshot().phase).toBe('running')
    expect(store.snapshot().totalRows).toBe(0)
  })

  it('snapshot returns an independent copy (no aliasing of internal state)', () => {
    const store = new SnapshotProgressStore()
    store.recordBatch('assets', 1)
    const first = store.snapshot()
    store.recordBatch('assets', 1)
    // The earlier snapshot is unaffected by the later mutation.
    expect(first.tables.assets.rows).toBe(1)
  })
})
