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
    ariaLabel?: string
    onChange: (value: string) => void
  }

  let {
    value,
    options,
    placeholder = '',
    disabled = false,
    ariaLabel,
    onChange,
  }: Props = $props()

  // One id per instance, used to wire the input to the listbox and the
  // active option via aria-controls / aria-activedescendant.
  const listId = `combobox-list-${Math.random().toString(36).slice(2, 8)}`

  let open = $state(false)
  let inputText: string = $state('')
  let rawHighlight = $state(0)
  let rootEl = $state<HTMLDivElement | null>(null)

  $effect(() => {
    // Reseed the input text whenever the committed value changes from outside.
    inputText = value
  })

  let filtered = $derived(
    inputText.trim() === ''
      ? options
      : options.filter((o) =>
          o.value.toLowerCase().includes(inputText.trim().toLowerCase()),
        ),
  )

  // Highlight is clamped at read time so we never need an effect to fix it up
  // after `filtered` shrinks.
  let highlight = $derived(
    filtered.length === 0 ? 0 : Math.min(rawHighlight, filtered.length - 1),
  )

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
      rawHighlight = Math.min(filtered.length - 1, highlight + 1)
      e.preventDefault()
    } else if (e.key === 'ArrowUp') {
      open = true
      rawHighlight = Math.max(0, highlight - 1)
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
    rawHighlight = 0
  }

  function pick(idx: number): void {
    rawHighlight = idx
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
    type="text"
    role="combobox"
    aria-expanded={open}
    aria-controls={listId}
    aria-activedescendant={open && filtered.length > 0 ? `${listId}-${highlight}` : undefined}
    aria-label={ariaLabel}
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
      id={listId}
      role="listbox"
      class="absolute left-0 right-0 top-full z-10 mt-0.5 max-h-48 overflow-auto rounded border border-gray-300 bg-white shadow-md"
    >
      {#each filtered as option, idx (option.value)}
        <li
          id="{listId}-{idx}"
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
