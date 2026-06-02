/**
 * Read-only views over the server-authoritative schema projection (ADR-008).
 *
 * E3/E4 use these to render type-appropriate widgets — the field set and data
 * types of a given asset/record type. Schema is server-authoritative and never
 * written locally (it arrives via the schema-change-log fold), so this repo is
 * read-only. Tombstoned (`active = 0`) rows are included; callers filter at
 * read time per use case (ADR-008/ADR-009).
 */

import type { TenantContext, TenantScoped } from './_tenant'
import type { TypeFieldRow, TypeRow } from './_rows'
import { parseJson, toBool } from './_sql'

const TYPE_COLUMNS = 'id, name, active'
const FIELD_COLUMNS = 'id, parent_id, name, data_type, validation, active'

function rowToType<B>(row: unknown[]): TenantScoped<TypeRow, B> {
  return {
    id: row[0] as string,
    name: row[1] as string,
    active: toBool(row[2]),
  } as TenantScoped<TypeRow, B>
}

function rowToField<B>(row: unknown[]): TenantScoped<TypeFieldRow, B> {
  return {
    id: row[0] as string,
    parent_id: row[1] as string,
    name: row[2] as string,
    data_type: row[3] as string,
    validation: parseJson(row[4]),
    active: toBool(row[5]),
  } as TenantScoped<TypeFieldRow, B>
}

export interface SchemaProjectionRepo<B> {
  listAssetTypes(): Promise<TenantScoped<TypeRow, B>[]>
  listAssetTypeFields(parentId: string): Promise<TenantScoped<TypeFieldRow, B>[]>
  listRecordTypes(): Promise<TenantScoped<TypeRow, B>[]>
  listRecordTypeFields(
    parentId: string,
  ): Promise<TenantScoped<TypeFieldRow, B>[]>
}

export function makeSchemaProjectionRepo<B>(
  ctx: TenantContext<B>,
): SchemaProjectionRepo<B> {
  const { db, tenantId } = ctx

  return {
    async listAssetTypes() {
      const rows = await db.exec(
        `SELECT ${TYPE_COLUMNS} FROM asset_types WHERE tenant_id = ? ORDER BY name`,
        [tenantId],
      )
      return rows.map((row) => rowToType<B>(row))
    },

    async listAssetTypeFields(parentId) {
      const rows = await db.exec(
        `SELECT ${FIELD_COLUMNS} FROM asset_type_fields
         WHERE tenant_id = ? AND parent_id = ? ORDER BY name`,
        [tenantId, parentId],
      )
      return rows.map((row) => rowToField<B>(row))
    },

    async listRecordTypes() {
      const rows = await db.exec(
        `SELECT ${TYPE_COLUMNS} FROM maintenance_record_types WHERE tenant_id = ? ORDER BY name`,
        [tenantId],
      )
      return rows.map((row) => rowToType<B>(row))
    },

    async listRecordTypeFields(parentId) {
      const rows = await db.exec(
        `SELECT ${FIELD_COLUMNS} FROM maintenance_record_type_fields
         WHERE tenant_id = ? AND parent_id = ? ORDER BY name`,
        [tenantId, parentId],
      )
      return rows.map((row) => rowToField<B>(row))
    },
  }
}
