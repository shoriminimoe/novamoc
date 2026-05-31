/**
 * Client-side DDL for the local SQLite-WASM database (ADR-003).
 *
 * Mirrors the server's tenant-scoped projection and log tables (ADR-012 /
 * ADR-019 projections, ADR-011 event log) modulo SQLite type affinity:
 * the server's ``GUID`` columns land as ``TEXT``, ``JsonB`` as ``TEXT``
 * (JSON serialised by the fold), booleans as ``INTEGER`` (0/1), and the
 * UTC audit timestamps as ``TEXT`` (ISO-8601). ``tenant_id`` is carried on
 * every table to match the server (ADR-014 / ADR-020); only one tenant's
 * DB file is open at a time (the file path is keyed by tenant), so the
 * column is for wire/fold parity rather than in-DB isolation.
 *
 * Three tables have no server counterpart: ``event_log`` here is the
 * client's local copy of the catch-up stream sufficient to drive the fold;
 * ``local_pending_events`` holds writes generated offline that have not yet
 * been POSTed; ``sync_state`` is a single-row table of replication
 * bookkeeping. The repository façade and the fold land in later issues —
 * this file only declares the shape.
 *
 * ``col:name`` and named columns are deliberately NOT split out the way the
 * server does; the client reconstructs derived entity JSON from per-field
 * rows (ADR-015), so the projection tables keep a JSON ``properties`` blob.
 *
 * Names use ``NOCASE`` collation where the server applies case-insensitive
 * uniqueness on schema entity names. Foreign keys mirror the server's
 * tenant-composite references so ``PRAGMA foreign_keys=ON`` enforces them.
 */

export const DDL: readonly string[] = [
  // --- Schema projections (server-authoritative, ADR-008) ---

  `CREATE TABLE IF NOT EXISTS asset_types (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, name)
  )`,

  `CREATE TABLE IF NOT EXISTS asset_type_fields (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    data_type TEXT NOT NULL,
    validation TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, parent_id, name),
    FOREIGN KEY (tenant_id, parent_id)
      REFERENCES asset_types (tenant_id, id) ON DELETE CASCADE
  )`,

  `CREATE TABLE IF NOT EXISTS maintenance_record_types (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, name)
  )`,

  `CREATE TABLE IF NOT EXISTS maintenance_record_type_fields (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    data_type TEXT NOT NULL,
    validation TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, parent_id, name),
    FOREIGN KEY (tenant_id, parent_id)
      REFERENCES maintenance_record_types (tenant_id, id) ON DELETE CASCADE
  )`,

  `CREATE TABLE IF NOT EXISTS schema_change_log (
    tenant_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    command TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    committed_at TEXT,
    actor_id TEXT,
    PRIMARY KEY (tenant_id, seq)
  )`,

  // --- Data projections (folded from the event log, ADR-012 / ADR-019) ---

  `CREATE TABLE IF NOT EXISTS assets (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    type_id TEXT NOT NULL,
    name TEXT,
    properties TEXT NOT NULL DEFAULT '{}',
    deleted INTEGER NOT NULL DEFAULT 0,
    row_state_hlc TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, type_id)
      REFERENCES asset_types (tenant_id, id)
  )`,

  `CREATE TABLE IF NOT EXISTS asset_field_values (
    tenant_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    value_json TEXT,
    hlc TEXT NOT NULL,
    PRIMARY KEY (tenant_id, asset_id, field_id),
    FOREIGN KEY (tenant_id, asset_id)
      REFERENCES assets (tenant_id, id)
  )`,

  `CREATE TABLE IF NOT EXISTS maintenance_records (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    type_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    name TEXT,
    properties TEXT NOT NULL DEFAULT '{}',
    deleted INTEGER NOT NULL DEFAULT 0,
    row_state_hlc TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, type_id)
      REFERENCES maintenance_record_types (tenant_id, id),
    FOREIGN KEY (tenant_id, asset_id)
      REFERENCES assets (tenant_id, id)
  )`,

  `CREATE TABLE IF NOT EXISTS maintenance_record_field_values (
    tenant_id TEXT NOT NULL,
    maintenance_record_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    value_json TEXT,
    hlc TEXT NOT NULL,
    PRIMARY KEY (tenant_id, maintenance_record_id, field_id),
    FOREIGN KEY (tenant_id, maintenance_record_id)
      REFERENCES maintenance_records (tenant_id, id)
  )`,

  // --- Client-only tables ---

  // Local copy of the catch-up stream (ADR-011). ``seq`` is the server's
  // globally monotonic cursor; per-tenant gaps are expected and fine.
  `CREATE TABLE IF NOT EXISTS event_log (
    seq INTEGER PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    hlc TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    table_name TEXT NOT NULL,
    type_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_id TEXT,
    op TEXT NOT NULL,
    value_json TEXT,
    received_at TEXT,
    UNIQUE (tenant_id, hlc)
  )`,

  // Writes generated locally that have not yet been POSTed. ``client_seq``
  // is a local monotonic ordering key; ``hlc`` is assigned at write time.
  `CREATE TABLE IF NOT EXISTS local_pending_events (
    client_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    hlc TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    table_name TEXT NOT NULL,
    type_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_id TEXT,
    op TEXT NOT NULL,
    value_json TEXT,
    created_at TEXT,
    UNIQUE (tenant_id, hlc)
  )`,

  // Single-row replication bookkeeping. ``id`` is pinned to 1 by a CHECK so
  // the table can hold at most one row.
  `CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_seen_seq INTEGER NOT NULL DEFAULT 0,
    active_schema_version INTEGER NOT NULL DEFAULT 0,
    node_id TEXT,
    last_sync_at TEXT
  )`,

  `INSERT OR IGNORE INTO sync_state (id) VALUES (1)`,
]
