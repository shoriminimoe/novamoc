from __future__ import annotations

import pytest
from litestar.datastructures import Headers

from novamoc.domain.accounts import TenantResolutionError


def test_valid_bearer_returns_t1_context() -> None:
    from novamoc.domain.accounts._resolver import (
        _TENANT_T1,
        _TENANT_T1_DEV_TOKEN,
        resolve_tenant,
    )

    headers = Headers({"authorization": f"Bearer {_TENANT_T1_DEV_TOKEN}"})
    assert resolve_tenant(headers) == _TENANT_T1


def test_missing_authorization_header_raises() -> None:
    from novamoc.domain.accounts._resolver import resolve_tenant

    with pytest.raises(TenantResolutionError):
        resolve_tenant(Headers())


def test_wrong_scheme_raises() -> None:
    from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN, resolve_tenant

    for scheme in ("Basic", "Token", "bearer"):  # case-sensitive per RFC 6750
        headers = Headers({"authorization": f"{scheme} {_TENANT_T1_DEV_TOKEN}"})
        with pytest.raises(TenantResolutionError):
            resolve_tenant(headers)


def test_wrong_token_raises() -> None:
    from novamoc.domain.accounts._resolver import resolve_tenant

    headers = Headers({"authorization": "Bearer not-the-real-token"})
    with pytest.raises(TenantResolutionError):
        resolve_tenant(headers)


def test_empty_token_raises() -> None:
    from novamoc.domain.accounts._resolver import resolve_tenant

    headers = Headers({"authorization": "Bearer "})
    with pytest.raises(TenantResolutionError):
        resolve_tenant(headers)


def test_authorization_value_with_extra_whitespace_raises() -> None:
    from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN, resolve_tenant

    # Tightest reasonable acceptance: exact "Bearer <single-token>" shape.
    headers = Headers({"authorization": f"Bearer  {_TENANT_T1_DEV_TOKEN}"})
    with pytest.raises(TenantResolutionError):
        resolve_tenant(headers)
