"""Round-trip tests for the request-body discriminated union.

Each command's wire shape is encoded and decoded as the union; the test
asserts the runtime variant class plus the typed payload field.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import msgspec
import pytest

from novamoc.domain.schema import _payloads

_ENTITY = "01958f3b-3b9f-7d3a-89aa-000000000001"
_PARENT = "01958f3b-3b9f-7d3a-89aa-000000000aaa"


def _decode(body: dict) -> _payloads.SchemaRequest:
    return msgspec.json.decode(json.dumps(body).encode(), type=_payloads.SchemaRequest)


# --- AssetType ---


def test_create_asset_type() -> None:
    obj = _decode(
        {
            "type": "create_asset_type",
            "entity_id": _ENTITY,
            "payload": {"name": "Truck"},
        }
    )
    assert isinstance(obj, _payloads.CreateAssetType)
    assert isinstance(obj.payload, _payloads._AssetTypeCreatePayload)
    assert obj.payload.name == "Truck"
    assert obj.entity_id == UUID(_ENTITY)


def test_create_asset_type_requires_name() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode(
            {
                "type": "create_asset_type",
                "entity_id": _ENTITY,
                "payload": {},  # name missing → 400 invalid_payload_shape
            }
        )


def test_activate_asset_type_takes_empty_payload() -> None:
    obj = _decode(
        {
            "type": "activate_asset_type",
            "entity_id": _ENTITY,
            "payload": {},
        }
    )
    assert isinstance(obj, _payloads.ActivateAssetType)
    assert isinstance(obj.payload, _payloads._Empty)


def test_activate_asset_type_allows_omitted_payload() -> None:
    """No-payload commands accept the ``payload`` key being absent on the wire."""
    obj = _decode(
        {
            "type": "activate_asset_type",
            "entity_id": _ENTITY,
        }
    )
    assert isinstance(obj, _payloads.ActivateAssetType)
    assert obj.payload is msgspec.UNSET


def test_activate_asset_type_rejects_payload_fields() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode(
            {
                "type": "activate_asset_type",
                "entity_id": _ENTITY,
                "payload": {"name": "Truck"},
            }
        )


def test_update_asset_type_partial() -> None:
    obj = _decode(
        {
            "type": "update_asset_type",
            "entity_id": _ENTITY,
            "payload": {"name": "Lorry"},
        }
    )
    assert isinstance(obj, _payloads.UpdateAssetType)
    assert isinstance(obj.payload, _payloads._AssetTypeUpdatePayload)
    assert obj.payload.name == "Lorry"


def test_deactivate_and_delete_require_empty_payload() -> None:
    deact = _decode(
        {
            "type": "deactivate_asset_type",
            "entity_id": _ENTITY,
            "payload": {},
        }
    )
    assert isinstance(deact, _payloads.DeactivateAssetType)
    assert isinstance(deact.payload, _payloads._Empty)

    delete = _decode(
        {
            "type": "delete_asset_type",
            "entity_id": _ENTITY,
            "payload": {},
        }
    )
    assert isinstance(delete, _payloads.DeleteAssetType)
    assert isinstance(delete.payload, _payloads._Empty)


def test_empty_payload_struct_rejects_unknown_fields() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode(
            {
                "type": "deactivate_asset_type",
                "entity_id": _ENTITY,
                "payload": {"name": "x"},
            }
        )


def test_unknown_command_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode(
            {
                "type": "do_a_barrel_roll",
                "entity_id": _ENTITY,
                "payload": {},
            }
        )


# --- AssetTypeField ---


def test_create_asset_type_field() -> None:
    obj = _decode(
        {
            "type": "create_asset_type_field",
            "entity_id": _ENTITY,
            "payload": {
                "parent_id": _PARENT,
                "name": "vin",
                "data_type": "text",
                "validation": {"max_length": 17},
            },
        }
    )
    assert isinstance(obj, _payloads.CreateAssetTypeField)
    assert isinstance(obj.payload, _payloads._AssetTypeFieldCreatePayload)
    assert obj.payload.parent_id == UUID(_PARENT)
    assert obj.payload.name == "vin"
    assert obj.payload.data_type == "text"
    assert obj.payload.validation == {"max_length": 17}


def test_create_asset_type_field_requires_data_type() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode(
            {
                "type": "create_asset_type_field",
                "entity_id": _ENTITY,
                "payload": {"parent_id": _PARENT, "name": "vin"},  # data_type missing
            }
        )


def test_update_asset_type_field_partial() -> None:
    obj = _decode(
        {
            "type": "update_asset_type_field",
            "entity_id": _ENTITY,
            "payload": {"name": "vin_number"},
        }
    )
    assert isinstance(obj, _payloads.UpdateAssetTypeField)
    assert obj.payload.name == "vin_number"
    assert obj.payload.data_type is msgspec.UNSET
    assert obj.payload.validation is msgspec.UNSET


def test_update_asset_type_field_distinguishes_unset_from_explicit_null() -> None:
    """Sending ``{"validation": null}`` must clear the column to NULL."""
    obj = _decode(
        {
            "type": "update_asset_type_field",
            "entity_id": _ENTITY,
            "payload": {"validation": None},
        }
    )
    assert isinstance(obj, _payloads.UpdateAssetTypeField)
    assert obj.payload.validation is None
    assert obj.payload.name is msgspec.UNSET
    serialized = msgspec.to_builtins(obj.payload)
    assert serialized == {"validation": None}


@pytest.mark.parametrize(
    ("command", "cls"),
    [
        ("activate_asset_type_field", _payloads.ActivateAssetTypeField),
        ("deactivate_asset_type_field", _payloads.DeactivateAssetTypeField),
        ("clear_asset_type_field", _payloads.ClearAssetTypeField),
        ("delete_asset_type_field", _payloads.DeleteAssetTypeField),
    ],
)
def test_asset_type_field_empty_payload_commands(command: str, cls: type) -> None:
    obj = _decode(
        {
            "type": command,
            "entity_id": _ENTITY,
            "payload": {},
        }
    )
    assert isinstance(obj, cls)


# --- MaintenanceRecordType ---


def test_create_maintenance_record_type() -> None:
    obj = _decode(
        {
            "type": "create_maintenance_record_type",
            "entity_id": _ENTITY,
            "payload": {"name": "Oil Change"},
        }
    )
    assert isinstance(obj, _payloads.CreateMaintenanceRecordType)
    assert isinstance(obj.payload, _payloads._MaintenanceRecordTypeCreatePayload)
    assert obj.payload.name == "Oil Change"


def test_update_maintenance_record_type_partial() -> None:
    obj = _decode(
        {
            "type": "update_maintenance_record_type",
            "entity_id": _ENTITY,
            "payload": {"name": "Annual Inspection"},
        }
    )
    assert isinstance(obj, _payloads.UpdateMaintenanceRecordType)
    assert obj.payload.name == "Annual Inspection"


@pytest.mark.parametrize(
    ("command", "cls"),
    [
        ("activate_maintenance_record_type", _payloads.ActivateMaintenanceRecordType),
        (
            "deactivate_maintenance_record_type",
            _payloads.DeactivateMaintenanceRecordType,
        ),
        ("delete_maintenance_record_type", _payloads.DeleteMaintenanceRecordType),
    ],
)
def test_maintenance_record_type_empty_payload(command: str, cls: type) -> None:
    obj = _decode(
        {
            "type": command,
            "entity_id": _ENTITY,
            "payload": {},
        }
    )
    assert isinstance(obj, cls)


# --- MaintenanceRecordTypeField ---


def test_create_maintenance_record_type_field() -> None:
    obj = _decode(
        {
            "type": "create_maintenance_record_type_field",
            "entity_id": _ENTITY,
            "payload": {
                "parent_id": _PARENT,
                "name": "mileage_at_service",
                "data_type": "integer",
            },
        }
    )
    assert isinstance(obj, _payloads.CreateMaintenanceRecordTypeField)
    assert isinstance(obj.payload, _payloads._MaintenanceRecordTypeFieldCreatePayload)
    assert obj.payload.parent_id == UUID(_PARENT)
    assert obj.payload.name == "mileage_at_service"
    assert obj.payload.data_type == "integer"


def test_update_maintenance_record_type_field_partial() -> None:
    obj = _decode(
        {
            "type": "update_maintenance_record_type_field",
            "entity_id": _ENTITY,
            "payload": {"data_type": "number"},
        }
    )
    assert isinstance(obj, _payloads.UpdateMaintenanceRecordTypeField)
    assert obj.payload.data_type == "number"


@pytest.mark.parametrize(
    ("command", "cls"),
    [
        (
            "activate_maintenance_record_type_field",
            _payloads.ActivateMaintenanceRecordTypeField,
        ),
        (
            "deactivate_maintenance_record_type_field",
            _payloads.DeactivateMaintenanceRecordTypeField,
        ),
        (
            "clear_maintenance_record_type_field",
            _payloads.ClearMaintenanceRecordTypeField,
        ),
        (
            "delete_maintenance_record_type_field",
            _payloads.DeleteMaintenanceRecordTypeField,
        ),
    ],
)
def test_maintenance_record_type_field_empty_payload(command: str, cls: type) -> None:
    obj = _decode(
        {
            "type": command,
            "entity_id": _ENTITY,
            "payload": {},
        }
    )
    assert isinstance(obj, cls)


# --- Response envelopes ---


def test_schema_response_has_expected_fields() -> None:
    resp = _payloads.SchemaResponse(
        schema_version=1,
        entity_id=UUID(_ENTITY),
        outcome="created",
        committed_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )
    encoded = msgspec.json.decode(msgspec.json.encode(resp))
    assert encoded == {
        "schema_version": 1,
        "entity_id": _ENTITY,
        "outcome": "created",
        "committed_at": "2026-05-01T12:00:00Z",
    }
