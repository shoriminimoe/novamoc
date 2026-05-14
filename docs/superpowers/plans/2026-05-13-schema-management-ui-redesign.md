# Schema management UI redesign — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal.** Replace the developer-flavored, two-column card UI of M4.1–M4.5 with a master-detail layout shaped for a maintenance manager — sortable + filterable tables on both sides, in-row form swap for edits, combobox + type-aware previews for the data-type picker, distinct archive (inline confirm) vs. delete (modal + typed-name) flows, and terminology cleanup. Wire layer (`api.ts`, `commands.ts`, `schema.ts`, `token.ts`) is unchanged.

**Architecture.** Six new components and two rewrites under `src/js/web/src/`. The new components form three layers:

1. **Primitives** (no schema knowledge): `Combobox.svelte`, `ArchiveConfirmBar.svelte`, `DeleteTypeDialog.svelte`.
2. **Composites** (schema-aware, no shell state): `FieldsTable.svelte`, `TypesRail.svelte`, `TypeDetail.svelte`.
3. **Shell** (state owner): `SchemaBrowser.svelte` (rewritten) + `App.svelte` (rewritten header bar).

Five existing components (`TypeCard`, `TypeActions`, `TypeCreateForm`, `FieldActions`, `FieldCreateForm`) get deleted in the cleanup task; they have no callers after the shell rewrite.

**Tech stack.** Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`), Tailwind v4. No new dependencies — combobox and modal are hand-rolled. Verification is `npm run check` (svelte-check + tsc) and `npm run build`; manual smoke through the Vite proxy is the integration surface (no frontend test runner today, per the M4.3 plan).

**Tooling reminder.** Every Svelte component edit must be followed by a run of the **Svelte autofixer** via `mcp__svelte__svelte-autofixer` (the official Svelte MCP server). The autofixer catches Svelte-5 lints, accessibility issues, runes-vs-stores mistakes, and CSS-vs-Tailwind drift. Re-run until it reports zero issues before committing. Don't skip this.

**Out of scope** (every item is wishlist for a separate issue):

- Per-field description / help text, required-vs-optional flag, value validation rules.
- Field display order (drag-to-reorder).
- Inline relationships between asset types and maintenance record types.
- Audit info (last edited by / when).
- Field-name search across types.
- Bulk operations, multi-column sort.
- URL-routable selection state.
- Mobile / responsive design.
- A real settings or auth surface.
- Concrete record-count data in the delete dialog (requires the data-side projections to be reachable; M2+).

---

## File structure

| Path                                              | Status     | Responsibility                                                                                                       |
| ------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------- |
| `src/js/web/src/lib/Combobox.svelte`              | **new**    | Generic typeable single-select. Filter-as-you-type, arrow-key + Enter pick, optional per-option `preview` slot.       |
| `src/js/web/src/lib/ArchiveConfirmBar.svelte`     | **new**    | Inline orange-tinted bar with a consequence sentence + Cancel / Confirm buttons. Used for archive and restore.        |
| `src/js/web/src/lib/DeleteTypeDialog.svelte`      | **new**    | Modal with data-loss disclosure, typed-name confirmation, and an "archive instead" hint. Reused for type and field.   |
| `src/js/web/src/lib/FieldsTable.svelte`           | **new**    | Sortable + filterable table of one type's fields. Hosts in-row create / edit (with `Combobox`) and `⋯` overflow menu.|
| `src/js/web/src/lib/TypesRail.svelte`             | **new**    | Left rail: `+ New ▾` combo, filter input, archived toggle, sortable types table, selection callback.                  |
| `src/js/web/src/lib/TypeDetail.svelte`            | **new**    | Right pane: header (title + status + action row), `FieldsTable`, archive confirm bar, delete dialog, empty state.    |
| `src/js/web/src/lib/SchemaBrowser.svelte`         | **rewrite**| Master-detail shell. Owns the snapshot fetch, selection state, show-archived state. Renders `TypesRail` + `TypeDetail`.|
| `src/js/web/src/App.svelte`                       | **rewrite**| Top header bar (title, sub, `v<N> · synced`, overflow menu with token field). Mounts `SchemaBrowser`.                 |
| `src/js/web/src/lib/TypeCard.svelte`              | **delete** | Replaced by `TypeDetail` + `FieldsTable`.                                                                            |
| `src/js/web/src/lib/TypeActions.svelte`           | **delete** | Replaced by the action row inside `TypeDetail`.                                                                      |
| `src/js/web/src/lib/TypeCreateForm.svelte`        | **delete** | Replaced by the `+ New ▾` combo and in-row editing in `TypeDetail`.                                                  |
| `src/js/web/src/lib/FieldActions.svelte`          | **delete** | Replaced by the `⋯` overflow and in-row editing in `FieldsTable`.                                                    |
| `src/js/web/src/lib/FieldCreateForm.svelte`       | **delete** | Replaced by the `+ Add field` button and in-row editing in `FieldsTable`.                                            |
| `src/js/web/src/lib/api.ts`                       | unchanged  | Wire layer.                                                                                                          |
| `src/js/web/src/lib/commands.ts`                  | unchanged  | Wire layer.                                                                                                          |
| `src/js/web/src/lib/schema.ts`                    | unchanged  | Wire layer.                                                                                                          |
| `src/js/web/src/lib/token.ts`                     | unchanged  | Wire layer.                                                                                                          |

Per CLAUDE.md, the `tests/e2e/*.spec.ts` Playwright suites stay as-is; they were never wired to a working browser (M4.1 chrome-path blocker). They are out of scope here but their existence is noted — they reference `TypeCard` / `TypeActions` selectors and will fail once those go away. Either keep them passing-skipped or update them to the new component names. **Decision for this plan:** leave the spec files untouched; the suites already don't run in CI. A follow-up issue can rewrite them when the chrome-path issue is fixed.

---

## Task 1: Combobox primitive

**Files:**
- Create: `src/js/web/src/lib/Combobox.svelte`

**Behavior.**

- Renders a text input plus a chevron. Typing filters a dropdown list of options.
- Props: `value: string`, `options: ReadonlyArray<{ value: string; preview?: string }>`, `placeholder?: string`, `disabled?: boolean`, `onChange: (value: string) => void`.
- Keyboard: `ArrowDown` / `ArrowUp` move highlight, `Enter` picks the highlighted option, `Escape` closes the list and reverts the input to the committed value, `Tab` commits the highlighted option and lets focus move on.
- Mouse: clicking an option commits + closes. Clicking outside closes (revert to committed value).
- Filtering is case-insensitive substring match on `value`. Empty input shows all options.
- The committed value is *one of* the `options[].value` strings — typing free text and tabbing away reverts to the last committed value.
- Optional `preview` text on each option renders to the right of the value in muted italic.

**Why first.** `FieldsTable` (Task 4) imports this. Landing it first means downstream components can rely on its prop surface.

- [ ] **Step 1: Create `src/js/web/src/lib/Combobox.svelte`**

```svelte
<script lang="ts">
  interface Option {
    value: string
    preview?: string
  }

  interface Props {
    value: string
    options: ReadonlyArray<Option>
    placeholder?: string
    disabled?: boolean
    onChange: (value: string) => void
  }

  let { value, options, placeholder = '', disabled = false, onChange }: Props = $props()

  let open = $state(false)
  let inputText = $state(value)
  let highlight = $state(0)
  let rootEl = $state<HTMLDivElement | null>(null)
  let inputEl = $state<HTMLInputElement | null>(null)

  $effect(() => {
    // Sync the input text whenever the committed value changes from outside.
    inputText = value
  })

  let filtered = $derived(
    inputText.trim() === ''
      ? options
      : options.filter((o) =>
          o.value.toLowerCase().includes(inputText.trim().toLowerCase()),
        ),
  )

  $effect(() => {
    // Keep highlight inside [0, filtered.length - 1]
    if (highlight >= filtered.length) highlight = Math.max(0, filtered.length - 1)
  })

  function commitHighlighted(): void {
    const picked = filtered[highlight]
    if (picked !== undefined) {
      inputText = picked.value
      onChange(picked.value)
    } else {
      inputText = value
    }
    open = false
  }

  function revert(): void {
    inputText = value
    open = false
  }

  function onKeyDown(e: KeyboardEvent): void {
    if (disabled) return
    if (e.key === 'ArrowDown') {
      open = true
      highlight = Math.min(filtered.length - 1, highlight + 1)
      e.preventDefault()
    } else if (e.key === 'ArrowUp') {
      open = true
      highlight = Math.max(0, highlight - 1)
      e.preventDefault()
    } else if (e.key === 'Enter') {
      if (open) {
        commitHighlighted()
        e.preventDefault()
      }
    } else if (e.key === 'Escape') {
      revert()
      e.preventDefault()
    } else if (e.key === 'Tab') {
      if (open) commitHighlighted()
      // let Tab navigate naturally afterward
    }
  }

  function onInput(): void {
    open = true
    highlight = 0
  }

  function pick(idx: number): void {
    highlight = idx
    commitHighlighted()
  }

  function onWindowClick(e: MouseEvent): void {
    if (!rootEl) return
    if (!(e.target instanceof Node)) return
    if (!rootEl.contains(e.target)) revert()
  }
</script>

<svelte:window onclick={onWindowClick} />

<div bind:this={rootEl} class="relative">
  <input
    bind:this={inputEl}
    type="text"
    class="w-full rounded border border-gray-300 px-2 py-1 pr-6 text-sm font-mono focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
    {placeholder}
    {disabled}
    bind:value={inputText}
    oninput={onInput}
    onkeydown={onKeyDown}
    onfocus={() => (open = true)}
  />
  <span aria-hidden="true" class="pointer-events-none absolute right-2 top-1.5 text-xs text-gray-500">▾</span>
  {#if open && filtered.length > 0}
    <ul
      role="listbox"
      class="absolute left-0 right-0 top-full z-10 mt-0.5 max-h-48 overflow-auto rounded border border-gray-300 bg-white shadow-md"
    >
      {#each filtered as option, idx (option.value)}
        <li
          role="option"
          aria-selected={idx === highlight}
          class="flex cursor-pointer items-center justify-between px-2 py-1 text-sm"
          class:bg-blue-50={idx === highlight}
          onmousedown={(e) => {
            // mousedown fires before the input's blur — avoid the revert race
            e.preventDefault()
            pick(idx)
          }}
        >
          <span class="font-mono">{option.value}</span>
          {#if option.preview}
            <span class="ml-3 text-xs italic text-gray-500">{option.preview}</span>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>
```

- [ ] **Step 2: Run the Svelte autofixer**

Invoke `mcp__svelte__svelte-autofixer` against `src/js/web/src/lib/Combobox.svelte`. Apply suggested edits. Re-run until it reports zero issues.

- [ ] **Step 3: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors, 0 warnings. (Combobox isn't wired in yet — `npm run check` still compiles it.)

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/Combobox.svelte
git commit -m "$(cat <<'EOF'
feat(web): Combobox primitive for typeable single-select

Generic typeable dropdown used by the data-type picker in the M4.6
fields table. Keyboard nav (Arrow / Enter / Esc / Tab), case-insensitive
substring filter, optional ``preview`` per option for the type-aware
input-widget cue. No external dependencies.

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: ArchiveConfirmBar primitive

**Files:**
- Create: `src/js/web/src/lib/ArchiveConfirmBar.svelte`

**Behavior.**

- Renders an orange-tinted inline bar with a consequence sentence on the left and `Cancel` / `Confirm` buttons on the right.
- Props: `subject: string` (the noun, e.g. `"Pump"` or `"manufacturer"`), `consequence: string` (the one-sentence body), `confirmLabel: string` (defaults to `"Archive"`; the restore call site passes `"Restore"`), `disabled?: boolean`, `onCancel: () => void`, `onConfirm: () => void`.
- No state — fully controlled.

- [ ] **Step 1: Create `src/js/web/src/lib/ArchiveConfirmBar.svelte`**

```svelte
<script lang="ts">
  interface Props {
    subject: string
    consequence: string
    confirmLabel?: string
    disabled?: boolean
    onCancel: () => void
    onConfirm: () => void
  }

  let {
    subject,
    consequence,
    confirmLabel = 'Archive',
    disabled = false,
    onCancel,
    onConfirm,
  }: Props = $props()
</script>

<div
  role="alertdialog"
  aria-label="{confirmLabel} {subject}?"
  class="mt-3 flex items-center justify-between gap-3 rounded border border-orange-300 bg-orange-50 px-3 py-2 text-sm text-orange-900"
>
  <span>
    <strong>{confirmLabel} <span class="font-mono">{subject}</span>?</strong>
    {consequence}
  </span>
  <span class="flex shrink-0 gap-2">
    <button
      type="button"
      class="rounded border border-orange-300 bg-white px-2 py-0.5 text-xs hover:bg-orange-100 disabled:opacity-50"
      {disabled}
      onclick={onCancel}
    >
      Cancel
    </button>
    <button
      type="button"
      class="rounded bg-orange-600 px-2 py-0.5 text-xs text-white hover:bg-orange-700 disabled:opacity-50"
      {disabled}
      onclick={onConfirm}
    >
      {confirmLabel}
    </button>
  </span>
</div>
```

- [ ] **Step 2: Run the Svelte autofixer**

Invoke `mcp__svelte__svelte-autofixer` against the new file. Apply suggestions; re-run until clean.

- [ ] **Step 3: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/ArchiveConfirmBar.svelte
git commit -m "$(cat <<'EOF'
feat(web): ArchiveConfirmBar primitive

Inline orange-tinted confirm bar used for archive and restore at both
type and field level in the M4.6 redesign. Lightweight (no modal) because
the action is reversible. Fully controlled — no internal state.

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: DeleteTypeDialog primitive

**Files:**
- Create: `src/js/web/src/lib/DeleteTypeDialog.svelte`

**Behavior.**

- Renders a centered modal (over a dimmed backdrop) with three sections: heading + irreversibility line, red-bordered warning panel with data-loss disclosure bullets, typed-name confirmation input.
- Props:
  - `subject: string` — the noun to display and to require for typed confirmation, e.g. `"Pump"` or field name.
  - `kindLabel: string` — short text for what's being deleted (`"asset type"`, `"maintenance record type"`, `"field"`).
  - `disclosure: string[]` — one bullet per data-loss line. The caller assembles this from the snapshot (e.g. field counts) per the spec's "Data-loss disclosure — what the modal can say today" section.
  - `disabled?: boolean` — when true (mid-request), Cancel and Delete are both inert.
  - `onCancel: () => void`, `onConfirm: () => void`, `onArchiveInstead?: () => void`.
- Internal state: only the user's typed confirmation string. The Delete button stays disabled until the typed string equals `subject` exactly.
- Closing with Escape calls `onCancel`. Clicking the dimmed backdrop also calls `onCancel`.

- [ ] **Step 1: Create `src/js/web/src/lib/DeleteTypeDialog.svelte`**

```svelte
<script lang="ts">
  interface Props {
    subject: string
    kindLabel: string
    disclosure: string[]
    disabled?: boolean
    onCancel: () => void
    onConfirm: () => void
    onArchiveInstead?: () => void
  }

  let {
    subject,
    kindLabel,
    disclosure,
    disabled = false,
    onCancel,
    onConfirm,
    onArchiveInstead,
  }: Props = $props()

  let typed = $state('')
  let inputEl = $state<HTMLInputElement | null>(null)

  $effect(() => {
    inputEl?.focus()
  })

  function onKeyDown(e: KeyboardEvent): void {
    if (disabled) return
    if (e.key === 'Escape') {
      onCancel()
      e.preventDefault()
    } else if (e.key === 'Enter' && typed === subject) {
      onConfirm()
      e.preventDefault()
    }
  }

  let canConfirm = $derived(typed === subject && !disabled)
</script>

<svelte:window onkeydown={onKeyDown} />

<div
  role="dialog"
  aria-modal="true"
  aria-labelledby="delete-dialog-title"
  class="fixed inset-0 z-20 flex items-start justify-center bg-black/30 p-6 pt-24"
>
  <button
    type="button"
    aria-label="Cancel"
    class="absolute inset-0 cursor-default"
    onclick={onCancel}
    {disabled}
  ></button>
  <div
    class="relative z-30 w-full max-w-lg rounded-lg border border-gray-300 bg-white p-5 shadow-xl"
  >
    <h2 id="delete-dialog-title" class="text-lg font-semibold text-red-700">
      Delete <span class="font-mono">{subject}</span>?
    </h2>
    <p class="mt-1 text-xs text-gray-600">
      This is permanent — there is no undo, and offline clients will lose this data on next sync.
    </p>

    <div class="mt-3 rounded border-l-4 border-red-600 bg-red-50 px-3 py-2 text-sm text-red-900">
      <p class="font-medium">You will permanently delete:</p>
      <ul class="mt-1 ml-4 list-disc space-y-0.5 text-sm">
        {#each disclosure as line, idx (idx)}
          <li>{line}</li>
        {/each}
      </ul>
    </div>

    <label for="delete-confirm-input" class="mt-4 block text-xs font-medium text-gray-700">
      Type
      <code class="rounded bg-gray-100 px-1 py-0.5 font-mono">{subject}</code>
      to confirm
    </label>
    <input
      id="delete-confirm-input"
      bind:this={inputEl}
      type="text"
      class="mt-1 w-full rounded border border-gray-300 px-2 py-1 font-mono text-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500"
      bind:value={typed}
      {disabled}
      placeholder={subject}
    />

    <div class="mt-5 flex items-center justify-between gap-3">
      {#if onArchiveInstead}
        <button
          type="button"
          class="text-xs text-blue-700 underline hover:text-blue-900 disabled:opacity-50"
          onclick={onArchiveInstead}
          {disabled}
        >
          Archive {kindLabel} instead
        </button>
      {:else}
        <span></span>
      {/if}
      <span class="flex gap-2">
        <button
          type="button"
          class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50"
          onclick={onCancel}
          {disabled}
        >
          Cancel
        </button>
        <button
          type="button"
          class="rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!canConfirm}
          onclick={onConfirm}
        >
          Delete forever
        </button>
      </span>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Run the Svelte autofixer**

Invoke `mcp__svelte__svelte-autofixer` against the new file. Apply suggestions; re-run until clean. (The autofixer will likely have opinions about the click-backdrop button — that's fine; accessibility-correct backdrops use a button with `aria-label` exactly as written.)

- [ ] **Step 3: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/DeleteTypeDialog.svelte
git commit -m "$(cat <<'EOF'
feat(web): DeleteTypeDialog primitive

Modal with data-loss disclosure and typed-name confirmation. Used at
type and field level in the M4.6 redesign. The disclosure bullets are
caller-supplied — today the caller passes field counts + generic copy;
once data-side projections are reachable client-side (M2+), concrete
record counts slot into the same shape.

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: FieldsTable composite

**Files:**
- Create: `src/js/web/src/lib/FieldsTable.svelte`

**Behavior.**

- Renders a sortable + filterable table of one type's fields. Columns: `Name`, `Type`, `Status`, overflow-menu.
- Props:
  - `kind: 'asset_type_field' | 'maintenance_record_type_field'` — selects the command discriminator for posts.
  - `parentTypeId: string` — `entity_id` of the type whose fields are shown; required as `parent_id` on `create_*_field`.
  - `fields: readonly FieldView[]` — fed from the snapshot.
  - `showArchived: boolean` — filter prop; archived fields hidden when false.
  - `onChanged: () => void` — bumps the snapshot reload after any successful mutation.
- State (all `$state`):
  - `filter: string` — substring filter on `name`.
  - `sortKey: 'name' | 'data_type' | 'active'` and `sortDir: 'asc' | 'desc' | 'none'` — single-column.
  - `mode` — discriminated union: `{ kind: 'idle' }`, `{ kind: 'editing'; fieldId: string; draftName: string; draftType: FieldDataType }`, `{ kind: 'adding'; draftName: string; draftType: FieldDataType }`, `{ kind: 'confirmingArchive'; field: FieldView }`, `{ kind: 'submitting' }`, `{ kind: 'error'; status: number; code: string; message: string }`.
  - `menuOpenFor: string | null` — which row's `⋯` popover is open.
- Filter + sort applied to the visible field list (memoized via `$derived`).
- `+ Add field` button below the table flips `mode` into `'adding'`. Submitting calls `postSchemaCommand` with `create_<kind>` carrying `parent_id`, `name`, `data_type`.
- Per-row `⋯` menu (a small absolute-positioned popover anchored to the kebab button) exposes: `Rename`, `Change type`, `Archive` (or `Restore`), `Delete…`. `Rename` / `Change type` flip `mode` into `'editing'` with the right field. `Archive` flips into `'confirmingArchive'`. `Delete…` opens a `DeleteTypeDialog` rendered alongside.
- The `ArchiveConfirmBar` and `DeleteTypeDialog` are rendered inside this component (per-field scope).

**Data-type options** for the combobox:

```ts
const DATA_TYPE_OPTIONS: ReadonlyArray<{ value: FieldDataType; preview: string }> = [
  { value: 'text',     preview: 'Aa' },
  { value: 'number',   preview: '12.5' },
  { value: 'integer',  preview: '42' },
  { value: 'boolean',  preview: '☐' },
  { value: 'date',     preview: '📅 2026-05-13' },
  { value: 'datetime', preview: '📅 2026-05-13 14:30' },
]
```

(Order roughly by frequency; the combobox filters as the user types.)

- [ ] **Step 1: Create `src/js/web/src/lib/FieldsTable.svelte`**

```svelte
<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { postSchemaCommand, type FieldKind } from './commands'
  import type { FieldView, FieldDataType } from './schema'
  import ArchiveConfirmBar from './ArchiveConfirmBar.svelte'
  import Combobox from './Combobox.svelte'
  import DeleteTypeDialog from './DeleteTypeDialog.svelte'

  interface Props {
    kind: FieldKind
    parentTypeId: string
    fields: readonly FieldView[]
    showArchived: boolean
    onChanged: () => void
  }

  let { kind, parentTypeId, fields, showArchived, onChanged }: Props = $props()

  type SortKey = 'name' | 'data_type' | 'active'
  type SortDir = 'asc' | 'desc' | 'none'

  type Mode =
    | { kind: 'idle' }
    | { kind: 'editing'; fieldId: string; draftName: string; draftType: FieldDataType }
    | { kind: 'adding'; draftName: string; draftType: FieldDataType }
    | { kind: 'confirmingArchive'; field: FieldView }
    | { kind: 'confirmingDelete'; field: FieldView }
    | { kind: 'submitting' }
    | { kind: 'error'; status: number; code: string; message: string }

  let filter = $state('')
  let sortKey = $state<SortKey>('name')
  let sortDir = $state<SortDir>('asc')
  let mode = $state<Mode>({ kind: 'idle' })
  let menuOpenFor = $state<string | null>(null)

  const DATA_TYPE_OPTIONS: ReadonlyArray<{ value: FieldDataType; preview: string }> = [
    { value: 'text',     preview: 'Aa' },
    { value: 'number',   preview: '12.5' },
    { value: 'integer',  preview: '42' },
    { value: 'boolean',  preview: '☐' },
    { value: 'date',     preview: '📅 2026-05-13' },
    { value: 'datetime', preview: '📅 2026-05-13 14:30' },
  ]

  let visible = $derived.by(() => {
    let rows = fields.filter((f) => showArchived || f.active)
    const needle = filter.trim().toLowerCase()
    if (needle !== '') rows = rows.filter((f) => f.name.toLowerCase().includes(needle))
    if (sortDir !== 'none') {
      const cmp = (a: FieldView, b: FieldView): number => {
        let va: string | number = ''
        let vb: string | number = ''
        if (sortKey === 'name') {
          va = a.name; vb = b.name
        } else if (sortKey === 'data_type') {
          va = a.data_type; vb = b.data_type
        } else {
          va = a.active ? 1 : 0; vb = b.active ? 1 : 0
        }
        if (va < vb) return sortDir === 'asc' ? -1 : 1
        if (va > vb) return sortDir === 'asc' ? 1 : -1
        return 0
      }
      rows = [...rows].sort(cmp)
    }
    return rows
  })

  function toggleSort(key: SortKey): void {
    if (sortKey !== key) {
      sortKey = key
      sortDir = 'asc'
    } else if (sortDir === 'asc') {
      sortDir = 'desc'
    } else if (sortDir === 'desc') {
      sortDir = 'none'
    } else {
      sortDir = 'asc'
    }
  }

  function arrow(key: SortKey): string {
    if (sortKey !== key || sortDir === 'none') return '↕'
    return sortDir === 'asc' ? '↑' : '↓'
  }

  function startAdd(): void {
    mode = { kind: 'adding', draftName: '', draftType: 'text' }
  }

  function startEdit(field: FieldView): void {
    mode = { kind: 'editing', fieldId: field.id, draftName: field.name, draftType: field.data_type }
    menuOpenFor = null
  }

  function startArchive(field: FieldView): void {
    mode = { kind: 'confirmingArchive', field }
    menuOpenFor = null
  }

  function startDelete(field: FieldView): void {
    mode = { kind: 'confirmingDelete', field }
    menuOpenFor = null
  }

  function resetMode(): void {
    mode = { kind: 'idle' }
  }

  function setError(e: unknown): void {
    if (e instanceof ProblemDetailsError) {
      mode = { kind: 'error', status: e.status, code: e.code, message: e.message }
    } else {
      mode = { kind: 'error', status: 0, code: 'network_error', message: String(e) }
    }
  }

  async function submitAdd(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (mode.kind !== 'adding') return
    const name = mode.draftName.trim()
    if (name === '') return
    const draftType = mode.draftType
    mode = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `create_${kind}` as const,
        entity_id: crypto.randomUUID(),
        payload: { parent_id: parentTypeId, name, data_type: draftType },
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  async function submitEdit(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (mode.kind !== 'editing') return
    const name = mode.draftName.trim()
    if (name === '') return
    const original = fields.find((f) => f.id === mode.fieldId)
    if (!original) return
    const payload: { name?: string; data_type?: FieldDataType } = {}
    if (name !== original.name) payload.name = name
    if (mode.draftType !== original.data_type) payload.data_type = mode.draftType
    if (Object.keys(payload).length === 0) {
      resetMode()
      return
    }
    const id = mode.fieldId
    mode = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `update_${kind}` as const,
        entity_id: id,
        payload,
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  async function confirmArchive(): Promise<void> {
    if (mode.kind !== 'confirmingArchive') return
    const field = mode.field
    const verb = field.active ? 'deactivate' : 'activate'
    mode = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `${verb}_${kind}` as const,
        entity_id: field.id,
        payload: {},
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  async function confirmDelete(): Promise<void> {
    if (mode.kind !== 'confirmingDelete') return
    const id = mode.field.id
    mode = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `delete_${kind}` as const,
        entity_id: id,
        payload: {},
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  let busy = $derived(mode.kind === 'submitting')
  let nameError = $derived(
    mode.kind === 'error' && (mode.code === 'name_reserved'),
  )
</script>

<div class="space-y-2">
  <div class="flex items-center gap-2">
    <input
      type="text"
      class="flex-1 rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      placeholder="Filter fields…"
      bind:value={filter}
    />
  </div>

  <table class="w-full border-collapse text-sm">
    <thead>
      <tr class="border-b border-gray-300 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
        <th class="cursor-pointer select-none px-2 py-1" onclick={() => toggleSort('name')}>
          Name <span class="text-blue-600">{arrow('name')}</span>
        </th>
        <th class="cursor-pointer select-none px-2 py-1" onclick={() => toggleSort('data_type')}>
          Type <span class="text-blue-600">{arrow('data_type')}</span>
        </th>
        <th class="cursor-pointer select-none px-2 py-1" onclick={() => toggleSort('active')}>
          Status <span class="text-blue-600">{arrow('active')}</span>
        </th>
        <th class="w-8 px-2 py-1"></th>
      </tr>
    </thead>
    <tbody>
      {#if mode.kind === 'adding'}
        <tr class="bg-blue-50">
          <td colspan="4" class="px-2 py-2">
            <form class="flex items-end gap-2" onsubmit={submitAdd}>
              <div class="flex-1">
                <label for="add-field-name" class="block text-xs font-medium text-gray-700">Name</label>
                <input
                  id="add-field-name"
                  type="text"
                  class="mt-0.5 w-full rounded border px-2 py-1 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  class:border-gray-300={!nameError}
                  class:border-red-500={nameError}
                  bind:value={mode.draftName}
                  disabled={busy}
                  required
                />
              </div>
              <div class="flex-1">
                <span class="block text-xs font-medium text-gray-700">Type</span>
                <div class="mt-0.5">
                  <Combobox
                    value={mode.draftType}
                    options={DATA_TYPE_OPTIONS}
                    disabled={busy}
                    onChange={(v) => {
                      if (mode.kind === 'adding') mode.draftType = v as FieldDataType
                    }}
                  />
                </div>
              </div>
              <button
                type="button"
                class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50"
                onclick={resetMode}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                type="submit"
                class="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                disabled={busy || mode.draftName.trim() === ''}
              >
                {busy ? 'Saving…' : 'Save'}
              </button>
            </form>
          </td>
        </tr>
      {/if}

      {#each visible as field (field.id)}
        {@const isEditing = mode.kind === 'editing' && mode.fieldId === field.id}
        {#if isEditing && mode.kind === 'editing'}
          <tr class="bg-blue-50">
            <td colspan="4" class="px-2 py-2">
              <form class="flex items-end gap-2" onsubmit={submitEdit}>
                <div class="flex-1">
                  <label for="edit-field-name-{field.id}" class="block text-xs font-medium text-gray-700">Name</label>
                  <input
                    id="edit-field-name-{field.id}"
                    type="text"
                    class="mt-0.5 w-full rounded border px-2 py-1 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    class:border-gray-300={!nameError}
                    class:border-red-500={nameError}
                    bind:value={mode.draftName}
                    disabled={busy}
                    required
                  />
                </div>
                <div class="flex-1">
                  <span class="block text-xs font-medium text-gray-700">Type</span>
                  <div class="mt-0.5">
                    <Combobox
                      value={mode.draftType}
                      options={DATA_TYPE_OPTIONS}
                      disabled={busy}
                      onChange={(v) => {
                        if (mode.kind === 'editing') mode.draftType = v as FieldDataType
                      }}
                    />
                  </div>
                </div>
                <button
                  type="button"
                  class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50"
                  onclick={resetMode}
                  disabled={busy}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  class="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                  disabled={busy || mode.draftName.trim() === ''}
                >
                  {busy ? 'Saving…' : 'Save'}
                </button>
              </form>
            </td>
          </tr>
        {:else}
          <tr class="border-b border-gray-100" class:opacity-60={!field.active}>
            <td class="px-2 py-1 font-mono">{field.name}</td>
            <td class="px-2 py-1 text-xs uppercase tracking-wide text-gray-500">{field.data_type}</td>
            <td class="px-2 py-1">
              {#if field.active}
                <span class="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">Active</span>
              {:else}
                <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">Archived</span>
              {/if}
            </td>
            <td class="relative px-2 py-1 text-right">
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={menuOpenFor === field.id}
                class="rounded border border-gray-300 px-1.5 py-0 text-xs hover:bg-gray-50"
                onclick={() => (menuOpenFor = menuOpenFor === field.id ? null : field.id)}
              >
                ⋯
              </button>
              {#if menuOpenFor === field.id}
                <div
                  role="menu"
                  class="absolute right-2 top-7 z-10 w-32 rounded border border-gray-300 bg-white text-left text-sm shadow-md"
                >
                  <button type="button" role="menuitem" class="block w-full px-3 py-1 hover:bg-gray-50" onclick={() => startEdit(field)}>Rename / type</button>
                  <button type="button" role="menuitem" class="block w-full px-3 py-1 hover:bg-gray-50" onclick={() => startArchive(field)}>
                    {field.active ? 'Archive…' : 'Restore…'}
                  </button>
                  <button type="button" role="menuitem" class="block w-full px-3 py-1 text-red-700 hover:bg-red-50" onclick={() => startDelete(field)}>Delete…</button>
                </div>
              {/if}
            </td>
          </tr>
        {/if}
      {/each}

      {#if visible.length === 0 && mode.kind !== 'adding'}
        <tr><td colspan="4" class="px-2 py-3 text-center text-xs italic text-gray-500">
          {fields.length === 0 ? 'No fields yet — use “+ Add field” to add one.' : 'No fields match the filter.'}
        </td></tr>
      {/if}
    </tbody>
  </table>

  {#if mode.kind !== 'adding'}
    <button
      type="button"
      class="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
      onclick={startAdd}
      disabled={busy}
    >
      + Add field
    </button>
  {/if}

  {#if mode.kind === 'confirmingArchive'}
    <ArchiveConfirmBar
      subject={mode.field.name}
      consequence={mode.field.active
        ? 'Values stay; new records can’t pick this field, but old values are kept and visible on archived rows. Restore any time.'
        : 'Restore this field so it can be picked on new records again.'}
      confirmLabel={mode.field.active ? 'Archive' : 'Restore'}
      onCancel={resetMode}
      onConfirm={() => void confirmArchive()}
    />
  {/if}

  {#if mode.kind === 'confirmingDelete'}
    <DeleteTypeDialog
      subject={mode.field.name}
      kindLabel="field"
      disclosure={[
        'All values recorded for this field across every existing record will be permanently deleted.',
        'The field disappears from the schema and offline clients lose it on next sync.',
      ]}
      onCancel={resetMode}
      onConfirm={() => void confirmDelete()}
      onArchiveInstead={() => {
        if (mode.kind === 'confirmingDelete') startArchive(mode.field)
      }}
    />
  {/if}

  {#if mode.kind === 'error'}
    <p class="text-xs text-red-700">
      {#if mode.code === 'entity_not_found'}
        This field no longer exists — reload.
      {:else if mode.code === 'name_reserved'}
        Name is already in use on this type.
      {:else}
        {mode.status} · {mode.code} — {mode.message}
      {/if}
    </p>
  {/if}
</div>
```

- [ ] **Step 2: Run the Svelte autofixer**

Invoke `mcp__svelte__svelte-autofixer` against the new file. The autofixer may flag the kebab popover for missing keyboard escape — apply suggestions; re-run until clean. The popover is intentionally non-modal: clicking elsewhere should *not* close it (we close it explicitly when the user picks an action), so an outside-click-closes handler is not added.

- [ ] **Step 3: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors. The `as Parameters<typeof postSchemaCommand>[1]` casts are deliberate — the discriminated union in `commands.ts` is template-literal-typed and the inferred narrowing fails on `create_${kind}` without the cast.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/FieldsTable.svelte
git commit -m "$(cat <<'EOF'
feat(web): FieldsTable composite

Sortable + filterable table of one type's fields. Per-row \`⋯\` menu
exposes Rename/type / Archive / Delete; \`+ Add field\` opens an in-row
form with the Combobox for the data type. ArchiveConfirmBar handles
archive + restore confirmations; DeleteTypeDialog handles delete with
typed-name confirm and an archive-instead link.

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: TypesRail composite

**Files:**
- Create: `src/js/web/src/lib/TypesRail.svelte`

**Behavior.**

- Renders the left rail: `+ New ▾` combo (asset type / maintenance record type), filter input, "Show archived" toggle, sortable + filterable types index table with `Kind` + `Name` columns.
- Props:
  - `assetTypes: readonly TypeView[]`, `recordTypes: readonly TypeView[]`.
  - `selectedId: string | null` — the currently selected entry; shown highlighted.
  - `showArchived: boolean` and `onShowArchivedChange: (next: boolean) => void` — lifted state so it applies to both rail and right pane consistently.
  - `onSelect: (id: string, kind: 'asset_type' | 'maintenance_record_type') => void`.
  - `onChanged: () => void` — bumped after a successful `create_*_type`.
- Internal state:
  - `filter: string`, `sortKey: 'kind' | 'name'`, `sortDir`.
  - `newKindMenuOpen: boolean` for the `+ New ▾` dropdown.
  - `creating: { kind: 'asset_type' | 'maintenance_record_type'; draftName: string } | null` — a pending in-memory placeholder. When non-null, the placeholder appears at the top of the table as an editing row, focused. Submitting posts `create_*_type` and on success calls `onSelect` with the new id then `onChanged`.
  - Error state mirrors `FieldsTable`'s pattern.
- The combined index = `assetTypes.map(t => ({ kind: 'asset_type', ...t })).concat(recordTypes.map(t => ({ kind: 'maintenance_record_type', ...t })))`, then filter (substring on name, hide archived if `!showArchived`), then sort. Default sort: kind asc, then name asc.

- [ ] **Step 1: Create `src/js/web/src/lib/TypesRail.svelte`**

```svelte
<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { postSchemaCommand, type TypeKind } from './commands'
  import type { TypeView } from './schema'

  interface Props {
    assetTypes: readonly TypeView[]
    recordTypes: readonly TypeView[]
    selectedId: string | null
    showArchived: boolean
    onShowArchivedChange: (next: boolean) => void
    onSelect: (id: string, kind: TypeKind) => void
    onChanged: () => void
  }

  let {
    assetTypes,
    recordTypes,
    selectedId,
    showArchived,
    onShowArchivedChange,
    onSelect,
    onChanged,
  }: Props = $props()

  type Row = { kind: TypeKind; type: TypeView }
  type SortKey = 'kind' | 'name'
  type SortDir = 'asc' | 'desc' | 'none'

  type CreateState =
    | null
    | { kind: TypeKind; draftName: string }

  type ErrState =
    | { kind: 'idle' }
    | { kind: 'submitting' }
    | { kind: 'error'; status: number; code: string; message: string }

  let filter = $state('')
  let sortKey = $state<SortKey>('kind')
  let sortDir = $state<SortDir>('asc')
  let newKindMenuOpen = $state(false)
  let creating = $state<CreateState>(null)
  let err = $state<ErrState>({ kind: 'idle' })

  let allRows = $derived<Row[]>(
    [
      ...assetTypes.map((t) => ({ kind: 'asset_type' as const, type: t })),
      ...recordTypes.map((t) => ({ kind: 'maintenance_record_type' as const, type: t })),
    ],
  )

  let visible = $derived.by(() => {
    let rows = allRows.filter((r) => showArchived || r.type.active)
    const needle = filter.trim().toLowerCase()
    if (needle !== '') rows = rows.filter((r) => r.type.name.toLowerCase().includes(needle))
    if (sortDir !== 'none') {
      const cmp = (a: Row, b: Row): number => {
        let va: string = ''
        let vb: string = ''
        if (sortKey === 'kind') {
          va = a.kind; vb = b.kind
        } else {
          va = a.type.name; vb = b.type.name
        }
        if (va < vb) return sortDir === 'asc' ? -1 : 1
        if (va > vb) return sortDir === 'asc' ? 1 : -1
        // Stable secondary sort by name when keys tie
        return a.type.name.localeCompare(b.type.name)
      }
      rows = [...rows].sort(cmp)
    }
    return rows
  })

  function toggleSort(key: SortKey): void {
    if (sortKey !== key) {
      sortKey = key
      sortDir = 'asc'
    } else if (sortDir === 'asc') {
      sortDir = 'desc'
    } else if (sortDir === 'desc') {
      sortDir = 'none'
    } else {
      sortDir = 'asc'
    }
  }

  function arrow(key: SortKey): string {
    if (sortKey !== key || sortDir === 'none') return '↕'
    return sortDir === 'asc' ? '↑' : '↓'
  }

  function startCreate(kind: TypeKind): void {
    creating = { kind, draftName: '' }
    newKindMenuOpen = false
    err = { kind: 'idle' }
  }

  function cancelCreate(): void {
    creating = null
    err = { kind: 'idle' }
  }

  async function submitCreate(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (creating === null) return
    const name = creating.draftName.trim()
    if (name === '') return
    const kind = creating.kind
    const entity_id = crypto.randomUUID()
    err = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `create_${kind}` as const,
        entity_id,
        payload: { name },
      } as Parameters<typeof postSchemaCommand>[1])
      creating = null
      err = { kind: 'idle' }
      onChanged()
      onSelect(entity_id, kind)
    } catch (e) {
      if (e instanceof ProblemDetailsError) {
        err = { kind: 'error', status: e.status, code: e.code, message: e.message }
      } else {
        err = { kind: 'error', status: 0, code: 'network_error', message: String(e) }
      }
    }
  }

  let nameError = $derived(err.kind === 'error' && err.code === 'name_reserved')
  let busy = $derived(err.kind === 'submitting')
</script>

<aside class="flex h-full w-64 flex-col gap-2 border-r border-gray-200 bg-gray-50 p-3">
  <div class="relative">
    <button
      type="button"
      class="w-full rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      aria-haspopup="menu"
      aria-expanded={newKindMenuOpen}
      onclick={() => (newKindMenuOpen = !newKindMenuOpen)}
      disabled={busy}
    >
      + New ▾
    </button>
    {#if newKindMenuOpen}
      <div role="menu" class="absolute left-0 right-0 top-9 z-10 rounded border border-gray-300 bg-white text-left text-sm shadow-md">
        <button type="button" role="menuitem" class="block w-full px-3 py-1.5 hover:bg-gray-50" onclick={() => startCreate('asset_type')}>Asset type</button>
        <button type="button" role="menuitem" class="block w-full px-3 py-1.5 hover:bg-gray-50" onclick={() => startCreate('maintenance_record_type')}>Maintenance record type</button>
      </div>
    {/if}
  </div>

  <input
    type="text"
    placeholder="Filter…"
    class="rounded border border-gray-300 bg-white px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
    bind:value={filter}
  />

  <label class="flex items-center gap-2 text-xs text-gray-700">
    <input
      type="checkbox"
      checked={showArchived}
      onchange={(e) => onShowArchivedChange((e.currentTarget as HTMLInputElement).checked)}
    />
    Show archived
  </label>

  <table class="w-full table-fixed border-collapse text-sm">
    <thead>
      <tr class="border-b border-gray-300 text-left text-xs uppercase tracking-wide text-gray-600">
        <th class="w-12 cursor-pointer select-none px-1 py-1" onclick={() => toggleSort('kind')}>
          Kind <span class="text-blue-600">{arrow('kind')}</span>
        </th>
        <th class="cursor-pointer select-none px-1 py-1" onclick={() => toggleSort('name')}>
          Name <span class="text-blue-600">{arrow('name')}</span>
        </th>
      </tr>
    </thead>
    <tbody>
      {#if creating !== null}
        <tr class="bg-blue-50">
          <td colspan="2" class="px-1 py-1">
            <form class="flex flex-col gap-1" onsubmit={submitCreate}>
              <span class="text-[10px] uppercase tracking-wide text-gray-500">
                New {creating.kind === 'asset_type' ? 'asset type' : 'maintenance record type'}
              </span>
              <input
                type="text"
                class="w-full rounded border px-2 py-1 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                class:border-gray-300={!nameError}
                class:border-red-500={nameError}
                bind:value={creating.draftName}
                disabled={busy}
                required
                autofocus
              />
              {#if err.kind === 'error'}
                <p class="text-[10px] text-red-700">
                  {#if err.code === 'name_reserved'}
                    Name is already in use.
                  {:else}
                    {err.status} · {err.code} — {err.message}
                  {/if}
                </p>
              {/if}
              <div class="flex justify-end gap-2">
                <button type="button" class="rounded border border-gray-300 bg-white px-2 py-0.5 text-xs hover:bg-gray-100" onclick={cancelCreate} disabled={busy}>Cancel</button>
                <button type="submit" class="rounded bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50" disabled={busy || creating.draftName.trim() === ''}>
                  {busy ? 'Saving…' : 'Save'}
                </button>
              </div>
            </form>
          </td>
        </tr>
      {/if}

      {#each visible as row (row.type.id)}
        <tr
          class="cursor-pointer border-b border-gray-100 hover:bg-blue-50"
          class:bg-blue-100={row.type.id === selectedId}
          class:opacity-60={!row.type.active}
          onclick={() => onSelect(row.type.id, row.kind)}
        >
          <td class="px-1 py-1">
            <span
              class="inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase"
              class:bg-indigo-100={row.kind === 'asset_type'}
              class:text-indigo-800={row.kind === 'asset_type'}
              class:bg-amber-100={row.kind === 'maintenance_record_type'}
              class:text-amber-800={row.kind === 'maintenance_record_type'}
            >
              {row.kind === 'asset_type' ? 'A' : 'R'}
            </span>
          </td>
          <td class="truncate px-1 py-1 font-mono text-sm">{row.type.name}</td>
        </tr>
      {/each}

      {#if visible.length === 0 && creating === null}
        <tr><td colspan="2" class="px-1 py-3 text-center text-xs italic text-gray-500">
          {allRows.length === 0 ? 'No types yet — start with “+ New ▾”.' : 'No types match the filter.'}
        </td></tr>
      {/if}
    </tbody>
  </table>
</aside>
```

- [ ] **Step 2: Run the Svelte autofixer**

Invoke `mcp__svelte__svelte-autofixer` against the new file. Apply suggestions; re-run until clean. The `autofocus` attribute will likely draw an a11y warning — keep it (per the spec the user expects focus on the new-row name input), but add the `// eslint-disable` comment the autofixer suggests if it surfaces one.

- [ ] **Step 3: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/TypesRail.svelte
git commit -m "$(cat <<'EOF'
feat(web): TypesRail composite

Left rail of the M4.6 master-detail layout. \`+ New ▾\` opens a 2-item
dropdown (Asset type / Maintenance record type); selecting one pins a
pending-creation row at the top of the rail with focus on the name
input. Submit posts \`create_*_type\` and on success calls
\`onChanged\` + \`onSelect\` with the new id so the right pane lights up.
The types index is filterable (substring on name) and sortable
(Kind / Name).

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: TypeDetail composite

**Files:**
- Create: `src/js/web/src/lib/TypeDetail.svelte`

**Behavior.**

- Right pane of the master-detail. Renders nothing useful when no type is selected (a friendly empty-state).
- Props:
  - `type: TypeView | null` — selected type from the snapshot, or null.
  - `kind: TypeKind | null` — selected kind (paired with `type`).
  - `showArchived: boolean` — passed through to the FieldsTable.
  - `onChanged: () => void`, `onDeleted: () => void` — `onDeleted` clears the selection upstream.
- Internal state — mode discriminated union for the type-level action row:
  - `{ kind: 'idle' }`
  - `{ kind: 'renaming'; draft: string }`
  - `{ kind: 'confirmingArchive' }`
  - `{ kind: 'confirmingDelete' }`
  - `{ kind: 'submitting' }`
  - `{ kind: 'error'; status: number; code: string; message: string }`
- Header layout:
  - Title row: `<h2>{type.name}</h2>` and a kind sub-line `Asset type · [Active|Archived pill]`.
  - Action row aligned right: `Rename` button, `Archive`/`Restore` button, `Delete…` (danger) button. All three flip mode appropriately.
- Body:
  - The `FieldsTable` for `type`'s fields, with `kind = '${kind}_field' as FieldKind`.
- Empty-state (no type selected): centered icon + "Pick a type on the left, or use **+ New ▾** to add one."

- [ ] **Step 1: Create `src/js/web/src/lib/TypeDetail.svelte`**

```svelte
<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { postSchemaCommand, type FieldKind, type TypeKind } from './commands'
  import type { TypeView } from './schema'
  import ArchiveConfirmBar from './ArchiveConfirmBar.svelte'
  import DeleteTypeDialog from './DeleteTypeDialog.svelte'
  import FieldsTable from './FieldsTable.svelte'

  interface Props {
    type: TypeView | null
    kind: TypeKind | null
    showArchived: boolean
    onChanged: () => void
    onDeleted: () => void
  }

  let { type, kind, showArchived, onChanged, onDeleted }: Props = $props()

  type Mode =
    | { kind: 'idle' }
    | { kind: 'renaming'; draft: string }
    | { kind: 'confirmingArchive' }
    | { kind: 'confirmingDelete' }
    | { kind: 'submitting' }
    | { kind: 'error'; status: number; code: string; message: string }

  let mode = $state<Mode>({ kind: 'idle' })

  // Reset mode when the selection changes.
  let prevId = $state<string | null>(null)
  $effect(() => {
    if ((type?.id ?? null) !== prevId) {
      prevId = type?.id ?? null
      mode = { kind: 'idle' }
    }
  })

  let kindLabel = $derived(kind === 'asset_type' ? 'asset type' : 'maintenance record type')
  let fieldKind = $derived<FieldKind | null>(
    kind === 'asset_type'
      ? 'asset_type_field'
      : kind === 'maintenance_record_type'
        ? 'maintenance_record_type_field'
        : null,
  )
  let busy = $derived(mode.kind === 'submitting')

  function setError(e: unknown): void {
    if (e instanceof ProblemDetailsError) {
      mode = { kind: 'error', status: e.status, code: e.code, message: e.message }
    } else {
      mode = { kind: 'error', status: 0, code: 'network_error', message: String(e) }
    }
  }

  function startRename(): void {
    if (type === null) return
    mode = { kind: 'renaming', draft: type.name }
  }

  function startArchive(): void {
    mode = { kind: 'confirmingArchive' }
  }

  function startDelete(): void {
    mode = { kind: 'confirmingDelete' }
  }

  function resetMode(): void {
    mode = { kind: 'idle' }
  }

  async function submitRename(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (mode.kind !== 'renaming' || type === null || kind === null) return
    const next = mode.draft.trim()
    if (next === '' || next === type.name) {
      resetMode()
      return
    }
    const id = type.id
    mode = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `update_${kind}` as const,
        entity_id: id,
        payload: { name: next },
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  async function confirmArchive(): Promise<void> {
    if (type === null || kind === null) return
    const verb = type.active ? 'deactivate' : 'activate'
    const id = type.id
    mode = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `${verb}_${kind}` as const,
        entity_id: id,
        payload: {},
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  async function confirmDelete(): Promise<void> {
    if (type === null || kind === null) return
    const id = type.id
    mode = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `delete_${kind}` as const,
        entity_id: id,
        payload: {},
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onDeleted()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  let nameError = $derived(mode.kind === 'error' && mode.code === 'name_reserved')
</script>

{#if type === null || kind === null}
  <div class="flex h-full flex-col items-center justify-center gap-2 p-8 text-center text-gray-500">
    <span aria-hidden="true" class="text-4xl opacity-40">⊟</span>
    <p class="text-sm font-medium">Pick a type on the left</p>
    <p class="text-xs">…or use <strong>+ New ▾</strong> to add an asset type or maintenance record type.</p>
  </div>
{:else}
  <section class="flex h-full flex-col gap-4 p-4">
    <header class="flex items-start justify-between gap-4 border-b border-gray-200 pb-3">
      <div>
        {#if mode.kind === 'renaming'}
          <form class="flex items-end gap-2" onsubmit={submitRename}>
            <div>
              <label for="rename-input" class="block text-xs font-medium text-gray-700">Rename</label>
              <input
                id="rename-input"
                type="text"
                class="mt-0.5 rounded border px-2 py-1 font-mono text-base focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                class:border-gray-300={!nameError}
                class:border-red-500={nameError}
                bind:value={mode.draft}
                disabled={busy}
                required
              />
            </div>
            <button type="button" class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50" onclick={resetMode} disabled={busy}>Cancel</button>
            <button
              type="submit"
              class="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              disabled={busy || mode.draft.trim() === '' || mode.draft.trim() === type.name}
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          </form>
        {:else}
          <h2 class="font-mono text-xl font-semibold">{type.name}</h2>
          <p class="mt-0.5 text-xs text-gray-600">
            {kindLabel} ·
            {#if type.active}
              <span class="ml-1 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-medium text-green-800">Active</span>
            {:else}
              <span class="ml-1 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-600">Archived</span>
            {/if}
          </p>
        {/if}
      </div>
      {#if mode.kind !== 'renaming'}
        <div class="flex shrink-0 gap-2">
          <button type="button" class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50" onclick={startRename} disabled={busy}>Rename</button>
          <button type="button" class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50" onclick={startArchive} disabled={busy}>
            {type.active ? 'Archive…' : 'Restore…'}
          </button>
          <button type="button" class="rounded border border-red-300 px-3 py-1 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50" onclick={startDelete} disabled={busy}>Delete…</button>
        </div>
      {/if}
    </header>

    {#if mode.kind === 'error'}
      <p class="text-xs text-red-700">
        {#if mode.code === 'entity_not_found'}
          This type no longer exists — reload.
        {:else if mode.code === 'name_reserved'}
          Name is already in use.
        {:else}
          {mode.status} · {mode.code} — {mode.message}
        {/if}
      </p>
    {/if}

    <div class="flex-1 overflow-auto">
      <p class="mb-2 text-xs font-medium uppercase tracking-wide text-gray-600">
        Fields · {type.fields.length}
      </p>
      {#if fieldKind}
        <FieldsTable
          kind={fieldKind}
          parentTypeId={type.id}
          fields={type.fields}
          {showArchived}
          {onChanged}
        />
      {/if}
    </div>

    {#if mode.kind === 'confirmingArchive'}
      <ArchiveConfirmBar
        subject={type.name}
        consequence={type.active
          ? 'Existing assets and records keep working; no new ones can be created. You can restore later.'
          : 'Restore this type so new assets / records can be created against it.'}
        confirmLabel={type.active ? 'Archive' : 'Restore'}
        onCancel={resetMode}
        onConfirm={() => void confirmArchive()}
      />
    {/if}

    {#if mode.kind === 'confirmingDelete'}
      <DeleteTypeDialog
        subject={type.name}
        {kindLabel}
        disclosure={[
          `All ${kindLabel}s and the records attached to them will be permanently deleted, along with every value and history entry.`,
          `The ${type.fields.length} field${type.fields.length === 1 ? '' : 's'} defined on ${type.name} will be removed.`,
          'Offline clients lose this data on next sync.',
        ]}
        onCancel={resetMode}
        onConfirm={() => void confirmDelete()}
        onArchiveInstead={startArchive}
      />
    {/if}
  </section>
{/if}
```

- [ ] **Step 2: Run the Svelte autofixer**

Invoke `mcp__svelte__svelte-autofixer` against the new file. Apply suggestions; re-run until clean.

- [ ] **Step 3: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/TypeDetail.svelte
git commit -m "$(cat <<'EOF'
feat(web): TypeDetail composite

Right pane of the M4.6 master-detail layout. Header carries the type
name, kind, status pill, and the Rename / Archive / Delete action row;
Rename swaps the title block into an inline form. Body renders the
FieldsTable for the selected type. Archive uses ArchiveConfirmBar at
the bottom of the pane; Delete opens DeleteTypeDialog with field-count
+ generic data-loss copy (concrete record counts arrive when data is
reachable client-side).

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Rewrite SchemaBrowser shell

**Files:**
- Modify: `src/js/web/src/lib/SchemaBrowser.svelte` (full rewrite — the old body is entirely replaced).

**Behavior.**

- Owns the snapshot fetch and re-fetch (same pattern as the current `load()`).
- Owns the selection state (`selectedId`, `selectedKind`) and the `showArchived` toggle.
- Renders `TypesRail` and `TypeDetail` side by side in a flex layout that fills the viewport below the header bar.
- After every successful mutation, `load()` is called via `onChanged`. After `load()` resolves, if the previously selected type no longer exists in the snapshot, selection is cleared.
- Pass-through props from the parent (`reloadKey`) still bump the fetch — same contract as today.
- No more two-column-cards anything. No more `TypeCard` / `TypeActions` / `TypeCreateForm` / `FieldActions` / `FieldCreateForm` imports.

- [ ] **Step 1: Replace `src/js/web/src/lib/SchemaBrowser.svelte`**

```svelte
<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { type TypeKind } from './commands'
  import { fetchSchema, type SchemaSnapshot, type TypeView } from './schema'
  import TypeDetail from './TypeDetail.svelte'
  import TypesRail from './TypesRail.svelte'

  interface Props {
    /** Bump from outside to force a re-fetch (e.g. after the token changes). */
    reloadKey?: number
  }

  let { reloadKey = 0 }: Props = $props()

  type LoadState =
    | { kind: 'idle' }
    | { kind: 'loading' }
    | { kind: 'loaded'; snapshot: SchemaSnapshot }
    | { kind: 'error'; status: number; code: string; message: string }

  let loadState = $state<LoadState>({ kind: 'idle' })
  let selectedId = $state<string | null>(null)
  let selectedKind = $state<TypeKind | null>(null)
  let showArchived = $state(false)

  async function load(): Promise<void> {
    loadState = { kind: 'loading' }
    try {
      const snapshot = await fetchSchema(createApiClient())
      loadState = { kind: 'loaded', snapshot }
      // Clear selection if it points at a type that no longer exists.
      if (selectedId !== null) {
        const all = [...snapshot.asset_types, ...snapshot.maintenance_record_types]
        if (!all.some((t) => t.id === selectedId)) {
          selectedId = null
          selectedKind = null
        }
      }
    } catch (e) {
      if (e instanceof ProblemDetailsError) {
        loadState = { kind: 'error', status: e.status, code: e.code, message: e.message }
      } else {
        loadState = { kind: 'error', status: 0, code: 'network_error', message: String(e) }
      }
    }
  }

  $effect(() => {
    reloadKey
    void load()
  })

  function handleSelect(id: string, kind: TypeKind): void {
    selectedId = id
    selectedKind = kind
  }

  function handleDeleted(): void {
    selectedId = null
    selectedKind = null
  }

  function findSelected(snapshot: SchemaSnapshot): TypeView | null {
    if (selectedId === null) return null
    const haystack =
      selectedKind === 'asset_type'
        ? snapshot.asset_types
        : selectedKind === 'maintenance_record_type'
          ? snapshot.maintenance_record_types
          : []
    return haystack.find((t) => t.id === selectedId) ?? null
  }

  let selectedType = $derived(loadState.kind === 'loaded' ? findSelected(loadState.snapshot) : null)
  let schemaVersion = $derived(loadState.kind === 'loaded' ? loadState.snapshot.schema_version : null)
</script>

<section class="flex h-full flex-col">
  {#if loadState.kind === 'loading'}
    <p class="p-6 text-sm text-gray-600">Loading schema…</p>
  {:else if loadState.kind === 'error'}
    <div class="m-6 rounded border border-red-300 bg-red-50 p-4">
      <p class="text-sm font-semibold text-red-700">{loadState.status} · {loadState.code}</p>
      <p class="mt-1 text-sm text-red-700">{loadState.message}</p>
    </div>
  {:else if loadState.kind === 'loaded'}
    <div class="flex flex-1 overflow-hidden">
      <TypesRail
        assetTypes={loadState.snapshot.asset_types}
        recordTypes={loadState.snapshot.maintenance_record_types}
        {selectedId}
        {showArchived}
        onShowArchivedChange={(next) => (showArchived = next)}
        onSelect={handleSelect}
        onChanged={() => void load()}
      />
      <div class="flex-1 overflow-auto">
        <TypeDetail
          type={selectedType}
          kind={selectedType !== null ? selectedKind : null}
          {showArchived}
          onChanged={() => void load()}
          onDeleted={handleDeleted}
        />
      </div>
    </div>
    {#if schemaVersion !== null}
      <p class="border-t border-gray-200 px-3 py-1 text-right text-[10px] text-gray-500">v{schemaVersion} · synced</p>
    {/if}
  {/if}
</section>
```

- [ ] **Step 2: Run the Svelte autofixer**

Invoke `mcp__svelte__svelte-autofixer` against `src/js/web/src/lib/SchemaBrowser.svelte`. Apply suggestions; re-run until clean.

- [ ] **Step 3: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors. `App.svelte` still imports `SchemaBrowser` — the rewrite preserves the `{ reloadKey: number }` prop contract so the existing call site keeps compiling.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/lib/SchemaBrowser.svelte
git commit -m "$(cat <<'EOF'
feat(web): rewrite SchemaBrowser as master-detail shell

Replaces the two-column card grid with a master-detail layout: the
\`TypesRail\` left rail and the \`TypeDetail\` right pane. The shell owns
the snapshot fetch (\`load\`), selection state, and the \`Show archived\`
toggle. Selection auto-clears when the selected type vanishes from the
post-mutation snapshot. The \`v<N> · synced\` status replaces the prior
top-of-page schema_version display.

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Rewrite App.svelte (header bar + overflow menu)

**Files:**
- Modify: `src/js/web/src/App.svelte` (full rewrite — header changes shape).

**Behavior.**

- A compact top header bar replaces the bearer-token form that takes up the top of the page today. The bar carries:
  - Page title (`novaMOC`) and a one-line subtitle (`Schema management`).
  - A small overflow button (`⋯`) on the right. Clicking opens a popover with the bearer-token input + Apply button.
- Below the header bar, `SchemaBrowser` mounts and fills the rest of the viewport.
- The `reloadKey` is bumped whenever the user applies a new token, same as today.

- [ ] **Step 1: Replace `src/js/web/src/App.svelte`**

```svelte
<script lang="ts">
  import SchemaBrowser from './lib/SchemaBrowser.svelte'
  import { getBearerToken, setBearerToken } from './lib/token'

  let token = $state(getBearerToken() ?? '')
  let reloadKey = $state(0)
  let overflowOpen = $state(false)

  function applyToken(): void {
    setBearerToken(token === '' ? null : token)
    reloadKey += 1
    overflowOpen = false
  }
</script>

<main class="flex h-screen flex-col">
  <header class="flex items-center justify-between gap-4 border-b border-gray-200 px-6 py-3">
    <div>
      <h1 class="text-lg font-semibold">novaMOC</h1>
      <p class="text-xs text-gray-600">Schema management</p>
    </div>
    <div class="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={overflowOpen}
        aria-label="More"
        class="rounded border border-gray-300 px-2 py-1 text-sm hover:bg-gray-50"
        onclick={() => (overflowOpen = !overflowOpen)}
      >
        ⋯
      </button>
      {#if overflowOpen}
        <div role="menu" class="absolute right-0 top-9 z-10 w-72 rounded border border-gray-300 bg-white p-3 text-sm shadow-md">
          <label for="bearer-token" class="block text-xs font-medium text-gray-700">Bearer token</label>
          <p class="mt-0.5 text-[10px] text-gray-500">Empty = fall back to <code>VITE_DEFAULT_BEARER_TOKEN</code>.</p>
          <div class="mt-2 flex gap-2">
            <input
              id="bearer-token"
              type="text"
              class="flex-1 rounded border border-gray-300 px-2 py-1 font-mono text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              bind:value={token}
            />
            <button
              type="button"
              class="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700"
              onclick={applyToken}
            >
              Apply
            </button>
          </div>
        </div>
      {/if}
    </div>
  </header>
  <div class="flex-1 overflow-hidden">
    <SchemaBrowser {reloadKey} />
  </div>
</main>
```

- [ ] **Step 2: Run the Svelte autofixer**

Invoke `mcp__svelte__svelte-autofixer` against `src/js/web/src/App.svelte`. Apply suggestions; re-run until clean.

- [ ] **Step 3: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/src/App.svelte
git commit -m "$(cat <<'EOF'
feat(web): top header bar with token in an overflow menu

Replaces the bearer-token form that owned the top of the page today
with a compact header (title + sub) and an overflow popover that hosts
the token input. The schema body now fills the viewport below the
header. Token Apply still bumps \`reloadKey\` so SchemaBrowser re-fetches.

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Delete obsolete components

**Files:**
- Delete: `src/js/web/src/lib/TypeCard.svelte`
- Delete: `src/js/web/src/lib/TypeActions.svelte`
- Delete: `src/js/web/src/lib/TypeCreateForm.svelte`
- Delete: `src/js/web/src/lib/FieldActions.svelte`
- Delete: `src/js/web/src/lib/FieldCreateForm.svelte`

**Why now.** The rewritten `SchemaBrowser` no longer imports these. `App.svelte` doesn't import them. `npm run check` will catch any straggler import that survived the rewrite — if it does, that's a bug in Task 7, not here.

- [ ] **Step 1: Delete the five files**

```bash
rm src/js/web/src/lib/TypeCard.svelte \
   src/js/web/src/lib/TypeActions.svelte \
   src/js/web/src/lib/TypeCreateForm.svelte \
   src/js/web/src/lib/FieldActions.svelte \
   src/js/web/src/lib/FieldCreateForm.svelte
```

- [ ] **Step 2: Run the type-checker**

```bash
cd src/js/web && npm run check
```

Expected: 0 errors. If any error reports a missing import, find the surviving caller in Task 7 / Task 8 and fix it there before continuing (do not re-add the deleted files).

- [ ] **Step 3: Run the production build**

```bash
cd src/js/web && npm run build
```

Expected: build succeeds, output in `dist/`.

- [ ] **Step 4: Commit**

```bash
git add -A src/js/web/src/lib/
git commit -m "$(cat <<'EOF'
chore(web): drop obsolete schema-management components

Removes the five components from the M4.1–M4.5 card-grid era —
TypeCard, TypeActions, TypeCreateForm, FieldActions, FieldCreateForm —
now that the M4.6 master-detail components fully replace them. No
remaining importers; \`npm run check\` and \`npm run build\` are clean.

Refs #79.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Manual smoke + open PR

**Files:** none.

This is the integration verification. The Playwright suites under `tests/e2e/*.spec.ts` still don't run in CI (M4.1 chrome-path blocker), so manual browser smoke is the integration surface.

- [ ] **Step 1: Boot the API and the SPA**

```bash
# terminal A — API
cd $(git rev-parse --show-toplevel) && just serve
```

```bash
# terminal B — SPA
cd $(git rev-parse --show-toplevel)/src/js/web && npm run dev
```

Open `http://127.0.0.1:5173/` in a browser.

- [ ] **Step 2: Walk the smoke matrix**

Run each item end-to-end. Each should succeed visibly; failures get logged in the PR body.

1. **Empty state.** Token is unset → an empty rail and a friendly right-pane empty-state. Open the overflow menu, paste a dev bearer token, Apply → the rail populates.
2. **+ New (asset type).** Click `+ New ▾` → pick Asset type → in-row form appears at the top of the rail with focus on the name input. Type `pump`, Save → row appears in the rail, selected; right pane shows `pump`'s detail with no fields.
3. **+ New (maintenance record type).** Same flow with `Maintenance record type` → `inspection`. Verify the kind pill renders the `R` chip and the right pane shows `maintenance record type` as the kind.
4. **+ Add field.** On `pump`, click `+ Add field` → in-row form. Name `manufacturer`, leave Type at `text`, Save → field appears.
5. **Combobox keyboard nav.** Start `+ Add field`, focus the Type input. Type `da`, see `date` and `datetime` filter in. Arrow-down to `datetime`, press Enter → committed to `datetime`. Save with name `install_at`.
6. **Combobox type-aware previews.** Open the Type combobox without filtering; each option shows its preview (`Aa`, `12.5`, `42`, `☐`, `📅 …`).
7. **Rename a type.** On `pump`, click `Rename` → header swaps to a form. Change to `pump_v2`, Save → header re-renders with the new name; rail row updates after `load()` resolves.
8. **Rename to a colliding name.** Create `compressor`, then on `pump_v2` try to rename to `compressor` → 409 surfaces as inline `Name is already in use.`; form stays open.
9. **Edit a field.** On `pump_v2`, click `⋯` on `manufacturer` → `Rename / type`. Change the name to `vendor`, Save → row updates.
10. **Filter.** Type `m` in the rail filter → only rows whose names contain `m` show.
11. **Sort.** Click `Name` in the rail header → toggles ascending / descending / unsorted. Same in the fields table.
12. **Show archived (off).** Archive a field → it disappears from the visible list. Archive a type → it disappears from the rail.
13. **Show archived (on).** Toggle `Show archived` → archived rows reappear muted with an `Archived` pill in the Status column. `Archive…` action becomes `Restore…` on those rows.
14. **Restore.** Restore the archived field → status flips to Active. Restore the archived type.
15. **Archive confirm bar.** Click `Archive…` on a type → an orange bar appears at the bottom of the pane. Click Cancel → bar dismisses with no mutation. Re-open and confirm → mutation lands.
16. **Delete (typed-name confirm).** Click `Delete…` on a type → modal opens with disclosure bullets (field count visible). Try clicking `Delete forever` while the input is empty → button is disabled. Type the wrong name → still disabled. Type the exact name → enabled. Cancel; modal closes. Re-open and confirm → type vanishes, selection clears, the right pane shows the empty state.
17. **Archive instead.** Open the Delete modal → click `Archive {kindLabel} instead` → modal closes, archive confirm bar appears.
18. **entity_not_found.** Use two browser windows. In window A, delete a type. In window B (which still has the stale selection on that type), click any action → inline `This type no longer exists — reload.` Refresh window B; selection clears.
19. **Sync indicator.** After every successful mutation, the `v<N> · synced` footer increments.

- [ ] **Step 3: Run the repo-wide check**

```bash
cd $(git rev-parse --show-toplevel) && just check
```

Expected: lint + format + typecheck + pytest clean. (`just check` covers Python; the frontend's `npm run check` and `npm run build` were verified in earlier tasks. Ratchet unchanged.)

- [ ] **Step 4: Push the branch and flip the PR out of draft**

The branch already has #80 (the spec PR) open as a draft on it. The 10-task implementation lands on the same branch (or a fresh implementation branch — if a separate branch is desired, rebase the impl commits onto a new branch `m4-6-schema-ui-impl` and open a new PR; the spec PR merges first).

Decide branch strategy:
- **Single PR**: keep everything on `m4-6-schema-ui-design-spec`, push, mark the existing PR ready for review.
- **Two PRs**: leave `m4-6-schema-ui-design-spec` as the design-only PR. Branch a new `m4-6-schema-ui-impl` from `main` after the spec PR merges, cherry-pick / rebase the implementation commits there, open the impl PR against `main`.

Either way:

```bash
git push
# if single-PR strategy:
gh pr ready 80
# if two-PR strategy:
# (after spec PR merges)
git checkout main && git pull
git checkout -b m4-6-schema-ui-impl
git cherry-pick <impl commits>
git push -u origin m4-6-schema-ui-impl
gh pr create --base main --title "M4.6 Schema management UI redesign — implementation" --body "..."
```

The PR body documents the smoke matrix above as the test plan, mirroring the M4.3 PR template.

---

## Verification

Final sanity checks before the PR ships:

- `cd src/js/web && npm run check` — 0 errors, 0 warnings.
- `cd src/js/web && npm run build` — succeeds, `dist/` contains the build.
- `just check` from repo root — lint + format + typecheck + pytest all clean. Ratchet unchanged (this PR touches no Python).
- Smoke matrix from Task 10 step 2 — every item passes.
- `git status` — clean (no straggler files).
- `git log --oneline main..HEAD` — nine commits (one per non-smoke task), in the order specified by this plan, each with the `Refs #79` footer.

If any check fails, find and fix the root cause in the task that introduced the regression — don't paper over with a fix-up commit unless the change is genuinely orthogonal.
