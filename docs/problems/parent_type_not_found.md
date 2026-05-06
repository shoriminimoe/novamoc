A field-level command (create / update / activate / deactivate / clear /
delete a field) referenced a parent type (asset type or
maintenance-record type) that does not exist in the tenant.

The parent type's identifier or name is included as an extension
member on the problem-details response when available.

## Common causes

- The parent type was deleted before the field-level command was
  applied.
- A typo or stale identifier in the request payload.
- Cross-tenant leakage in client code — IDs are scoped to a tenant.

## How to fix

- Confirm the parent type exists in the tenant via the schema read
  endpoint (`GET /schema`).
- If the parent was deleted, recreate it (or its replacement) before
  resubmitting field-level commands.

## Related

- `entity_not_found` — the same family of "target does not exist"
  failures, applied to entity-level commands rather than field-level.
