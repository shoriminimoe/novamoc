A schema entity (asset type, asset-type field, maintenance-record
type, or maintenance-record-type field) cannot be created with the
given name because that name is already in use within the tenant.

The conflicting name is included as the `name` extension member on
the problem-details response.

## Common causes

- Two clients tried to create the same entity concurrently — the
  later request loses.
- The entity exists but is currently tombstoned (`active=false`); names
  remain reserved across tombstone state, so the resurrection path is
  to call the matching `activate_*` command instead of `create_*`.

## How to fix

- If the entity exists in tombstoned form, issue the `activate_*`
  command for the entity kind instead of `create_*`.
- Otherwise pick a different name.

## Related

- `parent_type_not_found` — when adding fields, the parent type must
  exist and be active.
