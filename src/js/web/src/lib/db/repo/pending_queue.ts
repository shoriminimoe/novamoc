/**
 * Repository over `local_pending_events` — the offline write queue (ADR-013).
 *
 * E1.10's drainer is the consumer: it lists pending rows in HLC order, POSTs
 * them, and reports the outcome back here. The write path that *enqueues* rows
 * is E1.10's; this layer ships the read + status surface the drainer needs.
 *
 * The queue's storage contract today is "a row present == still pending." So:
 *
 *   - `markSent` deletes the row. A successfully-POSTed event is authoritative
 *     on the server and arrives back through the catch-up stream, so the local
 *     pending copy is redundant once accepted (the spec's retention window is
 *     an E1.10 refinement, not a column this layer owns).
 *   - `recordFailure` on a *transient* failure leaves the row in place so the
 *     next drain re-sends it — which is the entire durability guarantee
 *     (a failed POST must not lose the event). Persisting a *permanent*
 *     rejection (a status/reason column for the debug surface) requires a DDL
 *     column that lands with E1.10; until then `recordFailure` only asserts the
 *     row exists (so draining an unknown client_seq is a loud error, not a
 *     silent no-op) and leaves it eligible for retry. The rejection reason gets
 *     a parameter once there's a column to store it in.
 */

import type { TenantContext, TenantScoped } from './_tenant'
import type { PendingEventRow } from './_rows'
import { parseJson } from './_sql'

const COLUMNS =
  'client_seq, hlc, schema_version, table_name, type_id, entity_id, field_id, op, value_json, created_at'

function rowToPending<B>(row: unknown[]): TenantScoped<PendingEventRow, B> {
  return {
    client_seq: row[0] as number,
    hlc: row[1] as string,
    schema_version: row[2] as number,
    table_name: row[3] as string,
    type_id: row[4] as string,
    entity_id: row[5] as string,
    field_id: (row[6] as string | null) ?? null,
    op: row[7] as string,
    value_json: parseJson(row[8]),
    created_at: (row[9] as string | null) ?? null,
  } as TenantScoped<PendingEventRow, B>
}

export interface PendingQueueRepo<B> {
  /** Pending rows in HLC order (the send order), capped at `limit`. */
  listPending(limit?: number): Promise<TenantScoped<PendingEventRow, B>[]>
  /** A row the server accepted; remove it from the queue. */
  markSent(clientSeq: number): Promise<void>
  /**
   * Report a failed send attempt. Leaves the row queued for retry. Throws if
   * `clientSeq` names no pending row for this tenant.
   */
  recordFailure(clientSeq: number): Promise<void>
}

const DEFAULT_LIMIT = 500

export function makePendingQueueRepo<B>(
  ctx: TenantContext<B>,
): PendingQueueRepo<B> {
  const { db, tenantId } = ctx

  return {
    async listPending(limit = DEFAULT_LIMIT) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM local_pending_events
         WHERE tenant_id = ? ORDER BY hlc LIMIT ?`,
        [tenantId, limit],
      )
      return rows.map((row) => rowToPending<B>(row))
    },

    async markSent(clientSeq) {
      await db.exec(
        'DELETE FROM local_pending_events WHERE tenant_id = ? AND client_seq = ?',
        [tenantId, clientSeq],
      )
    },

    async recordFailure(clientSeq) {
      // No status/reason column on the queue table yet (it lands with the E1.10
      // write path), so the durability guarantee — a failed send keeps the
      // event — is met by leaving the row untouched. Assert it exists, though,
      // so draining an unknown client_seq surfaces loudly instead of silently.
      const rows = await db.exec(
        'SELECT 1 FROM local_pending_events WHERE tenant_id = ? AND client_seq = ?',
        [tenantId, clientSeq],
      )
      if (rows.length === 0) {
        throw new Error(`recordFailure: unknown client_seq ${clientSeq}`)
      }
    },
  }
}
