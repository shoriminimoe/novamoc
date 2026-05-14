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
  let collapsed = $state(false)
  let createNameEl = $state<HTMLInputElement | null>(null)

  // When the user opens the create row, drop the cursor into the name input
  // so they can type the name and hit Enter without a mouse trip.
  $effect(() => {
    if (creating !== null) createNameEl?.focus()
  })

  // Close the `+ New ▾` dropdown when the user clicks anywhere outside it.
  // Trigger button + dropdown carry `data-menu-region` so their own clicks
  // pass through.
  function onWindowClick(e: MouseEvent): void {
    if (!newKindMenuOpen) return
    if (!(e.target instanceof Element)) return
    if (e.target.closest('[data-menu-region]')) return
    newKindMenuOpen = false
  }

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

<svelte:window onclick={onWindowClick} />

<aside
  class="flex h-full flex-col gap-2 border-r border-gray-200 bg-gray-50 p-3 transition-[width] duration-150"
  class:w-64={!collapsed}
  class:w-10={collapsed}
>
  <button
    type="button"
    aria-label={collapsed ? 'Expand types panel' : 'Collapse types panel'}
    aria-expanded={!collapsed}
    class="self-end rounded border border-gray-300 bg-white px-2 py-0.5 text-xs text-gray-700 hover:bg-gray-100"
    onclick={() => (collapsed = !collapsed)}
  >
    {collapsed ? '»' : '«'}
  </button>

  {#if !collapsed}
  <div class="relative">
    <button
      type="button"
      data-menu-region
      class="w-full rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      aria-haspopup="menu"
      aria-expanded={newKindMenuOpen}
      onclick={() => (newKindMenuOpen = !newKindMenuOpen)}
      disabled={busy}
    >
      + New ▾
    </button>
    {#if newKindMenuOpen}
      <div role="menu" data-menu-region class="absolute left-0 right-0 top-9 z-10 rounded border border-gray-300 bg-white text-left text-sm shadow-md">
        <button type="button" role="menuitem" class="block w-full px-3 py-1.5 text-left hover:bg-gray-50" onclick={() => startCreate('asset_type')}>Asset type</button>
        <button type="button" role="menuitem" class="block w-full px-3 py-1.5 text-left hover:bg-gray-50" onclick={() => startCreate('maintenance_record_type')}>Maintenance record type</button>
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
        <th class="w-16 cursor-pointer select-none whitespace-nowrap px-1 py-1" onclick={() => toggleSort('kind')}>
          Kind <span class="text-blue-600">{arrow('kind')}</span>
        </th>
        <th class="cursor-pointer select-none whitespace-nowrap px-1 py-1" onclick={() => toggleSort('name')}>
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
                bind:this={createNameEl}
                type="text"
                class="w-full rounded border px-2 py-1 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                class:border-gray-300={!nameError}
                class:border-red-500={nameError}
                bind:value={creating.draftName}
                disabled={busy}
                required
                aria-label="New type name"
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
          tabindex="0"
          aria-selected={row.type.id === selectedId}
          class="cursor-pointer border-b border-gray-100 hover:bg-blue-50 focus:bg-blue-50 focus:outline-none"
          class:bg-blue-100={row.type.id === selectedId}
          class:opacity-60={!row.type.active}
          onclick={() => onSelect(row.type.id, row.kind)}
          onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onSelect(row.type.id, row.kind)
            }
          }}
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
  {/if}
</aside>
