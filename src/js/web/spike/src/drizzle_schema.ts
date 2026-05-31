/**
 * Candidate 3 — DRIZZLE schema.
 *
 * Schema declared once with drizzle-orm/sqlite-core column builders. The
 * `properties` JSON column uses Drizzle's native `.$type<T>()` + mode:'json'
 * so reads/writes are typed AND (de)serialized automatically — no manual
 * JSON.stringify at the call site. drizzle-kit generates DDL migrations from
 * this same file (see drizzle.config.ts).
 */
import { sqliteTable, text, integer, primaryKey } from 'drizzle-orm/sqlite-core'

export const assets = sqliteTable(
  'assets',
  {
    tenantId: text('tenant_id').notNull(),
    id: text('id').notNull(),
    typeId: text('type_id').notNull(),
    name: text('name'),
    properties: text('properties', { mode: 'json' })
      .$type<Record<string, unknown>>()
      .notNull()
      .default({}),
    deleted: integer('deleted', { mode: 'boolean' }).notNull().default(false),
    rowStateHlc: text('row_state_hlc').notNull(),
  },
  (t) => [primaryKey({ columns: [t.tenantId, t.id] })],
)

export const assetFieldValues = sqliteTable(
  'asset_field_values',
  {
    tenantId: text('tenant_id').notNull(),
    assetId: text('asset_id').notNull(),
    fieldId: text('field_id').notNull(),
    valueJson: text('value_json', { mode: 'json' }).$type<unknown>(),
    hlc: text('hlc').notNull(),
  },
  (t) => [primaryKey({ columns: [t.tenantId, t.assetId, t.fieldId] })],
)
