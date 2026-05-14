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
