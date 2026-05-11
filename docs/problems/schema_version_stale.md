The batch's `schema_version` does not match the tenant's current
schema version on the server. Schema upgrades are mandatory (ADR-009):
events authored against an old schema can reference fields that have
been deleted, or miss fields that the new schema requires, so the
server refuses the whole batch rather than risk a malformed
projection.

The response carries two extension members:

- `expected` — the tenant's current `schema_version` on the server.
- `received` — the `schema_version` the client sent on the batch.

## Common causes

- The client's locally cached schema is older than the server's. A
  concurrent `POST /schema` from another session has advanced the
  version since the client last fetched the schema.
- The client started the batch before catching up to a schema change
  it has already observed elsewhere.

## How to fix

- Re-read the schema via `GET /schema`; its `schema_version` is the
  value the next batch must carry. Apply any local consequences of
  the new schema (e.g., drop pending edits that reference deleted
  fields).
- Resubmit the batch with the refreshed `schema_version`. Past-dated
  HLCs remain valid (per ADR-006) so the original event ordering is
  preserved.

## Related

- ADR-008 — schema is server-authoritative; clients are followers.
- ADR-009 — mandatory schema upgrade and the catch-up flow.
