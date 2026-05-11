from __future__ import annotations

import pytest

from novamoc.domain._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)


def test_extras_still_carried() -> None:
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    assert exc.extras == {"name": "Truck"}


@pytest.mark.parametrize(
    ("exc_cls", "code"),
    [
        (ConflictError, ErrorCode.NAME_RESERVED),
        (EntityNotFoundError, ErrorCode.ENTITY_NOT_FOUND),
        (PayloadShapeError, ErrorCode.PAYLOAD_NO_CHANGES),
    ],
)
def test_subclasses_are_distinguishable(
    exc_cls: type[ConflictError | EntityNotFoundError | PayloadShapeError],
    code: ErrorCode,
) -> None:
    with pytest.raises(exc_cls):
        raise exc_cls(code=code)
