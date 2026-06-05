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

  it('upgrades a v1 DB: adds last_hlc and preserves the existing row', () => {
    // Hand-build the v1-shape sync_state (no last_hlc), the table a build
    // stamped at user_version=1 shipped. A fresh DB never takes the ALTER
    // path (STEP[0]'s DDL already has the column), so only this exercises it.
    const db = freshDb()
    db.exec(`CREATE TABLE sync_state (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      last_seen_seq INTEGER NOT NULL DEFAULT 0,
      active_schema_version INTEGER NOT NULL DEFAULT 0,
      node_id TEXT,
      last_sync_at TEXT
    )`)
    db.exec("INSERT INTO sync_state (id, last_seen_seq, node_id) VALUES (1, 7, 'node-a')")
    db.exec('PRAGMA user_version = 1')

    migrate(db)

    const hasLastHlc = db.exec({
      sql: "SELECT 1 FROM pragma_table_info('sync_state') WHERE name = 'last_hlc'",
      returnValue: 'resultRows',
      rowMode: 'array',
    })
    expect(hasLastHlc.length).toBe(1)
    expect(userVersion(db)).toBe(SCHEMA_VERSION)

    const [[seq, node, lastHlc]] = db.exec({
      sql: 'SELECT last_seen_seq, node_id, last_hlc FROM sync_state WHERE id = 1',
      returnValue: 'resultRows',
      rowMode: 'array',
    })
    expect(seq).toBe(7)
    expect(node).toBe('node-a')
    expect(lastHlc).toBeNull()
    db.close()
  })

  it('upgrades a v2 DB: adds the pending_schema_buffer table', () => {
    // A build stamped at user_version=2 had every table except the
    // schema-version-gated buffer. The 2->3 step backfills it.
    const db = freshDb()
    db.exec('CREATE TABLE sync_state (id INTEGER PRIMARY KEY CHECK (id = 1))')
    db.exec('INSERT INTO sync_state (id) VALUES (1)')
    db.exec('PRAGMA user_version = 2')

    migrate(db)

    const hasBuffer = db.exec({
      sql: "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pending_schema_buffer'",
      returnValue: 'resultRows',
      rowMode: 'array',
    })
    expect(hasBuffer.length).toBe(1)
    expect(userVersion(db)).toBe(SCHEMA_VERSION)
    db.close()
  })

  it('upgrades a v3 DB: adds the snapshot-resume columns, preserves the row', () => {
    // A build stamped at user_version=3 had sync_state without the snapshot
    // checkpoint columns. The 3->4 step backfills both; a fresh DB never takes
    // the ALTER path, so only this exercises it.
    const db = freshDb()
    db.exec(`CREATE TABLE sync_state (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      last_seen_seq INTEGER NOT NULL DEFAULT 0,
      active_schema_version INTEGER NOT NULL DEFAULT 0,
      node_id TEXT,
      last_sync_at TEXT,
      last_hlc TEXT
    )`)
    db.exec("INSERT INTO sync_state (id, last_seen_seq, last_hlc) VALUES (1, 9, 'h-9')")
    db.exec('PRAGMA user_version = 3')

    migrate(db)

    const cols = db.exec({
      sql: "SELECT name FROM pragma_table_info('sync_state') WHERE name IN ('snapshot_page', 'snapshot_schema_version')",
      returnValue: 'resultRows',
      rowMode: 'array',
    })
    expect(cols.length).toBe(2)
    expect(userVersion(db)).toBe(SCHEMA_VERSION)

    const [[seq, lastHlc, page, snapVersion]] = db.exec({
      sql: 'SELECT last_seen_seq, last_hlc, snapshot_page, snapshot_schema_version FROM sync_state WHERE id = 1',
      returnValue: 'resultRows',
      rowMode: 'array',
    })
    expect(seq).toBe(9)
    expect(lastHlc).toBe('h-9')
    expect(page).toBeNull()
    expect(snapVersion).toBeNull()
    db.close()
  })
})
