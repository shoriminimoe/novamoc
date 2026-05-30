"""PasswordHasher wrapper over argon2-cffi (ADR-020, M5.5).

Wraps :class:`argon2.PasswordHasher` to fold the library's exception hierarchy
into a boolean return for :meth:`verify` and :meth:`check_needs_rehash`, so
callers never branch on ``VerifyMismatchError`` vs ``InvalidHashError``.  Cost
parameters live on the dataclass so settings-driven tuning is a constructor
call, not module-global state.

Inner :class:`argon2.PasswordHasher` instances are built lazily on each
call — the underlying object is cheap to construct (parameter validation only,
no I/O) and a frozen dataclass cannot hold a mutable private attribute without
``object.__setattr__``.  Lazy construction keeps the class simple.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import argon2
import argon2.exceptions

# ``InvalidHashError`` is a ``ValueError`` rather than an ``Argon2Error``,
# so both bases must be listed to fold every verify failure into ``False``.
# Named so the ``except`` clause stays unambiguously a tuple of exception
# types under both ``except A, B:`` and ``except (A, B):`` parser forms.
_VERIFY_ERRORS = (argon2.exceptions.Argon2Error, argon2.exceptions.InvalidHashError)


@dataclass(frozen=True, slots=True)
class PasswordHasher:
    """Thin wrapper over argon2-cffi with OWASP-recommended defaults.

    Defaults align with OWASP / RFC 9106 for argon2id as of 2026:
    m=64 MiB, t=3 iterations, p=4 lanes.  The login handler (M5.10) calls
    :meth:`check_needs_rehash` after every successful verify so active users
    upgrade automatically when cost parameters rotate.

    Args:
        time_cost: Number of iterations (RFC 9106 ``t``).
        memory_cost_kib: Memory in KiB (RFC 9106 ``m``); maps 1:1 to
            ``argon2.PasswordHasher(memory_cost=...)``.
        parallelism: Degree of parallelism (RFC 9106 ``p``).
    """

    time_cost: int = 3
    memory_cost_kib: int = 64 * 1024  # 64 MiB
    parallelism: int = 4

    @classmethod
    def from_defaults(cls) -> PasswordHasher:
        """Return an instance with OWASP-recommended defaults."""
        return cls()

    def _inner(self) -> argon2.PasswordHasher:
        return argon2.PasswordHasher(
            time_cost=self.time_cost,
            memory_cost=self.memory_cost_kib,
            parallelism=self.parallelism,
        )

    def hash(self, password: str) -> str:
        """Return an argon2id-encoded hash of *password*.

        Args:
            password: Plaintext password to hash.

        Returns:
            An encoded ``$argon2id$...`` string including the salt and
            cost parameters.
        """
        return self._inner().hash(password)

    def dummy_hash(self) -> str:
        """Return a fixed-content argon2id hash with this instance's parameters.

        The hash is deterministic per ``(time_cost, memory_cost_kib,
        parallelism)`` triple and cached at module level so each
        parameter set pays the construction cost only once. The login
        handler (M5.10) calls this on the unknown-user / disabled-user
        branches to feed :meth:`verify` real work whose runtime
        matches a real user's verify — closing the anti-enumeration
        timing oracle (issue #134, ADR-020).

        The plaintext (``""``), salt (whatever argon2-cffi generates),
        and embedded encoding don't matter to callers; ``verify`` will
        always reject and timing parity is the sole correctness
        property.

        Returns:
            An encoded ``$argon2id$...`` string with this instance's
            cost parameters baked in.
        """
        return _build_dummy_hash(self.time_cost, self.memory_cost_kib, self.parallelism)

    def verify(self, encoded: str, password: str) -> bool:
        """Verify *password* against an argon2id-encoded hash.

        Never raises; all argon2-cffi exception types are folded into
        ``False`` so callers do not branch on
        ``VerifyMismatchError`` vs ``InvalidHashError``.

        Args:
            encoded: The ``$argon2id$...`` string produced by :meth:`hash`.
            password: Plaintext password to check.

        Returns:
            ``True`` iff the password matches; ``False`` for any mismatch
            or malformed encoded string.
        """
        try:
            return self._inner().verify(encoded, password)
        except _VERIFY_ERRORS:
            return False

    def check_needs_rehash(self, encoded: str) -> bool:
        """Return whether *encoded* should be rehashed with current parameters.

        Malformed encoded strings are treated as needing rehash — the caller
        should hash the plaintext again under the current parameters rather
        than attempting to use an unparseable stored value.

        Args:
            encoded: The ``$argon2id$...`` string to inspect.

        Returns:
            ``True`` if the hash's embedded parameters differ from this
            instance's parameters, or if *encoded* is malformed.
        """
        try:
            return self._inner().check_needs_rehash(encoded)
        except argon2.exceptions.InvalidHashError:
            return True


@functools.cache
def _build_dummy_hash(time_cost: int, memory_cost_kib: int, parallelism: int) -> str:
    """Build a one-time argon2id hash with the given parameters.

    Cached on the parameter triple so each unique cost configuration
    pays the hash cost exactly once per process. The plaintext is
    fixed (empty string) — only the cost-parameter parity matters to
    callers.
    """
    return argon2.PasswordHasher(
        time_cost=time_cost,
        memory_cost=memory_cost_kib,
        parallelism=parallelism,
    ).hash("")
