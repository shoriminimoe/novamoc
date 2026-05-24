The login endpoint did not accept the submitted credentials.

The response body is intentionally identical for every underlying
cause — wrong password, unknown user, disabled user, and the
0-membership transient all return the same byte sequence. That symmetry
is the anti-enumeration guarantee: an attacker cannot use the response
shape to distinguish "this username exists" from "this username does
not exist" (ADR-020).

The `detail` string deliberately does not mention "password" or
"username" for the same reason. No extension members are attached.

## Common causes

- The submitted password does not match.
- The submitted username does not exist.
- The user exists but is disabled.
- The user exists but has no tenant membership yet (the v1 1:1
  invariant requires both a user row and a membership row before
  login can succeed).

## How to fix

- Re-enter the credentials. If a reset flow exists, use it.
- Operators bootstrapping a new deployment must create both the user
  and the membership via the CLI (M5.13) before login will succeed.

## Related

- ADR-020 — authentication and tenant registry.
- `user_already_has_tenant` — raised at membership creation time when
  the 1:1 invariant would be violated.
