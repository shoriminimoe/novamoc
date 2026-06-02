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
 *
 * ``physical_ms`` is held as a JS ``number``, so the protocol's effective
 * upper bound on the physical component is ``Number.MAX_SAFE_INTEGER``
 * (~9.0e15 ms, year ~287396). Real wall-clock ms are ~1.7e12, so this is
 * not a near-term concern; values above the safe range would lose precision
 * and break the fixed-width round-trip.
 */

import type { DbHandle } from './bootstrap'

const PHYSICAL_WIDTH = 16
const LOGICAL_WIDTH = 5

/** Logical counter ceiling; one more tick within a ms would overflow the field. */
const LOGICAL_MAX = 10 ** LOGICAL_WIDTH - 1

/** Persisted-physical lag past which we surface a drift warning (ADR-006). */
const DRIFT_WARN_MS = 60_000

/**
 * Canonical serialized form: 16-digit physical, 5-digit logical, then a
 * non-empty opaque node id. Mirrors the server parser's regex (``_hlc.py``)
 * so the two implementations accept exactly the same strings.
 */
const HLC_RE = /^(\d{16})-(\d{5})-(.+)$/

/** The minimal persistence surface the clock needs — satisfied by {@link DbHandle}. */
export type HlcStore = Pick<DbHandle, 'exec'>

/** Raised when a string is not a canonical HLC (matches the server's HLCParseError). */
export class HlcParseError extends Error {}

/** One parsed HLC. {@link HlcParts.nodeId} is opaque and may itself contain dashes. */
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
 * Split a serialized HLC, rejecting anything that isn't the canonical form.
 * Validating here keeps a malformed remote (or a corrupted persisted value)
 * from propagating ``NaN`` into the clock's state and poisoning every
 * subsequent stamp.
 */
function parse(hlc: string): HlcParts {
  const m = HLC_RE.exec(hlc)
  if (m === null) {
    throw new HlcParseError(`invalid HLC: ${JSON.stringify(hlc)}`)
  }
  return { physicalMs: Number(m[1]), logical: Number(m[2]), nodeId: m[3] }
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
  /** Whether a prior HLC was persisted at open — gates drift detection. */
  readonly #resumed: boolean

  private constructor(
    store: HlcStore,
    nodeId: string,
    physicalMs: number,
    logical: number,
    resumed: boolean,
  ) {
    this.#store = store
    this.nodeId = nodeId
    this.#physicalMs = physicalMs
    this.#logical = logical
    this.#resumed = resumed
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
      // A persisted clock state with no identity means a prior node_id was
      // cleared while last_hlc survived. Resuming it under a fresh UUID would
      // emit monotonic-but-identity-confused stamps; fail loudly instead.
      if (lastHlc) {
        throw new Error(
          'sync_state has a persisted HLC but no node_id; refusing to resume an unidentified clock',
        )
      }
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
    return new Hlc(store, nodeId, physicalMs, logical, lastHlc !== null)
  }

  /**
   * Stamp and persist a new HLC for a locally-generated event (ADR-006
   * local-event algorithm): adopt wall time when it has advanced, else tick
   * the logical counter.
   *
   * Throws when the logical counter would overflow the 5-digit field within
   * one wall millisecond (matches the server's ``OverflowError``).
   */
  async now(): Promise<string> {
    const wall = wallNowMs()
    this.#warnIfDrifted(wall)

    if (wall > this.#physicalMs) {
      this.#physicalMs = wall
      this.#logical = 0
    } else {
      this.#logical = this.#tick(this.#logical, this.#physicalMs)
    }
    return this.#persist()
  }

  /**
   * Fold a remote HLC into local state (ADR-006 receive-event algorithm),
   * advancing physical to ``max(local, remote, wall)`` and resolving the
   * logical counter per the branch the new physical came from. Persists the
   * advanced state; returns nothing. Rejects a malformed remote and throws on
   * logical-counter overflow, like {@link now}.
   */
  async receive(remote: string): Promise<void> {
    const r = parse(remote)
    const wall = wallNowMs()
    this.#warnIfDrifted(wall)

    const newPhysical = Math.max(this.#physicalMs, r.physicalMs, wall)
    let newLogical: number
    if (newPhysical === this.#physicalMs && newPhysical === r.physicalMs) {
      newLogical = this.#tick(Math.max(this.#logical, r.logical), newPhysical)
    } else if (newPhysical === this.#physicalMs) {
      newLogical = this.#tick(this.#logical, newPhysical)
    } else if (newPhysical === r.physicalMs) {
      newLogical = this.#tick(r.logical, newPhysical)
    } else {
      newLogical = 0
    }
    this.#physicalMs = newPhysical
    this.#logical = newLogical
    await this.#persist()
  }

  /** Increment a logical counter, refusing to overflow the fixed-width field. */
  #tick(logical: number, physicalMs: number): number {
    if (logical >= LOGICAL_MAX) {
      throw new Error(`HLC logical counter overflow at physical_ms=${physicalMs}`)
    }
    return logical + 1
  }

  /** Surface a debug-only warning when a resumed clock's physical lags wall time. */
  #warnIfDrifted(wall: number): void {
    if (this.#resumed && wall - this.#physicalMs > DRIFT_WARN_MS) {
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
