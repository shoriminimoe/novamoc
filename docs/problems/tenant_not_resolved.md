The request did not present credentials that resolve to a known
tenant, or the credentials were structurally invalid.

The response is intentionally minimal: no extension members, no
breakdown of *which* part of the credential failed. That asymmetry is
deliberate — it does not reveal whether the bearer prefix, format, or
mapping was the problem. When token formats grow, additional codes
will split out and extras can carry per-code context.

## Common causes

- The `Authorization` header is missing.
- The header is not of the form `Bearer <token>`.
- The token does not map to any known tenant in the dev resolver
  (currently a single hardcoded tenant — see ADR-017).

## How to fix

- Send `Authorization: Bearer <token>` on every request.
- During development, use the dev token published by the test suite
  (`_TENANT_T1_DEV_TOKEN` in `novamoc.domain.accounts._resolver`).

## Related

- ADR-014 — multi-tenancy model.
- ADR-017 — tenant resolution from the request envelope.
