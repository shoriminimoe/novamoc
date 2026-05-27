# novaMOC

A local-first, multi-tenant maintenance-tracking app: Svelte SPA client + Python/Litestar server, joined by a hand-rolled event-sourced sync protocol (HLC ordering + per-field LWW). Architecture is fixed by the ADRs under [`docs/adr/`](docs/adr/); read the relevant ADRs before making non-trivial changes.

## Development setup

1. `uv sync` — install Python deps from `uv.lock`.
2. `just bootstrap-dev` — apply migrations, create the `Development` tenant, and provision the `admin` / `admin` user. Idempotent.
3. `just serve` — start the API on `http://localhost:8000`.
4. `cd src/js/web && npm install && npm run dev` — start the SPA.

Production deployments run the equivalent commands in an init container; there is no environment-conditional code in the server itself.

### Adding more tenants / users from the CLI

```sh
uv run novamoc tenant create --display-name "<Display Name>"
uv run novamoc user create <username>
uv run novamoc user add-to-tenant <username> <tenant-uuid>
```

## Authenticating against a running server

The auth cookie is HttpOnly and `SameSite=Lax`; the SPA never touches the token directly.

**Browser:** navigate to `/login`. The layout's boot-time `/auth/me` probe redirects unauthenticated requests to `/login` automatically.

**Scripts / curl:** persist the cookie jar.

```sh
curl -c cookies.txt -X POST http://localhost:8000/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username": "admin", "password": "admin"}'
curl -b cookies.txt http://localhost:8000/auth/me
```

`/openapi`, `/problems/*`, and `/auth/login` are unauthenticated; every other route returns 401 `tenant_not_resolved` without a valid session.
