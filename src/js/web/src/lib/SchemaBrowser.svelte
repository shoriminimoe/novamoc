<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { type TypeKind } from './commands'
  import { fetchSchema, type SchemaSnapshot, type TypeView } from './schema'
  import TypeDetail from './TypeDetail.svelte'
  import TypesRail from './TypesRail.svelte'

  interface Props {
    /** Bump from outside to force a re-fetch (e.g. after the token changes). */
    reloadKey?: number
  }

  let { reloadKey = 0 }: Props = $props()

  type LoadState =
    | { kind: 'idle' }
    | { kind: 'loading' }
    | { kind: 'loaded'; snapshot: SchemaSnapshot }
    | { kind: 'error'; status: number; code: string; message: string }

  let loadState = $state<LoadState>({ kind: 'idle' })
  let selectedId = $state<string | null>(null)
  let selectedKind = $state<TypeKind | null>(null)
  let showArchived = $state(false)
  // Generation counter — a non-reactive sequence number used to discard
  // results from stale in-flight fetches when ``load()`` is called again
  // before the previous response lands.
  let loadGen = 0

  async function load(): Promise<void> {
    loadGen += 1
    const gen = loadGen
    loadState = { kind: 'loading' }
    try {
      const snapshot = await fetchSchema(createApiClient())
      if (gen !== loadGen) return // a newer load is in flight; drop this result
      loadState = { kind: 'loaded', snapshot }
      // Clear selection if it points at a type that no longer exists.
      if (selectedId !== null) {
        const all = [...snapshot.asset_types, ...snapshot.maintenance_record_types]
        if (!all.some((t) => t.id === selectedId)) {
          selectedId = null
          selectedKind = null
        }
      }
    } catch (e) {
      if (gen !== loadGen) return
      if (e instanceof ProblemDetailsError) {
        loadState = { kind: 'error', status: e.status, code: e.code, message: e.message }
      } else {
        loadState = { kind: 'error', status: 0, code: 'network_error', message: String(e) }
      }
    }
  }

  $effect(() => {
    reloadKey
    void load()
  })

  function handleSelect(id: string, kind: TypeKind): void {
    selectedId = id
    selectedKind = kind
  }

  function handleDeleted(): void {
    selectedId = null
    selectedKind = null
  }

  function findSelected(snapshot: SchemaSnapshot): TypeView | null {
    if (selectedId === null) return null
    const haystack =
      selectedKind === 'asset_type'
        ? snapshot.asset_types
        : selectedKind === 'maintenance_record_type'
          ? snapshot.maintenance_record_types
          : []
    return haystack.find((t) => t.id === selectedId) ?? null
  }

  let selectedType = $derived(loadState.kind === 'loaded' ? findSelected(loadState.snapshot) : null)
  let schemaVersion = $derived(loadState.kind === 'loaded' ? loadState.snapshot.schema_version : null)
</script>

<section class="flex h-full flex-col">
  {#if loadState.kind === 'loading'}
    <p class="p-6 text-sm text-gray-600">Loading schema…</p>
  {:else if loadState.kind === 'error'}
    <div class="m-6 rounded border border-red-300 bg-red-50 p-4">
      <p class="text-sm font-semibold text-red-700">{loadState.status} · {loadState.code}</p>
      <p class="mt-1 text-sm text-red-700">{loadState.message}</p>
    </div>
  {:else if loadState.kind === 'loaded'}
    <div class="flex flex-1 overflow-hidden">
      <TypesRail
        assetTypes={loadState.snapshot.asset_types}
        recordTypes={loadState.snapshot.maintenance_record_types}
        {selectedId}
        {showArchived}
        onShowArchivedChange={(next) => (showArchived = next)}
        onSelect={handleSelect}
        onChanged={() => void load()}
      />
      <div class="flex-1 overflow-auto">
        <TypeDetail
          type={selectedType}
          kind={selectedType !== null ? selectedKind : null}
          {showArchived}
          onChanged={() => void load()}
          onDeleted={handleDeleted}
        />
      </div>
    </div>
    {#if schemaVersion !== null}
      <p class="border-t border-gray-200 px-3 py-1 text-right text-[10px] text-gray-500">v{schemaVersion} · synced</p>
    {/if}
  {/if}
</section>
