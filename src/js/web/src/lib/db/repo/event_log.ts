/**
 * Read-only repository over the local `event_log` (ADR-011 / ADR-013).
 *
 * The event log is written by the catch-up/ingest path, not by this layer.
 * E1.9 ships only the read access the debug surface and the fold-parity tests
 * need: a cursor-ordered scan and a single-row lookup by `seq`. Cross-tenant
 * gaps in `seq` are expected (it is the server's globally-monotonic cursor), so
 * every read still pins `tenant_id`.
 */

import type { TenantContext, TenantScoped } from './_tenant'
import type { EventLogRow } from './_rows'
import { parseJson } from './_sql'

const COLUMNS =
  'seq, hlc, schema_version, table_name, type_id, entity_id, field_id, op, value_json, received_at'

function rowToEvent<B>(row: unknown[]): TenantScoped<EventLogRow, B> {
  return {
    seq: row[0] as number,
    hlc: row[1] as string,
    schema_version: row[2] as number,
    table_name: row[3] as string,
    type_id: row[4] as string,
    entity_id: row[5] as string,
    field_id: (row[6] as string | null) ?? null,
    op: row[7] as string,
    value_json: parseJson(row[8]),
    received_at: (row[9] as string | null) ?? null,
  } as TenantScoped<EventLogRow, B>
}

export interface EventLogRepo<B> {
  /** Events with `seq > after`, in ascending `seq` order, capped at `limit`. */
  listSince(
    after: number,
    limit?: number,
  ): Promise<TenantScoped<EventLogRow, B>[]>
  getBySeq(seq: number): Promise<TenantScoped<EventLogRow, B> | null>
}

const DEFAULT_LIMIT = 500

export function makeEventLogRepo<B>(ctx: TenantContext<B>): EventLogRepo<B> {
  const { db, tenantId } = ctx

  return {
    async listSince(after, limit = DEFAULT_LIMIT) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM event_log
         WHERE tenant_id = ? AND seq > ? ORDER BY seq LIMIT ?`,
        [tenantId, after, limit],
      )
      return rows.map((row) => rowToEvent<B>(row))
    },

    async getBySeq(seq) {
      const rows = await db.exec(
        `SELECT ${COLUMNS} FROM event_log WHERE tenant_id = ? AND seq = ?`,
        [tenantId, seq],
      )
      return rows.length ? rowToEvent<B>(rows[0]) : null
    },
  }
}
