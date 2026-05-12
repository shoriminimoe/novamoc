# M4.3 Asset type lifecycle forms — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal.** Land the five `asset_type` lifecycle forms (create, activate, update, deactivate, delete) in the Svelte SPA so a tenant can mutate their asset types through the browser, hitting `POST /schema` via the M4.1 API client and refreshing the M4.2 snapshot on success.

**Architecture.** Three additions on top of the M4.2 schema browser:

1. `src/lib/commands.ts` — typed wire-format for `POST /schema` (asset-type lifecycle slice) mirroring `domain/schema/_payloads.py`, plus a `postSchemaCommand(client, body)` helper that returns `SchemaResponse`. Field-level and maintenance-record-side command shapes are deferred to M4.4 / M4.5 (YAGNI — only asset-type commands are needed for M4.3).
2. `src/lib/AssetTypeCreateForm.svelte` — collapsible "+ New asset type" form, one `name` input + `crypto.randomUUID()` for `entity_id`, submits `create_asset_type`. Mounted at the top of the asset-types column in `SchemaBrowser`.
3. `src/lib/AssetTypeActions.svelte` — per-type action row (Rename / Activate or Deactivate / Delete). Hosts an inline rename form (one `name` input) and confirm prompts for deactivate/delete. The Activate button shows only for tombstoned (`active=false`) types; the Deactivate button shows only for active types. Mounted under each asset-type's `TypeCard` in `SchemaBrowser`.

`SchemaBrowser` is the only modified existing file. It owns the `reloadKey` it already exposes; both new components take an `onChanged: () => void` callback that bumps it, which triggers the existing `$effect` to re-fetch.

`TypeCard` is **not** modified — it stays a pure display component. The actions row is rendered as a sibling under each asset-type card in `SchemaBrowser`, not inside `TypeCard` itself. This keeps `TypeCard` reusable by M4.5 (it'll be wrapped by a `MaintenanceRecordTypeActions` later) without snippet-prop plumbing now.

**Error rendering.** `ProblemDetailsError.code` already exposes the leaf code. The forms branch on:

- `name_reserved` (create/update) → highlight the `name` input red and render the error message under it.
- `payload_no_changes` (update) → render under the form ("No changes to apply").
- `entity_not_found` (activate/deactivate/delete) → render under the action row ("This asset type no longer exists — reload"). Rare; happens if a peer deletes it between snapshot and action.
- Anything else (non-`ProblemDetailsError` or unknown code) → render `status · code` + message, matching the M4.2 pattern.

The same `code`-based dispatch is reused by M4.4 (field-level errors add `parent_type_not_found`, plus `name_reserved` is reused).

**Tech stack.** Svelte 5 runes (`$state`, `$props`, `$effect`, `$derived`), Tailwind v4. No new dependencies. The frontend has no test runner — verification is `npm run check`, `npm run build`, and a manual curl smoke through the Vite proxy (the M4.1/M4.2 pattern).

**Out of scope.**

- Maintenance-record-type lifecycle (M4.5).
- Field-level lifecycle, including `clear_*_field` (M4.4 for asset-type fields, M4.5 for MR fields).
- Optimistic UI / partial updates — every successful mutation triggers a full `GET /schema` re-fetch via `reloadKey`. Cheap; matches the M4.2 design.
- Browser-driven Playwright smoke. Same Chrome-path blocker as M4.1 / M4.2; manual `curl` is the smoke surface for now.

---

## File structure

| Path | Status | Responsibility |
|---|---|---|
| `src/js/web/src/lib/commands.ts` | **new** | Typed POST /schema command bodies for the five asset-type lifecycle verbs + `postSchemaCommand` helper + `SchemaCommandResponse` type. |
| `src/js/web/src/lib/AssetTypeCreateForm.svelte` | **new** | "+ New asset type" collapsible form. Generates a UUID, posts `create_asset_type`, calls `onCreated()` on success, renders `name_reserved` inline. |
| `src/js/web/src/lib/AssetTypeActions.svelte` | **new** | Per-type action row. Hosts rename form + activate/deactivate/delete buttons with confirm flow. Calls `onChanged()` on success. |
| `src/js/web/src/lib/SchemaBrowser.svelte` | **modify** | Render `AssetTypeCreateForm` at the top of the asset-types column; render `AssetTypeActions` under each asset-type `TypeCard`. Both wire to `reloadKey += 1`. |

---

## Task 1: Add typed POST /schema command bodies and `postSchemaCommand` helper

**Files:**
- Create: `src/js/web/src/lib/commands.ts`

**Why first.** Every form in M4.3 imports from this module. Landing it first means tasks 2 and 3 can import a settled type surface.

- [ ] **Step 1: Create `src/js/web/src/lib/commands.ts`**

```ts
/**
 * Typed wire-format for ``POST /schema`` — asset-type lifecycle slice
 * (M4.3). Mirrors :class:`novamoc.domain.schema._payloads.SchemaRequest`
 * for the five ``*_asset_type`` commands. Field-level and
 * maintenance-record-side commands are added by M4.4 / M4.5.
 *
 * Each body has the msgspec discriminator ``type`` (snake-case), an
 * ``entity_id`` UUID (client-generated for create; from the snapshot for
 * the other four), and a ``payload`` whose shape depends on the verb.
 * Empty-payload commands (activate / deactivate / delete) accept an
 * absent payload key; we send ``{}`` explicitly to keep the wire bytes
 * stable.
 */

import type { ApiClient } from './api'

export interface CreateAssetTypeBody {
  type: 'create_asset_type'
  entity_id: string
  payload: { name: string }
}

export interface ActivateAssetTypeBody {
  type: 'activate_asset_type'
  entity_id: string
  payload: Record<string, never>
}

export interface UpdateAssetTypeBody {
  type: 'update_asset_type'
  entity_id: string
  payload: { name?: string }
}

export interface DeactivateAssetTypeBody {
  type: 'deactivate_asset_type'
  entity_id: string
  payload: Record<string, never>
}

export interface DeleteAssetTypeBody {
  type: 'delete_asset_type'
  entity_id: string
  payload: Record<string, never>
}

export type SchemaCommandBody =
  | CreateAssetTypeBody
  | ActivateAssetTypeBody
  | UpdateAssetTypeBody
  | DeactivateAssetTypeBody
  | DeleteAssetTypeBody

export type Outcome =
  | 'created'
  | 'activated'
  | 'updated'
  | 'deactivated'
  | 'cleared'
  | 'deleted'
  | 'noop'

export interface SchemaCommandResponse {
  schema_version: number
  entity_id: string
  outcome: Outcome
  committed_at: string
}

export function postSchemaCommand(
  client: ApiClient,
  body: SchemaCommandBody,
): Promise<SchemaCommandResponse> {
  return client.post<SchemaCommandResponse>('/schema', body)
}
```

- [ ] **Step 2: Run the type-checker**

Run from `src/js/web/`:

```bash
npm run check
```

Expected: 0 errors, 0 warnings. (Empty `Record<string, never>` is the canonical TS for "must be `{}`"; svelte-check / tsc accept it.)

- [ ] **Step 3: Commit**

```bash
git add src/js/web/src/lib/commands.ts
git commit -m "$(cat <<'EOF'
feat(web): typed POST /schema asset-type command bodies

Adds ``commands.ts`` with the five asset-type lifecycle wire shapes
(create / activate / update / deactivate / delete), a
``SchemaCommandBody`` discriminated union, ``SchemaCommandResponse``,
and the ``postSchemaCommand`` helper M4.3 forms call. Field-level and
maintenance-record-side commands are deferred to M4.4 / M4.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Implement `AssetTypeCreateForm.svelte`

**Files:**
- Create: `src/js/web/src/lib/AssetTypeCreateForm.svelte`

**Behavior.**

- Renders as a collapsed `+ New asset type` button. Clicking expands the form (a `name` input, Cancel, Create) and focuses the input.
- Submit generates `crypto.randomUUID()` for `entity_id`, posts `create_asset_type`, and on success collapses the form, clears the input, and calls `onCreated()`.
- On `ProblemDetailsError` with `code === 'name_reserved'`, the name input gets a red ring and the inline error reads "Name is already in use". Form stays open with the bad name still in the input so the user can fix it.
- Anything else falls through to the M4.2 status·code pattern ("HTTP 500 · server_error · …").

- [ ] **Step 1: Create `src/js/web/src/lib/AssetTypeCreateForm.svelte`**

```svelte
<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { postSchemaCommand } from './commands'

  interface Props {
    onCreated: () => void
  }

  let { onCreated }: Props = $props()

  type SubmitState =
    | { kind: 'idle' }
    | { kind: 'submitting' }
    | { kind: 'error'; status: number; code: string; message: string }

  let expanded = $state(false)
  let name = $state('')
  let submitState: SubmitState = $state({ kind: 'idle' })
  let nameInput = $state<HTMLInputElement | null>(null)

  function open(): void {
    expanded = true
    submitState = { kind: 'idle' }
    queueMicrotask(() => nameInput?.focus())
  }

  function close(): void {
    expanded = false
    name = ''
    submitState = { kind: 'idle' }
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (name.trim() === '') return
    submitState = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: 'create_asset_type',
        entity_id: crypto.randomUUID(),
        payload: { name: name.trim() },
      })
      close()
      onCreated()
    } catch (e) {
      if (e instanceof ProblemDetailsError) {
        submitState = {
          kind: 'error',
          status: e.status,
          code: e.code,
          message: e.message,
        }
      } else {
        submitState = {
          kind: 'error',
          status: 0,
          code: 'network_error',
          message: String(e),
        }
      }
    }
  }

  let nameError = $derived(
    submitState.kind === 'error' && submitState.code === 'name_reserved',
  )
</script>

{#if !expanded}
  <button
    type="button"
    class="w-full rounded border border-dashed border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50"
    onclick={open}
  >
    + New asset type
  </button>
{:else}
  <form
    class="rounded border border-gray-300 p-4 space-y-3"
    onsubmit={submit}
  >
    <div>
      <label for="new-asset-type-name" class="block text-xs font-medium text-gray-700">
        Name
      </label>
      <input
        id="new-asset-type-name"
        type="text"
        class="mt-1 w-full rounded border px-2 py-1 font-mono text-sm"
        class:border-gray-300={!nameError}
        class:border-red-500={nameError}
        class:ring-1={nameError}
        class:ring-red-500={nameError}
        bind:value={name}
        bind:this={nameInput}
        disabled={submitState.kind === 'submitting'}
        required
      />
      {#if submitState.kind === 'error'}
        <p class="mt-1 text-xs text-red-700">
          {submitState.status} · {submitState.code} — {submitState.message}
        </p>
      {/if}
    </div>
    <div class="flex justify-end gap-2">
      <button
        type="button"
        class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50"
        onclick={close}
        disabled={submitState.kind === 'submitting'}
      >
        Cancel
      </button>
      <button
        type="submit"
        class="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
        disabled={submitState.kind === 'submitting' || name.trim() === ''}
      >
        {submitState.kind === 'submitting' ? 'Creating…' : 'Create'}
      </button>
    </div>
  </form>
{/if}
```

- [ ] **Step 2: Run the Svelte autofixer**

The svelte MCP server's autofixer catches accessibility issues (label binding, button type, etc.) and Svelte-5 lints. Run it against the new file. If it reports issues, apply the suggested edits and re-run until clean.

- [ ] **Step 3: Run the type-checker**

Run from `src/js/web/`:

```bash
npm run check
```

Expected: 0 errors. (The component isn't wired into `App.svelte` yet, but `npm run check` will compile it.)

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/AssetTypeCreateForm.svelte
git commit -m "$(cat <<'EOF'
feat(web): asset-type create form with name_reserved inline error

Collapsible ``+ New asset type`` form. Submit posts
``create_asset_type`` via the M4.1 API client with a
``crypto.randomUUID()`` ``entity_id``; on success the form closes and
calls ``onCreated()`` (wired to the schema browser's reload in the
next commit). ``name_reserved`` is rendered inline under the input
with a red ring; anything else falls through to the M4.2
``status · code`` shape.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Implement `AssetTypeActions.svelte`

**Files:**
- Create: `src/js/web/src/lib/AssetTypeActions.svelte`

**Behavior.**

- Renders a single row of buttons under one asset-type's card: `Rename`, `Activate` (only when `!type.active`) or `Deactivate` (only when `type.active`), `Delete`.
- `Rename` toggles an inline form with a `name` input prefilled from `type.name`. Submit posts `update_asset_type`; on success collapses + calls `onChanged()`. Empty input or unchanged name → submit disabled (avoids `payload_no_changes` round-trips, but the error code is still handled for safety). `name_reserved` renders inline.
- `Activate` / `Deactivate` are one-click — no confirm. They post `activate_asset_type` / `deactivate_asset_type` with `payload: {}`. On success → `onChanged()`. On error → render under the action row.
- `Delete` flips the row into a confirm state ("Delete this asset type? [Cancel] [Delete]"). Confirm posts `delete_asset_type`. On success → `onChanged()`. On error → render under the row.
- `entity_not_found` on any of the four mutating verbs renders "This asset type no longer exists — reload" under the row.

- [ ] **Step 1: Create `src/js/web/src/lib/AssetTypeActions.svelte`**

```svelte
<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { postSchemaCommand, type SchemaCommandBody } from './commands'
  import type { TypeView } from './schema'

  interface Props {
    type: TypeView
    onChanged: () => void
  }

  let { type, onChanged }: Props = $props()

  type Mode =
    | { kind: 'idle' }
    | { kind: 'renaming'; draft: string }
    | { kind: 'confirming_delete' }
    | { kind: 'submitting' }
    | { kind: 'error'; status: number; code: string; message: string }

  let mode: Mode = $state({ kind: 'idle' })

  function reset(): void {
    mode = { kind: 'idle' }
  }

  function startRename(): void {
    mode = { kind: 'renaming', draft: type.name }
  }

  function startConfirmDelete(): void {
    mode = { kind: 'confirming_delete' }
  }

  async function send(body: SchemaCommandBody): Promise<void> {
    mode = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), body)
      reset()
      onChanged()
    } catch (e) {
      if (e instanceof ProblemDetailsError) {
        mode = {
          kind: 'error',
          status: e.status,
          code: e.code,
          message: e.message,
        }
      } else {
        mode = {
          kind: 'error',
          status: 0,
          code: 'network_error',
          message: String(e),
        }
      }
    }
  }

  function submitRename(event: SubmitEvent): void {
    event.preventDefault()
    if (mode.kind !== 'renaming') return
    const draft = mode.draft.trim()
    if (draft === '' || draft === type.name) return
    void send({
      type: 'update_asset_type',
      entity_id: type.id,
      payload: { name: draft },
    })
  }

  function activate(): void {
    void send({
      type: 'activate_asset_type',
      entity_id: type.id,
      payload: {},
    })
  }

  function deactivate(): void {
    void send({
      type: 'deactivate_asset_type',
      entity_id: type.id,
      payload: {},
    })
  }

  function confirmDelete(): void {
    void send({
      type: 'delete_asset_type',
      entity_id: type.id,
      payload: {},
    })
  }

  let nameError = $derived(
    mode.kind === 'error' && mode.code === 'name_reserved',
  )
  let busy = $derived(mode.kind === 'submitting')
</script>

<div class="mt-3 space-y-2">
  {#if mode.kind === 'renaming'}
    <form class="flex items-end gap-2" onsubmit={submitRename}>
      <div class="flex-1">
        <label for="rename-{type.id}" class="block text-xs font-medium text-gray-700">
          New name
        </label>
        <input
          id="rename-{type.id}"
          type="text"
          class="mt-1 w-full rounded border px-2 py-1 font-mono text-sm"
          class:border-gray-300={!nameError}
          class:border-red-500={nameError}
          class:ring-1={nameError}
          class:ring-red-500={nameError}
          bind:value={mode.draft}
          required
        />
      </div>
      <button
        type="button"
        class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50"
        onclick={reset}
      >
        Cancel
      </button>
      <button
        type="submit"
        class="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
        disabled={mode.draft.trim() === '' || mode.draft.trim() === type.name}
      >
        Save
      </button>
    </form>
  {:else if mode.kind === 'confirming_delete'}
    <div class="flex items-center justify-between rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
      <span>Delete <span class="font-mono">{type.name}</span>?</span>
      <span class="flex gap-2">
        <button
          type="button"
          class="rounded border border-red-300 bg-white px-2 py-0.5 text-xs hover:bg-red-100"
          onclick={reset}
        >
          Cancel
        </button>
        <button
          type="button"
          class="rounded bg-red-600 px-2 py-0.5 text-xs text-white"
          onclick={confirmDelete}
        >
          Delete
        </button>
      </span>
    </div>
  {:else}
    <div class="flex flex-wrap gap-2 text-xs">
      <button
        type="button"
        class="rounded border border-gray-300 px-2 py-0.5 hover:bg-gray-50 disabled:opacity-50"
        onclick={startRename}
        disabled={busy}
      >
        Rename
      </button>
      {#if type.active}
        <button
          type="button"
          class="rounded border border-gray-300 px-2 py-0.5 hover:bg-gray-50 disabled:opacity-50"
          onclick={deactivate}
          disabled={busy}
        >
          Deactivate
        </button>
      {:else}
        <button
          type="button"
          class="rounded border border-gray-300 px-2 py-0.5 hover:bg-gray-50 disabled:opacity-50"
          onclick={activate}
          disabled={busy}
        >
          Activate
        </button>
      {/if}
      <button
        type="button"
        class="rounded border border-red-300 px-2 py-0.5 text-red-700 hover:bg-red-50 disabled:opacity-50"
        onclick={startConfirmDelete}
        disabled={busy}
      >
        Delete
      </button>
      {#if busy}
        <span class="text-gray-500">Working…</span>
      {/if}
    </div>
  {/if}

  {#if mode.kind === 'error'}
    <p class="text-xs text-red-700">
      {#if mode.code === 'entity_not_found'}
        This asset type no longer exists — reload.
      {:else}
        {mode.status} · {mode.code} — {mode.message}
      {/if}
    </p>
  {/if}
</div>
```

- [ ] **Step 2: Run the Svelte autofixer**

Run it against `AssetTypeActions.svelte`. Apply suggestions until clean.

- [ ] **Step 3: Run the type-checker**

Run from `src/js/web/`:

```bash
npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/AssetTypeActions.svelte
git commit -m "$(cat <<'EOF'
feat(web): per-asset-type action row — rename, activate/deactivate, delete

Renders under each asset-type ``TypeCard``. Buttons drive an inline
rename form (``update_asset_type``), one-click activate / deactivate
(``activate_asset_type`` / ``deactivate_asset_type``), and a
two-step delete confirm (``delete_asset_type``). ``name_reserved``
highlights the rename input; ``entity_not_found`` renders an
explicit "no longer exists — reload" hint; other codes fall through
to the M4.2 ``status · code`` pattern. Hooked into the schema
browser's reload via ``onChanged()`` in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire the new components into `SchemaBrowser.svelte`

**Files:**
- Modify: `src/js/web/src/lib/SchemaBrowser.svelte`

**Why last.** Tasks 1–3 produce isolated, type-checkable units. This task plugs them into the only entry point.

**Behavior.**

- Render `AssetTypeCreateForm` above the asset-types `<h3>` heading, in both empty and non-empty branches.
- Render `AssetTypeActions` under each asset-type `TypeCard` (and *only* asset-type cards — `MaintenanceRecordTypeActions` arrives in M4.5).
- Both new components receive an `onChanged` / `onCreated` callback that calls the existing `load()` function. (Using the function directly is equivalent to bumping `reloadKey`; pick `load()` because it doesn't churn a piece of reactive state on every mutation.)

- [ ] **Step 1: Edit `src/js/web/src/lib/SchemaBrowser.svelte`**

Diff (apply as one edit):

```diff
 <script lang="ts">
   import { createApiClient, ProblemDetailsError } from './api'
   import { fetchSchema, type SchemaSnapshot, type TypeView } from './schema'
+  import AssetTypeActions from './AssetTypeActions.svelte'
+  import AssetTypeCreateForm from './AssetTypeCreateForm.svelte'
   import TypeCard from './TypeCard.svelte'
```

Replace the entire asset-types branch (the `<div>` whose `<h3>` reads "Asset types (...)") with one that renders `AssetTypeCreateForm` above the heading and wraps each `TypeCard` with the actions row:

```svelte
      <div>
        <AssetTypeCreateForm onCreated={() => void load()} />
        <h3 class="mb-3 mt-4 text-sm font-semibold uppercase tracking-wide text-gray-600">
          Asset types ({assetTypes.length})
        </h3>
        {#if assetTypes.length === 0}
          <p class="text-sm italic text-gray-500">
            no {showTombstoned ? '' : 'active '}asset types
          </p>
        {:else}
          <div class="space-y-3">
            {#each assetTypes as type (type.id)}
              <div>
                <TypeCard {type} {showTombstoned} />
                <AssetTypeActions {type} onChanged={() => void load()} />
              </div>
            {/each}
          </div>
        {/if}
      </div>
```

Leave the maintenance-record-types branch untouched.

- [ ] **Step 2: Run the Svelte autofixer**

Run it against `SchemaBrowser.svelte`. Apply suggestions until clean.

- [ ] **Step 3: Run the type-checker**

Run from `src/js/web/`:

```bash
npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Run the production build**

Run from `src/js/web/`:

```bash
npm run build
```

Expected: build succeeds, no errors, output written to `dist/`.

- [ ] **Step 5: Manual curl smoke through the Vite proxy**

Boot the API (`just serve` in repo root) and the SPA (`npm run dev` in `src/js/web/`) in separate terminals, then hit the proxy directly to verify each verb's wire contract:

```bash
TOKEN="dev-bearer-token"  # or whatever VITE_DEFAULT_BEARER_TOKEN is set to
NEW_ID=$(python -c 'import uuid; print(uuid.uuid4())')

# 1. Create
curl -sS -X POST http://127.0.0.1:5173/schema \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"create_asset_type\",\"entity_id\":\"$NEW_ID\",\"payload\":{\"name\":\"pump\"}}" | jq

# 2. Conflict (same name twice)
curl -sS -X POST http://127.0.0.1:5173/schema \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"create_asset_type\",\"entity_id\":\"$(python -c 'import uuid; print(uuid.uuid4())')\",\"payload\":{\"name\":\"pump\"}}" -i | head -20

# 3. Rename
curl -sS -X POST http://127.0.0.1:5173/schema \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"update_asset_type\",\"entity_id\":\"$NEW_ID\",\"payload\":{\"name\":\"pump_v2\"}}" | jq

# 4. Deactivate
curl -sS -X POST http://127.0.0.1:5173/schema \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"deactivate_asset_type\",\"entity_id\":\"$NEW_ID\",\"payload\":{}}" | jq

# 5. Activate
curl -sS -X POST http://127.0.0.1:5173/schema \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"activate_asset_type\",\"entity_id\":\"$NEW_ID\",\"payload\":{}}" | jq

# 6. Delete
curl -sS -X POST http://127.0.0.1:5173/schema \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"delete_asset_type\",\"entity_id\":\"$NEW_ID\",\"payload\":{}}" | jq

# 7. entity_not_found (deleted, try to deactivate)
curl -sS -X POST http://127.0.0.1:5173/schema \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"deactivate_asset_type\",\"entity_id\":\"$NEW_ID\",\"payload\":{}}" -i | head -20
```

Expected outcomes:

1. `200 {"schema_version":N,"entity_id":"…","outcome":"created","committed_at":"…"}`
2. `409` with `Content-Type: application/problem+json`, body's `type` URL ending in `name_reserved.html`.
3. `200 outcome=updated`.
4. `200 outcome=deactivated`.
5. `200 outcome=activated`.
6. `200 outcome=deleted`.
7. `404` with `type` ending in `entity_not_found.html`.

The curl smoke verifies the *wire contract* used by the new components, not the components themselves. UI verification (clicking the in-page buttons) follows in the next step.

- [ ] **Step 6: Browser smoke**

With both servers still running, open `http://127.0.0.1:5173/`, paste the dev bearer token (or leave blank to inherit `VITE_DEFAULT_BEARER_TOKEN`), and exercise each path:

1. Click `+ New asset type`, type a name, Create — the row appears in the snapshot list with version incremented.
2. Click `+ New asset type` again with the same name — the form stays open with a red ring around the name input and a `409 · name_reserved` inline message.
3. Rename a type, save — name updates, no inline error.
4. Rename to the same name — Save button stays disabled.
5. Rename to a different existing type's name — inline `name_reserved` error.
6. Deactivate a type — card greys out + `tombstoned` badge appears (Activate button replaces Deactivate). Toggle `Show tombstoned` to verify it stays visible.
7. Activate the tombstoned type — badge clears, Deactivate button returns.
8. Delete a type with two-step confirm — disappears from the list.
9. Toggle `Show tombstoned` off → on → off — no regression to the M4.2 display behavior.

If Playwright's chrome path is still broken (the M4.1 / M4.2 blocker), document the manual run results in the PR body and continue. Otherwise drive the same flow via Playwright MCP and capture a snapshot at the create-conflict and confirm-delete states.

- [ ] **Step 7: Run the repo-wide check (`just check`)**

Run from repo root:

```bash
just check
```

Expected: lint + format + typecheck + pytest all clean. The frontend isn't covered by `just check` directly, but the Python side must not regress. Ratchet unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/js/web/src/lib/SchemaBrowser.svelte
git commit -m "$(cat <<'EOF'
feat(web): M4.3 — asset-type lifecycle forms wired into the schema browser

Mounts ``AssetTypeCreateForm`` above the asset-types list and
``AssetTypeActions`` under each asset-type ``TypeCard``. Both
trigger ``load()`` on success, so a successful create / rename /
activate / deactivate / delete refreshes the snapshot and updates
``schema_version`` in the header. ``TypeCard`` stays display-only —
M4.5 wraps maintenance-record-type cards the same way.

Verification: ``npm run check``, ``npm run build``, ``just check``
all clean. Manual curl smoke through the Vite proxy covers all five
verbs plus ``name_reserved`` and ``entity_not_found``. Manual
browser smoke covers the inline error rendering and confirm flow.
Playwright-driven smoke still gated on the M4.1 / M4.2 chrome-path
blocker.

Closes #43.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Open the pull request

- [ ] **Step 1: Push the branch and open the PR**

```bash
git push -u origin worktree-bridge-cse_01Q5dBGoe6ahdrPw1qKbyWgA
gh pr create --title "feat(web): M4.3 — asset-type lifecycle forms" --body "$(cat <<'EOF'
## Summary

- Adds typed POST /schema asset-type command bodies + ``postSchemaCommand`` helper (``commands.ts``).
- Adds ``AssetTypeCreateForm`` (collapsible ``+ New asset type`` form, ``crypto.randomUUID()`` for ``entity_id``, inline ``name_reserved`` rendering).
- Adds ``AssetTypeActions`` per-type action row (rename inline form, one-click activate/deactivate, two-step delete confirm). Renders ``entity_not_found`` as a "reload" hint; other codes fall through to the M4.2 ``status · code`` shape.
- Wires both into ``SchemaBrowser`` — ``TypeCard`` stays display-only.

Field-level and maintenance-record-side lifecycle deferred to #44 / #45.

## Test plan
- [x] ``npm run check`` clean
- [x] ``npm run build`` clean
- [x] ``just check`` clean (pytest + ratchet unchanged)
- [x] Manual curl smoke through the Vite proxy: create, conflict (``name_reserved``), rename, deactivate, activate, delete, then ``entity_not_found`` on a stale id.
- [x] Manual browser smoke covering inline ``name_reserved``, two-step delete confirm, ``Show tombstoned`` toggle.
- [ ] Playwright-driven smoke (deferred — same chrome-path blocker as M4.1 / M4.2).

Closes #43.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Return the PR URL.
