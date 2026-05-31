/**
 * Schema-version scaffold for the local SQLite-WASM database (ADR-003).
 *
 * v1 is a single forward step: a fresh DB has ``user_version = 0``, so we
 * apply the DDL and stamp ``user_version = 1``. There is deliberately no
 * migration framework yet — when a future schema change needs one it owns
 * its own step here, gated on the stored ``user_version``. An already-open
 * DB at the current version is left untouched (the DDL is ``IF NOT
 * EXISTS``, so re-running it is harmless, but we skip the work).
 *
 * A DB stamped at a version newer than this build (a tab running stale code
 * against a DB a newer tab upgraded) is a hard error: silently downgrading
 * would corrupt the local store.
 */

import type { Database } from '@sqlite.org/sqlite-wasm'

import { DDL } from './ddl'

export const SCHEMA_VERSION = 1

function userVersion(db: Database): number {
  const [[version]] = db.exec({
    sql: 'PRAGMA user_version',
    returnValue: 'resultRows',
    rowMode: 'array',
  })
  return version as number
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
    for (const statement of DDL) {
      db.exec(statement)
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
