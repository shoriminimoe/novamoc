/**
 * Domain row shapes mirroring the server projections
 * (src/py/novamoc/db/models/data/_asset.py).
 *
 * - assets: (tenant_id, id) composite PK, `properties` JSON column.
 * - asset_field_values: (tenant_id, asset_id, field_id) PK, `hlc` ordering.
 */

export interface Asset {
  tenantId: string
  id: string
  typeId: string
  name: string | null
  properties: Record<string, unknown>
  deleted: boolean
  rowStateHlc: string
}

export interface AssetFieldValue {
  tenantId: string
  assetId: string
  fieldId: string
  valueJson: unknown
  hlc: string
}

/** Result of the assets × asset_field_values join. */
export interface AssetWithField {
  assetId: string
  assetName: string | null
  fieldId: string
  valueJson: unknown
  hlc: string
}
