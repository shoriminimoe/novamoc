# Tenant mismatch

The `tenant_id` carried in the WebSocket `hello` frame did not match the
tenant the connection is authenticated as. The active tenant is derived
from the session cookie on the WebSocket upgrade (ADR-017, ADR-020); the
`hello.tenant_id` is only a consistency check.

A client must send the same tenant it is logged in as. The connection is
closed with WebSocket code `1008` (policy violation).
