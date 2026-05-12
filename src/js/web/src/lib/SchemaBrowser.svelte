<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './api'
  import { fetchSchema, type SchemaSnapshot, type TypeView } from './schema'
  import FieldActions from './FieldActions.svelte'
  import FieldCreateForm from './FieldCreateForm.svelte'
  import TypeActions from './TypeActions.svelte'
  import TypeCard from './TypeCard.svelte'
  import TypeCreateForm from './TypeCreateForm.svelte'

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

  let loadState: LoadState = $state({ kind: 'idle' })
  let showTombstoned = $state(false)

  function visibleTypes(types: TypeView[]): TypeView[] {
    return showTombstoned ? types : types.filter((t) => t.active)
  }

  async function load(): Promise<void> {
    loadState = { kind: 'loading' }
    try {
      const snapshot = await fetchSchema(createApiClient())
      loadState = { kind: 'loaded', snapshot }
    } catch (e) {
      if (e instanceof ProblemDetailsError) {
        loadState = {
          kind: 'error',
          status: e.status,
          code: e.code,
          message: e.message,
        }
      } else {
        loadState = {
          kind: 'error',
          status: 0,
          code: 'network_error',
          message: String(e),
        }
      }
    }
  }

  $effect(() => {
    reloadKey
    void load()
  })
</script>

<section class="space-y-6">
  <div class="flex items-center justify-between">
    <div>
      <h2 class="text-xl font-semibold">Schema</h2>
      {#if loadState.kind === 'loaded'}
        <p class="text-xs text-gray-500">
          version {loadState.snapshot.schema_version}
        </p>
      {/if}
    </div>
    <div class="flex items-center gap-3">
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={showTombstoned} />
        <span>Show tombstoned</span>
      </label>
      <button
        type="button"
        class="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50"
        disabled={loadState.kind === 'loading'}
        onclick={() => void load()}
      >
        {loadState.kind === 'loading' ? 'Loading…' : 'Reload'}
      </button>
    </div>
  </div>

  {#if loadState.kind === 'loading'}
    <p class="text-sm text-gray-600">Loading schema…</p>
  {:else if loadState.kind === 'error'}
    <div class="rounded border border-red-300 bg-red-50 p-4">
      <p class="text-sm font-semibold text-red-700">
        {loadState.status} · {loadState.code}
      </p>
      <p class="mt-1 text-sm text-red-700">{loadState.message}</p>
    </div>
  {:else if loadState.kind === 'loaded'}
    {@const assetTypes = visibleTypes(loadState.snapshot.asset_types)}
    {@const activeAssetTypes = loadState.snapshot.asset_types.filter((t) => t.active)}
    {@const recordTypes = visibleTypes(loadState.snapshot.maintenance_record_types)}
    {@const activeRecordTypes = loadState.snapshot.maintenance_record_types.filter((t) => t.active)}
    <div class="grid gap-8 md:grid-cols-2">
      <div class="space-y-4">
        <TypeCreateForm
          kind="asset_type"
          label="asset type"
          onCreated={() => void load()}
        />
        <FieldCreateForm
          kind="asset_type_field"
          label="asset-type field"
          parentLabel="Parent asset type"
          parents={activeAssetTypes}
          onCreated={() => void load()}
        />
        <h3 class="mb-3 mt-4 text-sm font-semibold uppercase tracking-wide text-gray-600">
          Asset types ({assetTypes.length})
        </h3>
        {#if assetTypes.length === 0}
          <p class="text-sm italic text-gray-500">
            no {showTombstoned ? '' : 'active '}asset types
          </p>
        {:else}
          <div class="space-y-3">
            {#each assetTypes as type (type.id)}
              <div>
                <TypeCard {type} {showTombstoned}>
                  {#snippet fieldActions(field)}
                    <FieldActions
                      kind="asset_type_field"
                      {field}
                      onChanged={() => void load()}
                    />
                  {/snippet}
                </TypeCard>
                <TypeActions
                  kind="asset_type"
                  {type}
                  onChanged={() => void load()}
                />
              </div>
            {/each}
          </div>
        {/if}
      </div>
      <div class="space-y-4">
        <TypeCreateForm
          kind="maintenance_record_type"
          label="maintenance record type"
          onCreated={() => void load()}
        />
        <FieldCreateForm
          kind="maintenance_record_type_field"
          label="maintenance-record-type field"
          parentLabel="Parent maintenance record type"
          parents={activeRecordTypes}
          onCreated={() => void load()}
        />
        <h3 class="mb-3 mt-4 text-sm font-semibold uppercase tracking-wide text-gray-600">
          Maintenance record types ({recordTypes.length})
        </h3>
        {#if recordTypes.length === 0}
          <p class="text-sm italic text-gray-500">
            no {showTombstoned ? '' : 'active '}maintenance record types
          </p>
        {:else}
          <div class="space-y-3">
            {#each recordTypes as type (type.id)}
              <div>
                <TypeCard {type} {showTombstoned}>
                  {#snippet fieldActions(field)}
                    <FieldActions
                      kind="maintenance_record_type_field"
                      {field}
                      onChanged={() => void load()}
                    />
                  {/snippet}
                </TypeCard>
                <TypeActions
                  kind="maintenance_record_type"
                  {type}
                  onChanged={() => void load()}
                />
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  {/if}
</section>
