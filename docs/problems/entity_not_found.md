The command targeted an entity (asset type, field, maintenance record
type, etc.) that does not exist in the tenant's projection.

## Common causes

- The entity was deleted in a concurrent request between the client's
  read and write.
- A stale identifier on the client.
- Cross-tenant leakage — identifiers are scoped to a tenant.

## How to fix

- Re-read the schema (`GET /schema`) to confirm the
  entity's current state and identifier.
- If the entity has been tombstoned (`active=false`), use the matching
  `activate_*` command rather than `update_*` / `clear_*` / `delete_*`.

## Related

- `parent_type_not_found` — a more specific variant for missing parent
  types in field-level commands.
- `name_reserved` — when re-creating an entity, the name may still be
  reserved by the tombstone.
