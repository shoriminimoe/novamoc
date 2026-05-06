The request body was decoded as JSON but did not match the expected
shape for the command (missing required field, wrong type, unknown
discriminator, etc.).

## Common causes

- The client and server disagree on the schema-endpoint payload
  contract — usually because one side is on a stale build.
- A required field was omitted.
- The `type` discriminator on a `POST /schema` payload does not match
  any known command.

## How to fix

- Regenerate or re-check the client's payload struct against the
  current OpenAPI document at `/openapi`.
- Compare the rejected payload to the relevant `msgspec.Struct` under
  `novamoc/domain/schema/_payloads.py`.

## Related

- `payload_no_changes` — the payload was well-formed but had nothing
  to apply.
