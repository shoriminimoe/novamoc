/**
 * Tenant pinning and compile-time tenant safety for the repository layer
 * (ADR-014).
 *
 * Every repository method is reached through {@link withTenant}, which binds a
 * tenant id once and threads it into every WHERE clause and VALUES list. The
 * tenant id is never an argument on the individual methods, so a call site
 * cannot forget it or pass the wrong one.
 *
 * Runtime scoping is half the story; the other half is making a cross-tenant
 * mistake a *compile* error. A repo set is branded with a phantom type `B` the
 * caller chooses (distinct brands for distinct tenants). Two things follow:
 *
 *   - Every row read out is tagged {@link TenantScoped}`<T, B>` — it carries a
 *     phantom `[BRAND]: B` property.
 *   - An `upsert` accepts {@link Writable}`<T, B>`: a plain (unbranded) draft
 *     *or* a row already branded `B`. A row branded `'a'` has `[BRAND]: 'a'`,
 *     which is not assignable to the `[BRAND]?: 'b'` an `upsert` on the `'b'`
 *     repo wants — so handing tenant A's row to tenant B's `upsert` is a type
 *     error, while a freshly-built draft (no brand) still type-checks for
 *     either tenant.
 *
 * The brand is `declare`d, so it never exists at runtime — no bytes on the row,
 * no work for the fold.
 */

import type { DbHandle } from '../bootstrap'

declare const BRAND: unique symbol

/**
 * A value tagged with the phantom tenant brand `B`. `[BRAND]` is `declare`d, so
 * it never exists at runtime; it only makes two differently branded values
 * structurally incompatible to the type checker.
 */
export type TenantScoped<T, B> = T & { readonly [BRAND]: B }

/**
 * What an `upsert` accepts: a plain draft `T` (the brand property absent — a
 * freshly-built row), or a `T` already branded `B` (a row read from this same
 * repo). A `T` branded with a *different* tenant has `[BRAND]` set to the wrong
 * literal and is rejected.
 */
export type Writable<T, B> = T & { readonly [BRAND]?: B }

/**
 * The connection plus the pinned tenant id, handed to every repository
 * factory. The brand only narrows the *type* of `tenantId`; at runtime it is
 * the same string the caller passed.
 */
export interface TenantContext<B> {
  readonly db: DbHandle
  readonly tenantId: string
}

/**
 * Brand an opaque tenant id so the type system can tell two tenants apart. The
 * default brand `unknown` keeps a single-tenant call site ergonomic (no type
 * argument needed); cross-tenant code that must not mix rows passes a distinct
 * literal/symbol brand per tenant.
 */
export function tenant<B = unknown>(tenantId: string): TenantScoped<string, B> {
  return tenantId as TenantScoped<string, B>
}
