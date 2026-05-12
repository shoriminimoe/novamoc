<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { postSchemaCommand, type FieldKind } from './commands'
  import type { FieldDataType, TypeView } from './schema'

  interface Props {
    kind: FieldKind
    /** Human label, e.g. "asset-type field" or "maintenance-record-type field". */
    label: string
    /** Parent label for the dropdown, e.g. "Parent asset type". */
    parentLabel: string
    /** Active parent types — used to populate the parent dropdown. */
    parents: TypeView[]
    onCreated: () => void
  }

  let { kind, label, parentLabel, parents, onCreated }: Props = $props()

  type SubmitState =
    | { kind: 'idle' }
    | { kind: 'submitting' }
    | { kind: 'error'; status: number; code: string; message: string }

  const DATA_TYPES: FieldDataType[] = [
    'text',
    'number',
    'integer',
    'boolean',
    'date',
    'datetime',
  ]

  let expanded = $state(false)
  let parentId = $state('')
  let name = $state('')
  let dataType = $state<FieldDataType>('text')
  let validationJson = $state('')
  let submitState = $state<SubmitState>({ kind: 'idle' })
  let parentInput = $state<HTMLSelectElement | null>(null)

  let parentInputId = $derived(`new-${kind}-parent`)
  let nameInputId = $derived(`new-${kind}-name`)
  let dataTypeInputId = $derived(`new-${kind}-data-type`)
  let validationInputId = $derived(`new-${kind}-validation`)

  function open(): void {
    expanded = true
    parentId = parents[0]?.id ?? ''
    name = ''
    dataType = 'text'
    validationJson = ''
    submitState = { kind: 'idle' }
    queueMicrotask(() => parentInput?.focus())
  }

  function close(): void {
    expanded = false
    parentId = ''
    name = ''
    dataType = 'text'
    validationJson = ''
    submitState = { kind: 'idle' }
  }

  function parseValidation():
    | { ok: true; value: Record<string, unknown> | null }
    | { ok: false; reason: string } {
    const trimmed = validationJson.trim()
    if (trimmed === '') return { ok: true, value: null }
    try {
      const parsed = JSON.parse(trimmed) as unknown
      if (
        parsed === null ||
        (typeof parsed === 'object' && !Array.isArray(parsed))
      ) {
        return { ok: true, value: parsed as Record<string, unknown> | null }
      }
      return { ok: false, reason: 'Validation must be a JSON object or null' }
    } catch (e) {
      return { ok: false, reason: `Invalid JSON: ${String(e)}` }
    }
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (parentId === '' || name.trim() === '') return
    const validation = parseValidation()
    if (!validation.ok) {
      submitState = {
        kind: 'error',
        status: 0,
        code: 'invalid_payload_shape',
        message: validation.reason,
      }
      return
    }
    submitState = { kind: 'submitting' }
    try {
      await postSchemaCommand(createApiClient(), {
        type: `create_${kind}`,
        entity_id: crypto.randomUUID(),
        payload: {
          parent_id: parentId,
          name: name.trim(),
          data_type: dataType,
          validation: validation.value,
        },
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
  let parentError = $derived(
    submitState.kind === 'error' &&
      submitState.code === 'parent_type_not_found',
  )
  let validationError = $derived(
    submitState.kind === 'error' &&
      submitState.code === 'invalid_payload_shape',
  )
  let busy = $derived(submitState.kind === 'submitting')
  let noParents = $derived(parents.length === 0)
</script>

{#if !expanded}
  <button
    type="button"
    class="w-full rounded border border-dashed border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
    onclick={open}
    disabled={noParents}
    title={noParents ? `Create a ${parentLabel.toLowerCase()} first` : ''}
  >
    + New {label}
  </button>
{:else}
  <form
    class="space-y-3 rounded border border-gray-300 p-4"
    onsubmit={submit}
  >
    <div>
      <label
        for={parentInputId}
        class="block text-xs font-medium text-gray-700"
      >
        {parentLabel}
      </label>
      <select
        id={parentInputId}
        class="mt-1 w-full rounded border px-2 py-1 font-mono text-sm"
        class:border-gray-300={!parentError}
        class:border-red-500={parentError}
        class:ring-1={parentError}
        class:ring-red-500={parentError}
        bind:value={parentId}
        bind:this={parentInput}
        disabled={busy}
        required
      >
        {#each parents as parent (parent.id)}
          <option value={parent.id}>{parent.name}</option>
        {/each}
      </select>
    </div>
    <div>
      <label for={nameInputId} class="block text-xs font-medium text-gray-700">
        Name
      </label>
      <input
        id={nameInputId}
        type="text"
        class="mt-1 w-full rounded border px-2 py-1 font-mono text-sm"
        class:border-gray-300={!nameError}
        class:border-red-500={nameError}
        class:ring-1={nameError}
        class:ring-red-500={nameError}
        bind:value={name}
        disabled={busy}
        required
      />
    </div>
    <div>
      <label
        for={dataTypeInputId}
        class="block text-xs font-medium text-gray-700"
      >
        Data type
      </label>
      <select
        id={dataTypeInputId}
        class="mt-1 w-full rounded border border-gray-300 px-2 py-1 font-mono text-sm"
        bind:value={dataType}
        disabled={busy}
      >
        {#each DATA_TYPES as dt (dt)}
          <option value={dt}>{dt}</option>
        {/each}
      </select>
    </div>
    <div>
      <label
        for={validationInputId}
        class="block text-xs font-medium text-gray-700"
      >
        Validation (JSON object, optional)
      </label>
      <textarea
        id={validationInputId}
        class="mt-1 w-full rounded border px-2 py-1 font-mono text-xs"
        class:border-gray-300={!validationError}
        class:border-red-500={validationError}
        class:ring-1={validationError}
        class:ring-red-500={validationError}
        rows="2"
        placeholder={'e.g. {"min": 0, "max": 100}'}
        bind:value={validationJson}
        disabled={busy}
      ></textarea>
    </div>
    {#if submitState.kind === 'error'}
      <p class="text-xs text-red-700">
        {submitState.status} · {submitState.code} — {submitState.message}
      </p>
    {/if}
    <div class="flex justify-end gap-2">
      <button
        type="button"
        class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50"
        onclick={close}
        disabled={busy}
      >
        Cancel
      </button>
      <button
        type="submit"
        class="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
        disabled={busy || parentId === '' || name.trim() === ''}
      >
        {busy ? 'Creating…' : 'Create'}
      </button>
    </div>
  </form>
{/if}
