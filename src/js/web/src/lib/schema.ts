/**
 * Typed wire-format for ``GET /schema`` (M4.2).
 *
 * Mirrors :class:`novamoc.domain.schema._read_payloads.SchemaSnapshotResponse`.
 * Tombstoned entries (``active=false``) are included; the UI filters them at
 * render time per ADR-008 / ADR-009.
 */

import type { ApiClient } from './api'
import type {
  FieldDataType,
  SchemaSnapshotWire,
  SchemaWireField,
  SchemaWireType,
} from './db/types'

// The wire shape is defined once in `db/types.ts` (the fold's single source
// of truth) and surfaced here under the HTTP client's names so the two cannot
// drift. A plain type import from a sibling client `lib/` module carries no
// Litestar/runtime edge, so the db-layer layering rule is unaffected.
export type { FieldDataType }
export type FieldView = SchemaWireField
export type TypeView = SchemaWireType
export type SchemaSnapshot = SchemaSnapshotWire

export function fetchSchema(client: ApiClient): Promise<SchemaSnapshot> {
  return client.get<SchemaSnapshot>('/schema')
}
