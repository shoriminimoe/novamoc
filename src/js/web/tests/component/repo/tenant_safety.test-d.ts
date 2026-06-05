/**
 * Compile-time tenant-safety check.
 *
 * The acceptance criterion is that the type signatures *forbid* handing a row
 * read from one tenant's repo into another tenant's `upsert`. This file proves
 * it: each `@ts-expect-error` line MUST fail to type-check, so `svelte-check` /
 * `tsc` (run by `npm run check` and CI's typecheck-js job) goes red if the
 * brand ever stops working. There are no runtime assertions — the type checker
 * is the assertion.
 *
 * The brands `'a'` / `'b'` are phantom string-literal tenant tags; in real code
 * the call site picks any two distinct brands for the two tenants it juggles.
 */
import { withTenant } from '../../../src/lib/db/repo'
import type { DbHandle } from '../../../src/lib/db/bootstrap'

declare const db: DbHandle

const a = withTenant<'a'>(db, 'tenant-a')
const b = withTenant<'b'>(db, 'tenant-b')

async function crossTenantWritesAreCompileErrors(): Promise<void> {
  const rowFromA = await a.assets.getById('asset-1')
  if (rowFromA === null) {
    return
  }

  // A row read under brand 'a' is `TenantScoped<AssetRow, 'a'>`; B's upsert
  // wants `Writable<AssetDraft, 'b'>`. The brands disagree -> type error.
  // @ts-expect-error cross-tenant upsert must not type-check
  await b.assets.upsert(rowFromA)

  // Same guarantee for field values.
  const fvFromA = await a.assetFieldValues.listByAsset('asset-1')
  // @ts-expect-error cross-tenant field-value upsert must not type-check
  await b.assetFieldValues.upsert(fvFromA[0])

  // And maintenance records.
  const recFromA = await a.maintenanceRecords.getById('rec-1')
  if (recFromA !== null) {
    // @ts-expect-error cross-tenant record upsert must not type-check
    await b.maintenanceRecords.upsert(recFromA)
  }

  // The matching same-tenant write DOES type-check (no @ts-expect-error).
  await a.assets.upsert(rowFromA)
}

// Reference the function so `noUnusedLocals` stays quiet without running it.
export const _typeChecks = crossTenantWritesAreCompileErrors
