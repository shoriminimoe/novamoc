---
status: accepted
date: 2026-05-26
category: client
decision-makers: [Sam Caldwell]
consulted: []
informed: []
---

# ADR-021: SvelteKit with adapter-static for the client SPA

## Context and Problem Statement

The client SPA at `src/js/web/` was scaffolded from the `create-vite` minimal Svelte + TypeScript template — plain Svelte 5 mounted by `main.ts` into `index.html`, no router. The schema-management UI redesign spec (`docs/superpowers/specs/2026-05-13-schema-management-ui-redesign-design.md`) explicitly deferred URL routing as wishlist; the SPA has so far been a single view.

[Issue #95](https://github.com/shoriminimoe/novamoc/issues/95) introduces the login flow, and with it the first user-visible routing requirement: a deep-linkable `/login`, a layout-level `/auth/me` probe that redirects between `/login` and `/`, and a place to stash the principal so child pages can read it. This is the moment the no-routing posture stops working. ADR-020's session-cookie auth assumes a real route layer is in place to drive these redirects.

The choice is what to build that route layer with, given the constraints inherited from ADR-001 (local-first, client owns its data) and ADR-003 (SQLite-WASM via OPFS requires COOP/COEP and runs entirely in the browser): no SSR, no server-rendered HTML, no client-server data fetching at render time. The Litestar server (ADR-004) is the only backend; the SPA must be a pure CSR bundle that talks to it.

## Decision Drivers

* The routing semantics needed by ADR-020's session flow — deep-linkable URLs, a layout-level auth probe with redirect, ergonomic programmatic navigation.
* Compatibility with ADR-001 / ADR-003: client must be a static CSR bundle. SSR is not just unused, it is incompatible with an OPFS-backed SQLite-WASM client.
* COOP / COEP headers (ADR-003) must remain straightforward to set in dev and prod.
* The SPA is small today (one main view plus auxiliary components), so framework-migration cost is bounded.

## Considered Options

* **SvelteKit configured with `adapter-static`** (chosen).
* **Hand-rolled history-API router on the existing plain Svelte + Vite SPA.**
* **A third-party Svelte 5 router** (e.g., `svelte-routing`, `svelte-spa-router`).

## Decision Outcome

Chosen option: **SvelteKit with `adapter-static`**, because it provides the idiomatic Svelte 5 routing surface (file-system routes, `$app/navigation`, `$app/state`, layout hierarchy) at a migration cost the SPA is small enough to absorb now, while `adapter-static` keeps the output as a directory of HTML/JS/CSS that any HTTP server can host — preserving the ADR-001 local-first model. A hand-rolled router would solve `/login` and `/` but is a half-measure that grows into either a real router or a SvelteKit migration anyway. A third-party router avoids the framework switch but means committing to a library that lags Svelte 5 runes adoption and re-implements features SvelteKit already ships.

The boundary that makes this compatible with ADR-001 / ADR-003 is strict: **CSR only, no SSR, no SvelteKit server endpoints, no hooks.server.ts, no `src/lib/server/`**. The decision is to treat SvelteKit as a build-time tool that produces a static bundle, not as a server framework. The Litestar server (ADR-004) remains the only backend.

### Consequences

* Good, because routes, layouts, and navigation use standard Svelte idioms — future contributors reading SvelteKit documentation will find it directly applicable.
* Good, because the build output stays a static artifact (`adapter-static` with `fallback: 'index.html'` produces SPA-mode output), so it can be served by Litestar's `create_static_files_router`, by `vite preview`, or by any plain HTTP server.
* Good, because the layout-level auth probe required by ADR-020 lands naturally in `+layout.svelte`, where SvelteKit guarantees it runs once per full page load and not on SPA-internal navigation.
* Bad, because SvelteKit's SSR and server-side surfaces are off-limits and that boundary must be enforced socially — `+page.server.ts`, `+server.ts`, `hooks.server.ts`, and `src/lib/server/` are all syntactically valid but semantically forbidden. Future contributors may pattern-match to SvelteKit tutorials that use them.
* Bad, because backing out is a substantial refactor once routes accumulate. The decision is effectively one-way; the right time to revisit it is before the SPA grows past a handful of routes, not after.

### Confirmation

* `svelte.config.js` pins `adapter: adapter-static({ fallback: 'index.html' })`.
* The root layout sets `export const ssr = false;` and `export const prerender = false;` (CSR-only; no build-time prerender attempt that would require a fake browser environment).
* The repo does not contain `+page.server.ts`, `+layout.server.ts`, `+server.ts`, `hooks.server.ts`, or `src/lib/server/`. If the team later wants a hard check, a single grep in CI suffices.
* COOP/COEP headers (ADR-003) are set via Vite's `server.headers` in dev. In prod they are the responsibility of whichever HTTP server hosts the built `build/` directory; the README documents the requirement.

## More Information

The migration that lands alongside this ADR covers `App.svelte` → `src/routes/+page.svelte`, `index.html` → `src/app.html`, deletion of `main.ts` (SvelteKit owns mounting), and addition of `svelte.config.js` plus an updated `vite.config.ts`. The existing `lib/SchemaBrowser.svelte` and helper modules continue to live under `src/lib/` and import as before.

Revisit triggers: if SvelteKit's roadmap forces SSR-coupled changes that we cannot disable, or if `adapter-static` is deprecated. Neither is currently signaled.
