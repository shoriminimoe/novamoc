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
  let submitState = $state<SubmitState>({ kind: 'idle' })
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
