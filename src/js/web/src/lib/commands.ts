/**
 * Typed wire-format for ``POST /schema`` — full coverage of the 22
 * lifecycle commands across the four entity kinds. Mirrors
 * :class:`novamoc.domain.schema._payloads.SchemaRequest`.
 *
 * Each body has the msgspec discriminator ``type`` (snake-case), an
 * ``entity_id`` UUID (client-generated for create; from the snapshot for
 * the other verbs), and a ``payload`` whose shape depends on the verb.
 * Empty-payload commands (activate / deactivate / clear / delete) accept
 * an absent payload key; we send ``{}`` explicitly to keep the wire
 * bytes stable.
 *
 * The two type kinds (``asset_type``, ``maintenance_record_type``) and
 * the two field kinds (``asset_type_field``,
 * ``maintenance_record_type_field``) take identical payload shapes, so
 * the per-verb wire-format types are parameterised on a discriminator
 * string. The narrower per-kind aliases (``CreateAssetTypeBody`` etc.)
 * are re-exported for call sites that want a fixed shape.
 */

import type { ApiClient } from './api'
import type { FieldDataType } from './schema'

export type TypeKind = 'asset_type' | 'maintenance_record_type'
export type FieldKind = `${TypeKind}_field`
export type EntityKind = TypeKind | FieldKind

interface TypeCreateBody<K extends TypeKind> {
  type: `create_${K}`
  entity_id: string
  payload: { name: string }
}

interface TypeActivateBody<K extends TypeKind> {
  type: `activate_${K}`
  entity_id: string
  payload: Record<string, never>
}

interface TypeUpdateBody<K extends TypeKind> {
  type: `update_${K}`
  entity_id: string
  payload: { name?: string }
}

interface TypeDeactivateBody<K extends TypeKind> {
  type: `deactivate_${K}`
  entity_id: string
  payload: Record<string, never>
}

interface TypeDeleteBody<K extends TypeKind> {
  type: `delete_${K}`
  entity_id: string
  payload: Record<string, never>
}

interface FieldCreateBody<K extends FieldKind> {
  type: `create_${K}`
  entity_id: string
  payload: {
    parent_id: string
    name: string
    data_type: FieldDataType
    validation?: Record<string, unknown> | null
  }
}

interface FieldActivateBody<K extends FieldKind> {
  type: `activate_${K}`
  entity_id: string
  payload: Record<string, never>
}

interface FieldUpdateBody<K extends FieldKind> {
  type: `update_${K}`
  entity_id: string
  payload: {
    name?: string
    data_type?: FieldDataType
    validation?: Record<string, unknown> | null
  }
}

interface FieldDeactivateBody<K extends FieldKind> {
  type: `deactivate_${K}`
  entity_id: string
  payload: Record<string, never>
}

interface FieldClearBody<K extends FieldKind> {
  type: `clear_${K}`
  entity_id: string
  payload: Record<string, never>
}

interface FieldDeleteBody<K extends FieldKind> {
  type: `delete_${K}`
  entity_id: string
  payload: Record<string, never>
}

export type AssetTypeCommandBody =
  | TypeCreateBody<'asset_type'>
  | TypeActivateBody<'asset_type'>
  | TypeUpdateBody<'asset_type'>
  | TypeDeactivateBody<'asset_type'>
  | TypeDeleteBody<'asset_type'>

export type MaintenanceRecordTypeCommandBody =
  | TypeCreateBody<'maintenance_record_type'>
  | TypeActivateBody<'maintenance_record_type'>
  | TypeUpdateBody<'maintenance_record_type'>
  | TypeDeactivateBody<'maintenance_record_type'>
  | TypeDeleteBody<'maintenance_record_type'>

export type AssetTypeFieldCommandBody =
  | FieldCreateBody<'asset_type_field'>
  | FieldActivateBody<'asset_type_field'>
  | FieldUpdateBody<'asset_type_field'>
  | FieldDeactivateBody<'asset_type_field'>
  | FieldClearBody<'asset_type_field'>
  | FieldDeleteBody<'asset_type_field'>

export type MaintenanceRecordTypeFieldCommandBody =
  | FieldCreateBody<'maintenance_record_type_field'>
  | FieldActivateBody<'maintenance_record_type_field'>
  | FieldUpdateBody<'maintenance_record_type_field'>
  | FieldDeactivateBody<'maintenance_record_type_field'>
  | FieldClearBody<'maintenance_record_type_field'>
  | FieldDeleteBody<'maintenance_record_type_field'>

export type SchemaCommandBody =
  | AssetTypeCommandBody
  | MaintenanceRecordTypeCommandBody
  | AssetTypeFieldCommandBody
  | MaintenanceRecordTypeFieldCommandBody

export type Outcome =
  | 'created'
  | 'activated'
  | 'updated'
  | 'deactivated'
  | 'cleared'
  | 'deleted'
  | 'noop'

export interface SchemaCommandResponse {
  schema_version: number
  entity_id: string
  outcome: Outcome
  committed_at: string
}

export function postSchemaCommand(
  client: ApiClient,
  body: SchemaCommandBody,
): Promise<SchemaCommandResponse> {
  return client.post<SchemaCommandResponse>('/schema', body)
}
