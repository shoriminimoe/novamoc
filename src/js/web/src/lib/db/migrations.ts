/**
 * Schema-version scaffold for the local SQLite-WASM database (ADR-003).
 *
 * Migrations are an ordered list of forward steps, each gated on the stored
 * ``user_version``. A fresh DB (``user_version = 0``) runs every step; an
 * existing DB runs only the steps past its stamped version.
 *
 * ``ddl.ts`` always reflects the latest column set, so a fresh DB gets
 * everything from STEP[0]. Each ``STEPS[N>0]`` patches DBs that predate a
 * later column (e.g. an idempotent ``ALTER TABLE``). When you add a column:
 * edit ``ddl.ts`` AND append a STEPS entry together — the DDL change covers
 * fresh DBs, the new step covers existing ones. The patch steps must be
 * idempotent (guarded), since a fresh DB skips them only by version, not by
 * inspecting whether the change is already present.
 *
 * A DB stamped at a version newer than this build (a tab running stale code
 * against a DB a newer tab upgraded) is a hard error: silently downgrading
 * would corrupt the local store.
 */

import type { Database } from '@sqlite.org/sqlite-wasm'

import { DDL } from './ddl'

/**
 * Ordered forward migration steps. Index ``i`` brings a DB from
 * ``user_version = i`` to ``i + 1``. Append, never edit.
 */
const STEPS: readonly ((db: Database) => void)[] = [
  // 0 -> 1: the base schema.
  (db) => {
    for (const statement of DDL) {
      db.exec(statement)
    }
  },
  // 1 -> 2: add the persisted HLC column for DBs created before it existed.
  // Fresh DBs already have it from the (IF NOT EXISTS) DDL above, so guard
  // the ALTER against the duplicate-column error.
  (db) => {
    if (!hasColumn(db, 'sync_state', 'last_hlc')) {
      db.exec('ALTER TABLE sync_state ADD COLUMN last_hlc TEXT')
    }
  },
]

export const SCHEMA_VERSION = STEPS.length

function userVersion(db: Database): number {
  const [[version]] = db.exec({
    sql: 'PRAGMA user_version',
    returnValue: 'resultRows',
    rowMode: 'array',
  })
  return version as number
}

function hasColumn(db: Database, table: string, column: string): boolean {
  // The PRAGMA function form doesn't accept a bind parameter for its table
  // argument, so it has to be interpolated. Callers pass hard-coded literals,
  // but whitelist the identifier shape anyway so the helper can't become an
  // injection vector if a future caller is careless.
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(table)) {
    throw new Error(`unsafe table identifier: ${JSON.stringify(table)}`)
  }
  const rows = db.exec({
    sql: `SELECT 1 FROM pragma_table_info('${table}') WHERE name = ?`,
    bind: [column],
    returnValue: 'resultRows',
    rowMode: 'array',
  })
  return rows.length > 0
}

/** Bring a freshly-opened DB up to {@link SCHEMA_VERSION}. */
export function migrate(db: Database): void {
  const current = userVersion(db)

  if (current === SCHEMA_VERSION) {
    return
  }
  if (current > SCHEMA_VERSION) {
    throw new Error(
      `local DB is at schema version ${current}, newer than this build (${SCHEMA_VERSION})`,
    )
  }

  db.exec('BEGIN')
  try {
    for (let version = current; version < SCHEMA_VERSION; version++) {
      STEPS[version](db)
    }
    // PRAGMA user_version doesn't accept bind parameters; the value is a
    // module constant, never user input, so the interpolation is safe.
    db.exec(`PRAGMA user_version = ${SCHEMA_VERSION}`)
    db.exec('COMMIT')
  } catch (error) {
    db.exec('ROLLBACK')
    throw error
  }
}
