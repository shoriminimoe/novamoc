/**
 * Migration-scaffold tests (ADR-003). Runs against a raw in-memory
 * SQLite-WASM DB — no mocks, mirroring the server's real-DB discipline —
 * so the ``user_version`` gate is exercised against actual pragma
 * behaviour rather than a stub.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import sqlite3InitModule from '@sqlite.org/sqlite-wasm'
import type { Database, Sqlite3Static } from '@sqlite.org/sqlite-wasm'

import { SCHEMA_VERSION, migrate } from '../../src/lib/db/migrations'

let sqlite3: Sqlite3Static

beforeAll(async () => {
  sqlite3 = await sqlite3InitModule()
})

function freshDb(): Database {
  return new sqlite3.oo1.DB(':memory:', 'c')
}

function userVersion(db: Database): number {
  const [[version]] = db.exec({
    sql: 'PRAGMA user_version',
    returnValue: 'resultRows',
    rowMode: 'array',
  })
  return version as number
}

describe('migrate', () => {
  it('stamps a fresh DB to the current version', () => {
    const db = freshDb()
    migrate(db)
    expect(userVersion(db)).toBe(SCHEMA_VERSION)
    db.close()
  })

  it('is a no-op on a DB already at the current version', () => {
    const db = freshDb()
    migrate(db)
    // A second run must not throw and must leave the version unchanged.
    migrate(db)
    expect(userVersion(db)).toBe(SCHEMA_VERSION)
    db.close()
  })

  it('refuses a DB stamped at a newer version than this build', () => {
    const db = freshDb()
    db.exec(`PRAGMA user_version = ${SCHEMA_VERSION + 1}`)
    expect(() => migrate(db)).toThrow(/newer than this build/)
    db.close()
  })
})
