from __future__ import annotations

import msgspec
from litestar.exceptions import ValidationException
from litestar.plugins.problem_details import ProblemDetailsException

from novamoc.api._problem_details import (
    ProblemDetails,
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_error_to_problem_details,
)
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)


def test_problem_details_minimal_encode() -> None:
    pd = ProblemDetails(
        type="urn:novamoc:problems:name_reserved",
        title="Name reserved",
        status=409,
        detail="Name is already in use by another entity.",
        instance="urn:uuid:01JABC...",
    )
    encoded = msgspec.json.decode(msgspec.json.encode(pd))
    assert encoded == {
        "type": "urn:novamoc:problems:name_reserved",
        "title": "Name reserved",
        "status": 409,
        "detail": "Name is already in use by another entity.",
        "instance": "urn:uuid:01JABC...",
    }


def test_schema_command_error_conflict_renders_409_with_extras() -> None:
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    pd_exc = schema_error_to_problem_details(exc)

    assert isinstance(pd_exc, ProblemDetailsException)
    assert pd_exc.status_code == 409
    assert pd_exc.type_ == "urn:novamoc:problems:name_reserved"
    assert pd_exc.title == "Name reserved"
    assert pd_exc.detail == "Name is already in use by another entity."
    assert pd_exc.instance is not None
    assert pd_exc.instance.startswith("urn:uuid:")
    assert pd_exc.extra == {"name": "Truck"}


def test_schema_command_error_payload_shape_renders_400() -> None:
    exc = PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    pd_exc = schema_error_to_problem_details(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "urn:novamoc:problems:payload_no_changes"


def test_schema_command_error_entity_not_found_renders_404() -> None:
    exc = EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    pd_exc = schema_error_to_problem_details(exc)

    assert pd_exc.status_code == 404
    assert pd_exc.type_ == "urn:novamoc:problems:entity_not_found"


def test_msgspec_validation_error_renders_400_invalid_payload_shape() -> None:
    exc = msgspec.ValidationError("expected str, got int")
    pd_exc = msgspec_validation_error_to_problem_details(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "urn:novamoc:problems:invalid_payload_shape"
    assert pd_exc.title == "Invalid payload shape"
    assert "expected str, got int" in pd_exc.detail
    assert pd_exc.instance is not None and pd_exc.instance.startswith("urn:uuid:")


def test_litestar_validation_exception_renders_400_invalid_payload_shape() -> None:
    exc = ValidationException(detail="malformed body")
    pd_exc = litestar_validation_error_to_problem_details(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "urn:novamoc:problems:invalid_payload_shape"
    assert pd_exc.title == "Invalid payload shape"
    assert pd_exc.detail == "malformed body"


def test_schema_error_tenant_not_found_renders_404_with_extras() -> None:
    from novamoc.domain.schema._errors import TenantNotFoundError

    exc = TenantNotFoundError(code=ErrorCode.TENANT_NOT_FOUND, tenant_id="who-dis")
    pd_exc = schema_error_to_problem_details(exc)

    assert pd_exc.status_code == 404
    assert pd_exc.type_ == "urn:novamoc:problems:tenant_not_found"
    assert pd_exc.title == "Tenant not found"
    assert pd_exc.extra == {"tenant_id": "who-dis"}
