/**
 * Per-table progress observable for a bulk snapshot ingest (ADR-015).
 *
 * Framework-agnostic on purpose: the ingest loop (`snapshot.ts`) reports rows
 * and batches as they land, and any consumer — the debug modal, a future app
 * shell, a test — subscribes for snapshots. Kept out of `snapshot.ts` so the
 * ingest's progress reporting is a thin call into a value type rather than UI
 * state tangled into the transport loop.
 *
 * The four projection tables are the progress axes. A snapshot has no total
 * row count up front (the server paginates without a count), so progress is
 * "rows seen / batches seen" per table plus a coarse `phase`, not a percentage.
 */

/** The four projection tables a snapshot walks, in transfer order. */
export type SnapshotTable =
  | 'assets'
  | 'asset_field_values'
  | 'maintenance_records'
  | 'maintenance_record_field_values'

export const SNAPSHOT_TABLES: readonly SnapshotTable[] = [
  'assets',
  'asset_field_values',
  'maintenance_records',
  'maintenance_record_field_values',
]

/** Rows and batches seen for one table so far. */
export interface TableProgress {
  rows: number
  batches: number
}

/**
 * Coarse lifecycle of the ingest, for the modal's headline:
 * - `idle` — nothing in flight (initial and post-`reset`).
 * - `running` — batches are arriving.
 * - `restarted` — the snapshot was invalidated mid-transfer and the loop
 *   discarded partial state to start over (per-table counters reset).
 * - `done` — the terminal batch landed.
 * - `error` — a transport error left the loop; partial state persists for the
 *   next attempt to resume.
 */
export type SnapshotPhase = 'idle' | 'running' | 'restarted' | 'done' | 'error'

export interface SnapshotProgress {
  phase: SnapshotPhase
  /** Total rows across all tables — a single headline number for the modal. */
  totalRows: number
  /** Per-table breakdown, one entry per {@link SNAPSHOT_TABLES} member. */
  tables: Record<SnapshotTable, TableProgress>
}

type Listener = (progress: SnapshotProgress) => void

function emptyTables(): Record<SnapshotTable, TableProgress> {
  return {
    assets: { rows: 0, batches: 0 },
    asset_field_values: { rows: 0, batches: 0 },
    maintenance_records: { rows: 0, batches: 0 },
    maintenance_record_field_values: { rows: 0, batches: 0 },
  }
}

/**
 * A subscribable progress value. `subscribe` follows the Svelte store contract
 * (called immediately with the current value, returns an unsubscribe), so a
 * Svelte component can `$store` it directly; plain callers read `snapshot()`.
 */
export class SnapshotProgressStore {
  #phase: SnapshotPhase = 'idle'
  #tables = emptyTables()
  readonly #listeners = new Set<Listener>()

  /** Current immutable progress value. */
  snapshot(): SnapshotProgress {
    let totalRows = 0
    const tables = emptyTables()
    for (const table of SNAPSHOT_TABLES) {
      tables[table] = { ...this.#tables[table] }
      totalRows += this.#tables[table].rows
    }
    return { phase: this.#phase, totalRows, tables }
  }

  /** Svelte-store-compatible subscribe: immediate call + unsubscribe handle. */
  subscribe(listener: Listener): () => void {
    this.#listeners.add(listener)
    listener(this.snapshot())
    return () => {
      this.#listeners.delete(listener)
    }
  }

  #emit(): void {
    const value = this.snapshot()
    for (const listener of this.#listeners) {
      listener(value)
    }
  }

  /** Record one arrived batch: `rowCount` rows for `table`. */
  recordBatch(table: SnapshotTable, rowCount: number): void {
    this.#phase = 'running'
    const current = this.#tables[table]
    this.#tables[table] = {
      rows: current.rows + rowCount,
      batches: current.batches + 1,
    }
    this.#emit()
  }

  /** Move to a terminal lifecycle phase (`done` / `error`). */
  setPhase(phase: SnapshotPhase): void {
    this.#phase = phase
    this.#emit()
  }

  /**
   * Clear per-table counters back to zero and mark the run `restarted` — the
   * ingest calls this when it detects an invalidated snapshot and starts over.
   */
  reset(phase: SnapshotPhase = 'restarted'): void {
    this.#tables = emptyTables()
    this.#phase = phase
    this.#emit()
  }
}
