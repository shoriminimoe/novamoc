An event carried a value whose JSON shape does not match the
field's declared `data_type`. Type checking is shape-only at this
stage — strings for `text`, JSON numbers for `number` / `integer`,
JSON booleans for `boolean`, ISO 8601 strings for `date` /
`datetime`. `null` is always accepted (it is the "clear this cell"
sentinel per the wire format).

The response carries the following extension members:

- `field` — the field key (UUID or `col:<column>`) whose value
  failed validation.
- `expected` — the declared `FieldDataType` (e.g. `text`,
  `integer`).
- `received` — the JSON type observed (`string`, `number`,
  `integer`, `boolean`, `null`, `object`, `array`).

## Common causes

- A client serialiser emitting numbers as strings, or booleans as
  `0`/`1`.
- A field whose `data_type` was changed on the server while the
  client's local schema cache is stale (see also
  `schema_version_stale`).
- A value range that does not match the declared type — e.g.
  sending a float to an `integer` field, or a bool to `number`
  (Python's `True is 1` quirk does not apply at the wire layer).

## How to fix

- Re-read the schema via `GET /schema` to confirm the field's
  current `data_type`, then coerce the value on the client side
  before retrying.
- For date/datetime fields the wire format is the ISO 8601 string
  representation, not an epoch number.

## Related

- ADR-005 — schema-as-data and the `data_type` constraints.
- ADR-009 — mandatory schema upgrade.
