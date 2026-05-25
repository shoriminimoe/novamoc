"""Typed exceptions raised by the accounts domain.

``TenantResolutionError`` is the credential-missing-or-unrecognized
failure: v1 maps every variant (no header, wrong scheme, wrong token)
to a single code. When token formats grow, additional codes can split
out (``token_expired``, ``token_revoked``, ...); v1 keeps it to one so
client code does not branch on dev-period internals. Subclassing
:class:`litestar.exceptions.NotAuthorizedException` is the contract
documented for ``AbstractAuthenticationMiddleware``: the base class'
``authenticate_request`` must raise ``NotAuthorizedException`` or
``PermissionDeniedException`` on failure. The custom subclass keeps the
status code and HTTP integration the framework provides while letting
the problem-details mapper assign our own type-URI leaf.

``LoginFailedError`` and ``UserAlreadyHasTenantError`` are
:class:`DomainError` subclasses that ride through the same
problem-details converter as every other domain failure. Each carries
a fixed :class:`ErrorCode` and takes no constructor arguments, so
callers ``raise LoginFailedError`` / ``raise UserAlreadyHasTenantError``
without parens.
"""

from __future__ import annotations

from litestar.exceptions import NotAuthorizedException

from novamoc.domain._errors import DomainError, ErrorCode


class TenantResolutionError(NotAuthorizedException):
    """Raised when the request envelope did not carry a recognized credential."""

    detail = "Tenant could not be resolved from request."


class LoginFailedError(DomainError):
    """Raised when credentials are not accepted by the login endpoint.

    Anti-enumeration: wrong password, unknown user, disabled user, and
    the 0-membership transient all share the same response body. The
    detail string deliberately does not mention "password" or
    "username" — see :data:`ErrorCode.LOGIN_FAILED` in
    ``domain/_errors.py`` for the canonical message.
    """

    def __init__(self) -> None:
        super().__init__(code=ErrorCode.LOGIN_FAILED)


class UserAlreadyHasTenantError(DomainError):
    """Raised by ``UserTenantMembershipService.create`` when a second
    membership is attempted for a user that already has one.

    v1 supports only one tenant per user; switching active tenant is
    not yet available (ADR-020). The structural backstop is the
    ``UNIQUE(user_id)`` constraint on ``user_tenant_memberships``; this
    friendly error is what the service raises after its pre-check.
    """

    def __init__(self) -> None:
        super().__init__(code=ErrorCode.USER_ALREADY_HAS_TENANT)
