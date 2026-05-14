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
    | { kind: 'adding'; draftName: string; draftType: FieldDataType | '' }
    | { kind: 'confirmingArchive'; field: FieldView }
    | { kind: 'confirmingDelete'; field: FieldView }
    | { kind: 'submitting'; resumeAs: Mode }

  type ErrState =
    | { kind: 'idle' }
    | { kind: 'error'; status: number; code: string; message: string }

  let filter = $state('')
  let sortKey = $state<SortKey>('name')
  let sortDir = $state<SortDir>('asc')
  let mode = $state<Mode>({ kind: 'idle' })
  let err = $state<ErrState>({ kind: 'idle' })
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
    mode = { kind: 'adding', draftName: '', draftType: '' }
    err = { kind: 'idle' }
  }

  function startEdit(field: FieldView): void {
    mode = { kind: 'editing', fieldId: field.id, draftName: field.name, draftType: field.data_type }
    err = { kind: 'idle' }
    menuOpenFor = null
  }

  function startArchive(field: FieldView): void {
    mode = { kind: 'confirmingArchive', field }
    err = { kind: 'idle' }
    menuOpenFor = null
  }

  function startDelete(field: FieldView): void {
    mode = { kind: 'confirmingDelete', field }
    err = { kind: 'idle' }
    menuOpenFor = null
  }

  function resetMode(): void {
    mode = { kind: 'idle' }
    err = { kind: 'idle' }
  }

  // On error, keep the form (or confirm UI) open so the user can fix and retry.
  // ``resume`` is whatever mode the user was in before submit — we restore it
  // verbatim so their draft input survives the round-trip.
  function setError(e: unknown, resume: Mode): void {
    mode = resume
    if (e instanceof ProblemDetailsError) {
      err = { kind: 'error', status: e.status, code: e.code, message: e.message }
    } else {
      err = { kind: 'error', status: 0, code: 'network_error', message: String(e) }
    }
  }

  async function submitAdd(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (mode.kind !== 'adding') return
    const name = mode.draftName.trim()
    if (name === '') return
    if (mode.draftType === '') return
    const draftType = mode.draftType
    const resume = mode
    err = { kind: 'idle' }
    mode = { kind: 'submitting', resumeAs: resume }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `create_${kind}` as const,
        entity_id: crypto.randomUUID(),
        payload: { parent_id: parentTypeId, name, data_type: draftType },
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e, resume)
    }
  }

  async function submitEdit(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (mode.kind !== 'editing') return
    const { fieldId, draftType } = mode
    const name = mode.draftName.trim()
    if (name === '') return
    const original = fields.find((f) => f.id === fieldId)
    if (!original) return
    const payload: { name?: string; data_type?: FieldDataType } = {}
    if (name !== original.name) payload.name = name
    if (draftType !== original.data_type) payload.data_type = draftType
    if (Object.keys(payload).length === 0) {
      resetMode()
      return
    }
    const id = fieldId
    const resume = mode
    err = { kind: 'idle' }
    mode = { kind: 'submitting', resumeAs: resume }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `update_${kind}` as const,
        entity_id: id,
        payload,
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e, resume)
    }
  }

  async function confirmArchive(): Promise<void> {
    if (mode.kind !== 'confirmingArchive') return
    const field = mode.field
    const verb = field.active ? 'deactivate' : 'activate'
    const resume = mode
    err = { kind: 'idle' }
    mode = { kind: 'submitting', resumeAs: resume }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `${verb}_${kind}` as const,
        entity_id: field.id,
        payload: {},
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e, resume)
    }
  }

  async function confirmDelete(): Promise<void> {
    if (mode.kind !== 'confirmingDelete') return
    const id = mode.field.id
    const resume = mode
    err = { kind: 'idle' }
    mode = { kind: 'submitting', resumeAs: resume }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `delete_${kind}` as const,
        entity_id: id,
        payload: {},
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e, resume)
    }
  }

  let busy = $derived(mode.kind === 'submitting')
  let nameError = $derived(err.kind === 'error' && err.code === 'name_reserved')

  // Close the per-row `⋯` overflow when the user clicks anywhere outside a
  // menu region. Trigger buttons + menu containers carry `data-menu-region`
  // so their own clicks pass through.
  function onWindowClick(e: MouseEvent): void {
    if (menuOpenFor === null) return
    if (!(e.target instanceof Element)) return
    if (e.target.closest('[data-menu-region]')) return
    menuOpenFor = null
  }
</script>

<svelte:window onclick={onWindowClick} />

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
      {#snippet fieldForm(params: {
        nameId: string
        onsubmit: (e: SubmitEvent) => void
        draftName: string
        setDraftName: (v: string) => void
        draftType: string
        setDraftType: (v: string) => void
      })}
        <tr class="bg-blue-50">
          <td colspan="4" class="px-2 py-2">
            <form class="flex items-end gap-2" onsubmit={params.onsubmit}>
              <div class="flex-1">
                <label for={params.nameId} class="block text-xs font-medium text-gray-700">Name</label>
                <input
                  id={params.nameId}
                  type="text"
                  class="mt-0.5 w-full rounded border px-2 py-1 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  class:border-gray-300={!nameError}
                  class:border-red-500={nameError}
                  value={params.draftName}
                  oninput={(e) => params.setDraftName((e.currentTarget as HTMLInputElement).value)}
                  disabled={busy}
                  required
                />
              </div>
              <div class="flex-1">
                <span class="block text-xs font-medium text-gray-700">Type</span>
                <div class="mt-0.5">
                  <Combobox
                    value={params.draftType}
                    options={DATA_TYPE_OPTIONS}
                    ariaLabel="Field data type"
                    disabled={busy}
                    onChange={params.setDraftType}
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
                disabled={busy || params.draftName.trim() === '' || params.draftType === ''}
              >
                {busy ? 'Saving…' : 'Save'}
              </button>
            </form>
          </td>
        </tr>
      {/snippet}

      {#if mode.kind === 'adding'}
        {@render fieldForm({
          nameId: 'add-field-name',
          onsubmit: submitAdd,
          draftName: mode.draftName,
          setDraftName: (v) => { if (mode.kind === 'adding') mode.draftName = v },
          draftType: mode.draftType,
          setDraftType: (v) => { if (mode.kind === 'adding') mode.draftType = v as FieldDataType },
        })}
      {/if}

      {#each visible as field (field.id)}
        {#if mode.kind === 'editing' && mode.fieldId === field.id}
          {@render fieldForm({
            nameId: `edit-field-name-${field.id}`,
            onsubmit: submitEdit,
            draftName: mode.draftName,
            setDraftName: (v) => { if (mode.kind === 'editing') mode.draftName = v },
            draftType: mode.draftType,
            setDraftType: (v) => { if (mode.kind === 'editing') mode.draftType = v as FieldDataType },
          })}
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
                data-menu-region
                aria-haspopup="menu"
                aria-expanded={menuOpenFor === field.id}
                aria-label="Field actions for {field.name}"
                class="rounded border border-gray-300 px-1.5 py-0 text-xs hover:bg-gray-50"
                onclick={() => (menuOpenFor = menuOpenFor === field.id ? null : field.id)}
              >
                ⋯
              </button>
              {#if menuOpenFor === field.id}
                <div
                  role="menu"
                  data-menu-region
                  class="absolute right-2 top-7 z-10 w-32 rounded border border-gray-300 bg-white text-left text-sm shadow-md"
                >
                  <button type="button" role="menuitem" class="block w-full px-3 py-1 text-left hover:bg-gray-50" onclick={() => startEdit(field)}>Edit</button>
                  <button type="button" role="menuitem" class="block w-full px-3 py-1 text-left hover:bg-gray-50" onclick={() => startArchive(field)}>
                    {field.active ? 'Archive…' : 'Restore…'}
                  </button>
                  <button type="button" role="menuitem" class="block w-full px-3 py-1 text-left text-red-700 hover:bg-red-50" onclick={() => startDelete(field)}>Delete…</button>
                </div>
              {/if}
            </td>
          </tr>
        {/if}
        {#if mode.kind === 'confirmingArchive' && mode.field.id === field.id}
          <tr>
            <td colspan="4" class="px-2 pt-0 pb-2">
              <ArchiveConfirmBar
                subject={mode.field.name}
                consequence={mode.field.active
                  ? 'Values stay; new records can’t pick this field, but old values are kept and visible on archived rows. Restore any time.'
                  : 'Restore this field so it can be picked on new records again.'}
                confirmLabel={mode.field.active ? 'Archive' : 'Restore'}
                onCancel={resetMode}
                onConfirm={() => void confirmArchive()}
              />
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

  {#if err.kind === 'error'}
    <p class="text-xs text-red-700">
      {#if err.code === 'entity_not_found'}
        This field no longer exists — reload.
      {:else if err.code === 'name_reserved'}
        Name is already in use on this type.
      {:else}
        {err.status} · {err.code} — {err.message}
      {/if}
    </p>
  {/if}
</div>
