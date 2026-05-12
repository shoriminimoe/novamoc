/**
 * Typed wire-format for ``POST /schema`` — asset-type and asset-type-field
 * lifecycle slices (M4.3 + M4.4). Mirrors
 * :class:`novamoc.domain.schema._payloads.SchemaRequest` for the eleven
 * ``*_asset_type`` and ``*_asset_type_field`` commands.
 * Maintenance-record-side commands land in M4.5.
 *
 * Each body has the msgspec discriminator ``type`` (snake-case), an
 * ``entity_id`` UUID (client-generated for create; from the snapshot for
 * the other verbs), and a ``payload`` whose shape depends on the verb.
 * Empty-payload commands (activate / deactivate / clear / delete) accept
 * an absent payload key; we send ``{}`` explicitly to keep the wire bytes
 * stable.
 */

import type { ApiClient } from './api'
import type { FieldDataType } from './schema'

export interface CreateAssetTypeBody {
  type: 'create_asset_type'
  entity_id: string
  payload: { name: string }
}

export interface ActivateAssetTypeBody {
  type: 'activate_asset_type'
  entity_id: string
  payload: Record<string, never>
}

export interface UpdateAssetTypeBody {
  type: 'update_asset_type'
  entity_id: string
  payload: { name?: string }
}

export interface DeactivateAssetTypeBody {
  type: 'deactivate_asset_type'
  entity_id: string
  payload: Record<string, never>
}

export interface DeleteAssetTypeBody {
  type: 'delete_asset_type'
  entity_id: string
  payload: Record<string, never>
}

export interface CreateAssetTypeFieldBody {
  type: 'create_asset_type_field'
  entity_id: string
  payload: {
    parent_id: string
    name: string
    data_type: FieldDataType
    validation?: Record<string, unknown> | null
  }
}

export interface ActivateAssetTypeFieldBody {
  type: 'activate_asset_type_field'
  entity_id: string
  payload: Record<string, never>
}

export interface UpdateAssetTypeFieldBody {
  type: 'update_asset_type_field'
  entity_id: string
  payload: {
    name?: string
    data_type?: FieldDataType
    validation?: Record<string, unknown> | null
  }
}

export interface DeactivateAssetTypeFieldBody {
  type: 'deactivate_asset_type_field'
  entity_id: string
  payload: Record<string, never>
}

export interface ClearAssetTypeFieldBody {
  type: 'clear_asset_type_field'
  entity_id: string
  payload: Record<string, never>
}

export interface DeleteAssetTypeFieldBody {
  type: 'delete_asset_type_field'
  entity_id: string
  payload: Record<string, never>
}

export type SchemaCommandBody =
  | CreateAssetTypeBody
  | ActivateAssetTypeBody
  | UpdateAssetTypeBody
  | DeactivateAssetTypeBody
  | DeleteAssetTypeBody
  | CreateAssetTypeFieldBody
  | ActivateAssetTypeFieldBody
  | UpdateAssetTypeFieldBody
  | DeactivateAssetTypeFieldBody
  | ClearAssetTypeFieldBody
  | DeleteAssetTypeFieldBody

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
