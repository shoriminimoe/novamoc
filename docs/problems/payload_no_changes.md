The update payload had no fields to apply, so the request was rejected
without touching state.

## Common causes

- A client serialized an "update" payload from a form where every
  optional field was left unset, producing a payload with only the
  command discriminator and the target identifier.
- A diff between two equal projection states was sent as an update.

## How to fix

- Detect "no changes" before sending by comparing the proposed update
  to the current projection.
- For form-driven updates, collapse the request when no field has been
  touched.

## Related

- `invalid_payload_shape` — the payload was malformed, not just empty.
