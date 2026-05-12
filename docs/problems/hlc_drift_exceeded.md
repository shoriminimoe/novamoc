The event's Hybrid Logical Clock physical component is more than the
server's configured drift bound ahead of the server's wall clock. The
server rejects these events at acceptance time so a single client with
a badly-set clock cannot push the shared HLC state arbitrarily far into
the future (ADR-006).

The problem body carries three extension members:

- `hlc` — the rejected HLC string, as submitted.
- `drift_seconds` — how far ahead of the server the HLC's physical
  component sits.
- `limit_seconds` — the server's configured drift bound.

On `/events` the rejection arrives as a per-event entry in the
response's `outcomes` array: `outcome` is `rejected:hlc_drift_exceeded`
and the standard slots + extras above ride at the top of
`outcomes[i].problem`. The HTTP status is the batch envelope's `202`;
`problem.status` carries the `400` this rejection would surface at as
a standalone request.

## Common causes

- The client device's clock is wrong (no NTP, manual time set, dead
  battery on RTC, recent timezone change misinterpreted as wall-time
  change).
- A client is synthesising HLCs from a remote source it should not be
  trusting (e.g., echoing a peer's future-dated HLC during sync).

## How to fix

- Resynchronize the client clock against a reliable time source.
- Drift is one-sided: HLCs in the past are always accepted. The
  rejection only fires when the client is ahead of the server.
- If the drift is small and the bound is too tight for legitimate
  operation, raise `NOVAMOC_HLC_DRIFT_LIMIT_SECONDS` on the server
  side. The default trade-off favours catching bad clocks early.

## Related

- ADR-006 — the design rationale for HLCs and the one-sided drift
  bound.
