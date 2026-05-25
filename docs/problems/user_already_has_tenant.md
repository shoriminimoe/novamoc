A second membership row was attempted for a user that already belongs
to a tenant.

v1 supports only one tenant per user (ADR-020). The underlying
`user_tenant_memberships` table is N-to-N at the schema level —
the 1:1 restriction is a service-layer invariant enforced at write
time by `UserTenantMembershipService.create`, with the
`UNIQUE(user_id)` column constraint as a structural backstop for any
path that bypasses the service.

## Common causes

- A bootstrap script tried to attach a second tenant to an existing
  user. v1 has no UI or CLI for switching active tenant; this is the
  invariant rejecting the write rather than a transient error.

## How to fix

- Delete the existing membership first if the intent was to move the
  user to a different tenant. The invariant cares about live state,
  not history — once the existing row is gone, the new one can be
  created.
- A multi-tenant-per-user mode is not on the v1 roadmap; if you need
  one user to access two tenants, create a second user.

## Related

- ADR-020 — authentication and tenant registry.
- `login_failed` — the user-facing login path that depends on a
  membership existing.
