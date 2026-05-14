# Design: schema management UI redesign

## Status

Approved 2026-05-13 (issue #79 — "M4.6 Schema management UI design pass"). Replaces the
developer-flavored UI assembled piece-by-piece across M4.1 / M4.2 / M4.3 / M4.4 / M4.5
(issues #41–#45). The wire layer is untouched; only `src/js/web/src/` changes.

## Problem

The M4.1–M4.5 milestones shipped one lifecycle verb at a time. Each issue added
the smallest UI to drive its endpoint, and the next issue glued more onto
`SchemaBrowser.svelte` without revisiting the whole. The result functions
correctly but reads as a developer poking at the wire format:

- The two-column "asset types | maintenance record types" grid uses cards with
  rename / archive / delete buttons stacked under each card. Both columns
  always visible; no focused workspace; no way to scale past a few types per
  column.
- Wire-format vocabulary leaks: `tombstoned` (DB-internal), `data_type`
  (wire-key name), `schema_version` (debug breadcrumb), a bearer-token field
  taking up half the top of the page.
- Destructive actions all share one weight — a small inline button.
  Archive and delete look the same, but delete deletes data.
- Discovery is by stacked-card scanning. No filter, no sort, no master-detail
  selection state.

The actual user is a maintenance manager configuring asset types and
maintenance-record types during onboarding, then occasionally adding or
editing a field. Comfortable with spreadsheets; not comfortable with JSON.
The current UI doesn't speak to that user.

## Audience

Maintenance manager / tenant admin. Configures the schema once or twice
during onboarding, then occasional edits. Spreadsheet-comfortable, not
developer-comfortable. Never sees UUIDs or wire fields.

## Goals

1. Reframe the existing surface (no new server endpoints) for the
   maintenance-manager audience.
2. Replace the two-column card grid with a master-detail layout that
   uses tables on both sides.
3. Distinguish reversible (archive) from irreversible (delete) destructive
   actions visually and behaviorally.
4. Make filter and sort first-class on both the types index and the fields
   table.
5. Lay down design conventions (combobox for the data-type picker,
   type-aware form widgets, inline-vs-modal confirms) that the rest of the
   product can adopt later.

## Non-goals

- New server endpoints. The `POST /schema` command set and `GET /schema` read
  surface are unchanged.
- Field-level metadata beyond what the wire carries today (no description /
  help text, no required flag, no validation rules, no display order).
- Audit info (no last-edited-by / when).
- Cross-type field search.
- Bulk operations.
- Mobile / responsive design.
- A real settings or auth surface. The bearer-token input moves off the main
  page; a permanent settings home is a separate concern.
- URL-routable selection state. Master-detail selection is session state for
  now; URL routing is wishlist.

## Architecture

### Information architecture

Two regions inside a top header bar:

- **Left rail — types index.** Compact table with two columns: `Kind` (small
  pill `A` / `R`) and `Name`. A toolbar above the table holds a **`+ New ▾`**
  combo button, a filter input, and a **Show archived** toggle. Column
  headers are clickable to sort. Rows are clickable to select; the selected
  row is highlighted and drives the right pane.
- **Right pane — type workspace.** Header shows the selected type's name,
  kind, and status pill, plus an action row (`Rename`, `Archive`,
  `Delete…`). Body shows the **Fields** table with columns `Name` / `Type` /
  `Status` / overflow-menu. A filter input sits above the table; column
  headers sort. A `+ Add field` button below the table opens a new editing
  row inline.

Header bar contains the page title, a one-line description, and a small
**`v<N> · synced`** status indicator in the top-right (this is the
visible-but-deprioritized successor to `schema_version`).

The bearer-token input no longer sits in the page body. Until a real
settings surface exists, it lives behind a small overflow button in the
header bar.

```
┌─────────────────────────────────────────────────────────────────┐
│ Schema                                              v3 · synced │
│ Define what you track and the work you log                  ⋯   │
├──────────────┬──────────────────────────────────────────────────┤
│ + New ▾      │ Pump                                             │
│ [filter…]    │ Asset type · [Active]    Rename Archive Delete…  │
│ ☐ archived   ├──────────────────────────────────────────────────┤
│ Kind  Name ↑ │ Fields · 5                                       │
│ A     Compr… │ [filter fields…]                                 │
│ A     Pump * │ Name ↑       Type     Status     ⋯               │
│ A     Vehicle│ manufactur…  text     Active     ⋯               │
│ R     Inspe… │ model        text     Active     ⋯               │
│ R     Repair │ install_date date     Active     ⋯               │
│              │ + Add field                                      │
└──────────────┴──────────────────────────────────────────────────┘
```

### Entry points (`+ New ▾`)

A single combo button in the rail toolbar. Click reveals two items: **Asset
type** and **Maintenance record type**. Choosing one creates an empty
in-memory placeholder in the rail (selected, kind-pill set), focuses the
pane, and renders an in-row editing form in the pane header with the name
input focused. The type is not created on the server until Save. Cancel
discards the placeholder.

### Edit pattern (rename, change type, add field)

In-row form swap with explicit `Cancel` / `Save`. Same pattern at all
three levels:

- **Rename a type.** Clicking `Rename` swaps the pane header's title block
  for a name input and Save / Cancel buttons.
- **Add a field.** Clicking `+ Add field` appends an editing row to the
  fields table with a `Name` input and a `Type` combobox.
- **Edit a field.** Clicking `⋯ → Rename` (or `Change type`) swaps that
  field's row for an editing row.

A type's `kind` is immutable. A field's `Type` (data type) is mutable today
but should only widen the data type — narrowing semantics are out of scope
for this redesign and inherit whatever `update_*_field` allows.

### Data-type picker

The `Type` column's input is a **combobox** — a typeable single-select:

- Typing filters the option list.
- Arrow keys + Enter pick. Click also picks.
- Escape closes without changing.
- Each option shows the input widget the data type implies as a small
  italic preview to the right (`date` shows `📅 2026-05-13`, `integer`
  shows `123`, `boolean` shows `☐`, etc.). The preview is decorative —
  cue, not control.

### Type-aware form widgets (principle)

Anywhere the UI accepts a *value for a field* of a known data type, the
input widget matches the data type:

- `date` → date picker
- `datetime` → datetime picker
- `integer` / `float` → numeric input with appropriate keyboard
- `boolean` → checkbox / toggle
- `text` → text input

In M4.6 scope this only shows up as the combobox previews above. When
default values / validation rules / data-entry forms land in future scope,
they all inherit this principle.

### Filter and sort

Filter inputs above both the rail table and the fields table. Filtering is
client-side over the in-memory snapshot, case-insensitive substring match
on `Name`.

Column headers are clickable to sort. Click cycles through ascending /
descending / unsorted. The active sort key + direction is shown by a small
arrow next to the column label (`↑` / `↓` / dim `↕`). Single-column sort
only; multi-column sort is wishlist.

Both filter and sort live in component state — no URL persistence.

### Archived display

Archived types and fields are **hidden by default**.

A **Show archived** checkbox in the rail toolbar reveals archived rows
inline (no separate section). Archived rows render muted (`text-gray-400`)
and carry a single **Archived** pill in the `Status` column — no duplicate
indicators elsewhere on the row.

The same toggle applies to the fields table when the selected type has
archived fields. The toggle state is rail-level and persists across the
session (component state).

The pane's action row replaces `Archive` with `Restore` when the selected
type is archived; same swap happens for the field-level `⋯` menu.

### Destructive-action confirms

Two distinct patterns, scaled to consequence:

- **Archive (and Restore).** Inline confirm bar at the bottom of the
  right pane. Text reads "Archive Pump? Existing assets and records keep
  working; no new ones can be created. You can restore later." `Cancel` /
  `Archive` buttons. Lightweight because the action is reversible. Same
  pattern at field level ("Archive field `manufacturer`?").
- **Delete.** Modal dialog. The modal:
  - Shows a red-bordered warning panel with the data-loss disclosure
    (see below for what's shown today vs. when data syncing lands).
  - Requires the user to type the type's name in a confirmation input.
  - The `Delete forever` button stays disabled until the typed name
    matches exactly.
  - Includes an `Archive instead` affordance pointing the user at the
    reversible path.

  Same modal shape at field level.

  **Data-loss disclosure — what the modal can say today.** The schema
  snapshot (`GET /schema`) carries only the schema; data-side projections
  (asset rows, maintenance-record rows, field-value rows) aren't reachable
  client-side until data syncing lands in M2+. The deliverable in M4.6 is
  therefore:

  - At type level: list the field count (available from the snapshot,
    e.g. "5 fields defined on Pump") and a generic data-loss line
    ("All assets of this type and every maintenance record on them will
    be permanently deleted, along with their field values and history").
  - At field level: a generic line ("All values recorded for this field
    across every asset / record of this type will be permanently
    deleted"). No row count.
  - The modal copy is structured so concrete counts can be slotted in
    once the client has access to the data projections — but the M4.6
    implementation does **not** call a new endpoint to fetch them and
    does **not** lie about counts it can't see. When data is in scope
    later, the modal grows real numbers in the same slots.

### Terminology cleanup

Wire-format vocabulary that leaks today, and what replaces it in the UI:

| Today (UI string) | New (UI string)                              | Why                                                            |
| ----------------- | -------------------------------------------- | -------------------------------------------------------------- |
| `tombstoned`      | **Archived**                                 | The user's mental model is "I put it away," not "I killed it." |
| `data_type`       | **Type** (in the fields table column header) | Plain English.                                                 |
| `schema_version`  | **`v<N> · synced`** in the page header       | Stays visible (it's an honest sync signal) but deprioritized.  |
| `entity_id` / UUID| (never surfaced)                             | Identifies wire entities; not a user concept.                  |
| Bearer token UI   | Overflow menu in the header bar              | Auth state shouldn't dominate the main page.                   |

`asset type` and `maintenance record type` stay — they are domain terms.

### Error rendering

Unchanged from M4.2. RFC 9457 problem-details still render inline; the
forms still branch on the leaf code segment:

- `name_reserved` (create / update) — red ring on the offending `Name`
  input + the error message under it.
- `payload_no_changes` (update) — under the form: "No changes to apply".
- `entity_not_found` (any verb) — under the row or pane: "This no longer
  exists — reload."
- Anything else — `status · code · message` fallback.

The dispatch table from M4.3 / M4.4 carries forward; only the rendering
surface (where the inline message attaches to) shifts to the new
master-detail layout.

### Search scope

Rail-only, name-only, types only. Field-name search across types is
wishlist (it requires either a separate query surface or fanning out
client-side over all types' field arrays — not in M4.6 scope).

### Accessibility

Concrete a11y behavior (focus management on row select, focus-trap on the
delete modal, ARIA on the combobox, keyboard reachability of the `⋯`
overflow menu, etc.) is part of the implementation plan, not the design
spec. The expectation set here is that everything in the UI is
keyboard-reachable and screen-reader-labelled; the plan settles on the
specific patterns.

### Selection and refresh

Selection lives in component state — the selected type's `id`. After a
successful mutation, the page calls `load()` to re-fetch the full
snapshot (same pattern as today). On reload, the previously selected
type is re-selected by id if it still exists; if it was deleted, the
selection clears and the empty-state appears in the right pane.

The empty-state in the right pane reads "Pick a type on the left, or
use **+ New ▾** to add one." with a muted icon.

## Component / file plan

The wire layer (`lib/api.ts`, `lib/commands.ts`, `lib/schema.ts`,
`lib/token.ts`) is **unchanged**. The UI layer is reorganized:

| Path                                  | Status     | Responsibility                                                                  |
| ------------------------------------- | ---------- | ------------------------------------------------------------------------------- |
| `App.svelte`                          | **rewrite**| Header bar (title, sub, `v<N> · synced`, overflow menu hosting the token field). Mounts the schema app body.|
| `lib/SchemaBrowser.svelte`            | **rewrite**| Master-detail shell — owns the snapshot fetch, selection state, filter/sort state, `load()`. Renders `TypesRail` + `TypeDetail`.|
| `lib/TypesRail.svelte`                | **new**    | Left rail: toolbar (`+ New ▾`, filter, archived toggle), sortable types table, selection callback.|
| `lib/TypeDetail.svelte`               | **new**    | Right pane: pane header (title block + action row), fields table, empty-state.  |
| `lib/FieldsTable.svelte`              | **new**    | Sortable + filterable table of fields; hosts the `⋯` overflow popover; renders editing rows.|
| `lib/Combobox.svelte`                 | **new**    | Typeable single-select for the data-type picker. Generic enough to reuse for future pickers.|
| `lib/ArchiveConfirmBar.svelte`        | **new**    | Inline red-tinted confirm bar with consequence text + Cancel / Archive buttons. Used at type *and* field level.|
| `lib/DeleteTypeDialog.svelte`         | **new**    | Modal: data-loss counts + typed-name confirmation. Same component handles field-level delete via a `subject` prop.|
| `lib/TypeCard.svelte`                 | **delete** | Replaced by `TypeDetail` (pane header + fields table).                          |
| `lib/TypeActions.svelte`              | **delete** | Replaced by the action row inside `TypeDetail`.                                 |
| `lib/TypeCreateForm.svelte`           | **delete** | Replaced by `+ New ▾` + in-row editing in `TypeDetail`.                         |
| `lib/FieldActions.svelte`             | **delete** | Replaced by the `⋯` overflow + in-row editing in `FieldsTable`.                 |
| `lib/FieldCreateForm.svelte`          | **delete** | Replaced by `+ Add field` + in-row editing in `FieldsTable`.                    |
| `lib/api.ts`, `lib/commands.ts`,      | unchanged  | Wire layer.                                                                     |
| `lib/schema.ts`, `lib/token.ts`       |            |                                                                                 |

The Combobox and Dialog primitives are likely hand-rolled with Svelte 5
runes; whether to pull a headless component library (`bits-ui`, `melt-ui`,
etc.) is an implementation choice for the plan, not a design choice here.

## Tests

The frontend has no test runner today (per the M4.3 plan); verification is
`npm run check` (svelte-check + tsc) + `npm run build` + a manual smoke
through the Vite proxy and browser. The same surface applies:

- `npm run check` clean.
- `npm run build` clean.
- `just check` clean (Python side unchanged; ratchet unchanged).
- Manual browser smoke covering the golden paths and edge cases — at
  minimum:
  - Create an asset type via `+ New ▾`; selected, in-row editing, Save.
  - Create a maintenance record type the same way.
  - Add a field to a type via `+ Add field`; combobox keyboard nav.
  - Rename a type; rename a field.
  - Filter the rail; sort the rail by Name; sort the fields table by Type.
  - Toggle `Show archived` on and off; archive a type and verify it
    re-appears muted when the toggle is on.
  - Archive confirm bar at type level and field level.
  - Delete a type: modal opens, counts populate, button disabled until
    name typed, archive-instead path works.
  - Trigger a `name_reserved` and confirm the existing inline rendering
    still works.
- Playwright-driven smoke is still gated on the M4.1 / M4.2 chrome-path
  blocker; the manual results are documented in the PR.

When the frontend test runner lands (separate concern), the manual smoke
list above is the seed for the component / e2e suite.

## Out of scope (wishlist — separate issues)

- Per-field description / help text.
- Field display order (drag-to-reorder).
- Required-vs-optional flag on fields.
- Value validation rules (min / max, regex, enum).
- Inline relationships between asset types and maintenance record types
  (which record types apply to which assets, etc.).
- Audit info (last edited by / when) surfaced in the UI.
- Field-name search across types.
- Bulk operations (multi-select rows, batch archive / delete).
- Multi-column sort.
- URL-routable selection (`/schema/asset-type/<id>`) and bookmarkable
  filters.
- Mobile / responsive design.
- A real settings surface to host the bearer-token field.
- Real-time updates (push from server / cross-tab sync).

Each of these can be its own issue and is expected to land after M4.6
ships.

## Refs

- ADR-008 — server-authoritative schema (the verb set the UI drives).
- ADR-016 — RFC 9457 problem-details (the error envelope the inline
  rendering branches on).
- ADR-017 — tenant resolution via the bearer token (the reason the token
  field exists at all).
- Issue #79 — the M4.6 tracking issue.
