/**
 * Typed wire-format for ``POST /schema`` — asset-type lifecycle slice
 * (M4.3). Mirrors :class:`novamoc.domain.schema._payloads.SchemaRequest`
 * for the five ``*_asset_type`` commands. Field-level and
 * maintenance-record-side commands are added by M4.4 / M4.5.
 *
 * Each body has the msgspec discriminator ``type`` (snake-case), an
 * ``entity_id`` UUID (client-generated for create; from the snapshot for
 * the other four), and a ``payload`` whose shape depends on the verb.
 * Empty-payload commands (activate / deactivate / delete) accept an
 * absent payload key; we send ``{}`` explicitly to keep the wire bytes
 * stable.
 */

import type { ApiClient } from './api'

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

export type SchemaCommandBody =
  | CreateAssetTypeBody
  | ActivateAssetTypeBody
  | UpdateAssetTypeBody
  | DeactivateAssetTypeBody
  | DeleteAssetTypeBody

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
