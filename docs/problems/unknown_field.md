An event referenced a field that does not exist on the targeted
entity type. The server checks both legs of `(type_id, field_id)` —
a field that exists in the schema but under a different
`asset_type` (or `maintenance_record_type`) is still reported as
unknown for the type the event addressed.

The response carries the following extension members:

- `family` — the entity family the event targeted (`asset` or
  `maintenance_record`).
- `type_id` — the user-schema type the event addressed.
- `field` — the unrecognised field key, either a UUID (user
  field) or `col:<column>` (projection column).

## Common causes

- A field was `delete_*`-d on the server but the client still
  references it. (Deactivated, i.e. tombstoned, fields are *not*
  rejected here per ADR-012 — only deleted ones.)
- A typo or stale identifier on the client.
- The event's `type_id` is wrong for the field — the field lives
  under a different type.
- A `col:<name>` key whose column does not exist on the entity
  table for this family.

## How to fix

- Refresh the schema via `GET /schema` so the client knows which
  fields are still valid. The catch-up flow (ADR-009) is the
  intended path back to a consistent view.
- For `col:<name>` mistakes: only user-writable projection columns
  are addressable; server-managed columns (`col:type_id`,
  `col:asset_id`, `col:deleted`, `col:row_state_hlc`) are rejected
  separately as `invalid_payload_shape`.

## Related

- ADR-008 — schema is server-authoritative.
- ADR-012 — `col:` namespace and the decoupling of data fold from
  schema-active state.
