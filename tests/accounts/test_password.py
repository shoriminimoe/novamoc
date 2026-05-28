"""Tests for PasswordHasher (M5.5, issue #87).

Argon2id at defaults takes ~100-300 ms per hash, which makes five full-cost
round-trips unacceptably slow for a unit test suite. All tests here use a
deliberately weakened hasher (``time_cost=1, memory_cost_kib=8192,
parallelism=1``) to keep the suite under 2 s. The production defaults remain
on the class (``time_cost=3, memory_cost_kib=65536, parallelism=4``) per OWASP
/ RFC 9106; only the test-local instances are tuned down.
"""

# hardcoded test password literals

from __future__ import annotations

from novamoc.domain.accounts._password import PasswordHasher

_FAST = PasswordHasher(time_cost=1, memory_cost_kib=8192, parallelism=1)


def test_verify_wrong_password_returns_false_no_exception() -> None:
    encoded = _FAST.hash("correct-horse-battery-staple")

    assert _FAST.verify(encoded, "wrong-password") is False


def test_check_needs_rehash_after_cost_bump() -> None:
    low_cost = PasswordHasher(time_cost=1, memory_cost_kib=8192, parallelism=1)
    encoded = low_cost.hash("hunter2")

    higher_cost = PasswordHasher(time_cost=2, memory_cost_kib=8192, parallelism=1)

    assert higher_cost.check_needs_rehash(encoded) is True


def test_verify_malformed_encoded_returns_false_no_exception() -> None:
    assert _FAST.verify("not-a-hash", "hunter2") is False


def test_check_needs_rehash_malformed_returns_true_no_exception() -> None:
    assert _FAST.check_needs_rehash("not-a-hash") is True
