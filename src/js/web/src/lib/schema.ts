/**
 * Typed wire-format for ``GET /schema`` (M4.2).
 *
 * Mirrors :class:`novamoc.domain.schema._read_payloads.SchemaSnapshotResponse`.
 * Tombstoned entries (``active=false``) are included; the UI filters them at
 * render time per ADR-008 / ADR-009.
 */

import type { ApiClient } from './api'

export type FieldDataType =
  | 'text'
  | 'number'
  | 'integer'
  | 'boolean'
  | 'date'
  | 'datetime'

export interface FieldView {
  id: string
  name: string
  data_type: FieldDataType
  validation: Record<string, unknown> | null
  active: boolean
}

export interface TypeView {
  id: string
  name: string
  active: boolean
  fields: FieldView[]
}

export interface SchemaSnapshot {
  schema_version: number
  asset_types: TypeView[]
  maintenance_record_types: TypeView[]
}

export function fetchSchema(client: ApiClient): Promise<SchemaSnapshot> {
  return client.get<SchemaSnapshot>('/schema')
}
