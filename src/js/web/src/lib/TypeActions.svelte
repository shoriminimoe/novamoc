<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { postSchemaCommand, type SchemaCommandBody, type TypeKind } from './commands'
  import type { TypeView } from './schema'

  interface Props {
    kind: TypeKind
    type: TypeView
    onChanged: () => void
  }

  let { kind, type, onChanged }: Props = $props()

  type Mode =
    | { kind: 'idle' }
    | { kind: 'renaming'; draft: string }
    | { kind: 'confirming_delete' }
    | { kind: 'submitting' }
    | { kind: 'error'; status: number; code: string; message: string }

  let mode = $state<Mode>({ kind: 'idle' })

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
      type: `update_${kind}`,
      entity_id: type.id,
      payload: { name: draft },
    })
  }

  function activate(): void {
    void send({
      type: `activate_${kind}`,
      entity_id: type.id,
      payload: {},
    })
  }

  function deactivate(): void {
    void send({
      type: `deactivate_${kind}`,
      entity_id: type.id,
      payload: {},
    })
  }

  function confirmDelete(): void {
    void send({
      type: `delete_${kind}`,
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
        <label for="rename-{kind}-{type.id}" class="block text-xs font-medium text-gray-700">
          New name
        </label>
        <input
          id="rename-{kind}-{type.id}"
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
        This {kind === 'asset_type' ? 'asset type' : 'maintenance record type'} no longer exists — reload.
      {:else}
        {mode.status} · {mode.code} — {mode.message}
      {/if}
    </p>
  {/if}
</div>
