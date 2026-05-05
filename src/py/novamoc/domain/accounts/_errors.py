"""Typed exceptions raised by tenant resolution.

Today the only failure mode is "credential is missing or unrecognized" —
v1 maps every variant (no header, wrong scheme, wrong token) to a single
``TenantResolutionError``. When token formats grow, additional codes can
split out (``token_expired``, ``token_revoked``, ...); v1 keeps it to one
so client code does not branch on dev-period internals.

Subclassing :class:`litestar.exceptions.NotAuthorizedException` is the
contract documented for ``AbstractAuthenticationMiddleware``: the base
class' ``authenticate_request`` must raise ``NotAuthorizedException`` or
``PermissionDeniedException`` on failure. The custom subclass keeps the
status code and HTTP integration the framework provides while letting
the problem-details mapper assign our own type-URI leaf.
"""

from __future__ import annotations

from litestar.exceptions import NotAuthorizedException


class TenantResolutionError(NotAuthorizedException):
    """Raised when the request envelope did not carry a recognized credential."""

    detail = "Tenant could not be resolved from request."
