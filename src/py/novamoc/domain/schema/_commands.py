from __future__ import annotations

from enum import StrEnum


class SchemaCommand(StrEnum):
    """Commands accepted by ``POST /schema`` (ADR-008).

    Five verbs (activate / deactivate / update / clear / delete) prefixed by
    entity kind. ``clear`` applies to fields only — types do not have a
    field-value notion. Validity of a (command, payload) pair is enforced at
    the API decoder; storage carries the command as plain TEXT so adding new
    entity kinds or commands is a domain change, not a migration.
    """

    ACTIVATE_ASSET_TYPE = "activate_asset_type"
    DEACTIVATE_ASSET_TYPE = "deactivate_asset_type"
    UPDATE_ASSET_TYPE = "update_asset_type"
    DELETE_ASSET_TYPE = "delete_asset_type"

    ACTIVATE_ASSET_TYPE_FIELD = "activate_asset_type_field"
    DEACTIVATE_ASSET_TYPE_FIELD = "deactivate_asset_type_field"
    UPDATE_ASSET_TYPE_FIELD = "update_asset_type_field"
    CLEAR_ASSET_TYPE_FIELD = "clear_asset_type_field"
    DELETE_ASSET_TYPE_FIELD = "delete_asset_type_field"

    ACTIVATE_MAINTENANCE_RECORD_TYPE = "activate_maintenance_record_type"
    DEACTIVATE_MAINTENANCE_RECORD_TYPE = "deactivate_maintenance_record_type"
    UPDATE_MAINTENANCE_RECORD_TYPE = "update_maintenance_record_type"
    DELETE_MAINTENANCE_RECORD_TYPE = "delete_maintenance_record_type"

    ACTIVATE_MAINTENANCE_RECORD_TYPE_FIELD = "activate_maintenance_record_type_field"
    DEACTIVATE_MAINTENANCE_RECORD_TYPE_FIELD = "deactivate_maintenance_record_type_field"
    UPDATE_MAINTENANCE_RECORD_TYPE_FIELD = "update_maintenance_record_type_field"
    CLEAR_MAINTENANCE_RECORD_TYPE_FIELD = "clear_maintenance_record_type_field"
    DELETE_MAINTENANCE_RECORD_TYPE_FIELD = "delete_maintenance_record_type_field"
