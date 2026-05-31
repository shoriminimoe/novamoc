/**
 * Hybrid Logical Clock for locally-generated events (ADR-006).
 *
 * An HLC is the triple ``(physical_ms, logical, node_id)`` serialized as
 * the fixed-width zero-padded string ``{physical_ms:016}-{logical:05}-
 * {node_id}``. Fixed widths make lexicographic string comparison agree with
 * component-wise numeric comparison — the property the SQL fold (ADR-007)
 * and the server's parser rely on, so client- and server-produced strings
 * interleave correctly under plain ``TEXT`` ordering.
 *
 * State (the ``node_id`` and the last-issued HLC) lives in the single
 * ``sync_state`` row, so a reopened tab resumes from the persisted value and
 * cannot regress below an HLC it already handed out. The clock takes a
 * persistence handle as a dependency rather than reaching for a module
 * global, which keeps it testable against the ``:memory:`` DB.
 *
 * Drift is observed, not enforced: a persisted physical component more than
 * a minute behind wall time surfaces a debug warning, but the wall time is
 * still adopted. The server is the sole drift authority (ADR-006) — a client
 * rejecting its own wall clock would only desync it from the accepted set.
 */

import type { DbHandle } from './bootstrap'

const PHYSICAL_WIDTH = 16
const LOGICAL_WIDTH = 5

/** Logical counter ceiling; one more tick within a ms would overflow the field. */
const LOGICAL_MAX = 10 ** LOGICAL_WIDTH - 1

/** Persisted-physical lag past which we surface a drift warning (ADR-006). */
const DRIFT_WARN_MS = 60_000

/** The minimal persistence surface the clock needs — satisfied by {@link DbHandle}. */
export type HlcStore = Pick<DbHandle, 'exec'>

/** One parsed HLC. {@link node_id} is opaque and may itself contain dashes. */
interface HlcParts {
  physicalMs: number
  logical: number
  nodeId: string
}

/** Wall clock in HLC physical units (epoch ms). Indirected for test seams. */
function wallNowMs(): number {
  return Date.now()
}

function format(physicalMs: number, logical: number, nodeId: string): string {
  const phys = String(physicalMs).padStart(PHYSICAL_WIDTH, '0')
  const log = String(logical).padStart(LOGICAL_WIDTH, '0')
  return `${phys}-${log}-${nodeId}`
}

/**
 * Split a serialized HLC. The node id is everything after the second dash —
 * it may contain dashes (a UUID does), so we slice on the two fixed-width
 * numeric fields rather than splitting on ``-``.
 */
function parse(hlc: string): HlcParts {
  const physicalMs = Number(hlc.slice(0, PHYSICAL_WIDTH))
  const logical = Number(hlc.slice(PHYSICAL_WIDTH + 1, PHYSICAL_WIDTH + 1 + LOGICAL_WIDTH))
  const nodeId = hlc.slice(PHYSICAL_WIDTH + 1 + LOGICAL_WIDTH + 1)
  return { physicalMs, logical, nodeId }
}

/**
 * A persistent, monotonic Hybrid Logical Clock backed by ``sync_state``.
 *
 * Build instances via {@link createHlc}, which loads (or initialises) the
 * persisted ``node_id`` and last HLC. {@link now} stamps a new local event;
 * {@link receive} folds in a remote HLC. Both persist before returning so no
 * issued HLC is ever lost across a reload.
 */
export class Hlc {
  readonly nodeId: string
  #physicalMs: number
  #logical: number
  readonly #store: HlcStore

  private constructor(
    store: HlcStore,
    nodeId: string,
    physicalMs: number,
    logical: number,
  ) {
    this.#store = store
    this.nodeId = nodeId
    this.#physicalMs = physicalMs
    this.#logical = logical
  }

  /**
   * Open the clock for ``store``, generating and persisting a ``node_id`` on
   * first launch and resuming from any persisted HLC otherwise.
   */
  static async open(store: HlcStore): Promise<Hlc> {
    const rows = await store.exec(
      'SELECT node_id, last_hlc FROM sync_state WHERE id = 1',
    )
    const row = rows[0] ?? []
    let nodeId = row[0] as string | null
    const lastHlc = row[1] as string | null

    if (nodeId === null || nodeId === undefined || nodeId === '') {
      nodeId = crypto.randomUUID()
      await store.exec('UPDATE sync_state SET node_id = ? WHERE id = 1', [nodeId])
    }

    let physicalMs = 0
    let logical = 0
    if (lastHlc) {
      const parts = parse(lastHlc)
      physicalMs = parts.physicalMs
      logical = parts.logical
    }
    return new Hlc(store, nodeId, physicalMs, logical)
  }

  /**
   * Stamp and persist a new HLC for a locally-generated event (ADR-006
   * local-event algorithm): adopt wall time when it has advanced, else tick
   * the logical counter.
   */
  async now(): Promise<string> {
    const wall = wallNowMs()
    this.#warnIfDrifted(wall)

    if (wall > this.#physicalMs) {
      this.#physicalMs = wall
      this.#logical = 0
    } else {
      this.#logical += 1
    }
    return this.#persist()
  }

  /**
   * Fold a remote HLC into local state (ADR-006 receive-event algorithm),
   * advancing physical to ``max(local, remote, wall)`` and resolving the
   * logical counter per the branch the new physical came from. Persists the
   * advanced state; returns nothing.
   */
  async receive(remote: string): Promise<void> {
    const r = parse(remote)
    const wall = wallNowMs()
    this.#warnIfDrifted(wall)

    const newPhysical = Math.max(this.#physicalMs, r.physicalMs, wall)
    if (newPhysical === this.#physicalMs && newPhysical === r.physicalMs) {
      this.#logical = Math.max(this.#logical, r.logical) + 1
    } else if (newPhysical === this.#physicalMs) {
      this.#logical += 1
    } else if (newPhysical === r.physicalMs) {
      this.#logical = r.logical + 1
    } else {
      this.#logical = 0
    }
    this.#physicalMs = newPhysical
    await this.#persist()
  }

  /** Surface a debug-only warning when the persisted physical lags wall time. */
  #warnIfDrifted(wall: number): void {
    if (this.#physicalMs !== 0 && wall - this.#physicalMs > DRIFT_WARN_MS) {
      console.warn('clock_drift_detected', {
        persistedPhysicalMs: this.#physicalMs,
        wallMs: wall,
        driftMs: wall - this.#physicalMs,
      })
    }
  }

  async #persist(): Promise<string> {
    const serialized = format(this.#physicalMs, this.#logical, this.nodeId)
    await this.#store.exec('UPDATE sync_state SET last_hlc = ? WHERE id = 1', [
      serialized,
    ])
    return serialized
  }
}

/** Convenience alias for {@link Hlc.open}. */
export function createHlc(store: HlcStore): Promise<Hlc> {
  return Hlc.open(store)
}
