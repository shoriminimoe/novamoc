"""Primitive-level tests for the contextvar and use_tenant helper.

Each test opts out of the autouse ``tenant`` fixture so the assertions
are about the underlying ContextVar's behaviour, not the test
infrastructure that wraps it.
"""

from __future__ import annotations

import pytest

from novamoc.db._tenant_context import current_tenant_id, use_tenant
from tests._constants import DEV_TENANT_ID_A, DEV_TENANT_ID_B


@pytest.mark.no_tenant
def test_default_is_none() -> None:
    assert current_tenant_id.get() is None


@pytest.mark.no_tenant
def test_use_tenant_sets_and_resets() -> None:
    assert current_tenant_id.get() is None
    with use_tenant(DEV_TENANT_ID_A):
        assert current_tenant_id.get() == DEV_TENANT_ID_A
    assert current_tenant_id.get() is None


@pytest.mark.no_tenant
def test_use_tenant_nested() -> None:
    with use_tenant(DEV_TENANT_ID_A):
        with use_tenant(DEV_TENANT_ID_B):
            assert current_tenant_id.get() == DEV_TENANT_ID_B
        assert current_tenant_id.get() == DEV_TENANT_ID_A
    assert current_tenant_id.get() is None


@pytest.mark.no_tenant
def test_use_tenant_resets_on_exception() -> None:
    def _under_tenant() -> None:
        assert current_tenant_id.get() == DEV_TENANT_ID_A
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"), use_tenant(DEV_TENANT_ID_A):
        _under_tenant()
    assert current_tenant_id.get() is None
