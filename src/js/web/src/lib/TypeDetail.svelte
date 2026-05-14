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
    | { kind: 'submitting'; resumeAs: Mode }

  type ErrState =
    | { kind: 'idle' }
    | { kind: 'error'; status: number; code: string; message: string }

  let mode = $state<Mode>({ kind: 'idle' })
  let err = $state<ErrState>({ kind: 'idle' })

  // Reset mode when the selection changes.
  let prevId = $state<string | null>(null)
  $effect(() => {
    if ((type?.id ?? null) !== prevId) {
      prevId = type?.id ?? null
      mode = { kind: 'idle' }
      err = { kind: 'idle' }
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

  function setError(e: unknown, resume: Mode): void {
    mode = resume
    if (e instanceof ProblemDetailsError) {
      err = { kind: 'error', status: e.status, code: e.code, message: e.message }
    } else {
      err = { kind: 'error', status: 0, code: 'network_error', message: String(e) }
    }
  }

  function startRename(): void {
    if (type === null) return
    mode = { kind: 'renaming', draft: type.name }
    err = { kind: 'idle' }
  }

  function startArchive(): void {
    mode = { kind: 'confirmingArchive' }
    err = { kind: 'idle' }
  }

  function startDelete(): void {
    mode = { kind: 'confirmingDelete' }
    err = { kind: 'idle' }
  }

  function resetMode(): void {
    mode = { kind: 'idle' }
    err = { kind: 'idle' }
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
    const resume = mode
    err = { kind: 'idle' }
    mode = { kind: 'submitting', resumeAs: resume }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `update_${kind}` as const,
        entity_id: id,
        payload: { name: next },
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e, resume)
    }
  }

  async function confirmArchive(): Promise<void> {
    if (type === null || kind === null) return
    if (mode.kind !== 'confirmingArchive') return
    const verb = type.active ? 'deactivate' : 'activate'
    const id = type.id
    const resume = mode
    err = { kind: 'idle' }
    mode = { kind: 'submitting', resumeAs: resume }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `${verb}_${kind}` as const,
        entity_id: id,
        payload: {},
      } as Parameters<typeof postSchemaCommand>[1])
      resetMode()
      onChanged()
    } catch (e) {
      setError(e, resume)
    }
  }

  async function confirmDelete(): Promise<void> {
    if (type === null || kind === null) return
    if (mode.kind !== 'confirmingDelete') return
    const id = type.id
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
      onDeleted()
      onChanged()
    } catch (e) {
      setError(e, resume)
    }
  }

  let nameError = $derived(err.kind === 'error' && err.code === 'name_reserved')
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

    {#if err.kind === 'error'}
      <p class="text-xs text-red-700">
        {#if err.code === 'entity_not_found'}
          This type no longer exists — reload.
        {:else if err.code === 'name_reserved'}
          Name is already in use.
        {:else}
          {err.status} · {err.code} — {err.message}
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
