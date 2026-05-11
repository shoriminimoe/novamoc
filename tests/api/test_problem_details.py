from __future__ import annotations

import msgspec
from litestar.exceptions import ValidationException
from litestar.plugins.problem_details import ProblemDetailsException

from novamoc.api._problem_details import (
    ProblemDetails,
    make_domain_error_converter,
    make_litestar_validation_error_converter,
    make_msgspec_validation_error_converter,
)
from novamoc.domain._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)

_BASE_URL = "http://test"


def test_problem_details_minimal_encode() -> None:
    pd = ProblemDetails(
        type="http://test/problems/name_reserved.html",
        title="Name reserved",
        status=409,
        detail="Name is already in use by another entity.",
        instance="urn:uuid:01JABC...",
    )
    encoded = msgspec.json.decode(msgspec.json.encode(pd))
    assert encoded == {
        "type": "http://test/problems/name_reserved.html",
        "title": "Name reserved",
        "status": 409,
        "detail": "Name is already in use by another entity.",
        "instance": "urn:uuid:01JABC...",
    }


def test_schema_command_error_conflict_renders_409_with_extras() -> None:
    convert = make_domain_error_converter(_BASE_URL)
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    pd_exc = convert(exc)

    assert isinstance(pd_exc, ProblemDetailsException)
    assert pd_exc.status_code == 409
    assert pd_exc.type_ == "http://test/problems/name_reserved.html"
    assert pd_exc.title == "Name reserved"
    assert pd_exc.detail == "Name is already in use by another entity."
    assert pd_exc.instance is not None
    assert pd_exc.instance.startswith("urn:uuid:")
    assert pd_exc.extra == {"name": "Truck"}


def test_schema_command_error_payload_shape_renders_400() -> None:
    convert = make_domain_error_converter(_BASE_URL)
    exc = PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    pd_exc = convert(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "http://test/problems/payload_no_changes.html"


def test_schema_command_error_entity_not_found_renders_404() -> None:
    convert = make_domain_error_converter(_BASE_URL)
    exc = EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    pd_exc = convert(exc)

    assert pd_exc.status_code == 404
    assert pd_exc.type_ == "http://test/problems/entity_not_found.html"


def test_msgspec_validation_error_renders_400_invalid_payload_shape() -> None:
    convert = make_msgspec_validation_error_converter(_BASE_URL)
    exc = msgspec.ValidationError("expected str, got int")
    pd_exc = convert(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "http://test/problems/invalid_payload_shape.html"
    assert pd_exc.title == "Invalid payload shape"
    assert "expected str, got int" in pd_exc.detail
    assert pd_exc.instance is not None
    assert pd_exc.instance.startswith("urn:uuid:")


def test_litestar_validation_exception_renders_400_invalid_payload_shape() -> None:
    convert = make_litestar_validation_error_converter(_BASE_URL)
    exc = ValidationException(detail="malformed body")
    pd_exc = convert(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "http://test/problems/invalid_payload_shape.html"
    assert pd_exc.title == "Invalid payload shape"
    assert pd_exc.detail == "malformed body"


def test_tenant_resolution_error_renders_401() -> None:
    from novamoc.api._problem_details import (
        make_tenant_resolution_error_converter,
    )
    from novamoc.domain.accounts import TenantResolutionError

    convert = make_tenant_resolution_error_converter(_BASE_URL)
    exc = TenantResolutionError()
    pd_exc = convert(exc)

    assert pd_exc.status_code == 401
    assert pd_exc.type_ == "http://test/problems/tenant_not_resolved.html"
    assert pd_exc.title == "Tenant not resolved"
    assert pd_exc.extra is None
