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
